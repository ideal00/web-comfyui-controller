(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const FALLBACK_FREEU = {
    key: "sdxl_official",
    label: "官方 SDXL / ComfyUI V2",
    b1: 1.3,
    b2: 1.4,
    s1: 0.9,
    s2: 0.2,
    source: "FreeU 作者 SDXL 推荐 + ComfyUI FreeU_V2 默认值",
    presets: [
      { key: "sdxl_official", label: "官方 SDXL / ComfyUI V2（推荐）", b1: 1.3, b2: 1.4, s1: 0.9, s2: 0.2, note: "适用于 SDXL 与 Illustrious。" },
      { key: "sdxl_gentle", label: "SDXL 柔和参考（Diffusers）", b1: 1.1, b2: 1.2, s1: 0.6, s2: 0.4, note: "增强更柔和，适合官方值效果过重时。" },
    ],
  };

  function profile() {
    return typeof window.currentSamplingProfile === "function"
      ? window.currentSamplingProfile()
      : {};
  }

  function workflowFeatures() {
    return typeof window.currentWorkflowFeatures === "function"
      ? window.currentWorkflowFeatures()
      : {};
  }

  function help(text) {
    return `<span class="small" title="${String(text).replace(/&/g, "&amp;").replace(/"/g, "&quot;")}">?</span>`;
  }

  const OUTPUT_DEFAULTS = {
    off: { scale: 1.5, note: "关闭：保持模型原始输出，不增加耗时或改变细节。" },
    anime6b: { scale: 1.5, note: "推荐：1.5×。适合动漫线稿和发丝边缘，速度快；倍率过高可能产生锐化感。" },
    seedvr2: { scale: 1.25, note: "推荐：1.25× + LAB。更偏向保留原构图与颜色，适合保守修复。" },
    ultimate: { scale: 1.5, note: "推荐：1.5×、20 步、重绘 0.20、Tile 512。细节最完整，但耗时和显存占用最高。" },
  };

  function advancedPanelHtml() {
    return `
      <summary>模型增强与低显存 VAE</summary>
      <div class="color-panel">
        <div class="small" id="modelCapabilitySummary">读取当前模型能力…</div>
        <div class="two" style="margin-top:8px">
          <div>
            <div class="field-title"><span>模型增强</span>${help("对采样模型施加画质补丁。默认关闭最适合建立基线；FreeU V2 可增强 SDXL/Illustrious 结构细节，CFG Rescale 仅用于 v-pred 防过曝。")}</div>
            <select id="modelEnhancementMode" onchange="modelAdvancedChanged()">
              <option value="off">关闭（推荐基线）</option>
              <option value="freeu_v2">FreeU V2（SDXL/Illustrious 细节）</option>
              <option value="cfg_rescale">CFG Rescale（仅 v-pred 防过曝）</option>
            </select>
          </div>
          <div>
            <div class="field-title"><span>VAE 编解码</span>${help("标准模式速度更快，默认推荐；大图、高清二采或显存紧张时改用 Tiled。Tiled 推荐 Tile 512、重叠 64。")}</div>
            <select id="vaeMode" onchange="vaeModeChanged()">
              <option value="standard">标准（保持现有速度）</option>
              <option value="tiled">Tiled（低显存，较慢）</option>
            </select>
          </div>
        </div>
        <div id="freeuControls" style="display:none">
          <div class="field-title"><span>FreeU V2 推荐组合</span>${help("不增加采样步数，通过增强主干并抑制跳连改善结构和细节。默认使用官方 SDXL/ComfyUI V2：b1 1.3、b2 1.4、s1 0.9、s2 0.2。")}</div>
          <select id="freeuPreset" onchange="freeuPresetChanged(this.value)"><option value="sdxl_official">官方 SDXL / ComfyUI V2（推荐）</option><option value="sdxl_gentle">SDXL 柔和参考（Diffusers）</option><option value="custom">自定义</option></select>
          <div id="freeuPresetInfo" class="small" style="margin-top:6px"></div>
          <div class="two" style="margin-top:8px"><div><div class="field-title"><span>b1 · 主干阶段 1</span>${help("增强第一阶段主干特征；官方推荐 1.3。过高可能让对比和纹理过重。")}</div><input id="freeuB1" type="number" min="0" max="10" step="0.01" value="1.3" oninput="freeuValueChanged()"></div><div><div class="field-title"><span>b2 · 主干阶段 2</span>${help("增强第二阶段主干特征；官方推荐 1.4。")}</div><input id="freeuB2" type="number" min="0" max="10" step="0.01" value="1.4" oninput="freeuValueChanged()"></div></div>
          <div class="two"><div><div class="field-title"><span>s1 · 跳连阶段 1</span>${help("缩放第一阶段跳连特征；官方推荐 0.9，低于 1 可减少过度平滑。")}</div><input id="freeuS1" type="number" min="0" max="10" step="0.01" value="0.9" oninput="freeuValueChanged()"></div><div><div class="field-title"><span>s2 · 跳连阶段 2</span>${help("缩放第二阶段跳连特征；官方推荐 0.2。数值过低可能改变模型原有风格。")}</div><input id="freeuS2" type="number" min="0" max="10" step="0.01" value="0.2" oninput="freeuValueChanged()"></div></div>
          <div class="small" style="margin-top:6px">b1/b2 增强主干语义；s1/s2 抑制跳连造成的过度平滑或异常细节。建议固定种子，与关闭状态 A/B 对比。</div>
        </div>
        <div id="cfgRescaleControls" style="display:none">
          <div class="field-title"><span>CFG Rescale 强度</span>${help("仅对 v-pred 模型开放，用于降低高 CFG 造成的过曝和色彩烧灼。推荐默认 0.70；越高修正越强。")}</div>
          <input id="cfgRescaleMultiplier" type="number" min="0" max="1" step="0.01" value="0.7">
        </div>
        <div id="vaeTiledControls" style="display:none">
          <div class="two" style="margin-top:8px">
            <div><div class="field-title"><span>Tile 大小</span>${help("每块独立编解码的尺寸。推荐 512；显存不足用 384，显存充足可用 768 提速。")}</div><select id="vaeTileSize"><option value="384">384（更省显存）</option><option value="512" selected>512（推荐）</option><option value="768">768（更快）</option><option value="1024">1024</option></select></div>
            <div><div class="field-title"><span>重叠像素</span>${help("相邻 VAE 分块的重叠区域，用于减轻接缝。推荐 64；仍见接缝可升至 96，代价是更慢。")}</div><select id="vaeOverlap"><option value="32">32</option><option value="64" selected>64（推荐）</option><option value="96">96</option><option value="128">128</option></select></div>
          </div>
          <div class="small" style="margin-top:6px">Tiled 会同时用于普通 img2img 的 VAE Encode 和最终 Decode；局部修复仍使用专用 Inpaint 编码节点。</div>
        </div>
        <hr style="border:0;border-top:1px solid var(--line);margin:12px 0">
        <div class="field-title"><span>输出增强工作流</span>${help("生成完成后只选择一种整图增强；与高清二次采样、局部修复互斥。默认关闭用于基线对比。")}</div>
        <div class="two">
          <div><div class="field-title"><span>整图增强</span>${help("Anime6B 适合动漫锐线；SeedVR2 更保守地修复细节；Ultimate 会分块扩散重绘，质量高但最慢。")}</div><select id="outputEnhancementMode" onchange="outputEnhancementChanged()"><option value="off">关闭（推荐基线）</option><option value="anime6b">Anime6B 后处理超分</option><option value="seedvr2">SeedVR2 生成式超分</option><option value="ultimate">Ultimate SD Upscale（SDXL）</option></select></div>
          <div><div class="field-title"><span>输出倍率</span>${help("输出边长倍率。Anime6B/Ultimate 推荐 1.5×；SeedVR2 推荐 1.25×。倍率越高越吃显存，也越容易改变原图细节。")}</div><input id="outputEnhancementScale" type="number" min="1.1" max="4" step="0.05" value="1.5"></div>
        </div>
        <div id="outputEnhancementRecommendation" class="small" style="margin-top:6px">${OUTPUT_DEFAULTS.off.note}</div>
        <div id="ultimateControls" style="display:none" class="two"><div><div class="field-title"><span>Ultimate 步数 / 重绘</span>${help("左侧为扩散步数，右侧为重绘幅度。推荐 20 步 / 0.20；提高重绘会增加细节，也更容易改变脸和构图。")}</div><div class="two"><input id="ultimateSteps" type="number" min="8" max="40" value="20" aria-label="Ultimate 步数"><input id="ultimateDenoise" type="number" min="0.05" max="0.6" step="0.05" value="0.2" aria-label="Ultimate 重绘幅度"></div></div><div><div class="field-title"><span>Tile</span>${help("Ultimate 分块扩散尺寸。推荐 512；显存不足用 384，768/1024 更快但更吃显存。")}</div><select id="ultimateTileSize"><option value="384">384</option><option value="512" selected>512（推荐）</option><option value="768">768</option><option value="1024">1024</option></select></div></div>
        <div id="seedvrControls" style="display:none"><div class="field-title"><span>SeedVR2 色彩修正</span>${help("生成式超分后把颜色拉回原图。LAB 是默认推荐；Wavelet 更柔和，AdaIN 风格影响更明显，关闭可能出现色偏。")}</div><select id="seedvrColor"><option value="lab" selected>LAB（推荐）</option><option value="wavelet">Wavelet</option><option value="adain">AdaIN</option><option value="none">关闭</option></select></div>
        <div class="two" style="margin-top:8px"><label><input id="faceDetailerEnabled" type="checkbox" onchange="outputEnhancementChanged(true)"> 输出后自动修脸（FaceDetailer） ${help("检测并局部重绘脸部。单人大图可选；默认关闭，因为它可能改变身份和五官。推荐：引导 512、12 步、重绘 0.35。")}</label><label><input id="autoColorMatchEnabled" type="checkbox" onchange="outputEnhancementChanged(true)"> 自动匹配原图色彩 ${help("将增强结果的颜色匹配回增强前原图。出现色偏时开启；默认关闭，开启时推荐 Reinhard LAB、强度 0.70。")}</label></div>
        <div id="faceDetailerControls" style="display:none" class="three"><div><div class="field-title"><span>引导尺寸</span>${help("脸部局部处理分辨率。推荐 512；远景小脸可用 640，过高会更慢且可能改变五官。")}</div><input id="faceDetailerGuideSize" type="number" min="256" max="1024" step="64" value="512"></div><div><div class="field-title"><span>步数</span>${help("脸部局部重绘步数。推荐 12；通常 10–16 已足够。")}</div><input id="faceDetailerSteps" type="number" min="6" max="30" value="12"></div><div><div class="field-title"><span>重绘幅度</span>${help("脸部改动强度。推荐 0.35；降低可保身份，提高会修更多缺陷但可能换脸。")}</div><input id="faceDetailerDenoise" type="number" min="0.15" max="0.65" step="0.05" value="0.35"></div></div>
        <div class="field-title"><span>手脚局部修复</span>${help("整图增强只会放大已有手脚，不能可靠重建指趾。本功能用专用 YOLO 检测器定位后局部重绘；原图直出也会生效，检测不到时不改图。")}</div>
        <div class="two"><label><input id="handDetailerEnabled" type="checkbox" checked onchange="outputEnhancementChanged(true)"> 自动修复手指（推荐） ${help("默认开启。使用 hand_yolov8s 定位手部并局部重绘，补救模糊、粘连、缺指或多指；手被遮挡严重时仍可能无法检测。")}</label><label><input id="footDetailerEnabled" type="checkbox" checked onchange="outputEnhancementChanged(true)"> 自动修复脚趾/鞋形（推荐） ${help("默认开启。裸足时强调五趾，穿鞋时改用正确鞋形提示，避免把脚趾画到鞋面上。")}</label></div>
        <div id="limbDetailerControls" class="three"><div><div class="field-title"><span>引导尺寸</span>${help("手脚局部重绘分辨率。推荐 512；远景小手脚可试 640，但会更慢。")}</div><input id="limbDetailerGuideSize" type="number" min="256" max="1024" step="64" value="512"></div><div><div class="field-title"><span>步数</span>${help("手脚局部重绘步数。推荐 16；比修脸略高，以便重建指趾结构。")}</div><input id="limbDetailerSteps" type="number" min="8" max="30" value="16"></div><div><div class="field-title"><span>重绘幅度</span>${help("推荐 0.45。低于 0.35 往往只会保留原有模糊；高于 0.60 容易改变手势、鞋形或产生新指趾。")}</div><input id="limbDetailerDenoise" type="number" min="0.2" max="0.7" step="0.05" value="0.45"></div></div>
        <div id="autoColorControls" style="display:none" class="two"><div><div class="field-title"><span>匹配算法</span>${help("Reinhard LAB 是稳妥默认；MKL LAB 匹配更强，Histogram 适合明显色阶差异但可能压缩层次。")}</div><select id="autoColorMethod"><option value="reinhard_lab">Reinhard LAB（推荐）</option><option value="mkl_lab">MKL LAB</option><option value="histogram">Histogram</option></select></div><div><div class="field-title"><span>强度</span>${help("颜色回匹配强度。推荐 0.70；色偏仍明显可提高，颜色变平则降低。")}</div><input id="autoColorStrength" type="number" min="0" max="1" step="0.05" value="0.7"></div></div>
        <div id="outputEnhancementAvailability" class="small" style="margin-top:8px"></div>
      </div>`;
  }

  function installPanel() {
    if (byId("modelAdvancedExtras")) return;
    const regions = byId("regionsEnabled")?.closest("details");
    if (!regions) return;
    const details = document.createElement("details");
    details.id = "modelAdvancedExtras";
    details.innerHTML = advancedPanelHtml();
    regions.parentNode.insertBefore(details, regions);

    const workflowHeading = byId("illustriousPanel")?.querySelector("h3");
    if (workflowHeading) workflowHeading.textContent = "SDXL / Illustrious 精准生成";
    const hiresControls = byId("hiresControls");
    if (hiresControls && !byId("hiresSampler")) {
      const row = document.createElement("div");
      row.className = "two";
      row.style.marginTop = "8px";
      row.innerHTML = `<div><div class="field-title"><span>二次采样器</span>${help("高清重绘阶段使用的去噪算法。默认推荐自动，跟随当前模型专属配置；只有做固定参数 A/B 时才手动覆盖。")}</div><select id="hiresSampler" onchange="applyIllustriousMode()"><option value="auto">自动（按模型预设，推荐）</option></select></div><div><div class="field-title"><span>二次调度器</span>${help("高清重绘阶段的噪声曲线。默认推荐自动；错误调度器可能造成柔糊、噪点或模型风格偏移。")}</div><select id="hiresScheduler" onchange="applyIllustriousMode()"><option value="auto">自动（按模型预设，推荐）</option></select></div>`;
      hiresControls.appendChild(row);
      if (byId("sampler")) byId("hiresSampler").innerHTML = byId("sampler").innerHTML;
      if (byId("scheduler")) byId("hiresScheduler").innerHTML = byId("scheduler").innerHTML;
    }

    const size = byId("size");
    if (size && !Array.from(size.options).some((item) => item.value === "2048x2048")) {
      size.add(new Option("Krea 2 超清方图 2048 × 2048", "2048x2048"));
    }
  }

  function syncSourceLink() {
    const target = byId("advancedSource");
    const current = profile();
    if (!target) return;
    target.textContent = "";
    if (current.source_url) {
      const link = document.createElement("a");
      link.href = current.source_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = current.source || "来源";
      link.style.color = "#cfc4ff";
      target.appendChild(link);
    } else {
      target.textContent = current.source || "";
    }
  }

  function freeuConfig() {
    const configured = profile().freeu;
    return configured && Array.isArray(configured.presets) ? configured : FALLBACK_FREEU;
  }

  function updateFreeuInfo() {
    const select = byId("freeuPreset");
    const info = byId("freeuPresetInfo");
    if (!select || !info) return;
    const preset = freeuConfig().presets.find((item) => item.key === select.value);
    info.textContent = preset
      ? `${preset.note} 当前：b1 ${preset.b1} · b2 ${preset.b2} · s1 ${preset.s1} · s2 ${preset.s2}`
      : "自定义参数；数值 1 表示该通道不缩放。";
  }

  window.applyFreeuPreset = function (key, silent) {
    const config = freeuConfig();
    const preset = config.presets.find((item) => item.key === key) ||
      config.presets.find((item) => item.key === config.key) || config;
    [["freeuB1", "b1"], ["freeuB2", "b2"], ["freeuS1", "s1"], ["freeuS2", "s2"]]
      .forEach(([id, field]) => { if (byId(id)) byId(id).value = preset[field]; });
    if (byId("freeuPreset")) byId("freeuPreset").value = preset.key;
    updateFreeuInfo();
    if (!silent && byId("status")) {
      byId("status").textContent = `已应用 ${preset.label}：b1 ${preset.b1} / b2 ${preset.b2} / s1 ${preset.s1} / s2 ${preset.s2}。`;
    }
  };

  window.freeuPresetChanged = function (key) {
    if (key === "custom") updateFreeuInfo();
    else window.applyFreeuPreset(key, false);
  };

  window.freeuValueChanged = function () {
    if (byId("freeuPreset")) byId("freeuPreset").value = "custom";
    updateFreeuInfo();
  };

  function syncFreeuPresets() {
    const select = byId("freeuPreset");
    if (!select) return;
    const config = freeuConfig();
    const previous = select.value || config.key;
    select.innerHTML = config.presets.map((preset) =>
      `<option value="${preset.key}">${preset.label}</option>`
    ).join("") + '<option value="custom">自定义</option>';
    select.value = previous === "custom" || config.presets.some((preset) => preset.key === previous)
      ? previous
      : config.key;
    if (select.value !== "custom") window.applyFreeuPreset(select.value, true);
    else updateFreeuInfo();
  }

  function syncCapabilities() {
    const current = profile();
    const caps = current.capabilities || {};
    const mode = byId("modelEnhancementMode");
    if (!mode) return;
    const selectedModel = byId("model")?.selectedOptions[0];
    if (selectedModel && current.family === "krea2") {
      selectedModel.textContent = `${selectedModel.value}（${current.label}${current.locked ? "，参数锁定" : ""}）`;
    }
    const freeu = mode.querySelector('option[value="freeu_v2"]');
    const rescale = mode.querySelector('option[value="cfg_rescale"]');
    freeu.disabled = !caps.freeu_v2;
    rescale.disabled = !caps.cfg_rescale;
    if (mode.selectedOptions[0]?.disabled) mode.value = "off";

    const promptLabels = { tags: "标签提示词", hybrid: "标签 + 自然语言", natural_language: "自然语言" };
    const resolution = current.resolution || {};
    const summary = byId("modelCapabilitySummary");
    if (summary) {
      summary.textContent = `${promptLabels[caps.prompt_mode] || "模型自适应提示词"} · ` +
        `${resolution.min || 512}–${resolution.max || 1920}px · ` +
        `${caps.regional_prompting ? "支持多人分区" : "不支持多人分区"} · ` +
        `${caps.negative_prompt === false ? "Turbo 负面提示不生效" : "支持负面提示"}`;
    }

    const maxSize = Number(resolution.max || 1920);
    const size = byId("size");
    if (size) {
      Array.from(size.options).forEach((option) => {
        const [width, height] = option.value.split("x").map(Number);
        option.disabled = Math.max(width || 0, height || 0) > maxSize;
      });
      if (size.selectedOptions[0]?.disabled) {
        const recommended = (resolution.recommended || [])[0];
        const wanted = Array.isArray(recommended) ? recommended.join("x") : "";
        size.value = Array.from(size.options).some((item) => item.value === wanted && !item.disabled)
          ? wanted
          : Array.from(size.options).find((item) => !item.disabled)?.value || size.value;
      }
    }
    syncSourceLink();
    syncFreeuPresets();
    syncOutputCapabilities();
    window.modelAdvancedChanged(true);
    window.vaeModeChanged(true);
  }

  function syncOutputCapabilities() {
    const features = workflowFeatures();
    const mode = byId("outputEnhancementMode");
    if (!mode) return;
    const support = { anime6b: !!features.anime6b, seedvr2: !!features.seedvr2,
      ultimate: !!features.ultimate && profile().family !== "anima" && profile().family !== "krea2" };
    Object.entries(support).forEach(([key, enabled]) => {
      const option = mode.querySelector(`option[value="${key}"]`);
      if (option) option.disabled = !enabled;
    });
    if (mode.selectedOptions[0]?.disabled) mode.value = "off";
    const face = byId("faceDetailerEnabled");
    if (face) {
      face.disabled = !features.face_detailer || profile().family === "krea2";
      if (face.disabled) face.checked = false;
    }
    const color = byId("autoColorMatchEnabled");
    if (color) {
      color.disabled = !features.color_transfer;
      if (color.disabled) color.checked = false;
    }
    const hand = byId("handDetailerEnabled");
    if (hand) {
      hand.disabled = features.hand_detailer !== true || profile().family === "krea2";
      // Before /api/models finishes, capability is undefined. Keep the checked
      // default so it becomes active as soon as the installed detector is known.
      if (features.hand_detailer === false || profile().family === "krea2") hand.checked = false;
    }
    const foot = byId("footDetailerEnabled");
    if (foot) {
      foot.disabled = features.foot_detailer !== true || profile().family === "krea2";
      if (features.foot_detailer === false || profile().family === "krea2") foot.checked = false;
    }
    const missing = [];
    if (!features.anime6b) missing.push("Anime6B 模型");
    if (!features.seedvr2) missing.push("SeedVR2 节点/权重");
    if (!features.ultimate) missing.push("Ultimate SD Upscale 节点");
    if (!features.face_detailer) missing.push("FaceDetailer 检测器");
    if (!features.hand_detailer) missing.push("手部检测模型");
    if (!features.foot_detailer) missing.push("足部检测模型");
    if (!features.color_transfer) missing.push("ColorTransfer 节点");
    const status = byId("outputEnhancementAvailability");
    if (status) status.textContent = missing.length
      ? `本机尚不可用：${missing.join("、")}；对应选项已禁用。`
      : "输出增强依赖均已就绪。建议固定种子逐项 A/B，避免同时叠加多个增强。";
    window.outputEnhancementChanged(true);
  }

  window.outputEnhancementChanged = function (silent) {
    const mode = byId("outputEnhancementMode")?.value || "off";
    const defaults = OUTPUT_DEFAULTS[mode] || OUTPUT_DEFAULTS.off;
    if (!silent && byId("outputEnhancementScale")) {
      byId("outputEnhancementScale").value = defaults.scale;
      if (mode === "ultimate") {
        if (byId("ultimateSteps")) byId("ultimateSteps").value = 20;
        if (byId("ultimateDenoise")) byId("ultimateDenoise").value = 0.2;
        if (byId("ultimateTileSize")) byId("ultimateTileSize").value = 512;
      } else if (mode === "seedvr2" && byId("seedvrColor")) {
        byId("seedvrColor").value = "lab";
      }
    }
    if (mode !== "off" && byId("illustriousMode")?.value === "hires") {
      byId("illustriousMode").value = "precision";
      if (typeof window.applyIllustriousMode === "function") window.applyIllustriousMode();
    }
    if (byId("ultimateControls")) byId("ultimateControls").style.display = mode === "ultimate" ? "grid" : "none";
    if (byId("seedvrControls")) byId("seedvrControls").style.display = mode === "seedvr2" ? "block" : "none";
    if (byId("faceDetailerControls")) byId("faceDetailerControls").style.display = byId("faceDetailerEnabled")?.checked ? "grid" : "none";
    const limbBlocked = profile().family === "krea2" || !!byId("regionsEnabled")?.checked || byId("illustriousMode")?.value === "repair";
    for (const id of ["handDetailerEnabled", "footDetailerEnabled"]) {
      const control = byId(id);
      if (control) control.disabled = limbBlocked || (id === "handDetailerEnabled" ? !workflowFeatures().hand_detailer : !workflowFeatures().foot_detailer);
    }
    const activeLimbDetailer = ["handDetailerEnabled", "footDetailerEnabled"].some((id) => byId(id)?.checked && !byId(id)?.disabled);
    if (byId("limbDetailerControls")) byId("limbDetailerControls").style.display = activeLimbDetailer ? "grid" : "none";
    if (byId("autoColorControls")) byId("autoColorControls").style.display = byId("autoColorMatchEnabled")?.checked ? "grid" : "none";
    if (byId("outputEnhancementRecommendation")) byId("outputEnhancementRecommendation").textContent = defaults.note;
    if (!silent && byId("status")) {
      const labels = { off: "输出增强已关闭，保持模型原始输出。", anime6b: "Anime6B 已启用，并应用推荐 1.5×。", seedvr2: "SeedVR2 已启用，并应用推荐 1.25× + LAB。", ultimate: "Ultimate SD Upscale 已启用，并应用推荐 1.5×、20 步、0.20 重绘、Tile 512。" };
      byId("status").textContent = labels[mode] || labels.off;
    }
  };

  window.modelAdvancedChanged = function (silent) {
    const mode = byId("modelEnhancementMode")?.value || "off";
    if (byId("freeuControls")) byId("freeuControls").style.display = mode === "freeu_v2" ? "block" : "none";
    if (byId("cfgRescaleControls")) byId("cfgRescaleControls").style.display = mode === "cfg_rescale" ? "block" : "none";
    if (!silent && byId("status")) {
      byId("status").textContent = mode === "off"
        ? "模型增强已关闭，保持原始模型基线。"
        : mode === "freeu_v2"
          ? `FreeU V2 已启用：${byId("freeuPreset")?.selectedOptions[0]?.textContent || "当前推荐组合"}；建议固定种子与关闭状态对比。`
          : "CFG Rescale 已启用，仅用于当前 v-pred 模型。";
    }
  };

  window.vaeModeChanged = function (silent) {
    const tiled = byId("vaeMode")?.value === "tiled";
    if (byId("vaeTiledControls")) byId("vaeTiledControls").style.display = tiled ? "block" : "none";
    if (!silent && byId("status")) {
      byId("status").textContent = tiled
        ? "已启用 Tiled VAE：显存占用更低，但编解码会变慢。"
        : "已恢复标准 VAE 编解码。";
    }
  };

  function wrapPayload() {
    if (typeof window.payload !== "function" || window.payload.__advancedWrapped) return;
    const original = window.payload;
    const wrapped = function () {
      const data = original();
      data.modelEnhancement = {
        mode: byId("modelEnhancementMode")?.value || "off",
        b1: byId("freeuB1")?.value || 1.3,
        b2: byId("freeuB2")?.value || 1.4,
        s1: byId("freeuS1")?.value || 0.9,
        s2: byId("freeuS2")?.value || 0.2,
        multiplier: byId("cfgRescaleMultiplier")?.value || 0.7,
      };
      data.vae = {
        mode: byId("vaeMode")?.value || "standard",
        tileSize: byId("vaeTileSize")?.value || 512,
        overlap: byId("vaeOverlap")?.value || 64,
      };
      data.outputEnhancement = {
        mode: byId("outputEnhancementMode")?.value || "off",
        scale: byId("outputEnhancementScale")?.value || 1.5,
        steps: byId("ultimateSteps")?.value || 20,
        denoise: byId("ultimateDenoise")?.value || 0.2,
        tileSize: byId("ultimateTileSize")?.value || 512,
        seedvrColor: byId("seedvrColor")?.value || "lab",
        faceDetailer: {
          enabled: !!byId("faceDetailerEnabled")?.checked,
          guideSize: byId("faceDetailerGuideSize")?.value || 512,
          steps: byId("faceDetailerSteps")?.value || 12,
          denoise: byId("faceDetailerDenoise")?.value || 0.35,
        },
        limbDetailer: {
          hands: !!byId("handDetailerEnabled")?.checked && !byId("handDetailerEnabled")?.disabled,
          feet: !!byId("footDetailerEnabled")?.checked && !byId("footDetailerEnabled")?.disabled,
          guideSize: byId("limbDetailerGuideSize")?.value || 512,
          steps: byId("limbDetailerSteps")?.value || 16,
          denoise: byId("limbDetailerDenoise")?.value || 0.45,
        },
        colorMatch: {
          enabled: !!byId("autoColorMatchEnabled")?.checked,
          method: byId("autoColorMethod")?.value || "reinhard_lab",
          strength: byId("autoColorStrength")?.value || 0.7,
        },
      };
      return data;
    };
    wrapped.__advancedWrapped = true;
    window.payload = wrapped;
  }

  function wrapProfileRefresh(name) {
    const original = window[name];
    if (typeof original !== "function" || original.__capabilityWrapped) return;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      syncCapabilities();
      return result;
    };
    wrapped.__capabilityWrapped = true;
    window[name] = wrapped;
  }

  function wrapHiresConflict() {
    const original = window.applyIllustriousMode;
    if (typeof original !== "function" || original.__outputConflictWrapped) return;
    const wrapped = function (...args) {
      if (byId("illustriousMode")?.value === "hires" &&
          byId("outputEnhancementMode")?.value !== "off") {
        byId("outputEnhancementMode").value = "off";
        window.outputEnhancementChanged(true);
      }
      const result = original.apply(this, args);
      window.outputEnhancementChanged(true);
      return result;
    };
    wrapped.__outputConflictWrapped = true;
    window.applyIllustriousMode = wrapped;
  }

  installPanel();
  wrapPayload();
  wrapProfileRefresh("renderAdvancedRecommendation");
  wrapProfileRefresh("applySamplingProfileForModel");
  wrapProfileRefresh("modelChanged");
  wrapProfileRefresh("toggleRegions");
  wrapHiresConflict();
  syncCapabilities();
})();
