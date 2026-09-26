/* Anima 细节增强（Detail Refine）：同尺寸、低 denoise 的二次重绘。
 *
 * 与二采（放大 + 重绘）、输出增强（Anime6B / SeedVR2）是三件不同的事：
 *   首采         → 画什么、画在哪里
 *   细节增强      → 画得多细（不改尺寸）
 *   输出增强      → 尺寸与后处理
 * 只在 Anima 模型下显示，不污染其他模型族。
 */
(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);

  // 与后端 easy_panel_app/anima_refine.py 的 REFINE_MODES 保持一致。
  const MODES = {
    preserve: { label: "保构图", denoise: 0.08, min: 0.06, max: 0.10,
                note: "保构图：人物、道具与背景结构都尽量不动。建议 0.06–0.10。" },
    balanced: { label: "均衡", denoise: 0.12, min: 0.10, max: 0.15,
                note: "均衡：补发丝、眼睛、服装褶皱与道具细节。建议 0.10–0.15。" },
    scene: { label: "场景强化", denoise: 0.16, min: 0.14, max: 0.20,
             note: "场景强化：允许背景（水面、树林、雨、反射）更积极地重新组织。建议 0.14–0.20。" },
  };
  const MODULES = [
    ["hair", "发丝"], ["eyes", "眼睛"], ["clothing", "服装"], ["accessory", "饰品"],
    ["prop", "道具"], ["foliage", "植物"], ["water", "水面"], ["rain", "雨景"],
    ["light", "光影"], ["line", "线稿"], ["texture", "材质"],
  ];

  let refineModules = [];

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = String(value || "");
    return node.innerHTML;
  }

  function installPanel() {
    const anchor = byId("animaGenerationEnhancementMount") || byId("animaHighresMount") || byId("animaPromptPanel");
    if (!anchor || byId("animaRefinePanel")) return;
    const block = document.createElement("details");
    block.id = "animaRefinePanel";
    block.className = "anima-refine-panel";
    block.innerHTML = `
      <summary>Anima 细节增强（同尺寸低温重绘）</summary>
      <div class="small">首采决定画什么、在哪里；细节增强只决定画得多细。它不放大、不改尺寸，和二采（放大 + 重绘）互不替代。</div>
      <label class="switch" style="margin-top:6px"><input id="animaRefineEnabled" type="checkbox"><div><b>启用细节增强</b><div class="small">会多跑一次低重绘幅度的重采样，只保留最终结果（不再另存对照图）。</div></div></label>
      <div id="animaRefineBody" style="display:none">
        <div class="field-title"><span>模式</span></div>
        <div class="anima-refine-modes">
          ${Object.entries(MODES).map(([key, item]) =>
            `<button type="button" data-refine-mode="${key}" onclick="animaRefineApplyMode('${key}')"><b>${escapeHtml(item.label)}</b><span>denoise ${item.min}–${item.max}</span></button>`).join("")}
        </div>
        <div class="two" style="margin-top:8px">
          <div><div class="field-title"><span>重绘幅度</span></div><input id="animaRefineDenoise" type="number" min="0.05" max="0.20" step="0.01" value="0.12"></div>
          <div><div class="field-title"><span>步数</span></div><input id="animaRefineSteps" type="number" min="6" max="40" step="1" value="16"></div>
        </div>
        <div class="field-title" style="margin-top:8px"><span>Seed</span></div>
        <select id="animaRefineSeedMode"><option value="inherit">继承首采（便于对比）</option><option value="random">每次随机</option></select>
        <div class="field-title" style="margin-top:8px"><span>快速增强</span><span class="small">点一下追加对应细节词</span></div>
        <div class="anima-refine-modules">
          ${MODULES.map(([key, label]) =>
            `<button type="button" class="secondary" data-refine-module="${key}" onclick="animaRefineToggleModule('${key}')">＋ ${escapeHtml(label)}</button>`).join("")}
        </div>
        <div class="field-title" style="margin-top:8px"><span>Detail Prompt</span><span class="small">只写细节；首采提示词会自动保留</span></div>
        <textarea id="animaRefinePrompt" rows="2" placeholder="例如：wet reflective pavement, detailed foliage, fine rain streaks"></textarea>
        <div class="actions"><button class="secondary" type="button" onclick="animaRefineClearPrompt()">清空</button></div>
        <div id="animaRefineNote" class="small"></div>
      </div>`;
    // 挂在生成设置的同一挂载点：与高清重建并列，避免把生成级细节控制埋在提示词输入区。
    anchor.appendChild(block);
    byId("animaRefineEnabled")?.addEventListener("change", animaRefineRefresh);
    byId("animaRefineDenoise")?.addEventListener("input", animaRefineRefresh);
    byId("animaRefinePrompt")?.addEventListener("input", animaRefineRefresh);
    window.animaRefineApplyMode("balanced", true);
    window.animaRefineSyncVisibility();
  }

  window.animaRefineState = function () {
    const active = document.querySelector("[data-refine-mode].active");
    return {
      enabled: byId("animaRefineEnabled")?.checked === true,
      mode: active?.dataset.refineMode || "balanced",
      denoise: Number(byId("animaRefineDenoise")?.value || MODES.balanced.denoise),
      steps: Number(byId("animaRefineSteps")?.value || 16),
      seedMode: byId("animaRefineSeedMode")?.value || "inherit",
      modules: refineModules.slice(),
      prompt: String(byId("animaRefinePrompt")?.value || "").trim(),
    };
  };

  window.animaRefineApplyMode = function (mode, silent) {
    const preset = MODES[mode];
    if (!preset) return;
    const denoise = byId("animaRefineDenoise");
    if (denoise) {
      denoise.min = String(preset.min);
      denoise.max = String(preset.max);
      denoise.value = String(preset.denoise);
    }
    document.querySelectorAll("[data-refine-mode]").forEach((button) => {
      button.classList.toggle("active", button.dataset.refineMode === mode);
    });
    if (!silent) animaRefineRefresh();
  };

  window.animaRefineToggleModule = function (key) {
    refineModules = refineModules.includes(key)
      ? refineModules.filter((item) => item !== key)
      : refineModules.concat(key);
    document.querySelectorAll("[data-refine-module]").forEach((button) => {
      button.classList.toggle("active", refineModules.includes(button.dataset.refineModule));
    });
    animaRefineRefresh();
  };

  window.animaRefineClearPrompt = function () {
    if (byId("animaRefinePrompt")) byId("animaRefinePrompt").value = "";
    animaRefineRefresh();
  };

  function animaRefineRefresh() {
    const state = window.animaRefineState();
    const preset = MODES[state.mode] || MODES.balanced;
    const body = byId("animaRefineBody");
    if (body) body.style.display = state.enabled ? "" : "none";
    const note = byId("animaRefineNote");
    if (note) {
      const custom = state.prompt ? " + 自定义细节词" : "";
      const chosen = state.modules.length ? state.modules.length + " 个细节模块" : "未选模块";
      note.textContent = `${preset.note} 当前：denoise ${state.denoise} · ${state.steps} 步 · ${chosen}${custom}；输出尺寸与首采相同。`;
    }
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

  // 能力契约（capabilities.detail_refine）优先；catalog 未就绪时默认允许。
  function refineCapable() {
    try {
      const profile = window.currentSamplingProfile ? window.currentSamplingProfile() : null;
      const caps = (profile && profile.capabilities) || null;
      if (caps) return caps.detail_refine !== false;
    } catch (error) { /* 回退 */ }
    return true;
  }

  window.animaRefineSyncVisibility = function () {
    const panel = byId("animaRefinePanel");
    if (!panel) return;
    const isAnima = modelFamily() === "anima" && refineCapable();
    panel.hidden = !isAnima;
    if (!isAnima && byId("animaRefineEnabled")) byId("animaRefineEnabled").checked = false;
  };

  function injectPayload() {
    const original = window.payload;
    if (typeof original !== "function" || original.__animaRefineWrapped) return;
    const wrapped = function (...args) {
      const data = original.apply(this, args) || {};
      const state = window.animaRefineState();
      if (state.enabled && modelFamily() === "anima") data.animaDetailRefine = state;
      return data;
    };
    wrapped.__animaRefineWrapped = true;
    window.payload = wrapped;
  }

  function wrapRestore() {
    const original = window.restorePayloadToPanel;
    if (typeof original !== "function" || original.__animaRefineWrapped) return;
    const wrapped = function (data, ...rest) {
      const result = original.apply(this, [data, ...rest]);
      const refine = data && typeof data === "object" ? data.animaDetailRefine : null;
      if (refine && typeof refine === "object") {
        if (byId("animaRefineEnabled")) byId("animaRefineEnabled").checked = Boolean(refine.enabled);
        if (refine.mode) window.animaRefineApplyMode(refine.mode, true);
        if (refine.denoise != null && byId("animaRefineDenoise")) byId("animaRefineDenoise").value = String(refine.denoise);
        if (refine.steps != null && byId("animaRefineSteps")) byId("animaRefineSteps").value = String(refine.steps);
        if (refine.seedMode && byId("animaRefineSeedMode")) byId("animaRefineSeedMode").value = String(refine.seedMode);
        refineModules = Array.isArray(refine.modules) ? refine.modules.slice() : [];
        document.querySelectorAll("[data-refine-module]").forEach((button) => {
          button.classList.toggle("active", refineModules.includes(button.dataset.refineModule));
        });
        if (byId("animaRefinePrompt")) byId("animaRefinePrompt").value = String(refine.prompt || "");
        animaRefineRefresh();
      }
      window.animaRefineSyncVisibility();
      return result;
    };
    wrapped.__animaRefineWrapped = true;
    window.restorePayloadToPanel = wrapped;
  }

  function wrapModelChanged() {
    const original = window.modelChanged;
    if (typeof original !== "function" || original.__animaRefineWrapped) return;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      window.animaRefineSyncVisibility();
      return result;
    };
    wrapped.__animaRefineWrapped = true;
    window.modelChanged = wrapped;
  }

  function boot() {
    installPanel();
    injectPayload();
    wrapRestore();
    wrapModelChanged();
    window.animaRefineSyncVisibility();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
