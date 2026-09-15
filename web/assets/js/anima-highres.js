/* Anima 高清重建（Highres Reconstruction）：放大 → 二采 → 高清输出。
 *
 * 与「细节增强」和「输出增强」是三件不同的事：
 *   首采         → 约 1MP，决定画什么、画在哪里
 *   细节增强      → 同尺寸低 denoise 润色（不改尺寸，见 anima-refine.js）
 *   高清重建      → Anime6B 超分 → 缩放回目标倍率 → Anima 二采（本脚本）
 *
 * 参数范围不再写在本文件：统一读能力契约 profile.constraints.highres_reconstruction
 * （model_profiles.FAMILY_CONSTRAINTS → /api/models → window.currentSamplingProfile）。
 * 这里的 FALLBACK_LIMITS 仅作为 catalog 未就绪时的兑底。
 */
(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);

  // 与后端 easy_panel_app/anima_highres.py::ANIMA_HIGHRES_PRESETS 保持一致：
  // 细节 = DPM++ 2M SDE GPU / SGM Uniform（默认）；保真 = ER-SDE / SGM Uniform；
  // 纹理 = ER-SDE / beta57（低噪声纹理，需 RES4LYF 节点）。
  const PRESETS = {
    detail: { label: "二采·细节", scale: 1.50, denoise: 0.28, steps: 24, cfg: 4.2,
              sampler: "dpmpp_2m_sde_gpu", scheduler: "sgm_uniform",
              note: "⭐ 二采默认：DPM++ 2M SDE GPU / SGM Uniform，20–30 步、CFG 4.0–4.5、denoise 0.20–0.35；补发丝、褶皱与材质细节。" },
    fidelity: { label: "二采·保真", scale: 1.50, denoise: 0.24, steps: 24, cfg: 4.2,
                sampler: "er_sde", scheduler: "sgm_uniform",
                note: "保真：ER-SDE / SGM Uniform，denoise 0.20–0.30；最贴首采，只提清晰度与稳定度。" },
    texture: { label: "二采·纹理", scale: 1.50, denoise: 0.26, steps: 24, cfg: 4.2,
               sampler: "er_sde", scheduler: "beta57",
               note: "纹理：ER-SDE / beta57（alpha 0.5 / beta 0.7），denoise 0.20–0.30；更强调低噪声纹理。需要 RES4LYF 节点提供 beta57。" },
  };
  const DETAIL_TERMS =
    "fine individual hair strands, refined fabric folds, detailed clothing texture, " +
    "clean line details, small accessory details, crisp facial features";

  // catalog 未就绪时的兑底（正常路径一律走约束契约）。
  const FALLBACK_LIMITS = {
    scale: { min: 1.15, max: 2.0, step: 0.05 },
    denoise: { min: 0.20, max: 0.30, step: 0.01 },
    steps: { min: 6, max: 40, step: 1 },
    cfg: { min: 1, max: 10, step: 0.1 },
    max_long_edge: 2560,
    upscalers: ["RealESRGAN_x4plus_anime_6B.pth"],
  };

  function highresConstraints() {
    try {
      const profile = window.currentSamplingProfile ? window.currentSamplingProfile() : null;
      const value = profile && profile.constraints ? profile.constraints.highres_reconstruction : null;
      if (value && typeof value === "object") return value;
    } catch (error) { /* 回退到兑底常量 */ }
    return {};
  }

  function constraintPair(value, fallback) {
    if (Array.isArray(value) && value.length === 2 && Number.isFinite(Number(value[0]))
        && Number.isFinite(Number(value[1]))) {
      return { min: Number(value[0]), max: Number(value[1]) };
    }
    return { min: fallback.min, max: fallback.max };
  }

  function rangeLimits() {
    const contract = highresConstraints();
    return {
      scale: { ...constraintPair(contract.scale, FALLBACK_LIMITS.scale), step: FALLBACK_LIMITS.scale.step },
      denoise: { ...constraintPair(contract.denoise, FALLBACK_LIMITS.denoise), step: FALLBACK_LIMITS.denoise.step },
      steps: { ...constraintPair(contract.steps, FALLBACK_LIMITS.steps), step: FALLBACK_LIMITS.steps.step },
      cfg: { ...constraintPair(contract.cfg, FALLBACK_LIMITS.cfg), step: FALLBACK_LIMITS.cfg.step },
    };
  }

  function allowedUpscalers() {
    const value = highresConstraints().allowed_upscalers;
    if (Array.isArray(value) && value.length) return value.map(String);
    return FALLBACK_LIMITS.upscalers;
  }

  // 二采采样器/调度器下拉：选项从主采样器下拉复制（主下拉由 initSamplerOptions 建），
  // 另加一个「自动（按档位预设）」。选完会写回 #hiresSampler / #hiresScheduler。
  function refreshHighresOptions() {
    [["animaHighresSampler", "sampler"], ["animaHighresScheduler", "scheduler"]].forEach(([targetId, sourceId]) => {
      const target = byId(targetId);
      const source = byId(sourceId);
      if (!target || !source || !source.options.length) return;
      const current = String(target.value || "auto");
      const options = Array.from(source.options).filter((option) => option.value !== "auto")
        .map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.textContent)}</option>`).join("");
      target.innerHTML = '<option value="auto">自动（按档位预设）</option>' + options;
      target.value = Array.from(target.options).some((option) => option.value === current) ? current : "auto";
    });
  }

  // beta57 是 RES4LYF 注入的调度器；主下拉里没有它说明节点没装/没重启。
  function schedulerAvailable(name) {
    const source = byId("scheduler");
    if (!source) return true;
    return Array.from(source.options).some((option) => option.value === String(name));
  }

  // 把契约里的范围写回输入框（换模型 / 重启面板后立即生效，不再硬编码 min/max）。
  function applyConstraintRanges() {
    const limits = rangeLimits();
    ["animaHighresScale", "animaHighresDenoise", "animaHighresSteps", "animaHighresCfg"]
      .forEach((id) => {
        const field = byId(id);
        const limit = limits[id.replace("animaHighres", "").toLowerCase()];
        if (!field || !limit) return;
        field.min = String(limit.min);
        field.max = String(limit.max);
        field.step = String(limit.step);
      });
  }

  let scope = "auto";
  // 上一次已知的模型族。select 的 value 在下拉 change 之前就已经更新，所以不能
  // 用“进入 modelChanged 时的族”当切换前的族，只能自己累计。
  let lastKnownFamily = null;

  // 按族隔离 #hires*：进入 Anima 前先记住非 Anima 用户的二采设置，离开时恢复，
  // 避免 Anima 档位（1.5× / 0.25 / 4.8）残留到 Illustrious / SDXL 的二采控件里。
  const HIRES_FIELD_IDS = ["hiresScale", "hiresDenoise", "hiresSteps", "hiresCfg",
                          "hiresSampler", "hiresScheduler"];
  const HIRES_STASH_KEY = "easyPanelHiresStashV1";

  function readHiresFields() {
    const out = {};
    HIRES_FIELD_IDS.forEach((id) => { const field = byId(id); if (field) out[id] = String(field.value); });
    return out;
  }

  function writeHiresFields(values) {
    if (!values || typeof values !== "object") return;
    HIRES_FIELD_IDS.forEach((id) => {
      const value = values[id];
      if (value == null || value === "") return;
      const field = byId(id);
      if (field) field.value = String(value);
    });
  }

  function loadHiresStash() {
    try { return JSON.parse(sessionStorage.getItem(HIRES_STASH_KEY) || "null"); } catch (error) { return null; }
  }

  function saveHiresStash(value) {
    try {
      if (value) sessionStorage.setItem(HIRES_STASH_KEY, JSON.stringify(value));
      else sessionStorage.removeItem(HIRES_STASH_KEY);
    } catch (error) { /* 隐私模式忽略 */ }
  }

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
      <div class="small">首采约 1MP 决定构图。<b>高清重建内部就包含 Anime6B 超分</b>：先用 Anime6B 放大、缩放回目标倍率，再由 Anima 二采在更高分辨率上重建细节。所以开高清重建时不需要（也不允许）再开「输出增强」的 Anime6B —— 那是放大两次；只有「只想放大、不做二采」时才改用输出增强。与「细节增强」（同尺寸润色）互不替代。</div>
      <label class="switch" style="margin-top:6px"><input id="animaHighresEnabled" type="checkbox"><div><b>启用高清重建</b><div class="small">目标倍率 1.15–2.0×（推荐 1.25–1.5×）；Anime6B 超分已内含，开启后「输出增强」会置为关闭（避免重复放大）。作品库主作品=最终成品，首采对照图另行保存（文件名带 _base_，仅用于二采对照）。</div></div></label>
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
          <div><div class="field-title"><span>二采步数</span></div><input id="animaHighresSteps" type="number" min="6" max="40" step="1" value="24"></div>
          <div><div class="field-title"><span>二采 CFG</span></div><input id="animaHighresCfg" type="number" min="1" max="10" step="0.1" value="4.2"></div>
        </div>
        <div class="two" style="margin-top:8px">
          <div><div class="field-title"><span>二采采样器</span><span class="small">可单独指定，不再固定 ER-SDE</span></div><select id="animaHighresSampler" onchange="animaHighresRefresh()"></select></div>
          <div><div class="field-title"><span>二采调度器</span><span class="small">beta57 需 RES4LYF 节点</span></div><select id="animaHighresScheduler" onchange="animaHighresRefresh()"></select></div>
        </div>
        <div class="field-title" style="margin-top:8px"><span>高清重建提示词</span></div>
        <select id="animaHighresScope" onchange="animaHighresScopeChanged()">
          <option value="inherit">完全继承首采（只放大重绘）</option>
          <option value="auto" selected>继承 + 自动细节词（推荐）</option>
          <option value="custom">自定义二采提示词</option>
        </select>
        <div id="animaHighresCustomWrap" style="display:none;margin-top:6px">
          <div class="field-title"><span class="prompt-section-label">自定义二采提示词<button class="prompt-section-clear" id="animaHighresCustomClear" type="button" onclick="animaHighresCustomClear()">清除</button><button class="prompt-section-paste" id="animaHighresCustomPaste" type="button" onclick="animaHighresCustomPaste()">粘贴</button></span></div>
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
    // 与输出增强互斥：提前拦截，避免提交后才被后端拒绝。
    byId("animaHighresEnabled")?.addEventListener("change", () => {
      const enabled = byId("animaHighresEnabled").checked === true;
      const outputMode = String(byId("outputEnhancementMode")?.value || "off");
      if (enabled && outputMode !== "off") {
        byId("animaHighresEnabled").checked = false;
        const status = byId("status");
        if (status) status.textContent = "输出增强已开启：高清重建内部已包含 Anime6B 超分，再开会重复放大；已保持高清重建关闭。若要纯放大（不做二采），就用输出增强。";
      }
      window.animaHighresRefresh();
    });
    byId("outputEnhancementMode")?.addEventListener("change", () => {
      const mode = String(byId("outputEnhancementMode")?.value || "off");
      if (mode !== "off" && byId("animaHighresEnabled")?.checked === true) {
        byId("animaHighresEnabled").checked = false;
        const status = byId("status");
        if (status) status.textContent = "已关闭 Anima 高清重建：它内部已包含 Anime6B 超分，与输出增强重复放大；本次按「输出增强」执行。需要 Anime6B + 二采时请只开高清重建。";
        window.animaHighresRefresh();
      }
    });
    window.animaHighresApplyPreset("detail", true);
    window.animaHighresScopeChanged(true);
    const panel = byId("animaHighresPanel");
    if (panel) panel.open = true;
    refreshHighresOptions();
    window.animaHighresSyncVisibility();
  }

  function modelFamily() {
    // 单一真相源：后端 /api/models 的 samplingProfiles[model].family。
    try {
      const profile = window.currentSamplingProfile ? window.currentSamplingProfile() : null;
      if (profile && profile.family) return String(profile.family);
    } catch (error) { /* 回退到旧的文件名嗅探，仅在 catalog 未就绪时使用 */ }
    const model = String(byId("model")?.value || "").toLowerCase();
    if (model.includes("krea")) return "krea2";
    if (model.includes("anima")) return "anima";
    return "sdxl";
  }

  // 能力契约（capabilities.highres_reconstruction）优先；catalog 未就绪时默认允许。
  function highresCapable() {
    try {
      const profile = window.currentSamplingProfile ? window.currentSamplingProfile() : null;
      const caps = (profile && profile.capabilities) || null;
      if (caps) return caps.highres_reconstruction !== false && caps.anima_highres !== false;
    } catch (error) { /* 回退 */ }
    return true;
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
      preset: active?.dataset.highresPreset || "detail",
      scale: num(byId("animaHighresScale"), 1.5),
      denoise: num(byId("animaHighresDenoise"), 0.28),
      steps: Math.round(num(byId("animaHighresSteps"), 24)),
      cfg: num(byId("animaHighresCfg"), 4.2),
      sampler: String(byId("animaHighresSampler")?.value || "auto"),
      scheduler: String(byId("animaHighresScheduler")?.value || "auto"),
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
    set("hiresSampler", state.sampler);
    set("hiresScheduler", state.scheduler);
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
    const syncSelect = (inputId, sourceId) => {
      const input = byId(inputId);
      const source = byId(sourceId);
      if (!input || !source) return;
      const value = String(source.value || "");
      if (!value || value === input.value) return;
      if (!Array.from(input.options).some((option) => option.value === value)) return;
      input.value = value;
    };
    syncSelect("animaHighresSampler", "hiresSampler");
    syncSelect("animaHighresScheduler", "hiresScheduler");
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
    refreshHighresOptions();
    set("animaHighresScale", preset.scale);
    set("animaHighresDenoise", preset.denoise);
    set("animaHighresSteps", preset.steps);
    set("animaHighresCfg", preset.cfg);
    set("animaHighresSampler", preset.sampler);
    set("animaHighresScheduler", preset.scheduler);
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

  // 与提示词分区的粘贴/清除保持一致，但提示写到 tokenHint（无则写 status）。
  // 这里只改文本框，仍然经 animaHighresRefresh() 走一遍参数校验与同步。
  function highresCustomHint(text) {
    const hint = byId("tokenHint") || byId("status");
    if (hint) hint.textContent = text;
  }

  window.animaHighresCustomPaste = async function () {
    const field = byId("animaHighresCustom");
    if (!field) return;
    try {
      if (!navigator.clipboard?.readText) throw new Error("no clipboard");
      const text = (await navigator.clipboard.readText()).trim();
      if (!text) { highresCustomHint("剪贴板中没有可粘贴的文字。"); return; }
      field.value = text;
      window.animaHighresRefresh();
      field.focus();
      highresCustomHint("已从剪贴板填入自定义二采提示词。");
    } catch (error) {
      highresCustomHint("无法读取剪贴板：请允许此页面访问剪贴板，或在输入框中按 Ctrl+V。");
    }
  };

  window.animaHighresCustomClear = function () {
    const field = byId("animaHighresCustom");
    if (!field) return;
    field.value = "";
    window.animaHighresRefresh();
    field.focus();
    highresCustomHint("已清空自定义二采提示词。");
  };

  window.animaHighresRefresh = function () {
    const state = window.animaHighresState();
    applyConstraintRanges();
    const body = byId("animaHighresBody");
    if (body) body.style.display = state.enabled ? "" : "none";
    if (state.enabled) pushToHiresControls();
    const preview = byId("animaHighresDetailPreview");
    if (preview) preview.textContent = DETAIL_TERMS;

    const note = byId("animaHighresNote");
    if (!note) return;
    const lines = [];
    const [baseWidth, baseHeight] = String(byId("size")?.value || "864x1152").split("x").map(Number);
    const contract = highresConstraints();
    const maxLongEdge = Number(contract.max_long_edge || FALLBACK_LIMITS.max_long_edge) || 0;
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
    const effectiveScale = (baseWidth || 864) > 0 ? width / (baseWidth || 864) : state.scale;
    const clampNote = limited
      ? `请求 ${state.scale}×，受长边上限 ${maxLongEdge} 限制，实际约 ${effectiveScale.toFixed(2)}×`
      : `按 ${state.scale}× 执行`;
    lines.push(`预计输出 ${width}×${height}（${clampNote}）· 二采 ${state.steps} 步 · CFG ${state.cfg} · denoise ${state.denoise} · ${state.sampler} + ${state.scheduler}。`);
    if (state.enabled && state.scheduler === "beta57" && !schedulerAvailable("beta57")) {
      lines.push("⚠ 调度器 beta57 需要 RES4LYF 自定义节点；当前调度器列表里没有它，请先安装/重启 ComfyUI，否则生成会失败。");
    }
    lines.push(`超分模型：${String(allowedUpscalers()[0] || FALLBACK_LIMITS.upscalers[0]).replace(".pth", "")}（高清重建内部完成，无需再开输出增强）`);
    if (!state.enabled) lines.length = 1;
    const outputMode = String(byId("outputEnhancementMode")?.value || "off");
    if (state.enabled && outputMode !== "off") {
      lines.push("⚠ 输出增强已开启：高清重建内部已含 Anime6B 超分，两者重复放大；开启高清重建会自动关闭输出增强。");
    }
    if (state.enabled && byId("animaRefineEnabled")?.checked === true) {
      lines.push("⚠ 细节增强也已开启：本次将执行「首采 → 高清二采 → 细节重绘」共 3 次采样，耗时与显存显著增加。");
    }
    if (state.enabled && width * height > 2600 * 1300) {
      lines.push("⚠ 目标尺寸较大：8GB 显存会明显变慢，必要时把倍率降到 1.25×。");
    }
    note.textContent = lines.filter(Boolean).join(" ");
  };

  window.animaHighresPresetLabel = function (key) {
    const preset = PRESETS[String(key || "")];
    return preset ? preset.label : "";
  };

  window.animaHighresSyncVisibility = function () {
    const panel = byId("animaHighresPanel");
    if (!panel) return;
    const isAnima = modelFamily() === "anima" && highresCapable();
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
          sampler: state.sampler, scheduler: state.scheduler, preset: state.preset,
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
        refreshHighresOptions();
        [["animaHighresSampler", raw.sampler], ["animaHighresScheduler", raw.scheduler]].forEach(([id, value]) => {
          const field = byId(id);
          const next = String(value || "");
          if (!field || !next) return;
          if (Array.from(field.options).some((option) => option.value === next)) field.value = next;
        });
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
      const before = readHiresFields();
      const result = original.apply(this, args);
      const family = modelFamily();
      const previous = lastKnownFamily;
      if (previous !== null && previous !== family) {
        if (family === "anima" && previous !== "anima") {
          // 进入 Anima 前，先把用户为非 Anima 模型调过的二采设置存起来。
          if (!loadHiresStash()) saveHiresStash(before);
        } else if (family !== "anima" && previous === "anima") {
          const stash = loadHiresStash();
          if (stash) {
            writeHiresFields(stash);
            saveHiresStash(null);
          }
        }
      }
      lastKnownFamily = family;
      refreshHighresOptions();
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
