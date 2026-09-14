/* 执行链摘要：在「生成图片」按钮上方说明这一张会走哪几步。
 *
 * 只读现有控件与能力契约，不参与提交：
 *   - 步骤与互斥关系来自 capabilities（highres_reconstruction / detail_refine /
 *     post_upscale / face_detailer…），不再按模型族写死；
 *   - 数值范围来自 profile.constraints（例如 highres_reconstruction.max_long_edge）；
 *   - 采样次数 / 显存级别由本脚本按步骤推算，只作为预期提示，不影响后端行为。
 */
(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const OUTPUT_LABELS = {
    anime6b: ["输出放大（Anime6B）", 0],
    seedvr2: ["输出增强（SeedVR2）", 1],
    ultimate: ["输出增强（Ultimate SD Upscale）", 1],
  };

  function profile() {
    try {
      return window.currentSamplingProfile ? window.currentSamplingProfile() : null;
    } catch (error) {
      return null;
    }
  }

  function family() {
    const current = profile();
    if (current && current.family) return String(current.family);
    const model = String(byId("model")?.value || "").toLowerCase();
    if (model.includes("krea")) return "krea2";
    if (model.includes("anima")) return "anima";
    return "sdxl";
  }

  function caps() {
    const current = profile();
    const value = current && current.capabilities;
    return value && typeof value === "object" ? value : {};
  }

  function constraint(name) {
    const current = profile();
    const value = current && current.constraints ? current.constraints[name] : null;
    return value && typeof value === "object" ? value : {};
  }

  function num(id, fallback) {
    const value = Number(byId(id)?.value);
    return Number.isFinite(value) ? value : fallback;
  }

  function checked(id) {
    return byId(id)?.checked === true;
  }

  function align8(value) {
    return Math.max(8, Math.round(Number(value) / 8) * 8);
  }

  function baseSize() {
    const raw = String(byId("size")?.value || "864x1152").split("x").map(Number);
    return { width: raw[0] || 864, height: raw[1] || 1152 };
  }

  // 目标尺寸按契约上限收敛（与 anima-highres.js 的显示口径一致）。
  function scaledSize(size, scale, maxLongEdge) {
    let width = align8(size.width * scale);
    let height = align8(size.height * scale);
    if (maxLongEdge > 0 && Math.max(width, height) > maxLongEdge) {
      const ratio = maxLongEdge / Math.max(width, height);
      width = align8(width * ratio);
      height = align8(height * ratio);
    }
    return { width, height, limited: maxLongEdge > 0 && Math.max(align8(size.width * scale), align8(size.height * scale)) > maxLongEdge };
  }

  function buildChain() {
    const start = baseSize();
    const current = family();
    const capabilities = caps();
    const items = [{ label: `首采 ${start.width}×${start.height}`, scale: 1 }];
    let samplers = 1;
    let size = { width: start.width, height: start.height };
    const notes = [];

    const highresCapable = capabilities.highres_reconstruction !== false
      && capabilities.anima_highres !== false;
    const hiresEnabled = checked("animaHighresEnabled") && highresCapable;
    const illustriousHires = current === "illustrious" && highresCapable
      && String(byId("illustriousMode")?.value || "") === "hires"
      && capabilities.hires_fix !== false;
    const refineEnabled = checked("animaRefineEnabled") && capabilities.detail_refine !== false;

    if (hiresEnabled || illustriousHires) {
      const highres = constraint("highres_reconstruction");
      const scale = hiresEnabled
        ? num("animaHighresScale", Number(highres.default_scale) || 1.5)
        : num("hiresScale", Number(highres.default_scale) || 1.25);
      const maxLongEdge = Number(highres.max_long_edge) || 0;
      size = scaledSize(start, scale, maxLongEdge);
      const label = hiresEnabled ? "Anima 高清重建" : "高清二采";
      items.push({ label: `${label} ${scale.toFixed(2)}×（约 ${size.width}×${size.height}）`, scale: scale });
      samplers += 1;
      if (size.limited) notes.push(`受长边上限 ${maxLongEdge} 收敛`);
    }

    if (refineEnabled) {
      const denoise = num("animaRefineDenoise", 0.12);
      items.push({ label: `Detail Refine（同尺寸 denoise ${denoise.toFixed(2)}）`, scale: 1 });
      samplers += 1;
    }

    const outputMode = String(byId("outputEnhancementMode")?.value || "off");
    const output = OUTPUT_LABELS[outputMode];
    if (output && capabilities.post_upscale !== false) {
      const scale = num("outputEnhancementScale", 1.5);
      size = { width: align8(size.width * scale), height: align8(size.height * scale) };
      items.push({ label: `${output[0]} ${scale.toFixed(2)}×`, scale: scale });
      samplers += output[1];
    }

    const detailers = [];
    if (checked("faceDetailerEnabled") && capabilities.face_detailer !== false) detailers.push("Face Detailer");
    if (checked("handDetailerEnabled") && capabilities.hand_detailer !== false) detailers.push("手部修复");
    if (checked("footDetailerEnabled") && capabilities.foot_detailer !== false) detailers.push("脚部修复");
    if (detailers.length) items.push({ label: `${detailers.join(" + ")}（局部重绘）`, scale: 1 });

    if (checked("img2imgEnabled")) items.unshift({ label: `整图重绘 denoise ${num("img2imgDenoise", 0.6).toFixed(2)}`, scale: 1 });

    return { items, samplers, size, notes, current };
  }

  function vramLabel(samplers, size) {
    const megapixels = (size.width * size.height) / (1024 * 1024);
    const score = samplers + (megapixels > 2.4 ? 1.5 : megapixels > 1.5 ? 0.75 : 0);
    if (score >= 3.5) return "显存高";
    if (score >= 2) return "显存较高";
    return "显存常规";
  }

  function render() {
    const box = byId("generationChainSummary");
    if (!box) return;
    const chain = buildChain();
    const steps = chain.items.map((item) => item.label).join(" → ");
    const tail = `预计 ${chain.samplers} 次采样 · ${vramLabel(chain.samplers, chain.size)} · 最终约 ${chain.size.width}×${chain.size.height}`;
    const note = chain.notes.length ? `（${chain.notes.join("；")}）` : "";
    const text = `执行链：${steps}｜${tail}${note}`;
    if (box.textContent === text) return;
    box.textContent = text;
    box.title = text;
    box.hidden = false;
  }

  window.refreshGenerationChain = render;

  function start() {
    document.addEventListener("change", render, true);
    document.addEventListener("input", render, true);
    ["modelChanged", "animaHighresRefresh", "animaRefineRefresh", "outputEnhancementChanged"]
      .forEach((name) => window.addEventListener(name, render));
    window.addEventListener("load", render);
    // 其它脚本会异步注入 #outputEnhancement* / 细节增强开关，定时轻量重算兜底。
    setInterval(render, 2000);
    render();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
