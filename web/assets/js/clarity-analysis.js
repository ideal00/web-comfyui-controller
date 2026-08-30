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
    result.parentNode.insertBefore(panel, result);
    const action = document.createElement("section");
    action.id = "clarityUpscalePanel";
    action.className = "clarity-upscale-panel";
    action.innerHTML = `
      <div class="field-title"><b>生成同图清晰版</b><span class="small">保留原图，不重新抽噪声</span></div>
      <div class="clarity-upscale-controls">
        <select id="clarityUpscaleTarget" aria-label="选择要增强的生成图片"><option value="">— 当前没有生成图片 —</option></select>
        <button id="clarityUpscaleButton" class="secondary" type="button" onclick="generateSelectedClarityVersion()" disabled>生成清晰版</button>
      </div>
      <div id="clarityUpscaleStatus" class="small">多张图片时先选择其中一张；结果会追加到预览并另存。</div>`;
    result.closest(".preview-card")?.appendChild(action);
    const observer = new MutationObserver(() => {
      refreshClarityTargets();
      scheduleClarityAnalysis();
    });
    observer.observe(result, { childList: true, subtree: true, attributes: true, attributeFilter: ["src"] });
    refreshClarityTargets();
    scheduleClarityAnalysis();
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

  function refreshClarityTargets() {
    const select = byId("clarityUpscaleTarget");
    const button = byId("clarityUpscaleButton");
    if (!select || !button) return;
    const previous = select.value;
    const entries = clarityTargetEntries();
    select.innerHTML = entries.length ? entries.map((item, index) =>
      `<option value="${escapeHtml(item.name)}">第 ${index + 1} 张 · ${escapeHtml(item.name)}</option>`
    ).join("") : '<option value="">— 当前没有生成图片 —</option>';
    if (previous && entries.some((item) => item.name === previous)) select.value = previous;
    button.disabled = !entries.length;
  }

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = String(value || "");
    return node.innerHTML;
  }

  window.generateSelectedClarityVersion = async function () {
    const select = byId("clarityUpscaleTarget");
    const button = byId("clarityUpscaleButton");
    const status = byId("clarityUpscaleStatus");
    const name = select?.value || "";
    if (!name || !button || !status) return;
    const oldLabel = button.textContent;
    button.disabled = true;
    button.textContent = "正在增强…";
    status.textContent = `正在处理：${name}；原图不会被覆盖。`;
    try {
      const previous = typeof generatedViewerImages === "undefined" ? [] : generatedViewerImages.map((item) => ({
        filename: item.name, experimentLabel: item.label || "",
      }));
      beginGenerationProgress(1, "同图清晰版");
      const response = await fetch("/api/clarity-upscale", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, scale: 1.5 }),
      });
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      registerGenerationPrompt(data.prompt_id);
      const output = await poll(data.prompt_id);
      output.forEach((image) => image.experimentLabel = `清晰版 · 来源 ${name}`);
      renderGeneratedImages([...previous, ...output]);
      finishGenerationProgress(true, "同图清晰版已生成并追加到预览。原图仍保留。 ");
      status.textContent = `完成：${name} 的 1.5× 清晰版已追加到预览，原图仍保留。`;
      loadOutputImages();
    } catch (error) {
      finishGenerationProgress(false, error.message);
      status.textContent = "生成清晰版失败：" + error.message;
    } finally {
      button.textContent = oldLabel;
      refreshClarityTargets();
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
