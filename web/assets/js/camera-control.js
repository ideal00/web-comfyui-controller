/* 相机机位控制（BSK 语义）：滑杆 → 加权相机提示词。
 *
 * 与 BSK 插件的 BSK_相机控制 节点同一套参数（左右 X / 上下 Y / 前后 Z / 翻滚 Roll），
 * 但不需要安装外部插件：面板在生成时直接把机位词并入正向提示词。
 * 真正的机位效果来自配套 LoRA（Anima 版：anima_相机机位控制（BSK），作者建议权重 0.6–1.0）。
 * 算法唯一权威在后端 easy_panel_app/camera_control.py；本脚本只做界面、预览请求与 payload 接线。
 */
(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const LORA_HINT = "相机机位控制";

  const AXES = [
    { key: "x", label: "左右 X（方位）", hint: "0=正面；0.5→from left；-0.5→from right；±1=背面。方位预算 10×，占比低于 0.2 的方向不输出。" },
    { key: "y", label: "上下 Y（高度）", hint: "0=平视（eye-level 权重最高 3.0）；+0.4 俯视；+0.85 鸟瞰；-0.4 仰视；-0.85 正下。" },
    { key: "z", label: "前后 Z（距离）", hint: "0=中景；+0.5 近景；+0.9 特写；-0.5 全身；-0.9 远景。" },
    { key: "roll", label: "翻滚 Roll（倾斜）", hint: "|值| ≥ 0.15 时输出 dutch angle。" },
  ];
  const PRESETS = [
    { title: "方位", items: [["正面", "x", 0], ["左机位", "x", 0.5], ["右机位", "x", -0.5], ["背面", "x", 1]] },
    { title: "高度", items: [["鸟瞰", "y", 0.85], ["俯视", "y", 0.4], ["平视", "y", 0], ["仰视", "y", -0.4], ["正下", "y", -0.85]] },
    { title: "距离", items: [["特写", "z", 0.9], ["近景", "z", 0.5], ["中景", "z", 0], ["全身", "z", -0.5], ["远景", "z", -0.9]] },
  ];

  let previewTimer = 0;
  let quickPreviewTimer = 0;
  let quickPreviewBusy = false;
  let quickPreviewSeed = null;
  let quickPreviewCount = 0;

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = String(value || "");
    return node.innerHTML;
  }

  function installPanel() {
    const anchor = byId("animaPromptPanel");
    if (!anchor || byId("cameraControlPanel")) return;
    const block = document.createElement("details");
    block.id = "cameraControlPanel";
    block.className = "camera-control-panel";
    block.innerHTML = `
      <summary>机位控制（BSK 相机：左右 / 上下 / 前后 / 翻滚）</summary>
      <div class="small">滑杆只改「提示词」：下面的机位词框和右侧「最终提示词」会马上变；<b>图片要重新生成才会变</b>。
        机位本身不会凭空生效——需要同时挂载配套的「相机机位控制（BSK）」LoRA（权重 0.6–1.0）。</div>
      <label class="switch" style="margin-top:6px"><input id="cameraControlEnabled" type="checkbox"><div><b>启用机位控制</b><div class="small">关闭时滑杆值不会进入提示词。</div></div></label>
      <div id="cameraControlBody" style="display:none">
        <div id="cameraControlAxes">
          ${AXES.map((axis) => `
            <div class="camera-control-axis">
              <div class="field-title"><span>${escapeHtml(axis.label)}</span><span class="small" id="cameraControlValue_${axis.key}">0.00</span></div>
              <input id="cameraControl_${axis.key}" type="range" min="-1" max="1" step="0.05" value="0" title="${escapeHtml(axis.hint)}">
              <div class="small">${escapeHtml(axis.hint)}</div>
            </div>`).join("")}
        </div>
        <canvas id="cameraControlStage" style="width:100%;height:190px;display:block;border-radius:6px;background:rgba(127,127,127,.10);touch-action:none;cursor:grab"></canvas>
        <div class="small">舞台可拖：左右 = 环绕（X）、上下 = 俯仰（Y）；双击归位。</div>
        <div id="cameraControlPresets">
          ${PRESETS.map((group) => `
            <div class="field-title" style="margin-top:6px"><span>${escapeHtml(group.title)}</span></div>
            <div class="actions">
              ${group.items.map(([label, key, value]) =>
                `<button type="button" class="secondary" onclick="cameraControlSetPreset('${key}', ${value})">${escapeHtml(label)}</button>`).join("")}
            </div>`).join("")}
        </div>
        <div class="field-title" style="margin-top:8px"><span>将写入的机位词（实时）</span></div>
        <div id="cameraControlPreviewBox" style="border:1px solid rgba(127,127,127,.45);border-radius:6px;padding:6px 8px;background:rgba(127,127,127,.10)">
          <div id="cameraControlSummary" style="font-weight:600">当前：—</div>
          <div id="cameraControlPreviewValue" class="small" style="word-break:break-all">（未启用）</div>
        </div>
        <div id="cameraControlHint" class="small"></div>
        <div class="two" style="margin-top:8px">
          <div><div class="field-title"><span>机位 LoRA 权重</span></div><input id="cameraControlLoraWeight" type="number" min="0.1" max="1.5" step="0.05" value="0.8"></div>
          <div><div class="field-title"><span>挂载</span></div><div class="actions"><button type="button" class="secondary" onclick="cameraControlMountLora()">挂载机位 LoRA</button><button type="button" class="secondary" onclick="cameraControlReset()">重置滑杆</button></div></div>
        </div>
        <div id="cameraControlStatus" class="small"></div>
        <div class="field-title" style="margin-top:8px"><span>快速预览（松手自动出图）</span></div>
        <label class="switch"><input id="cameraControlAutoPreview" type="checkbox"><div><b>拖动结束后自动跑一张预览图</b><div class="small">停止拖动约 1.5 秒后，按当前机位跑一张低步数图（同一 Seed 便于对比，只跑首采）；会占用算力，图片存到 <code>output/EasyPanel_aux</code> 子目录，不会进作品库。</div></div></label>
        <div class="two" style="margin-top:6px">
          <div><div class="field-title"><span>预览步数</span></div><input id="cameraControlPreviewSteps" type="number" min="4" max="30" step="1" value="8"></div>
          <div><div class="field-title"><span>手动</span></div><div class="actions"><button type="button" class="secondary" onclick="cameraControlQuickPreview(true)">立即预览</button></div></div>
        </div>
      </div>`;
    anchor.appendChild(block);
    byId("cameraControlEnabled")?.addEventListener("change", cameraControlRefresh);
    AXES.forEach((axis) => {
      byId("cameraControl_" + axis.key)?.addEventListener("input", cameraControlRefresh);
    });
    bindCameraStage();
    window.cameraControlSyncVisibility();
    cameraControlRefresh();
  }

  // 与后端 capabilities/detail_refine 同理：机位 LoRA 只有 Anima 版，其他族先不显示。
  function cameraCapable() {
    try {
      if (window.modelFamilyClient) return window.modelFamilyClient() === "anima";
    } catch (error) { /* 回退到下面的文件名嗅探 */ }
    const model = String(byId("model")?.value || "").toLowerCase();
    return model.includes("anima");
  }

  window.cameraControlState = function () {
    return {
      enabled: byId("cameraControlEnabled")?.checked === true,
      x: Number(byId("cameraControl_x")?.value || 0),
      y: Number(byId("cameraControl_y")?.value || 0),
      z: Number(byId("cameraControl_z")?.value || 0),
      roll: Number(byId("cameraControl_roll")?.value || 0),
    };
  };

  window.cameraControlSetPreset = function (key, value) {
    const input = byId("cameraControl_" + key);
    if (!input) return;
    input.value = String(value);
    if (byId("cameraControlEnabled") && !byId("cameraControlEnabled").checked) {
      byId("cameraControlEnabled").checked = true;
    }
    cameraControlRefresh();
  };

  window.cameraControlReset = function () {
    ["x", "y", "z", "roll"].forEach((key) => {
      const input = byId("cameraControl_" + key);
      if (input) input.value = "0";
    });
    cameraControlRefresh();
  };

  window.cameraControlMountLora = async function () {
    const status = byId("cameraControlStatus");
    if (!status) return;
    try {
      const response = await fetch("/api/models");
      const data = await response.json();
      const found = (data.loras || []).find((name) => String(name).includes(LORA_HINT));
      if (!found) {
        status.textContent = "模型目录里没有找到机位 LoRA；先把 anima_相机机位控制（BSK）.safetensors 放进 Anima_Soft_Illustration/03_通用功能。";
        return;
      }
      const current = (window.payload() || {}).loras || [];
      if (current.some((item) => item.name === found)) {
        status.textContent = "机位 LoRA 已在 LoRA 列表中，无需重复挂载。";
        return;
      }
      const weight = Number(byId("cameraControlLoraWeight")?.value || 0.8);
      window.addLora(found, String(weight));
      status.textContent = `已挂载 ${String(found).split(/[\\/]/).pop()}（权重 ${weight}）。`;
      updateCameraControlHint();
    } catch (error) {
      status.textContent = "挂载失败：" + error.message;
    }
  };

  // ---------- 实时 3D 舞台（透视轨道 + 可拖拽相机 + 视线） ----------
  const STAGE = { dragging: false, lastX: 0, lastY: 0 };

  function setSlider(key, value) {
    const input = byId("cameraControl_" + key);
    if (input) input.value = String(Math.max(-1, Math.min(1, value)).toFixed(2));
  }

  function drawCameraStage() {
    const canvas = byId("cameraControlStage");
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(220, Math.round(rect.width) || 480);
    const h = Math.max(150, Math.round(rect.height) || 190);
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const state = window.cameraControlState();
    const cx = w / 2;
    const cy = h * 0.60;
    const baseR = Math.min(w * 0.32, h * 0.62);
    const radius = baseR * (1 - state.z * 0.45);
    const rx = radius;
    const ry = radius * 0.42;
    const az = state.x * Math.PI;

    // 轨道 + 地面参考轴
    ctx.save();
    ctx.strokeStyle = "rgba(150,150,150,.55)";
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = "rgba(150,150,150,.28)";
    ctx.beginPath(); ctx.moveTo(cx - baseR, cy); ctx.lineTo(cx + baseR, cy); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(cx, cy - ry); ctx.lineTo(cx, cy + ry); ctx.stroke();
    ctx.restore();

    // 被摄体
    const subjY = cy - Math.min(24, ry * 0.35);
    const sphere = ctx.createRadialGradient(cx - 5, subjY - 7, 2, cx, subjY, 17);
    sphere.addColorStop(0, "#d7dde3");
    sphere.addColorStop(1, "#5b636c");
    ctx.fillStyle = sphere;
    ctx.beginPath(); ctx.arc(cx, subjY, 15, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "rgba(170,175,180,.9)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("人物", cx, cy + ry + 20);

    // 相机位置（方位 → 椭圆上，高度 → 屏幕 Y，距离 → 轨道半径）
    const mx = cx + rx * Math.sin(az);
    const my = cy + ry * Math.cos(az) - state.y * h * 0.34;

    // 视线 + 高度参考线
    ctx.strokeStyle = "rgba(74,163,255,.6)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(mx, my); ctx.lineTo(cx, subjY); ctx.stroke();
    ctx.strokeStyle = "rgba(74,163,255,.3)";
    ctx.beginPath(); ctx.moveTo(mx, my); ctx.lineTo(mx, cy + ry * Math.cos(az)); ctx.stroke();
    ctx.setLineDash([]);

    // 相机标记（随 Roll 旋转）
    ctx.save();
    ctx.translate(mx, my);
    ctx.rotate(state.roll * Math.PI * 0.28);
    ctx.fillStyle = "#4aa3ff";
    ctx.strokeStyle = "rgba(0,0,0,.35)";
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") ctx.roundRect(-13, -9, 26, 18, 4);
    else ctx.rect(-13, -9, 26, 18);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#0b1220";
    ctx.beginPath(); ctx.arc(0, 0, 4.5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,.9)";
    ctx.beginPath(); ctx.arc(-1.5, -1.5, 1.6, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }

  function bindCameraStage() {
    const canvas = byId("cameraControlStage");
    if (!canvas || canvas.__cameraControlBound) return;
    canvas.__cameraControlBound = true;
    canvas.addEventListener("pointerdown", (event) => {
      if (byId("cameraControlEnabled") && !byId("cameraControlEnabled").checked) {
        byId("cameraControlEnabled").checked = true;
      }
      STAGE.dragging = true;
      STAGE.lastX = event.clientX;
      STAGE.lastY = event.clientY;
      canvas.style.cursor = "grabbing";
      try { canvas.setPointerCapture(event.pointerId); } catch (error) { /* 忽略 */ }
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!STAGE.dragging) return;
      const dx = event.clientX - STAGE.lastX;
      const dy = event.clientY - STAGE.lastY;
      STAGE.lastX = event.clientX;
      STAGE.lastY = event.clientY;
      setSlider("x", Number(byId("cameraControl_x")?.value || 0) + dx * 0.006);
      setSlider("y", Number(byId("cameraControl_y")?.value || 0) - dy * 0.006);
      cameraControlRefresh();
    });
    const stopDrag = (event) => {
      STAGE.dragging = false;
      canvas.style.cursor = "grab";
      try { canvas.releasePointerCapture(event.pointerId); } catch (error) { /* 忽略 */ }
    };
    canvas.addEventListener("pointerup", stopDrag);
    canvas.addEventListener("pointercancel", stopDrag);
    canvas.addEventListener("dblclick", () => window.cameraControlReset());
    window.addEventListener("resize", drawCameraStage);
  }

  function directionLabel(x) {
    // 与后端归一化后 “谁占大头” 一致：|<0.25| 正面、0.25–0.75 左右、>0.75 背面。
    if (Math.abs(x) >= 0.75) return "背面";
    if (x >= 0.25) return "左机位";
    if (x <= -0.25) return "右机位";
    return "正面";
  }

  function elevationLabel(y) {
    if (y > 0.7) return "鸟瞰";
    if (y > 0.2) return "俯视";
    if (y >= 0) return "平视";
    if (y >= -0.7) return "仰视";
    return "正下";
  }

  function distanceLabel(z) {
    if (z > 0.7) return "特写";
    if (z > 0.2) return "近景";
    if (z >= -0.2) return "中景";
    if (z >= -0.7) return "全身";
    return "远景";
  }

  function cameraControlRefresh() {
    const state = window.cameraControlState();
    const body = byId("cameraControlBody");
    if (body) body.style.display = state.enabled ? "" : "none";
    ["x", "y", "z", "roll"].forEach((key) => {
      const label = byId("cameraControlValue_" + key);
      if (label) label.textContent = Number(state[key]).toFixed(2);
    });
    const summary = byId("cameraControlSummary");
    if (summary) {
      summary.textContent = state.enabled
        ? `当前：${directionLabel(state.x)} · ${elevationLabel(state.y)} · ${distanceLabel(state.z)}`
          + (Math.abs(state.roll) >= 0.15 ? " · 倾斜" : "")
        : "当前：未启用";
    }
    drawCameraStage();
    updateCameraControlHint();
    if (window.promptEditorChanged) window.promptEditorChanged();
    scheduleCameraPreview();
    scheduleQuickPreview();
  }

  // 松手后的低步数预览：拖完就出一张图，效果上就是“调机位→图片跟着变”。
  function cameraAutoPreviewEnabled() {
    return byId("cameraControlAutoPreview")?.checked === true
      && byId("cameraControlEnabled")?.checked === true
      && cameraCapable();
  }

  function scheduleQuickPreview() {
    if (!cameraAutoPreviewEnabled() || quickPreviewBusy) return;
    clearTimeout(quickPreviewTimer);
    quickPreviewTimer = setTimeout(() => window.cameraControlQuickPreview(false), 1500);
  }

  window.cameraControlQuickPreview = async function () {
    if (quickPreviewBusy || !byId("model")?.value) return;
    const steps = Math.max(4, Math.min(30, Number(byId("cameraControlPreviewSteps")?.value || 8)));
    quickPreviewBusy = true;
    const status = byId("cameraControlStatus");
    if (status) status.textContent = "正在跑低步数预览…";
    try {
      const data = window.payload();
      data.steps = steps;
      if (quickPreviewSeed == null) {
        const current = Number(byId("seed")?.value);
        quickPreviewSeed = Number.isFinite(current) && current > 0
          ? current
          : Math.floor(Math.random() * 2 ** 31);
      }
      data.seed = quickPreviewSeed;
      data.filenamePrefix = "camPreview";
      // 落进 output/EasyPanel_aux 子目录：作品库与“最近输出”列表都会跳过。
      data.auxiliaryOutput = true;
      // 预览只跑首采：关掉高清/细节增强/输出增强，避免每次拖动排长链。
      if (data.hires && typeof data.hires === "object") data.hires = { ...data.hires, enabled: false };
      delete data.animaHighres;
      delete data.animaDetailRefine;
      delete data.outputEnhancement;
      if (data.illustriousMode) data.illustriousMode = "precision";
      const response = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const result = await response.json();
      if (result.error) throw new Error(result.error);
      if (window.registerGenerationPrompt) window.registerGenerationPrompt(result.prompt_id, result.plan);
      const images = await window.poll(result.prompt_id);
      if (window.renderGeneratedImages) window.renderGeneratedImages(images);
      quickPreviewCount += 1;
      if (status) status.textContent = `预览 #${quickPreviewCount} 完成（步数 ${steps}，Seed ${quickPreviewSeed}）。`;
    } catch (error) {
      if (status) status.textContent = "预览失败：" + error.message;
    } finally {
      quickPreviewBusy = false;
    }
  };

  // 机位词只是指令，真正执行转向的是配套 LoRA；没挂时直接提醒，别生成完才发现没效果。
  function updateCameraControlHint() {
    const hint = byId("cameraControlHint");
    if (!hint) return;
    const state = window.cameraControlState();
    if (!state.enabled) {
      hint.textContent = "";
      hint.className = "small";
      return;
    }
    let mounted = false;
    try {
      const loras = (window.payload() || {}).loras || [];
      mounted = loras.some((item) => String(item && item.name || "").includes(LORA_HINT));
    } catch (error) { /* 拿不到 LoRA 列表时按未挂载提醒 */ }
    hint.textContent = mounted
      ? "✅ 机位 LoRA 已挂载；生成时这些词会并入正向提示词。"
      : "⚠️ 还没挂载机位 LoRA：机位词只是文字，不会真的转镜头。点上面的「挂载机位 LoRA」。";
    hint.className = "small " + (mounted ? "" : "diagnostic-warning");
  }

  function scheduleCameraPreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(requestCameraPreview, 200);
  }

  async function requestCameraPreview() {
    const target = byId("cameraControlPreviewValue");
    if (!target) return;
    const state = window.cameraControlState();
    if (!state.enabled) {
      target.textContent = "（未启用）";
      return;
    }
    try {
      const response = await fetch("/api/camera-prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x: state.x, y: state.y, z: state.z, roll: state.roll }),
      });
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      target.textContent = (data.terms || []).join(", ") || "（当前滑杆位置不产生机位词）";
    } catch (error) {
      target.textContent = "预览失败（生成仍会按当前滑杆计算）：" + error.message;
    }
  }

  window.cameraControlSyncVisibility = function () {
    const panel = byId("cameraControlPanel");
    if (!panel) return;
    const capable = cameraCapable();
    panel.hidden = !capable;
    if (!capable && byId("cameraControlEnabled")) byId("cameraControlEnabled").checked = false;
  };

  function injectPayload() {
    const original = window.payload;
    if (typeof original !== "function" || original.__cameraControlWrapped) return;
    const wrapped = function (...args) {
      const data = original.apply(this, args) || {};
      const state = window.cameraControlState();
      if (state.enabled && cameraCapable()) data.cameraControl = state;
      return data;
    };
    wrapped.__cameraControlWrapped = true;
    window.payload = wrapped;
  }

  function injectCompilePayload() {
    const original = window.promptCompilePayload;
    if (typeof original !== "function" || original.__cameraControlWrapped) return;
    const wrapped = function (...args) {
      const data = original.apply(this, args) || {};
      const state = window.cameraControlState();
      if (state.enabled && cameraCapable()) data.cameraControl = state;
      return data;
    };
    wrapped.__cameraControlWrapped = true;
    window.promptCompilePayload = wrapped;
  }

  function wrapRestore() {
    const original = window.restorePayloadToPanel;
    if (typeof original !== "function" || original.__cameraControlWrapped) return;
    const wrapped = function (data, ...rest) {
      const result = original.apply(this, [data, ...rest]);
      const camera = data && typeof data === "object" ? data.cameraControl : null;
      if (camera && typeof camera === "object") {
        if (byId("cameraControlEnabled")) byId("cameraControlEnabled").checked = Boolean(camera.enabled);
        ["x", "y", "z", "roll"].forEach((key) => {
          const input = byId("cameraControl_" + key);
          if (input && camera[key] != null) input.value = String(camera[key]);
        });
      }
      window.cameraControlSyncVisibility();
      cameraControlRefresh();
      return result;
    };
    wrapped.__cameraControlWrapped = true;
    window.restorePayloadToPanel = wrapped;
  }

  function wrapModelChanged() {
    const original = window.modelChanged;
    if (typeof original !== "function" || original.__cameraControlWrapped) return;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      quickPreviewSeed = null;
      window.cameraControlSyncVisibility();
      cameraControlRefresh();
      return result;
    };
    wrapped.__cameraControlWrapped = true;
    window.modelChanged = wrapped;
  }

  // LoRA 行增删（挂载/清空/手动改动）后，挂载提醒要跟着变。
  function wrapPromptEditorChanged() {
    const original = window.promptEditorChanged;
    if (typeof original !== "function" || original.__cameraControlWrapped) return;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      updateCameraControlHint();
      return result;
    };
    wrapped.__cameraControlWrapped = true;
    window.promptEditorChanged = wrapped;
  }

  function boot() {
    installPanel();
    injectPayload();
    injectCompilePayload();
    wrapRestore();
    wrapModelChanged();
    wrapPromptEditorChanged();
    window.cameraControlSyncVisibility();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
