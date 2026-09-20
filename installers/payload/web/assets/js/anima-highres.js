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
 *
 * 面板位置：生成设置 → 高级参数 下方（#animaHighresMount），默认折叠；
 * window.animaHighresReveal() 可展开并滚过去。
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

  // 与后端 HAND_REPAIR_DEFAULTS / hand_repair 约束保持一致。
  const HAND_DEFAULTS = {
    denoise: 0.45,
    steps: 24,
    grow: 6,
    cfg: 4.2,
    positive: "perfect hands, five fingers, detailed hands, natural hand pose",
    negative: "bad hands, extra fingers, missing fingers, fused fingers, malformed hands, extra limbs, wrong finger count",
  };
  const HAND_FALLBACK_LIMITS = {
    denoise: { min: 0.20, max: 0.65, step: 0.01 },
    steps: { min: 8, max: 40, step: 1 },
    grow: { min: 0, max: 48, step: 1 },
  };
  // 已上传的蒙版/原图文件名（ComfyUI input 目录里的相对名），随 payload 提交。
  let handUpload = { image: "", mask: "" };
  // 蒙版绘制器状态（与 Illustrious「局部修复」同一套交互：画笔/橡皮/撤销/清空，红=重绘区）。
  let handBaseImg = null, handBaseFile = null, handBaseUrl = "", handMaskCv = null,
      handTintCv = null, handUndo = [], handDrawing = false, handLast = null,
      handTool = "paint";

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

  function handLimits() {
    const contract = highresConstraints().hand_repair;
    const source = contract && typeof contract === "object" ? contract : {};
    const merge = (pair, fallback) => {
      const value = Array.isArray(pair) && pair.length === 2 ? pair : null;
      return {
        min: value ? Number(value[0]) : fallback.min,
        max: value ? Number(value[1]) : fallback.max,
        step: fallback.step,
      };
    };
    return {
      denoise: merge(source.denoise, HAND_FALLBACK_LIMITS.denoise),
      steps: merge(source.steps, HAND_FALLBACK_LIMITS.steps),
      grow: merge(source.grow, HAND_FALLBACK_LIMITS.grow),
    };
  }

  function setHandStatus(text, error) {
    const node = byId("animaHighresHandStatus");
    if (!node) return;
    node.textContent = text;
    node.classList.toggle("diagnostic-error", !!error);
  }

  window.animaHighresHandState = function () {
    return {
      enabled: byId("animaHighresHandEnabled")?.checked === true,
      image: handUpload.image,
      mask: handUpload.mask,
      denoise: num(byId("animaHighresHandDenoise"), HAND_DEFAULTS.denoise),
      steps: Math.round(num(byId("animaHighresHandSteps"), HAND_DEFAULTS.steps)),
      grow: Math.round(num(byId("animaHighresHandGrow"), HAND_DEFAULTS.grow)),
      cfg: num(byId("animaHighresHandCfg"), HAND_DEFAULTS.cfg),
      positive: String(byId("animaHighresHandPositive")?.value ?? HAND_DEFAULTS.positive),
      negative: String(byId("animaHighresHandNegative")?.value ?? HAND_DEFAULTS.negative),
    };
  };

  // 蒙版上传：复用 /api/upload-inpaint（会归一化成 PNG 放进 ComfyUI input）。
  async function handUploadFiles(imageFile, maskBlob, label) {
    const form = new FormData();
    form.append("image", imageFile, imageFile.name || "anima_hand_base.png");
    form.append("mask", maskBlob, "anima_hand_mask.png");
    setHandStatus("正在上传蒙版…");
    try {
      const response = await fetch("/api/upload-inpaint", { method: "POST", body: form });
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      handUpload = { image: String(data.image || ""), mask: String(data.mask || "") };
      setHandStatus(`蒙版已就绪：${label}；生成时会在 Anime6B 超分前先修手（多一次采样）。`);
      window.animaHighresRefresh();
      return true;
    } catch (error) {
      handUpload = { image: "", mask: "" };
      setHandStatus("蒙版上传失败：" + error.message, true);
      return false;
    }
  }

  // 导入现成蒙版文件（原图可选，只选蒙版时把同一个文件当 image 提交）。
  window.animaHighresHandUpload = async function () {
    const maskFile = byId("animaHighresHandMask")?.files?.[0] || null;
    if (!maskFile) return;
    const imageFile = byId("animaHighresHandImage")?.files?.[0] || maskFile;
    const onlyMask = imageFile === maskFile ? "（只上传了蒙版，工作流只用蒙版）" : "";
    await handUploadFiles(imageFile, maskFile, maskFile.name + onlyMask);
  };

  // ---- 面板内自画蒙版（与 Illustrious「局部修复」同一套交互） ----
  function handCanvas() { return byId("animaHighresHandCanvas"); }
  function handCtx() { return handMaskCv ? handMaskCv.getContext("2d", { willReadFrequently: true }) : null; }

  function handRender() {
    const canvas = handCanvas();
    if (!canvas || !handBaseImg) return;
    const width = canvas.width, height = canvas.height;
    if (handMaskCv) {
      // 红色叠加不能直接在视图画布上用 source-in（底图不透明会整张变红）：
      // 先用临时画布把蒙版染红，再叠到原图上。
      if (!handTintCv) handTintCv = document.createElement("canvas");
      handTintCv.width = width;
      handTintCv.height = height;
      const tint = handTintCv.getContext("2d", { willReadFrequently: true });
      tint.clearRect(0, 0, width, height);
      tint.drawImage(handMaskCv, 0, 0, width, height);
      tint.globalCompositeOperation = "source-in";
      tint.fillStyle = "rgba(255,60,60,0.55)";
      tint.fillRect(0, 0, width, height);
    }
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(handBaseImg, 0, 0, width, height);
    if (handTintCv) ctx.drawImage(handTintCv, 0, 0, width, height);
  }

  function handPushUndo() {
    if (!handMaskCv) return;
    handUndo.push(handCtx().getImageData(0, 0, handMaskCv.width, handMaskCv.height));
    while (handUndo.length > 12) handUndo.shift();
  }

  function handPointerPos(event) {
    const canvas = handCanvas(), rect = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) * canvas.width / (rect.width || canvas.width),
      y: (event.clientY - rect.top) * canvas.height / (rect.height || canvas.height),
    };
  }

  function handStroke(from, to) {
    const ctx = handCtx();
    if (!ctx) return;
    const radius = Math.max(2, Number(byId("animaHighresHandBrush")?.value || 48) / 2);
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = radius * 2;
    ctx.globalCompositeOperation = handTool === "erase" ? "destination-out" : "source-over";
    ctx.strokeStyle = "#ffffff";
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(to.x, to.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    handRender();
  }

  function handPointerDown(event) {
    if (!handMaskCv) { setHandStatus("请先载入底图。", true); return; }
    event.preventDefault();
    handDrawing = true;
    handPushUndo();
    const point = handPointerPos(event);
    handLast = point;
    handStroke(point, point);
    handCanvas()?.setPointerCapture?.(event.pointerId);
  }

  function handPointerMove(event) {
    if (!handDrawing) return;
    event.preventDefault();
    const point = handPointerPos(event);
    handStroke(handLast || point, point);
    handLast = point;
  }

  function handPointerUp() { handDrawing = false; handLast = null; }

  function handMaskPixels() {
    if (!handMaskCv) return 0;
    const data = handCtx().getImageData(0, 0, handMaskCv.width, handMaskCv.height).data;
    let count = 0;
    for (let i = 3; i < data.length; i += 4) if (data[i] > 8) count += 1;
    return count;
  }

  function handSetBase(blob, label) {
    if (handBaseUrl) URL.revokeObjectURL(handBaseUrl);
    handBaseUrl = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      handBaseImg = image;
      handBaseFile = new File([blob], "anima_hand_base.png", { type: blob.type || "image/png" });
      const canvas = handCanvas();
      const scale = Math.min(1, 1024 / Math.max(image.naturalWidth, image.naturalHeight));
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      handMaskCv = document.createElement("canvas");
      handMaskCv.width = canvas.width;
      handMaskCv.height = canvas.height;
      handUndo = [];
      handTintCv = null;
      handRender();
      setHandStatus(`已载入底图${label ? "（" + label + "）" : ""}：涂出要修的手（红色区域），再点「上传蒙版」。`);
    };
    image.onerror = () => setHandStatus("底图载入失败，请换一张图片。", true);
    image.src = handBaseUrl;
  }

  async function refreshHandBaseOptions() {
    const select = byId("animaHighresHandBase");
    if (!select || select.dataset.loaded === "1") return;
    try {
      const data = await (await fetch("/api/output-images")).json();
      select.innerHTML = '<option value="">— 从最近生成结果选择 —</option>' +
        (data.entries || []).map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`).join("");
      select.dataset.loaded = "1";
    } catch (error) { /* 保持空列表，用户仍可上传底图 */ }
  }

  window.animaHighresHandLoadBase = async function () {
    const name = String(byId("animaHighresHandBase")?.value || "");
    if (!name) { setHandStatus("请先选择一张最近生成的结果。", true); return; }
    setHandStatus("正在读取底图…");
    try {
      const response = await fetch("/output?name=" + encodeURIComponent(name));
      if (!response.ok) throw new Error("HTTP " + response.status);
      handSetBase(await response.blob(), name);
    } catch (error) { setHandStatus("读取底图失败：" + error.message, true); }
  };

  window.animaHighresHandUploadBase = function (file) {
    if (file) handSetBase(file, file.name);
  };

  // 「上次首采图」：从快照里取最新的对比图（_base），顺便把 seed 与尺寸填回面板，
  // 这样用同一张构图重跑时蒙版位置才对得上。
  window.animaHighresHandLoadLastBase = async function () {
    setHandStatus("正在查找上次首采图…");
    try {
      const data = await (await fetch("/api/snapshots")).json();
      const entry = (data.entries || []).find((item) => Array.isArray(item.comparisonOutputs) && item.comparisonOutputs.length);
      if (!entry) throw new Error("还没有首采对照图（先开一次高清重建生成）");
      const name = String(entry.comparisonOutputs[0]);
      const response = await fetch("/output?name=" + encodeURIComponent(name) + "&subfolder=EasyPanel_aux");
      if (!response.ok) throw new Error("HTTP " + response.status);
      handSetBase(await response.blob(), name);
      const payload = entry.payload || {};
      const notes = [];
      if (payload.seed != null) {
        const seed = byId("seed");
        if (seed) { seed.value = String(payload.seed); notes.push("seed " + payload.seed); }
      }
      if (payload.width && payload.height) {
        const value = `${payload.width}x${payload.height}`;
        const size = byId("size");
        if (size && Array.from(size.options).some((option) => option.value === value)) {
          size.value = value;
          size.dispatchEvent(new Event("change", { bubbles: true }));
          notes.push(value);
        }
      }
      setHandStatus(`已载入上次首采图（${notes.join(" · ") || "参数未记录"}）：用同一 seed 重跑才对齐；涂完手点「上传蒙版」。`);
      window.animaHighresRefresh();
    } catch (error) { setHandStatus("载入上次首采图失败：" + error.message, true); }
  };

  window.animaHighresHandSetTool = function (tool) {
    handTool = tool === "erase" ? "erase" : "paint";
    byId("animaHighresHandPaint")?.classList.toggle("active", handTool === "paint");
    byId("animaHighresHandErase")?.classList.toggle("active", handTool === "erase");
  };

  window.animaHighresHandBrushChanged = function () {
    const label = byId("animaHighresHandBrushValue");
    if (label) label.textContent = String(byId("animaHighresHandBrush")?.value || "");
  };

  window.animaHighresHandUndo = function () {
    if (!handMaskCv || !handUndo.length) return;
    handCtx().putImageData(handUndo.pop(), 0, 0);
    handRender();
  };

  window.animaHighresHandResetMask = function () {
    if (handMaskCv) {
      handPushUndo();
      handCtx().clearRect(0, 0, handMaskCv.width, handMaskCv.height);
      handRender();
    }
    handUpload = { image: "", mask: "" };
    setHandStatus("已清空蒙版（需要重新上传才能生效）。");
    window.animaHighresRefresh();
  };

  window.animaHighresHandSaveMask = async function () {
    if (!handMaskCv || !handBaseFile) { setHandStatus("请先载入底图并涂出要修的手。", true); return; }
    const pixels = handMaskPixels();
    if (!pixels) { setHandStatus("蒙版是空的：先在图上涂出要修的手（红色区域）。", true); return; }
    const exporter = document.createElement("canvas");
    exporter.width = handMaskCv.width;
    exporter.height = handMaskCv.height;
    const ctx = exporter.getContext("2d");
    ctx.fillStyle = "#000000";
    ctx.fillRect(0, 0, exporter.width, exporter.height);
    ctx.drawImage(handMaskCv, 0, 0);
    const blob = await new Promise((resolve) => exporter.toBlob(resolve, "image/png"));
    if (!blob) { setHandStatus("蒙版导出失败，请重试。", true); return; }
    await handUploadFiles(handBaseFile, blob, `${handMaskCv.width}×${handMaskCv.height} 画布 · ${pixels.toLocaleString()} px 重绘区`);
  };

  window.animaHighresHandClear = function () {
    handUpload = { image: "", mask: "" };
    if (handMaskCv) {
      handCtx().clearRect(0, 0, handMaskCv.width, handMaskCv.height);
      handRender();
    }
    ["animaHighresHandImage", "animaHighresHandMask", "animaHighresHandBaseFile"].forEach((id) => {
      const field = byId(id);
      if (field) field.value = "";
    });
    setHandStatus("已清除蒙版。");
    window.animaHighresRefresh();
  };

  // 由「手部修复」工作台调用：把工作台里已上传好的原图/蒙版直接接到本面板。
  window.animaHighresHandReceive = function (imageName, maskName, label) {
    handUpload = { image: String(imageName || ""), mask: String(maskName || "") };
    const handEnabled = byId("animaHighresHandEnabled");
    if (handEnabled) handEnabled.checked = true;
    const highres = byId("animaHighresEnabled");
    if (highres && !highres.checked) {
      highres.checked = true;
      highres.dispatchEvent(new Event("change", { bubbles: true }));
    }
    setHandStatus(`已从手部工作台接收蒙版${label ? "（" + label + "）" : ""}；生成时会在 Anime6B 超分前先修复手部。`);
    const block = byId("animaHighresHandBlock");
    if (block) block.open = true;
    window.animaHighresRefresh();
    revealPanel();
  };

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
    // 手部修复的滑块范围同样来自约束契约（anima 族 hand_repair）。
    const hand = handLimits();
    [["animaHighresHandDenoise", hand.denoise], ["animaHighresHandSteps", hand.steps],
     ["animaHighresHandGrow", hand.grow]].forEach(([id, limit]) => {
      const field = byId(id);
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
    // 挂在「生成设置 → 高级参数」下方的 #animaHighresMount（HTML 缓存未更新时回退到提示词面板）。
    const anchor = byId("animaHighresMount") || byId("animaPromptPanel");
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
        <details id="animaHighresHandBlock" style="margin-top:10px">
          <summary>二采前手部修复（可选 · 蒙版 inpaint）</summary>
          <div class="small">在 Anime6B 超分<b>之前</b>用一张黑白蒙版（白=重绘区）把手重画一次：先改结构，再放大重建细节。下面可以直接画：先载入底图（推荐「上次首采图」，会顺便把 seed 与尺寸对齐），涂出要修的手再上传蒙版。</div>
          <label class="switch" style="margin-top:6px"><input id="animaHighresHandEnabled" type="checkbox"><div><b>启用二采前手部修复</b><div class="small">会多一次采样（首采 → 手部修复 → 高清二采）；修复结果另存到 EasyPanel_aux 供对照，不进作品库。</div></div></label>
          <div id="animaHighresHandBody" style="display:none">
            <div class="field-title" style="margin-top:6px"><span>① 载入底图</span><span class="small">蒙版要与本次首采对齐：用「上次首采图」最准</span></div>
            <div class="anima-hand-row">
              <select id="animaHighresHandBase" style="flex:1;min-width:120px"><option value="">— 从最近生成结果选择 —</option></select>
              <button class="secondary" type="button" onclick="animaHighresHandLoadBase()">载入</button>
              <button class="secondary" type="button" onclick="animaHighresHandLoadLastBase()">上次首采图（对齐 seed/尺寸）</button>
              <label class="secondary anima-hand-file">上传底图<input id="animaHighresHandBaseFile" type="file" accept="image/*" onchange="animaHighresHandUploadBase(this.files[0])"></label>
            </div>
            <div class="field-title" style="margin-top:6px"><span>② 涂出要修的手</span><span class="small">红色 = 重绘区</span></div>
            <div class="anima-hand-row">
              <button id="animaHighresHandPaint" class="secondary active" type="button" onclick="animaHighresHandSetTool('paint')">画笔</button>
              <button id="animaHighresHandErase" class="secondary" type="button" onclick="animaHighresHandSetTool('erase')">橡皮</button>
              <span class="small">笔刷</span><input id="animaHighresHandBrush" type="range" min="4" max="200" step="2" value="48" style="max-width:110px" oninput="animaHighresHandBrushChanged()"><span id="animaHighresHandBrushValue" class="small">48</span>
              <button class="secondary" type="button" onclick="animaHighresHandUndo()">撤销</button>
              <button class="secondary" type="button" onclick="animaHighresHandResetMask()">清空</button>
              <button type="button" onclick="animaHighresHandSaveMask()">③ 上传蒙版</button>
            </div>
            <canvas id="animaHighresHandCanvas" width="1" height="1" style="display:block;width:100%;height:auto;max-height:420px;margin-top:6px;border:1px solid var(--line);border-radius:8px;background:#111;touch-action:none;cursor:crosshair"></canvas>
            <div id="animaHighresHandStatus" class="small">尚未上传蒙版：可先「上次首采图」再涂手，然后点「上传蒙版」。</div>
            <details style="margin-top:6px"><summary class="small">导入已画好的蒙版文件</summary>
              <div class="two" style="margin-top:6px">
                <div><div class="field-title"><span>原图（可选）</span></div><input id="animaHighresHandImage" type="file" accept="image/*"></div>
                <div><div class="field-title"><span>蒙版（白=重绘区）</span></div><input id="animaHighresHandMask" type="file" accept="image/*"></div>
              </div>
            </details>
            <div class="two" style="margin-top:6px">
              <div><div class="field-title"><span>重绘幅度 denoise</span></div><input id="animaHighresHandDenoise" type="number" min="0.2" max="0.65" step="0.01" value="0.45"></div>
              <div><div class="field-title"><span>修复步数</span></div><input id="animaHighresHandSteps" type="number" min="8" max="40" step="1" value="24"></div>
            </div>
            <div class="two" style="margin-top:6px">
              <div><div class="field-title"><span>蒙版扩张 px</span></div><input id="animaHighresHandGrow" type="number" min="0" max="48" step="1" value="6"></div>
              <div><div class="field-title"><span>修复 CFG</span></div><input id="animaHighresHandCfg" type="number" min="1" max="10" step="0.1" value="4.2"></div>
            </div>
            <div class="field-title" style="margin-top:6px"><span>手部正向词</span></div>
            <textarea id="animaHighresHandPositive" rows="2"></textarea>
            <div class="field-title" style="margin-top:6px"><span>手部负向词</span></div>
            <textarea id="animaHighresHandNegative" rows="2"></textarea>
            <div class="actions" style="margin-top:6px"><button class="secondary" type="button" onclick="animaHighresHandClear()">清除蒙版</button></div>
          </div>
        </details>
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
     "animaHighresSteps", "animaHighresCfg", "animaHighresHandEnabled",
     "animaHighresHandDenoise", "animaHighresHandSteps", "animaHighresHandGrow",
     "animaHighresHandCfg"].forEach((id) => {
      byId(id)?.addEventListener("input", animaHighresRefresh);
      byId(id)?.addEventListener("change", animaHighresRefresh);
    });
    ["animaHighresHandPositive", "animaHighresHandNegative"].forEach((id) => {
      const field = byId(id);
      if (!field) return;
      field.value = HAND_DEFAULTS[id === "animaHighresHandPositive" ? "positive" : "negative"];
      field.addEventListener("input", animaHighresRefresh);
      field.addEventListener("change", animaHighresRefresh);
    });
    ["animaHighresHandImage", "animaHighresHandMask"].forEach((id) => {
      byId(id)?.addEventListener("change", () => window.animaHighresHandUpload());
    });
    // 蒙版绘制器：指针事件直接绑在画布上（touch-action:none，手机也能涂）。
    const handCanvasNode = byId("animaHighresHandCanvas");
    if (handCanvasNode) {
      handCanvasNode.addEventListener("pointerdown", handPointerDown);
      handCanvasNode.addEventListener("pointermove", handPointerMove);
      handCanvasNode.addEventListener("pointerup", handPointerUp);
      handCanvasNode.addEventListener("pointercancel", handPointerUp);
      handCanvasNode.addEventListener("pointerleave", () => { if (handDrawing) handPointerUp(); });
    }
    window.animaHighresHandBrushChanged();
    refreshHandBaseOptions();
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
    // 与「Anima 提示词分层」一致：默认折叠，展开状态交给浏览器。
    const panel = byId("animaHighresPanel");
    if (panel) panel.open = false;
    refreshHighresOptions();
    window.animaHighresSyncVisibility();
  }

  // 展开面板并滚过去（跨标签页时先切到「生成设置」）。
  function revealPanel() {
    const panel = byId("animaHighresPanel");
    if (!panel) return;
    panel.open = true;
    if (typeof window.setStudioCreationTab === "function") window.setStudioCreationTab("settings");
    panel.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  window.animaHighresReveal = revealPanel;

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
      handRepair: window.animaHighresHandState(),
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
    const handBody = byId("animaHighresHandBody");
    if (handBody) handBody.style.display = state.handRepair.enabled ? "" : "none";
    // 打开手部修复时刷新一次底图下拉（会话里新出的图也能选到）。
    if (state.handRepair.enabled) {
      const select = byId("animaHighresHandBase");
      if (select) refreshHandBaseOptions();
    }
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
    if (state.enabled && state.handRepair.enabled) {
      if (state.handRepair.mask) {
        lines.push(`二采前手部修复：蒙版已就绪 · ${state.handRepair.steps} 步 · denoise ${state.handRepair.denoise} · 扩张 ${state.handRepair.grow}px · CFG ${state.handRepair.cfg}（会多一次采样）`);
      } else {
        lines.push("⚠ 已勾选「二采前手部修复」但还没有蒙版：下面「上次首采图 → 涂手 → 上传蒙版」画一张，或导入现成蒙版 / 用导航栏「手部修复」工作台画好发送。");
      }
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
          handRepair: state.handRepair,
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
        const handRaw = raw.handRepair && typeof raw.handRepair === "object" ? raw.handRepair : null;
        if (handRaw) {
          if (byId("animaHighresHandEnabled")) byId("animaHighresHandEnabled").checked = handRaw.enabled === true;
          assign("animaHighresHandDenoise", handRaw.denoise);
          assign("animaHighresHandSteps", handRaw.steps);
          assign("animaHighresHandGrow", handRaw.grow);
          assign("animaHighresHandCfg", handRaw.cfg);
          if (typeof handRaw.positive === "string" && byId("animaHighresHandPositive")) {
            byId("animaHighresHandPositive").value = handRaw.positive;
          }
          if (typeof handRaw.negative === "string" && byId("animaHighresHandNegative")) {
            byId("animaHighresHandNegative").value = handRaw.negative;
          }
          handUpload = { image: String(handRaw.image || ""), mask: String(handRaw.mask || "") };
          setHandStatus(handUpload.mask ? "已从快照恢复蒙版。" : "快照里没有可用蒙版，请重新上传或在手部工作台重新发送。");
        }
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
