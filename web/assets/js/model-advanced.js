(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);

  function profile() {
    return typeof window.currentSamplingProfile === "function"
      ? window.currentSamplingProfile()
      : {};
  }

  function advancedPanelHtml() {
    return `
      <summary>模型增强与低显存 VAE</summary>
      <div class="color-panel">
        <div class="small" id="modelCapabilitySummary">读取当前模型能力…</div>
        <div class="two" style="margin-top:8px">
          <div>
            <div class="field-title"><span>模型增强</span><span class="small">默认关闭，不改变原工作流</span></div>
            <select id="modelEnhancementMode" onchange="modelAdvancedChanged()">
              <option value="off">关闭（推荐基线）</option>
              <option value="freeu_v2">FreeU V2（SDXL/Illustrious 细节）</option>
              <option value="cfg_rescale">CFG Rescale（仅 v-pred 防过曝）</option>
            </select>
          </div>
          <div>
            <div class="field-title"><span>VAE 编解码</span><span class="small">大图显存不足时使用分块</span></div>
            <select id="vaeMode" onchange="vaeModeChanged()">
              <option value="standard">标准（保持现有速度）</option>
              <option value="tiled">Tiled（低显存，较慢）</option>
            </select>
          </div>
        </div>
        <div id="freeuControls" style="display:none">
          <div class="field-title"><span>FreeU V2 参数</span><span class="small">ComfyUI 原生默认值，建议先固定种子 A/B 对比</span></div>
          <div class="two"><input id="freeuB1" type="number" min="0" max="10" step="0.01" value="1.3" title="Backbone stage 1"><input id="freeuB2" type="number" min="0" max="10" step="0.01" value="1.4" title="Backbone stage 2"></div>
          <div class="two" style="margin-top:6px"><input id="freeuS1" type="number" min="0" max="10" step="0.01" value="0.9" title="Skip stage 1"><input id="freeuS2" type="number" min="0" max="10" step="0.01" value="0.2" title="Skip stage 2"></div>
        </div>
        <div id="cfgRescaleControls" style="display:none">
          <div class="field-title"><span>CFG Rescale 强度</span><span class="small">降低高 CFG 的过曝与色彩烧灼</span></div>
          <input id="cfgRescaleMultiplier" type="number" min="0" max="1" step="0.01" value="0.7">
        </div>
        <div id="vaeTiledControls" style="display:none">
          <div class="two" style="margin-top:8px">
            <div><div class="field-title"><span>Tile 大小</span></div><select id="vaeTileSize"><option value="384">384（更省显存）</option><option value="512" selected>512（推荐）</option><option value="768">768（更快）</option><option value="1024">1024</option></select></div>
            <div><div class="field-title"><span>重叠像素</span></div><select id="vaeOverlap"><option value="32">32</option><option value="64" selected>64（推荐）</option><option value="96">96</option><option value="128">128</option></select></div>
          </div>
          <div class="small" style="margin-top:6px">Tiled 会同时用于普通 img2img 的 VAE Encode 和最终 Decode；局部修复仍使用专用 Inpaint 编码节点。</div>
        </div>
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

  function syncCapabilities() {
    const current = profile();
    const caps = current.capabilities || {};
    const mode = byId("modelEnhancementMode");
    if (!mode) return;
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
    window.modelAdvancedChanged(true);
    window.vaeModeChanged(true);
  }

  window.modelAdvancedChanged = function (silent) {
    const mode = byId("modelEnhancementMode")?.value || "off";
    if (byId("freeuControls")) byId("freeuControls").style.display = mode === "freeu_v2" ? "block" : "none";
    if (byId("cfgRescaleControls")) byId("cfgRescaleControls").style.display = mode === "cfg_rescale" ? "block" : "none";
    if (!silent && byId("status")) {
      byId("status").textContent = mode === "off"
        ? "模型增强已关闭，保持原始模型基线。"
        : mode === "freeu_v2"
          ? "FreeU V2 已启用；建议固定种子与关闭状态对比，效果不佳时直接关闭。"
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

  installPanel();
  wrapPayload();
  wrapProfileRefresh("renderAdvancedRecommendation");
  wrapProfileRefresh("applySamplingProfileForModel");
  wrapProfileRefresh("modelChanged");
  syncCapabilities();
})();
