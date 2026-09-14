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
      <div class="small">滑杆折算成加权相机词（from left / eye-level / close-up …），生成时并入正向提示词。
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
        <div id="cameraControlPresets">
          ${PRESETS.map((group) => `
            <div class="field-title" style="margin-top:6px"><span>${escapeHtml(group.title)}</span></div>
            <div class="actions">
              ${group.items.map(([label, key, value]) =>
                `<button type="button" class="secondary" onclick="cameraControlSetPreset('${key}', ${value})">${escapeHtml(label)}</button>`).join("")}
            </div>`).join("")}
        </div>
        <div class="field-title" style="margin-top:8px"><span>将写入的机位词</span></div>
        <div id="cameraControlPreviewValue" class="small" style="word-break:break-all">（未启用）</div>
        <div class="two" style="margin-top:8px">
          <div><div class="field-title"><span>机位 LoRA 权重</span></div><input id="cameraControlLoraWeight" type="number" min="0.1" max="1.5" step="0.05" value="0.8"></div>
          <div><div class="field-title"><span>挂载</span></div><div class="actions"><button type="button" class="secondary" onclick="cameraControlMountLora()">挂载机位 LoRA</button><button type="button" class="secondary" onclick="cameraControlReset()">重置滑杆</button></div></div>
        </div>
        <div id="cameraControlStatus" class="small"></div>
      </div>`;
    anchor.appendChild(block);
    byId("cameraControlEnabled")?.addEventListener("change", cameraControlRefresh);
    AXES.forEach((axis) => {
      byId("cameraControl_" + axis.key)?.addEventListener("input", cameraControlRefresh);
    });
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
    } catch (error) {
      status.textContent = "挂载失败：" + error.message;
    }
  };

  function cameraControlRefresh() {
    const state = window.cameraControlState();
    const body = byId("cameraControlBody");
    if (body) body.style.display = state.enabled ? "" : "none";
    ["x", "y", "z", "roll"].forEach((key) => {
      const label = byId("cameraControlValue_" + key);
      if (label) label.textContent = Number(state[key]).toFixed(2);
    });
    if (window.promptEditorChanged) window.promptEditorChanged();
    scheduleCameraPreview();
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
      window.cameraControlSyncVisibility();
      cameraControlRefresh();
      return result;
    };
    wrapped.__cameraControlWrapped = true;
    window.modelChanged = wrapped;
  }

  function boot() {
    installPanel();
    injectPayload();
    injectCompilePayload();
    wrapRestore();
    wrapModelChanged();
    window.cameraControlSyncVisibility();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
