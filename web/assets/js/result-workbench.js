/* Result workbench: keep one finished generation editable instead of a dead file.
 * Reuses the existing panel form as the "state": every action below only touches
 * one input, so the next generation is a single-variable variation of the last one.
 */
(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const text = (value, fallback) => {
    const result = String(value == null ? "" : value).trim();
    return result || (fallback || "");
  };
  const esc = (value) => String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const baseName = (value) => String(value == null ? "" : value).replace(/\\/g, "/").split("/").pop() || "";
  const shortText = (value, limit) => {
    const result = String(value == null ? "" : value).trim();
    return result.length > limit ? `${result.slice(0, limit - 1)}…` : result;
  };

  let lastPayload = null;
  let lastImages = [];
  let lastBaseImages = [];
  let focusTimer = 0;

  // Easy Panel writes the hi-res first pass as "<prefix>_base_00001_.png".
  const HIRES_BASE_MARKER = "_base_";
  const COMPOSITION_TERMS = [
    "close-up", "close up", "extreme close-up", "medium shot", "full body",
    "wide shot", "long shot", "portrait", "zoomed in", "headshot",
    "upper body", "lower body", "cowboy shot", "from above", "from below",
    "side view", "front view", "back view", "perspective", "panorama",
  ];

  const isBaseImage = (image) => image && String(image.filename || "").includes(HIRES_BASE_MARKER);

  // One generic mechanism: every "只改一项" swaps exactly one prompt section.
  const SECTION_SWAP = {
    clothing: {
      label: "服装", field: "promptClothing", category: "clothing",
      tip: "只替换「服装与材质」分区；外貌、表情、姿势、构图、场景与二采设置保持不变。",
      placeholder: "例如：maid outfit, white apron, black thighhighs",
    },
    scene: {
      label: "场景", field: "promptScene", category: "scene",
      tip: "只替换「场景」分区；构图、镜头、姿势与人物保持不变。",
      placeholder: "例如：forest, tall trees, mossy ground, daylight",
    },
    pose: {
      label: "姿势", field: "promptPose", category: "pose",
      tip: "只替换「姿势」分区；服装、外貌、构图与场景保持不变。",
      placeholder: "例如：sitting, leaning against wall, crossed legs",
    },
    expression: {
      label: "表情", field: "promptExpression", category: "expression",
      tip: "只替换「表情」分区；发色、眼睛、服装与姿势保持不变。",
      placeholder: "例如：soft smile, half-closed eyes, blush",
    },
  };

  let lastSectionEdit = null;
  let swapDialog = null;

  function swapOperation(section) {
    if (section === "clothing") return "outfit_change";
    if (section === "scene") return "scene_change";
    if (section === "style") return "style_change";
    return "section_change";
  }

  function sectionPresets(category) {
    let presets = [];
    try {
      presets = Array.isArray(userPromptPresets) ? userPromptPresets : []; // eslint-disable-line no-undef
    } catch (_) {
      presets = [];
    }
    return presets.filter((item) => item && item.category === category && (item.content || item.sections));
  }

  function presetText(preset, section) {
    if (!preset) return "";
    const sections = preset.sections && typeof preset.sections === "object" ? preset.sections : {};
    return text(sections[section], text(preset.content, ""));
  }

  function sectionValue(section) {
    const config = SECTION_SWAP[section];
    return config ? text(byId(config.field)?.value, "") : "";
  }

  function sectionLabel(key) {
    return {
      subject: "人物与角色", appearance: "外貌", expression: "表情", clothing: "服装与材质",
      pose: "姿势", composition: "构图与镜头", scene: "场景", lighting: "光线",
      style: "画风与上色", naturalLanguage: "自然语言", manual: "其他补充",
    }[key] || key;
  }

  function swapResultValue(section, value, mode) {
    const current = sectionValue(section);
    if (mode !== "append" || !current) return value;
    const seen = new Set();
    const terms = [];
    for (const part of [current, value]) {
      for (const item of String(part).split(/[,;\n]+/)) {
        const term = item.trim();
        const key = term.toLowerCase();
        if (term && !seen.has(key)) {
          seen.add(key);
          terms.push(term);
        }
      }
    }
    return terms.join(", ");
  }

  const WORKBENCH_STYLE = `
.result-workbench{margin-top:8px;border:1px solid var(--line,#3a3a46);border-radius:10px;padding:8px 10px;background:rgba(255,255,255,.02)}
.result-workbench .workbench-head{display:flex;flex-wrap:wrap;gap:6px;align-items:baseline}
.result-workbench .workbench-head b{color:#cfc4ff;font-size:13px}
.result-workbench .workbench-actions{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:6px}
.result-workbench .workbench-actions button{padding:4px 9px;font-size:12px;border-radius:8px}
.result-workbench .workbench-note{margin-top:6px;color:var(--muted,#9a9aa8)}
.workbench-focus{outline:2px solid #7c8cff;outline-offset:2px;transition:outline-color .25s ease}
dialog.hires-compare{border:1px solid var(--line,#3a3a46);border-radius:12px;padding:12px;max-width:min(96vw,860px);background:#16161c;color:inherit}
dialog.hires-compare::backdrop{background:rgba(0,0,0,.55)}
dialog.hires-compare .hc-head{display:flex;justify-content:space-between;align-items:center;gap:10px}
dialog.hires-compare .hc-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px}
dialog.hires-compare figure{margin:0;display:grid;gap:4px;justify-items:center}
dialog.hires-compare img{max-width:100%;max-height:46vh;border-radius:8px;border:1px solid var(--line,#3a3a46)}
dialog.hires-compare .hc-block{margin-top:8px}
dialog.hires-compare .hc-level{font-weight:600}
dialog.section-swap select,dialog.section-swap textarea{width:100%;box-sizing:border-box}
dialog.section-swap .small label{display:inline-flex;gap:4px;align-items:center;margin-right:10px}
@media (max-width:720px){dialog.hires-compare .hc-grid{grid-template-columns:1fr}}
`;

  function injectStyle() {
    if (byId("resultWorkbenchStyle")) return;
    const style = document.createElement("style");
    style.id = "resultWorkbenchStyle";
    style.textContent = WORKBENCH_STYLE;
    document.head.appendChild(style);
  }

  function status(message) {
    const element = byId("status");
    if (element) element.textContent = message;
  }

  function focusField(id, label, message, tab) {
    if (typeof window.setStudioCreationTab === "function") window.setStudioCreationTab(tab || "prompt");
    const field = byId(id);
    if (!field) {
      status(`未找到「${label}」输入框；请手动切换到提示词分区。`);
      return;
    }
    field.scrollIntoView({ behavior: "smooth", block: "center" });
    field.focus();
    field.classList.add("workbench-focus");
    clearTimeout(focusTimer);
    focusTimer = setTimeout(() => field.classList.remove("workbench-focus"), 2400);
    status(message || `已定位到「${label}」：只修改这一项，其他参数保持不变，改完点“生成图片”。`);
  }

  function randomSeed() {
    return String(Math.floor(Math.random() * 900000000000000000) + 1);
  }

  function batchSize() {
    const count = Number.parseInt(String(byId("batchCount")?.value || "1"), 10);
    return Number.isFinite(count) && count > 0 ? Math.min(16, count) : 1;
  }

  function seedOnly() {
    const input = byId("seed");
    if (!input) return;
    const previous = String(input.value || "").trim();
    const step = BigInt(batchSize());
    let next;
    if (/^\d+$/.test(previous)) {
      try { next = (BigInt(previous) + step).toString(); } catch (_) { next = randomSeed(); }
    } else {
      next = randomSeed();
    }
    input.value = next;
    status(`已只修改 Seed：${previous || "随机"} → ${next}；模型、提示词、LoRA、尺寸和二采参数全部保持不变，点“生成图片”即可。`);
  }

  function repeat() {
    if (typeof window.generate !== "function") return;
    status("已按当前面板参数重新提交一次相同生成…");
    window.generate();
  }

  function hiresSummary(data) {
    if (text(data.illustriousMode, "precision") !== "hires") return "二采：未启用";
    const mode = text(data.hiresPromptMode, "append");
    const label = mode === "inherit" ? "继承首采" : mode === "append" ? "追加补充" : "完全独立";
    const lock = data.hiresCompositionLock === true ? " · 优先保持首采构图" : "";
    return `二采：${text(data.hiresScale, "1.3")}× / denoise ${text(data.hiresDenoise, "0.25")} / ${text(data.hiresSteps, "16")} 步 / CFG ${text(data.hiresCfg, "4")} · ${label}${lock}`;
  }

  function cardSummary() {
    const data = lastPayload || {};
    const parts = [
      baseName(data.model) || "未记录模型",
      `${text(data.width, "?")} × ${text(data.height, "?")}`,
    ];
    const customSampler = text(data.sampler, "auto") === "auto" ? "" : ` / ${data.sampler}`;
    parts.push(`${text(data.steps, "?")} 步 · CFG ${text(data.cfg, "?")}${customSampler}`);
    parts.push(hiresSummary(data));
    const loras = Array.isArray(data.loras) ? data.loras.filter((item) => text(item?.name)) : [];
    parts.push(loras.length ? `${loras.length} 个 LoRA` : "无 LoRA");
    if (lastImages.length > 1) parts.push(`本次 ${lastImages.length} 张`);
    return parts.join(" · ");
  }

  function parameterText() {
    const data = lastPayload || {};
    const loras = Array.isArray(data.loras) ? data.loras.filter((item) => text(item?.name)) : [];
    const lines = [
      `模型：${baseName(data.model) || "未知"}`,
      `尺寸：${text(data.width, "?")} × ${text(data.height, "?")}`,
      `Seed：${data.seed == null ? "随机" : data.seed}`,
      `首采：${text(data.steps, "?")} 步 / CFG ${text(data.cfg, "?")} / ${text(data.sampler, "auto")} + ${text(data.scheduler, "auto")}`,
      hiresSummary(data),
      `LoRA：${loras.length ? loras.map((item) => `${baseName(item.name)}${item.weight == null ? "" : `(${item.weight})`}`).join(", ") : "无"}`,
      "",
      "正向：",
      text(byId("compiledPositive")?.value, ""),
      "",
      "负向：",
      text(byId("compiledNegative")?.value, ""),
    ];
    return lines.join("\n");
  }

  async function copyParameters() {
    const content = parameterText();
    const fallbackCopy = () => {
      const area = document.createElement("textarea");
      area.value = content;
      area.setAttribute("readonly", "readonly");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      return ok;
    };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
          await navigator.clipboard.writeText(content);
        } catch (clipboardError) {
          // Some browsers refuse the async API when the page lost focus; the
          // selection based fallback still works in that case.
          if (!fallbackCopy()) throw clipboardError;
        }
      } else if (!fallbackCopy()) {
        throw new Error("浏览器不支持自动复制");
      }
      status("已复制本次参数（含首采正负向与二采设置），可直接粘贴到别处留档。");
    } catch (error) {
      status("复制失败：" + (error && error.message ? error.message : error));
    }
  }

  function continueHires() {
    const select = byId("illustriousMode");
    const supported = typeof window.supportsHiresClient === "function" && window.supportsHiresClient();
    if (!select || !supported) {
      status("当前模型不支持高清二次采样；如需放大请改用“输出增强”（Anime6B / SeedVR2 / Ultimate）。");
      return;
    }
    select.value = "hires";
    if (typeof window.setStudioCreationTab === "function") window.setStudioCreationTab("settings");
    if (typeof window.applyIllustriousMode === "function") window.applyIllustriousMode();
    byId("hiresControls")?.scrollIntoView({ behavior: "smooth", block: "center" });
    focusField("hiresPositive", "二采补充 Prompt",
      "已切换到高清二次采样：在「二采补充 Prompt」里只写要强化的细节（发丝、材质、表情），构图交给首采。", "settings");
  }

  async function toImg2img() {
    const name = text(lastImages[0]?.filename, "");
    const toggle = byId("img2imgEnabled");
    if (!toggle) return;
    toggle.checked = true;
    if (typeof window.toggleImg2img === "function") window.toggleImg2img();
    status("已启用整图重绘；正在把本图设为底图…");
    const select = byId("img2imgOutput");
    if (select && name) {
      const hasOption = () => Array.from(select.options).some((option) => option.value === name);
      if (!hasOption() && typeof window.loadOutputImages === "function") {
        try {
          await Promise.race([
            window.loadOutputImages(),
            new Promise((resolve) => setTimeout(resolve, 4000)),
          ]);
        } catch (_) { /* keep the manual picker */ }
      }
      if (hasOption()) {
        select.value = name;
        if (typeof window.selectImg2imgOutput === "function") window.selectImg2imgOutput();
      }
    }
    byId("img2imgControls")?.scrollIntoView({ behavior: "smooth", block: "center" });
    status("已启用整图重绘并选中本图作为底图；调整重绘幅度后点“生成图片”，即可在不改提示词的前提下重绘这张结果。");
  }

  function compositionOutlook() {
    const data = lastPayload || {};
    const denoise = Number(data.hiresDenoise);
    const mode = text(data.hiresPromptMode, "append");
    const supplement = String(data.hiresPositive || "").toLowerCase();
    const hits = COMPOSITION_TERMS.filter((term) => supplement.includes(term));
    const high = [];
    const medium = [];
    if (Number.isFinite(denoise) && denoise > 0.35) high.push(`二采重绘幅度 ${denoise} 超过 0.35`);
    if (mode === "replace" && supplement.trim()) high.push("二采使用完全独立提示词");
    if (Number.isFinite(denoise) && denoise > 0.30 && denoise <= 0.35) medium.push(`二采重绘幅度 ${denoise}`);
    if (hits.length) medium.push(`检测到构图词：${hits.slice(0, 4).join("、")}`);
    const risk = high.length ? "high" : (medium.length ? "medium" : "low");
    const keep = risk === "high" ? "低" : (risk === "medium" ? "中" : "高");
    const reasons = risk === "high" ? high : (risk === "medium" ? medium : []);
    if (!reasons.length) {
      reasons.push(`二采重绘幅度 ${Number.isFinite(denoise) ? denoise : "—"}，未检测到构图词`);
    }
    return { risk, keep, reason: reasons.join("；") };
  }

  function hiresPromptDiff() {
    const data = lastPayload || {};
    const mode = text(data.hiresPromptMode, "append");
    const supplement = text(data.hiresPositive, "");
    const items = supplement ? supplement.split(/[,;\n]+/).map((item) => item.trim()).filter(Boolean).slice(0, 24) : [];
    if (mode === "inherit") return { title: "二采沿用首采提示词（无变化）", items: [] };
    if (mode === "replace") {
      return { title: "二采使用完全独立提示词（不继承首采）", items };
    }
    return { title: items.length ? `二采在首采基础上追加 ${items.length} 项` : "二采未填写补充词（等同继承）", items };
  }

  function hiresParameterDiff() {
    const data = lastPayload || {};
    const scale = Number(data.hiresScale);
    const baseWidth = Number(data.width);
    const baseHeight = Number(data.height);
    const expected = Number.isFinite(scale) && baseWidth && baseHeight
      ? `${Math.round(baseWidth * scale / 8) * 8} × ${Math.round(baseHeight * scale / 8) * 8}`
      : "—";
    return {
      size: `${text(data.width, "?")} × ${text(data.height, "?")} → ${expected}`,
      seed: String(data.seed == null ? "随机" : data.seed),
      hires: `${text(data.hiresScale, "1.3")}× · denoise ${text(data.hiresDenoise, "0.25")} · ${text(data.hiresSteps, "16")} 步 · CFG ${text(data.hiresCfg, "4")}`,
    };
  }

  function ensureCompareDialog() {
    let dialog = byId("hiresCompareDialog");
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.id = "hiresCompareDialog";
    dialog.className = "hires-compare";
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog || (event.target.closest && event.target.closest("[data-compare-close]"))) dialog.close();
    });
    document.body.appendChild(dialog);
    return dialog;
  }

  function openCompare() {
    if (!lastBaseImages.length || !lastImages.length) return;
    const base = lastBaseImages[0];
    const final = lastImages[0];
    const outlook = compositionOutlook();
    const promptDiff = hiresPromptDiff();
    const parameters = hiresParameterDiff();
    const dialog = ensureCompareDialog();
    dialog.innerHTML = `
      <div class="hc-head"><b>首采 / 二采对照</b><button class="secondary" type="button" data-compare-close>关闭</button></div>
      <div class="hc-grid">
        <figure><figcaption>首采（决定构图）</figcaption>
          <img alt="首采结果" data-role="base" src="/output?name=${encodeURIComponent(base.filename)}">
          <span class="small" data-role="baseSize">${esc(parameters.size.split(" → ")[0])}</span>
          <span class="small">Seed ${esc(parameters.seed)}</span></figure>
        <figure><figcaption>二采（补细节）</figcaption>
          <img alt="二采结果" data-role="final" src="/output?name=${encodeURIComponent(final.filename)}">
          <span class="small" data-role="finalSize">${esc(parameters.size.split(" → ")[1] || "")}</span>
          <span class="small">Seed ${esc(parameters.seed)}</span></figure>
      </div>
      <div class="hc-block"><b>二采参数</b><div class="small">${esc(parameters.hires)} · ${esc(text(lastPayload?.hiresPromptMode, "append") === "inherit" ? "继承首采" : text(lastPayload?.hiresPromptMode, "append") === "append" ? "追加补充" : "完全独立")}${lastPayload?.hiresCompositionLock === true ? " · 优先保持首采构图" : ""}</div></div>
      <div class="hc-block"><b>提示词变化</b><div class="small">${esc(promptDiff.title)}${promptDiff.items.length ? `<br>${promptDiff.items.map((item) => `+ ${esc(item)}`).join("<br>")}` : ""}</div></div>
      <div class="hc-block"><b>参数变化</b><div class="small">尺寸 ${esc(parameters.size)}<br>Seed ${esc(parameters.seed)}（两阶段相同）</div></div>
      <div class="hc-block"><span class="hc-level">构图保持：${esc(outlook.keep)}</span><div class="small">原因：${esc(outlook.reason)}（基于二采参数与补充词的规则判断，不是对两张图做视觉分析）</div></div>`;
    dialog.querySelectorAll("img").forEach((image) => {
      image.addEventListener("load", () => {
        const target = dialog.querySelector(`[data-role="${image.dataset.role}Size"]`);
        if (target) target.textContent = `实际 ${image.naturalWidth} × ${image.naturalHeight}`;
      });
    });
    dialog.showModal();
  }

  function ensureSwapDialog() {
    if (swapDialog) return swapDialog;
    swapDialog = document.createElement("dialog");
    swapDialog.id = "sectionSwapDialog";
    swapDialog.className = "hires-compare section-swap";
    swapDialog.addEventListener("click", (event) => {
      if (event.target === swapDialog) swapDialog.close();
    });
    swapDialog.addEventListener("input", () => renderSwapPreview());
    swapDialog.addEventListener("change", () => renderSwapPreview());
    swapDialog.addEventListener("click", handleSwapClick);
    document.body.appendChild(swapDialog);
    return swapDialog;
  }

  let swapSection = "";

  function swapChosenValue() {
    const dialog = swapDialog;
    if (!dialog) return "";
    const preset = dialog.querySelector('[data-swap="preset"]')?.value || "";
    if (preset) return preset;
    return text(dialog.querySelector('[data-swap="custom"]')?.value, "");
  }

  function swapChosenMode() {
    const dialog = swapDialog;
    return dialog?.querySelector('[data-swap="mode"]:checked')?.value || "replace";
  }

  function renderSwapPreview() {
    const dialog = swapDialog;
    if (!dialog) return;
    const config = SECTION_SWAP[swapSection];
    if (!config) return;
    const value = swapChosenValue();
    const mode = swapChosenMode();
    const current = sectionValue(swapSection) || "（空）";
    const result = value ? swapResultValue(swapSection, value, mode) : "";
    const preview = dialog.querySelector('[data-swap="preview"]');
    if (preview) {
      preview.innerHTML = `
        <div class="small"><b>${esc(sectionLabel(swapSection))}</b>：${esc(current)} → ${esc(result || "（未填写）")}</div>
        <div class="small">保持：${esc(Object.keys(SECTION_SWAP).filter((key) => key !== swapSection).map(sectionLabel).join("、"))}、构图与镜头、二采设置、模型与 LoRA</div>`;
    }
    const button = dialog.querySelector('[data-swap="apply"]');
    if (button) button.disabled = !value;
    const applyOnly = dialog.querySelector('[data-swap="applyOnly"]');
    if (applyOnly) applyOnly.disabled = !value;
  }

  function openSectionSwap(section) {
    const config = SECTION_SWAP[section];
    if (!config) return;
    swapSection = section;
    const dialog = ensureSwapDialog();
    const presets = sectionPresets(config.category);
    const options = presets
      .map((item) => `<option value="${esc(presetText(item, section))}">${esc(item.name)}</option>`)
      .join("");
    dialog.innerHTML = `
      <div class="hc-head"><b>只换${esc(config.label)}</b><button class="secondary" type="button" data-swap="close">取消</button></div>
      <div class="small" style="margin-top:6px">${esc(config.tip)}</div>
      <div class="hc-block"><b>当前${esc(config.label)}</b><div class="small">${esc(sectionValue(section) || "（当前分区为空）")}</div></div>
      <div class="hc-block"><b>替换为</b>
        ${presets.length ? `<select data-swap="preset"><option value="">— 我的${esc(config.label)}预设（${presets.length} 条）—</option>${options}</select>` : ""}
        <textarea data-swap="custom" rows="2" style="margin-top:6px" placeholder="${esc(config.placeholder)}"></textarea>
      </div>
      <div class="hc-block"><b>方式</b>
        <label class="small"><input type="radio" name="swapMode" data-swap="mode" value="replace" checked> 替换（清空旧内容）</label>
        <label class="small" style="margin-left:10px"><input type="radio" name="swapMode" data-swap="mode" value="append"> 追加（保留旧内容，适合加配饰）</label>
      </div>
      <div class="hc-block" data-swap="preview"></div>
      <div class="hc-block"><button class="primary" type="button" data-swap="apply">生成新版本</button>
        <button class="secondary" type="button" data-swap="applyOnly" style="margin-left:6px">仅应用到表单</button></div>`;
    renderSwapPreview();
    dialog.showModal();
  }

  function handleSwapClick(event) {
    const target = event.target.closest ? event.target.closest("[data-swap]") : null;
    if (!target) return;
    const action = target.dataset.swap;
    if (action === "close") swapDialog.close();
    else if (action === "apply") applySectionSwap(true);
    else if (action === "applyOnly") applySectionSwap(false);
  }

  function applySectionSwap(generate) {
    const config = SECTION_SWAP[swapSection];
    const value = swapChosenValue();
    const mode = swapChosenMode();
    if (!config || !value) return;
    const field = byId(config.field);
    if (!field) {
      status(`当前面板没有「${config.label}」分区输入框；请先刷新面板。`);
      return;
    }
    const before = String(field.value || "").trim();
    const after = swapResultValue(swapSection, value, mode);
    field.value = after;
    if (typeof window.promptEditorChanged === "function") window.promptEditorChanged();
    // Record the edit for the snapshot / library.  "replace" is deliberate: the
    // field already holds the merged text, and the backend must not append twice.
    lastSectionEdit = { section: swapSection, mode, originalMode: mode, before, after, value: after };
    if (typeof window.setStudioCreationTab === "function") window.setStudioCreationTab("prompt");
    status(`已把「${config.label}」改为：${after}（${mode === "append" ? "追加" : "替换"}）。其他分区、模型、LoRA、尺寸与二采设置保持不变。`);
    swapDialog.close();
    renderWorkbench();
    if (generate && typeof window.generate === "function") window.generate();
  }

  function renderWorkbench() {
    const root = ensureContainer();
    if (!root) return;
    if (!lastImages.length) {
      root.hidden = true;
      root.innerHTML = "";
      return;
    }
    root.hidden = false;
    root.innerHTML = `
      <div class="workbench-head"><b>本次生成 · 可继续创作</b><span class="small">${esc(cardSummary())}</span></div>
      <div class="workbench-actions">
        <button class="secondary" type="button" data-workbench="continue">✏️ 继续编辑</button>
        <button class="secondary" type="button" data-workbench="seed">🎲 只换 Seed</button>
        <button class="secondary" type="button" data-workbench="repeat">🔁 重复生成</button>
        <button class="secondary" type="button" data-workbench="copy">📋 复制参数</button>
      </div>
      <div class="workbench-actions"><span class="small">只改一项：</span>
        <button class="secondary" type="button" data-swap-section="clothing">换服装</button>
        <button class="secondary" type="button" data-swap-section="scene">换场景</button>
        <button class="secondary" type="button" data-swap-section="pose">换姿势</button>
        <button class="secondary" type="button" data-swap-section="expression">换表情</button>
        <button class="secondary" type="button" data-workbench="hires">🖼 继续二采</button>
        <button class="secondary" type="button" data-workbench="img2img">♻️ 转整图重绘</button>
        ${lastBaseImages.length ? '<button class="secondary" type="button" data-workbench="compare">🔍 首采 / 二采对照</button>' : ""}
      </div>
      <div class="small workbench-note">${lastSectionEdit ? `本版本变化：${esc(sectionLabel(lastSectionEdit.section))} ${esc(shortText(lastSectionEdit.before, 36) || "空")} → ${esc(shortText(lastSectionEdit.after, 36))}（其余分区、模型、LoRA、采样与二采保持）；` : ""}改动只作用于下一次生成：结果会作为子版本记录在生成快照 / 作品库（可复现、可查看父子谱系）。</div>`;
  }

  function bindActions(root) {
    root.addEventListener("click", (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      const focusId = button.dataset ? button.dataset.focus : "";
      const swapSectionKey = button.dataset ? button.dataset.swapSection : "";
      if (swapSectionKey) {
        openSectionSwap(swapSectionKey);
        return;
      }
      if (focusId) {
        focusField(focusId, button.dataset.label || focusId);
        return;
      }
      const action = button.dataset ? button.dataset.workbench : "";
      if (action === "continue") {
        focusField("promptSubject", "人物与角色",
          "已回到提示词分区；只修改需要变化的部分，其他参数保持不变，改完点“生成图片”。");
      } else if (action === "seed") seedOnly();
      else if (action === "repeat") repeat();
      else if (action === "copy") copyParameters();
      else if (action === "hires") continueHires();
      else if (action === "img2img") toImg2img();
      else if (action === "compare") openCompare();
    });
  }

  function watchResult(result) {
    if (typeof MutationObserver !== "function") return;
    const observer = new MutationObserver(() => {
      const root = byId("resultWorkbench");
      if (!root || root.hidden) return;
      // "Submitting…" / "not generated yet" placeholders must not keep showing
      // the previous generation's actions.
      if (!result.querySelector("img")) root.hidden = true;
    });
    observer.observe(result, { childList: true, subtree: true });
  }

  function ensureContainer() {
    let root = byId("resultWorkbench");
    if (root) return root;
    const result = byId("result");
    if (!result) return null;
    root = document.createElement("div");
    root.id = "resultWorkbench";
    root.className = "result-workbench";
    root.hidden = true;
    result.insertAdjacentElement("afterend", root);
    bindActions(root);
    watchResult(result);
    return root;
  }

  function capturePayload() {
    if (typeof window.payload !== "function" || window.payload.__workbenchWrapped) return;
    const original = window.payload;
    const wrapped = function () {
      const data = original.apply(this, arguments);
      if (data && typeof data === "object") {
        lastPayload = data;
        // The section swap already edited the field; this record only carries the
        // edit into the snapshot / library so a version can show 旧 → 新.
        if (lastSectionEdit) data.sectionEdit = { ...lastSectionEdit };
      }
      return data;
    };
    wrapped.__workbenchWrapped = true;
    window.payload = wrapped;
  }

  function wrapRender() {
    const original = window.renderGeneratedImages;
    if (typeof original !== "function" || original.__workbenchWrapped) return;
    const wrapped = function (images) {
      const all = Array.isArray(images) ? images.filter((item) => item && item.filename) : [];
      const base = all.filter(isBaseImage);
      const finals = all.filter((item) => !isBaseImage(item));
      const visible = finals.length ? finals : all;
      const args = Array.prototype.slice.call(arguments);
      args[0] = visible;
      const output = original.apply(this, args);
      // The first-stage image is an output the panel owns, not a gallery item:
      // it only feeds the 首采 / 二采 comparison dialog.
      lastBaseImages = base;
      lastImages = visible;
      renderWorkbench();
      return output;
    };
    wrapped.__workbenchWrapped = true;
    window.renderGeneratedImages = wrapped;
  }

  injectStyle();
  capturePayload();
  wrapRender();
}());
