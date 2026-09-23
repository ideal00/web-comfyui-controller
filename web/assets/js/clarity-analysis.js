(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);
  let clarityTimer = 0;
  let clarityRun = 0;

  function installClarityPanel() {
    const result = byId("result");
    if (!result || byId("clarityAnalysisPanel")) return;
    const panel = document.createElement("section");
    panel.id = "clarityAnalysisPanel";
    panel.className = "clarity-analysis-panel";
    panel.dataset.level = "idle";
    panel.innerHTML = `
      <header><div><span class="studio-kicker">像素检查</span><b>自动清晰度检测</b></div><button class="secondary" type="button" onclick="analyzeGeneratedClarity(true)">重新检测</button></header>
      <div id="clarityAnalysisResult" class="small">生成图片后自动检测；只评估像素锐度，不判断手、脸或肢体结构是否正确。</div>`;
    result.parentNode.insertBefore(panel, result.nextSibling); // 放在图片下方：预览栏首屏留给图片本身
    const action = document.createElement("section");
    action.id = "clarityUpscalePanel";
    action.className = "clarity-upscale-panel";
    action.innerHTML = `
      <div class="field-title"><b>生成同图清晰版</b><span class="small">保留原图，不重新抽噪声</span></div>
      <div class="clarity-upscale-controls">
        <select id="clarityUpscaleTarget" aria-label="选择要增强的生成图片"><option value="">— 当前没有生成图片 —</option></select>
        <button id="clarityUpscaleButton" class="secondary" type="button" onclick="generateSelectedClarityVersion()" disabled>生成清晰版</button>
      </div>
      <div id="clarityUpscaleStatus" class="small">清晰版不重新构图，只提高输出清晰度/尺寸。多张图片时先选一张；要选历史图、换增强方式或改倍率，请打开左侧「高级工具 → 同图清晰版」。</div>`;
    result.closest(".preview-card")?.appendChild(action);
    const observer = new MutationObserver(() => {
      refreshClarityTargets();
      scheduleClarityAnalysis();
    });
    observer.observe(result, { childList: true, subtree: true, attributes: true, attributeFilter: ["src"] });
    refreshClarityTargets();
    scheduleClarityAnalysis();
    installClarityDrawerPanel();
    loadClarityCatalog();
  }

  // 左侧「高级工具」抽屉里的完整版：可选任意历史图、换增强方式、改倍率。
  function installClarityDrawerPanel() {
    const root = byId("studioToolDrawerContent");
    if (!root || byId("clarityDrawerPanel")) return;
    const block = document.createElement("details");
    block.id = "clarityDrawerPanel";
    block.className = "clarity-drawer-panel";
    block.open = true;
    block.innerHTML = `
      <summary>同图清晰版（可选任意图 · 换模型 · 改倍率）</summary>
      <div class="clarity-upscale-panel">
        <div class="small" style="margin-bottom:6px">定位：不重新构图，只提高输出清晰度 / 尺寸。要改善结构、补生成细节请用二采。</div>
        <div class="field-title"><span>要增强的图片</span><span class="small">「本次生成」或「历史输出」里任选</span></div>
        <select id="clarityDrawerTarget" aria-label="选择要增强的图片"><option value="">— 正在读取输出目录… —</option></select>
        <div class="two" style="margin-top:8px">
          <div><div class="field-title"><span>增强方式</span><span class="small" title="放大模型最快、最保真，适合交付放大；SeedVR2 是生成式超分，会重绘细节，最慢但修得最多。">?</span></div><select id="clarityDrawerEngine" onchange="clarityDrawerEngineChanged()"><option value="upscale">放大模型（快 · 保真）</option></select></div>
          <div><div class="field-title"><span>放大倍率</span><span class="small" title="成品边长 = 原图 × 倍率；倍率越高越吃显存，也越容易看出增强痕迹。">?</span></div><input id="clarityDrawerScale" type="number" min="1.1" max="4" step="0.05" value="1.5"></div>
        </div>
        <div id="clarityDrawerModelWrap"><div class="field-title"><span>放大模型</span></div><select id="clarityUpscaleModel"><option value="">— 放大模型加载中 —</option></select></div>
        <img id="clarityUpscalePreview" class="clarity-upscale-preview" alt="待增强图片预览" hidden>
        <div class="actions"><button id="clarityDrawerButton" class="secondary" type="button" onclick="generateDrawerClarityVersion()" disabled>生成清晰版</button></div>
        <div id="clarityDrawerStatus" class="small">结果另存为新图，原图不会被覆盖。</div>
      </div>`;
    root.insertBefore(block, root.firstChild);
    byId("clarityDrawerTarget")?.addEventListener("change", () => refreshClarityPreview("clarityDrawerTarget", "clarityUpscalePreview"));
  }

  function clarityTargetEntries() {
    const result = byId("result");
    if (!result) return [];
    const seen = new Set();
    return [...result.querySelectorAll("img")].map((image, index) => {
      try {
        const url = new URL(image.currentSrc || image.src, window.location.href);
        const name = url.searchParams.get("name") || "";
        return { name, label: image.alt || `第 ${index + 1} 张` };
      } catch {
        return { name: "", label: "" };
      }
    }).filter((item) => item.name && !seen.has(item.name) && seen.add(item.name));
  }

  let clarityHistoryEntries = [];
  let clarityModelOptions = { models: [], default: "", seedvr2: { ready: false, model: "" } };

  function clarityTargetGroups() {
    const current = clarityTargetEntries();
    const listed = new Set(current.map((item) => item.name));
    return { current, history: clarityHistoryEntries.filter((item) => !listed.has(item.name)) };
  }

  function refreshClarityTargets() {
    // 主界面：只列本次生成的图（保持原来的样子）。
    const select = byId("clarityUpscaleTarget");
    const button = byId("clarityUpscaleButton");
    if (select && button) {
      const previous = select.value;
      const current = clarityTargetEntries();
      select.innerHTML = current.length
        ? current.map((item, index) =>
            `<option value="${escapeHtml(item.name)}">第 ${index + 1} 张 · ${escapeHtml(item.name)}</option>`).join("")
        : '<option value="">— 当前没有生成图片 —</option>';
      if (previous && [...select.options].some((option) => option.value === previous)) select.value = previous;
      button.disabled = !current.length;
    }
    // 抽屉：本次生成 + 历史输出。
    const drawer = byId("clarityDrawerTarget");
    const drawerButton = byId("clarityDrawerButton");
    if (!drawer || !drawerButton) return;
    const previous = drawer.value;
    const { current, history } = clarityTargetGroups();
    if (!current.length && !history.length) {
      drawer.innerHTML = '<option value="">— 当前没有可用的图片 —</option>';
      drawerButton.disabled = true;
    } else {
      const groups = [];
      if (current.length) {
        groups.push(`<optgroup label="本次生成">${current.map((item, index) =>
          `<option value="${escapeHtml(item.name)}">第 ${index + 1} 张 · ${escapeHtml(item.name)}</option>`
        ).join("")}</optgroup>`);
      }
      if (history.length) {
        groups.push(`<optgroup label="历史输出（最近 ${history.length} 张）">${history.map((item) =>
          `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`
        ).join("")}</optgroup>`);
      }
      drawer.innerHTML = groups.join("");
      if (previous && [...drawer.options].some((option) => option.value === previous)) drawer.value = previous;
      drawerButton.disabled = false;
    }
    refreshClarityPreview("clarityDrawerTarget", "clarityUpscalePreview");
  }

  async function loadClarityCatalog() {
    try {
      const response = await fetch("/api/upscale-models");
      const data = await response.json();
      clarityModelOptions = {
        models: Array.isArray(data.models) ? data.models.map(String) : [],
        default: String(data.default || ""),
        seedvr2: {
          ready: Boolean(data.seedvr2 && data.seedvr2.ready),
          model: String(data.seedvr2 && data.seedvr2.model || ""),
        },
      };
    } catch {
      clarityModelOptions = { models: [], default: "", seedvr2: { ready: false, model: "" } };
    }
    const modelSelect = byId("clarityUpscaleModel");
    if (modelSelect) {
      const previous = modelSelect.value;
      if (!clarityModelOptions.models.length) {
        modelSelect.innerHTML = '<option value="">— 没有可用的放大模型 —</option>';
      } else {
        modelSelect.innerHTML = clarityModelOptions.models
          .map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
        const wanted = clarityModelOptions.models.includes(previous) ? previous : clarityModelOptions.default;
        if (wanted) modelSelect.value = wanted;
      }
    }
    const engineSelect = byId("clarityDrawerEngine");
    if (engineSelect) {
      const previous = engineSelect.value;
      engineSelect.innerHTML = '<option value="upscale">放大模型（快 · 保真）</option>'
        + (clarityModelOptions.seedvr2.ready
            ? '<option value="seedvr2">SeedVR2 生成式超分（慢 · 修细节）</option>' : "");
      if (previous === "seedvr2" && clarityModelOptions.seedvr2.ready) engineSelect.value = "seedvr2";
      window.clarityDrawerEngineChanged();
    }
    try {
      const response = await fetch("/api/output-images");
      const data = await response.json();
      clarityHistoryEntries = (Array.isArray(data.entries) ? data.entries : [])
        .map((item) => ({ name: String(item && item.name || ""), mtime: Number(item && item.mtime || 0) }))
        .filter((item) => item.name);
    } catch {
      clarityHistoryEntries = [];
    }
    refreshClarityTargets();
  }

  window.clarityDrawerEngineChanged = function () {
    const engine = byId("clarityDrawerEngine")?.value || "upscale";
    const modelWrap = byId("clarityDrawerModelWrap");
    if (modelWrap) modelWrap.style.display = engine === "seedvr2" ? "none" : "";
  };

  function refreshClarityPreview(selectId, previewId) {
    const select = byId(selectId);
    const preview = byId(previewId);
    if (!select || !preview) return;
    const name = select.value;
    if (!name) {
      preview.hidden = true;
      preview.removeAttribute("src");
      return;
    }
    preview.hidden = false;
    preview.src = "/output?name=" + encodeURIComponent(name);
  }

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = String(value || "");
    return node.innerHTML;
  }

  let clarityBusy = false;

  async function runClarityUpscale({ name, engine, model, scale, button, status }) {
    const ratio = Math.min(4, Math.max(1.1, Number(scale) || 1.5));
    if (engine !== "seedvr2" && !model) {
      status.textContent = "没有可用的放大模型：把 .pth 放进 models/upscale_models 后重新载入页面。";
      return false;
    }
    const label = engine === "seedvr2" ? "SeedVR2 生成式超分" : `放大模型 ${model}`;
    const oldLabel = button.textContent;
    button.disabled = true;
    button.textContent = "正在增强…";
    status.textContent = `正在处理：${name}（${label} · ${ratio}×）；原图不会被覆盖。`;
    try {
      const previous = typeof generatedViewerImages === "undefined" ? [] : generatedViewerImages.map((item) => ({
        filename: item.name, experimentLabel: item.label || "",
      }));
      beginGenerationProgress(1, "同图清晰版");
      const body = { name, scale: ratio };
      if (engine === "seedvr2") body.engine = "seedvr2";
      else body.model = model;
      const response = await fetch("/api/clarity-upscale", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      registerGenerationPrompt(data.prompt_id);
      const output = await poll(data.prompt_id);
      output.forEach((image) => image.experimentLabel = `清晰版 · 来源 ${name}`);
      renderGeneratedImages([...previous, ...output]);
      finishGenerationProgress(true, "同图清晰版已生成并追加到预览。原图仍保留。 ");
      status.textContent = `完成：${name} 的 ${ratio}× 清晰版（${label}）已追加到预览，原图仍保留。`;
      loadOutputImages();
      loadClarityCatalog();
      return true;
    } catch (error) {
      finishGenerationProgress(false, error.message);
      status.textContent = "生成清晰版失败：" + error.message;
      return false;
    } finally {
      button.textContent = oldLabel;
      button.disabled = false;
    }
  }

  // 主界面：沿用原来的行为——只处理本次生成、默认放大模型、1.5×。
  window.generateSelectedClarityVersion = async function () {
    if (clarityBusy) return;
    const select = byId("clarityUpscaleTarget");
    const button = byId("clarityUpscaleButton");
    const status = byId("clarityUpscaleStatus");
    const name = select?.value || "";
    if (!name || !button || !status) return;
    clarityBusy = true;
    try {
      await runClarityUpscale({
        name, engine: "upscale",
        model: clarityModelOptions.default || (clarityModelOptions.models[0] || ""),
        scale: 1.5, button, status,
      });
    } finally {
      clarityBusy = false;
      refreshClarityTargets();
    }
  };

  // 抽屉：可选任意图、换增强方式、改倍率。
  window.generateDrawerClarityVersion = async function () {
    if (clarityBusy) return;
    const target = byId("clarityDrawerTarget");
    const engine = byId("clarityDrawerEngine")?.value || "upscale";
    const modelSelect = byId("clarityUpscaleModel");
    const scaleInput = byId("clarityDrawerScale");
    const button = byId("clarityDrawerButton");
    const status = byId("clarityDrawerStatus");
    const name = target?.value || "";
    if (!name || !button || !status) return;
    clarityBusy = true;
    try {
      await runClarityUpscale({
        name, engine, model: modelSelect?.value || "",
        scale: scaleInput?.value || 1.5, button, status,
      });
    } finally {
      clarityBusy = false;
    }
  };

  function scheduleClarityAnalysis() {
    clearTimeout(clarityTimer);
    clarityTimer = setTimeout(() => window.analyzeGeneratedClarity(false), 180);
  }

  function loadAnalysisImage(src) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.decoding = "async";
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("图片无法读取"));
      image.src = src;
    });
  }

  function regionMetrics(gray, width, height, bounds) {
    const x0 = Math.max(1, Math.floor(width * bounds[0]));
    const y0 = Math.max(1, Math.floor(height * bounds[1]));
    const x1 = Math.min(width - 1, Math.ceil(width * bounds[2]));
    const y1 = Math.min(height - 1, Math.ceil(height * bounds[3]));
    let lapSum = 0, lapSquareSum = 0, gradientSum = 0, edges = 0, count = 0;
    for (let y = y0; y < y1; y += 1) {
      const row = y * width;
      for (let x = x0; x < x1; x += 1) {
        const index = row + x;
        const center = gray[index];
        const laplacian = 4 * center - gray[index - 1] - gray[index + 1] - gray[index - width] - gray[index + width];
        const gradient = Math.abs(gray[index + 1] - gray[index - 1]) + Math.abs(gray[index + width] - gray[index - width]);
        lapSum += laplacian;
        lapSquareSum += laplacian * laplacian;
        gradientSum += gradient;
        if (gradient > 34) edges += 1;
        count += 1;
      }
    }
    const mean = count ? lapSum / count : 0;
    return {
      variance: count ? Math.max(0, lapSquareSum / count - mean * mean) : 0,
      gradient: count ? gradientSum / count : 0,
      edgeRatio: count ? edges / count : 0,
    };
  }

  function analyzePixels(image) {
    const naturalWidth = image.naturalWidth || image.width;
    const naturalHeight = image.naturalHeight || image.height;
    const scale = Math.min(1, 512 / Math.max(naturalWidth, naturalHeight));
    const width = Math.max(32, Math.round(naturalWidth * scale));
    const height = Math.max(32, Math.round(naturalHeight * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    context.drawImage(image, 0, 0, width, height);
    const pixels = context.getImageData(0, 0, width, height).data;
    const gray = new Float32Array(width * height);
    for (let index = 0, pixel = 0; index < pixels.length; index += 4, pixel += 1) {
      gray[pixel] = pixels[index] * 0.299 + pixels[index + 1] * 0.587 + pixels[index + 2] * 0.114;
    }
    const portrait = naturalHeight >= naturalWidth * 1.05;
    const whole = regionMetrics(gray, width, height, [0.01, 0.01, 0.99, 0.99]);
    const upper = regionMetrics(gray, width, height, portrait ? [0.18, 0.03, 0.82, 0.48] : [0.28, 0.08, 0.72, 0.55]);
    return { naturalWidth, naturalHeight, whole, upper };
  }

  function recommendation(metrics) {
    const whole = metrics.whole.variance;
    const upper = metrics.upper.variance;
    const minSide = Math.min(metrics.naturalWidth, metrics.naturalHeight);
    if (whole < 100 || upper < 140) {
      return { level: "soft", rank: 3, title: "明显偏软", advice: "建议优先高清二采；若结构已经稳定，可用 SeedVR2 1.25×。" };
    }
    if (whole < 620 || upper < 850) {
      return { level: "medium", rank: 2, title: "细节稍软", advice: "建议 Anime6B 1.5×；需要重新补纹理时再选 SeedVR2。" };
    }
    if (minSide < 700) {
      return { level: "medium", rank: 2, title: "当前清晰，但尺寸偏小", advice: "无需重绘；需要更大成图时可用 Anime6B 放大。" };
    }
    if (whole > 1800 && metrics.whole.edgeRatio > 0.20) {
      return { level: "sharp", rank: 0, title: "已经非常锐利", advice: "不建议继续锐化，避免线条发硬和产生假纹理。" };
    }
    return { level: "clear", rank: 1, title: "清晰度正常", advice: "通常无需整图增强；放大交付时再考虑 Anime6B。" };
  }

  window.analyzeGeneratedClarity = async function (manual) {
    const result = byId("result");
    const output = byId("clarityAnalysisResult");
    const panel = byId("clarityAnalysisPanel");
    if (!result || !output || !panel) return;
    const sources = [...result.querySelectorAll("img")].map((image) => image.currentSrc || image.src).filter(Boolean).slice(0, 8);
    if (!sources.length) {
      if (manual) output.textContent = "当前没有可检测的生成图片。";
      panel.dataset.level = "idle";
      return;
    }
    const run = ++clarityRun;
    output.textContent = `正在分析 ${sources.length} 张图片的整图和人物上部候选区域…`;
    panel.dataset.level = "working";
    try {
      const reports = [];
      for (let index = 0; index < sources.length; index += 1) {
        const image = await loadAnalysisImage(sources[index]);
        const metrics = analyzePixels(image);
        reports.push({ index, metrics, recommendation: recommendation(metrics) });
      }
      if (run !== clarityRun) return;
      const worst = reports.reduce((selected, item) => item.recommendation.rank > selected.recommendation.rank ? item : selected, reports[0]);
      const metrics = worst.metrics;
      const prefix = reports.length > 1 ? `共 ${reports.length} 张；第 ${worst.index + 1} 张最需要关注。` : "";
      output.innerHTML = `<b>${worst.recommendation.title}</b>　${prefix}${worst.recommendation.advice}<br><span>原图 ${metrics.naturalWidth}×${metrics.naturalHeight} · 整图锐度 ${metrics.whole.variance.toFixed(1)} · 人物上部 ${metrics.upper.variance.toFixed(1)} · 边缘比例 ${(metrics.whole.edgeRatio * 100).toFixed(1)}%</span>`;
      panel.dataset.level = worst.recommendation.level;
    } catch (error) {
      if (run !== clarityRun) return;
      output.textContent = `清晰度检测失败：${error.message}`;
      panel.dataset.level = "error";
    }
  };

  window.scheduleClarityAnalysis = scheduleClarityAnalysis;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", installClarityPanel, { once: true });
  else installClarityPanel();
})();
