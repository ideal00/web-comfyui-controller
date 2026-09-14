/* Anima 高清重建（Highres Reconstruction）：放大 → 二采 → 高清输出。
 *
 * 与「细节增强」和「输出增强」是三件不同的事：
 *   首采         → 约 1MP，决定画什么、画在哪里
 *   细节增强      → 同尺寸低 denoise 润色（不改尺寸，见 anima-refine.js）
 *   高清重建      → Anime6B 超分 → 缩放回目标倍率 → Anima 二采（本脚本）
 *
 * 参数范围与后端 easy_panel_app/anima_highres.py 保持一致：
 * 倍率 1.15–2.0、denoise 0.20–0.30（默认 1.5× / 0.25 / 20 步），长边上限 2560。
 * 所有数值都同步写入现有一整套 #hires* 控件（payload 的唯一来源），
 * 本面板只负责 Anima 友好的档位与文案；仅在 Anima 模型下显示。
 */
(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);

  // 与后端 ANIMA_HIGHRES_PRESETS 保持一致。
  const PRESETS = {
    conservative: { label: "保守", scale: 1.25, denoise: 0.25, steps: 19,
                    note: "尽量不改首采；LoRA 测试、角色一致性对比用。" },
    recommended: { label: "推荐", scale: 1.50, denoise: 0.25, steps: 20,
                   note: "正式出图的默认档：补发丝、服装褶皱与镜头细节。" },
    strong: { label: "强化", scale: 1.50, denoise: 0.29, steps: 24,
              note: "发丝、饰品、背景纹理多的图；更接近结构重绘。" },
  };
  const DETAIL_TERMS =
    "fine individual hair strands, refined fabric folds, detailed clothing texture, " +
    "clean line details, small accessory details, crisp facial features";

  const RANGES = {
    scale: { min: 1.15, max: 2.0, step: 0.05 },
    denoise: { min: 0.20, max: 0.30, step: 0.01 },
    steps: { min: 6, max: 40, step: 1 },
    cfg: { min: 1, max: 10, step: 0.1 },
  };

  let scope = "auto";

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = String(value || "");
    return node.innerHTML;
  }

  function num(input, fallback) {
    const value = Number(input?.value);
    return Number.isFinite(value) ? value : fallback;
  }

  function installPanel() {
    const anchor = byId("animaPromptPanel");
    if (!anchor || byId("animaHighresPanel")) return;
    const block = document.createElement("details");
    block.id = "animaHighresPanel";
    block.className = "anima-highres-panel";
    block.innerHTML = `
      <summary>Anima 高清重建（放大 + 二采）</summary>
      <div class="small">首采约 1MP 决定构图；高清重建先做 Anime6B 超分、缩放回目标倍率，再由 Anima 二采在更高分辨率上重建细节。与「细节增强」（同尺寸润色）互不替代；与输出增强（Anime6B 等）不能同时开启。</div>
      <label class="switch" style="margin-top:6px"><input id="animaHighresEnabled" type="checkbox"><div><b>启用高清重建</b><div class="small">目标倍率 1.25–2.0×；只保留最终成品（首采对照图仍会另存，用于与二采结果对比）。</div></div></label>
      <div id="animaHighresBody" style="display:none">
        <div class="field-title"><span>档位</span><span class="small">先选目的，再微调数字</span></div>
        <div class="hires-purpose-row anima-highres-presets">
          ${Object.entries(PRESETS).map(([key, item]) =>
            `<button type="button" data-highres-preset="${key}" onclick="animaHighresApplyPreset('${key}')"><b>${escapeHtml(item.label)}</b><span>${item.scale}× · denoise ${item.denoise} · ${item.steps} 步</span></button>`).join("")}
        </div>
        <div class="two" style="margin-top:8px">
          <div><div class="field-title"><span>目标倍率</span></div><input id="animaHighresScale" type="number" min="1.15" max="2" step="0.05" value="1.5"></div>
          <div><div class="field-title"><span>二采重绘幅度</span></div><input id="animaHighresDenoise" type="number" min="0.2" max="0.3" step="0.01" value="0.25"></div>
        </div>
        <div class="two" style="margin-top:8px">
          <div><div class="field-title"><span>二采步数</span></div><input id="animaHighresSteps" type="number" min="6" max="40" step="1" value="20"></div>
          <div><div class="field-title"><span>二采 CFG</span></div><input id="animaHighresCfg" type="number" min="1" max="10" step="0.1" value="4.8"></div>
        </div>
        <div class="field-title" style="margin-top:8px"><span>高清重建提示词</span></div>
        <select id="animaHighresScope" onchange="animaHighresScopeChanged()">
          <option value="inherit">完全继承首采（只放大重绘）</option>
          <option value="auto" selected>继承 + 自动细节词（推荐）</option>
          <option value="custom">自定义二采提示词</option>
        </select>
        <div id="animaHighresCustomWrap" style="display:none;margin-top:6px">
          <textarea id="animaHighresCustom" rows="2" placeholder="自定义二采提示词：首采描述不再参与，建议写清角色与构图，再补细节词" oninput="animaHighresRefresh()"></textarea>
          <div class="small">自定义 = 二采只用这里的文本（替换模式）；不确定时请用「继承 + 自动细节词」。</div>
        </div>
        <div class="field-title" style="margin-top:8px"><span>自动细节词预览</span></div>
        <div id="animaHighresDetailPreview" class="small"></div>
        <div id="animaHighresNote" class="small" style="margin-top:8px"></div>
      </div>`;
    anchor.appendChild(block);

    ["animaHighresEnabled", "animaHighresScale", "animaHighresDenoise",
     "animaHighresSteps", "animaHighresCfg"].forEach((id) => {
      byId(id)?.addEventListener("input", animaHighresRefresh);
      byId(id)?.addEventListener("change", animaHighresRefresh);
    });
    window.animaHighresApplyPreset("recommended", true);
    window.animaHighresScopeChanged(true);
    const panel = byId("animaHighresPanel");
    if (panel) panel.open = true;
    window.animaHighresSyncVisibility();
  }

  function modelFamily() {
    const model = String(byId("model")?.value || "").toLowerCase();
    if (model.includes("krea")) return "krea2";
    if (model.includes("anima")) return "anima";
    return "sdxl";
  }

  function profileHires() {
    try {
      const profile = window.currentSamplingProfile ? window.currentSamplingProfile() : {};
      return profile && typeof profile.hires === "object" && profile.hires ? profile.hires : {};
    } catch (error) {
      return {};
    }
  }

  window.animaHighresState = function () {
    const active = document.querySelector("[data-highres-preset].active");
    return {
      enabled: byId("animaHighresEnabled")?.checked === true,
      preset: active?.dataset.highresPreset || "recommended",
      scale: num(byId("animaHighresScale"), 1.5),
      denoise: num(byId("animaHighresDenoise"), 0.25),
      steps: Math.round(num(byId("animaHighresSteps"), 20)),
      cfg: num(byId("animaHighresCfg"), 4.8),
      scope,
    };
  };

  // 把面板值写进现有一整套 #hires* 控件（payload / 快照 / 手机端的唯一来源）。
  // 只在 Anima 模型下写入，避免污染 Illustrious / SDXL 的二采设置。
  function pushToHiresControls() {
    if (modelFamily() !== "anima") return;
    const state = window.animaHighresState();
    const set = (id, value) => { const field = byId(id); if (field) field.value = String(value); };
    set("hiresScale", state.scale);
    set("hiresDenoise", state.denoise);
    set("hiresSteps", state.steps);
    set("hiresCfg", state.cfg);
    const mode = byId("hiresPromptMode");
    const positive = byId("hiresPositive");
    if (state.scope === "inherit") {
      if (mode) mode.value = "inherit";
    } else if (state.scope === "auto") {
      if (mode) mode.value = "append";
      if (positive) positive.value = DETAIL_TERMS;
    } else {
      if (mode) mode.value = "replace";
      if (positive) positive.value = String(byId("animaHighresCustom")?.value || "").trim();
    }
    if (typeof window.hiresPromptModeChanged === "function") window.hiresPromptModeChanged(true);
  }

  // 反向同步：外部（换模型 / 快照恢复 / 手机端回填）改写 #hires* 后刷新面板。
  function pullFromHiresControls() {
    if (modelFamily() !== "anima") return;
    if (byId("animaHighresPanel")?.hidden) return;
    const nearly = (a, b) => Math.abs(Number(a) - Number(b)) < 1e-6;
    const sync = (inputId, sourceId) => {
      const input = byId(inputId);
      const source = byId(sourceId);
      if (!input || !source || String(source.value).trim() === "") return;
      const value = Number(source.value);
      if (!Number.isFinite(value) || nearly(input.value, value)) return;
      input.value = String(value);
    };
    sync("animaHighresScale", "hiresScale");
    sync("animaHighresDenoise", "hiresDenoise");
    sync("animaHighresSteps", "hiresSteps");
    sync("animaHighresCfg", "hiresCfg");
    const mode = String(byId("hiresPromptMode")?.value || "");
    const text = String(byId("hiresPositive")?.value || "").trim();
    const next = mode === "inherit" ? "inherit"
      : mode === "replace" ? "custom"
        : text === DETAIL_TERMS ? "auto" : (text ? "custom" : "auto");
    if (next !== scope) {
      scope = next;
      if (byId("animaHighresScope")) byId("animaHighresScope").value = next;
      if (next === "custom" && byId("animaHighresCustom") && text !== DETAIL_TERMS) {
        byId("animaHighresCustom").value = text;
      }
      window.animaHighresRefresh();
    }
  }

  window.animaHighresApplyPreset = function (key, silent) {
    const preset = PRESETS[key];
    if (!preset) return;
    const set = (id, value) => { const field = byId(id); if (field) field.value = String(value); };
    set("animaHighresScale", preset.scale);
    set("animaHighresDenoise", preset.denoise);
    set("animaHighresSteps", preset.steps);
    document.querySelectorAll("[data-highres-preset]").forEach((button) => {
      button.classList.toggle("active", button.dataset.highresPreset === key);
    });
    pushToHiresControls();
    if (!silent) animaHighresRefresh();
  };

  window.animaHighresScopeChanged = function (silent) {
    scope = String(byId("animaHighresScope")?.value || "auto");
    const wrap = byId("animaHighresCustomWrap");
    if (wrap) wrap.style.display = scope === "custom" ? "block" : "none";
    pushToHiresControls();
    if (!silent) animaHighresRefresh();
  };

  window.animaHighresRefresh = function () {
    const state = window.animaHighresState();
    const body = byId("animaHighresBody");
    if (body) body.style.display = state.enabled ? "" : "none";
    if (state.enabled) pushToHiresControls();
    const preview = byId("animaHighresDetailPreview");
    if (preview) preview.textContent = DETAIL_TERMS;

    const note = byId("animaHighresNote");
    if (!note) return;
    const lines = [];
    const [baseWidth, baseHeight] = String(byId("size")?.value || "864x1152").split("x").map(Number);
    const maxLongEdge = Number(profileHires().max_long_edge || 2560) || 0;
    let width = Math.max(8, Math.round((baseWidth || 864) * state.scale / 8) * 8);
    let height = Math.max(8, Math.round((baseHeight || 1152) * state.scale / 8) * 8);
    let limited = false;
    if (maxLongEdge > 0 && Math.max(width, height) > maxLongEdge) {
      const ratio = maxLongEdge / Math.max(width, height);
      width = Math.max(8, Math.round(width * ratio / 8) * 8);
      height = Math.max(8, Math.round(height * ratio / 8) * 8);
      limited = true;
    }
    const preset = PRESETS[state.preset];
    lines.push(preset ? preset.note : "");
    lines.push(`预计输出 ${width}×${height}${limited ? `（已按长边上限 ${maxLongEdge} 收窄）` : ""} · 二采 ${state.steps} 步 · CFG ${state.cfg} · denoise ${state.denoise}。`);
    if (!state.enabled) lines.length = 1;
    const outputMode = String(byId("outputEnhancementMode")?.value || "off");
    if (state.enabled && outputMode !== "off") {
      lines.push("⚠ 输出增强已开启：高清重建与输出增强不能同时使用，请关闭其中一项。");
    }
    if (state.enabled && width * height > 2600 * 1300) {
      lines.push("⚠ 目标尺寸较大：8GB 显存会明显变慢，必要时把倍率降到 1.25×。");
    }
    note.textContent = lines.filter(Boolean).join(" ");
  };

  window.animaHighresSyncVisibility = function () {
    const panel = byId("animaHighresPanel");
    if (!panel) return;
    const isAnima = modelFamily() === "anima";
    panel.hidden = !isAnima;
    if (!isAnima) {
      if (byId("animaHighresEnabled")) byId("animaHighresEnabled").checked = false;
      const body = byId("animaHighresBody");
      if (body) body.style.display = "none";
    }
  };

  function injectPayload() {
    const original = window.payload;
    if (typeof original !== "function" || original.__animaHighresWrapped) return;
    const wrapped = function (...args) {
      if (modelFamily() === "anima") pushToHiresControls();
      const data = original.apply(this, args) || {};
      if (modelFamily() === "anima") {
        const state = window.animaHighresState();
        data.animaHighres = {
          enabled: state.enabled, scale: state.scale, denoise: state.denoise,
          steps: state.steps, cfg: state.cfg,
        };
      }
      return data;
    };
    wrapped.__animaHighresWrapped = true;
    window.payload = wrapped;
  }

  function wrapRestore() {
    const original = window.restorePayloadToPanel;
    if (typeof original !== "function" || original.__animaHighresWrapped) return;
    const wrapped = function (data, ...rest) {
      const result = original.apply(this, [data, ...rest]);
      const raw = data && typeof data === "object" ? data.animaHighres : null;
      if (raw && typeof raw === "object") {
        if (byId("animaHighresEnabled")) byId("animaHighresEnabled").checked = raw.enabled === true;
        const assign = (id, value) => {
          if (value == null || !Number.isFinite(Number(value))) return;
          const field = byId(id);
          if (field) field.value = String(value);
        };
        assign("animaHighresScale", raw.scale);
        assign("animaHighresDenoise", raw.denoise);
        assign("animaHighresSteps", raw.steps);
        assign("animaHighresCfg", raw.cfg);
        const enabled = byId("animaHighresEnabled");
        if (enabled) enabled.checked = raw.enabled === true;
        window.animaHighresScopeChanged(true);
      }
      window.animaHighresSyncVisibility();
      window.animaHighresRefresh();
      return result;
    };
    wrapped.__animaHighresWrapped = true;
    window.restorePayloadToPanel = wrapped;
  }

  function wrapModelChanged() {
    const original = window.modelChanged;
    if (typeof original !== "function" || original.__animaHighresWrapped) return;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      window.animaHighresSyncVisibility();
      pullFromHiresControls();
      window.animaHighresRefresh();
      return result;
    };
    wrapped.__animaHighresWrapped = true;
    window.modelChanged = wrapped;
  }

  if (!window.__animaHighresTimer) {
    // 换模型与快照恢复会直接改写 #hires* 控件，这里持续回读保持面板一致。
    window.__animaHighresTimer = setInterval(() => {
      const panel = byId("animaHighresPanel");
      if (!panel || panel.hidden || panel.offsetParent === null) return;
      pullFromHiresControls();
    }, 1000);
  }

  function boot() {
    installPanel();
    injectPayload();
    wrapRestore();
    wrapModelChanged();
    window.animaHighresSyncVisibility();
    window.animaHighresRefresh();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
