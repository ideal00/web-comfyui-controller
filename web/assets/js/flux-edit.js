/* FLUX 智能修图（FLUX.2 Klein 4B Distilled）：对已有成品做后处理。
 *
 * 分工：节点链、参数范围、蒙版裁剪与羽化都在后端
 * `easy_panel_app/flux_klein_edit.py`；这里只负责
 *   结果卡入口 → 对话框 → 拿蒙版（手部工作台 / 导入）→ 提交 /api/generate → 轮询出图。
 * 提交时 payload 里带 `fluxEdit`，后端 build_workflow 一看就走 Klein 那张图，
 * 与主模型 / 提示词编译完全无关（这是「修图」不是「又一个文生图模型」）。
 */
(function (global) {
  "use strict";

  const MODES = Object.freeze([
    ["full", "整图细化"],
    ["regional", "局部修复"],
  ]);
  const STRATEGIES = Object.freeze([
    ["conservative", "保守"],
    ["standard", "标准"],
    ["restructure", "重构"],
  ]);
  const PRESERVE_OPTIONS = Object.freeze([
    ["identity", "角色身份"],
    ["face", "脸部"],
    ["pose", "姿势"],
    ["clothing", "服装设计"],
    ["composition", "构图与镜头"],
    ["background", "背景"],
  ]);
  const DEFAULT_PRESERVE = Object.freeze(PRESERVE_OPTIONS.map(([key]) => key));
  const MASK_STORAGE_KEY = "easyPanelFluxMaskV1";

  const DEFAULT_INSTRUCTION = {
    full: "Refine hair strands, fabric texture, small accessories and lighting. Keep the character, pose and composition unchanged.",
    regional: "Repair the selected region: fix the details, keep the surrounding pixels and style unchanged.",
  };

  const MODEL_FOLDERS = Object.freeze({
    "flux-2-klein-4b-fp8.safetensors": "models/diffusion_models/",
    "qwen_3_4b.safetensors": "models/text_encoders/",
    "flux2-vae.safetensors": "models/vae/",
  });

  /**
   * ComfyUI 的 400 会把 node_errors 整包丢回来；缺模型时直接告诉用户放哪里。
   * 其余情况退回原始文本，不吞错误信息。
   */
  function readableError(message) {
    const raw = String(message == null ? "" : message).trim();
    if (!raw) return "未知错误";
    let payload = null;
    try {
      payload = JSON.parse(raw);
    } catch (_) {
      return raw;
    }
    const nodeErrors = payload && payload.node_errors;
    if (!nodeErrors || typeof nodeErrors !== "object") {
      return (payload && (payload.error || payload.message)) ? String(payload.error || payload.message) : raw;
    }
    const hints = [];
    for (const entry of Object.values(nodeErrors)) {
      for (const item of (entry && entry.errors) || []) {
        const details = String((item && item.details) || item.message || "").trim();
        const name = /'([^']+)' not in/.exec(details);
        if (name && MODEL_FOLDERS[name[1]]) {
          hints.push(`缺少模型文件 ${name[1]}（请放到 ComfyUI 的 ${MODEL_FOLDERS[name[1]]} 下）`);
        } else if (details) {
          hints.push(details);
        }
      }
    }
    return hints.length ? hints.slice(0, 3).join("；") : raw;
  }

  function normalizeMode(value) {
    const key = String(value == null ? "" : value).trim().toLowerCase();
    return MODES.some(([item]) => item === key) ? key : "full";
  }

  function normalizeStrategy(value) {
    const key = String(value == null ? "" : value).trim().toLowerCase();
    return STRATEGIES.some(([item]) => item === key) ? key : "standard";
  }

  function normalizePreserve(values) {
    if (!Array.isArray(values)) return DEFAULT_PRESERVE.slice();
    const allowed = new Set(PRESERVE_OPTIONS.map(([key]) => key));
    const seen = [];
    for (const item of values) {
      const key = String(item == null ? "" : item).trim().toLowerCase();
      if (allowed.has(key) && !seen.includes(key)) seen.push(key);
    }
    return seen;
  }

  /** 表单状态 → 提交给 /api/generate 的 fluxEdit 字段（纯函数，方便测试）。 */
  function normalizeEdit(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    const mode = normalizeMode(source.mode);
    return {
      enabled: true,
      mode,
      source: String(source.source || "").trim(),
      mask: String(source.mask || "").trim(),
      instruction: String(source.instruction || "").trim(),
      strategy: normalizeStrategy(source.strategy),
      preserve: normalizePreserve(source.preserve),
      references: Array.isArray(source.references)
        ? source.references.map((item) => String(item || "").trim()).filter(Boolean).slice(0, 2)
        : [],
      megapixels: Number(source.megapixels) > 0 ? Number(source.megapixels) : 1,
    };
  }

  /** 明确的客户端校验（后端还会再查一遍；这里只为即时提示）。 */
  function validateEdit(edit) {
    const errors = [];
    if (!edit.source) errors.push("请先选择要修的原图。");
    if (!edit.instruction) errors.push("请填写「修改描述」。");
    if (edit.mode === "regional" && !edit.mask) errors.push("局部修复需要蒙版：请先圈出要改的区域。");
    return errors;
  }

  function describeEdit(edit) {
    const mode = (MODES.find(([key]) => key === edit.mode) || [, "整图细化"])[1];
    const strategy = (STRATEGIES.find(([key]) => key === edit.strategy) || [, "标准"])[1];
    const parts = [`${mode} · ${strategy}`];
    if (edit.mode === "regional") parts.push("带蒙版");
    if (edit.references.length) parts.push(`${edit.references.length} 张参考图`);
    return parts.join(" · ");
  }

  /** payload + fluxEdit（父版本交给后端按文件名自动认领，前端不猜编号）。 */
  function buildRequestPayload(edit, basePayload) {
    const base = basePayload && typeof basePayload === "object" ? basePayload : {};
    return { ...base, fluxEdit: edit, operation: "flux_edit" };
  }

  const testApi = {
    MODES, STRATEGIES, PRESERVE_OPTIONS, DEFAULT_PRESERVE, DEFAULT_INSTRUCTION,
    MASK_STORAGE_KEY, MODEL_FOLDERS,
    normalizeMode, normalizeStrategy, normalizePreserve, normalizeEdit,
    validateEdit, describeEdit, buildRequestPayload, readableError,
  };
  global.EasyPanelFluxEdit = testApi;
  if (typeof module !== "undefined" && module.exports) module.exports = testApi;
  if (typeof global.document === "undefined") return;

  const byId = (id) => global.document.getElementById(id);
  const esc = (value) => String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  let dialog = null;
  let busy = false;
  let memory = { mask: "", preview: "" };
  let handPrefill = null;

  const STYLE = `
dialog.flux-edit{border:1px solid var(--line,#3a3a46);border-radius:12px;padding:12px;max-width:min(96vw,760px);background:#16161c;color:inherit}
dialog.flux-edit::backdrop{background:rgba(0,0,0,.55)}
dialog.flux-edit .fx-head{display:flex;justify-content:space-between;align-items:center;gap:10px}
dialog.flux-edit .fx-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px}
dialog.flux-edit .fx-block{margin-top:10px}
dialog.flux-edit .fx-block>b{display:block;margin-bottom:4px}
dialog.flux-edit select,dialog.flux-edit textarea{width:100%;box-sizing:border-box}
dialog.flux-edit .fx-source{display:flex;gap:10px;align-items:flex-start}
dialog.flux-edit .fx-source img{max-width:132px;max-height:132px;border-radius:8px;border:1px solid var(--line,#3a3a46)}
dialog.flux-edit .fx-mask-preview{max-width:132px;max-height:132px;border-radius:8px;border:1px solid var(--line,#3a3a46);background:#000}
dialog.flux-edit .fx-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:6px}
dialog.flux-edit .fx-note{color:var(--muted,#9a9aa8)}
@media (max-width:720px){dialog.flux-edit .fx-grid{grid-template-columns:1fr}.flux-edit .fx-row{display:block}}
`;

  function injectStyle() {
    if (byId("fluxEditStyle")) return;
    const style = global.document.createElement("style");
    style.id = "fluxEditStyle";
    style.textContent = STYLE;
    global.document.head.appendChild(style);
  }

  function setStatus(message, error) {
    const node = byId("status");
    if (!node) return;
    node.textContent = message;
    node.classList.toggle("diagnostic-error", !!error);
  }

  function loadMemory() {
    try {
      const stored = global.localStorage.getItem(MASK_STORAGE_KEY);
      if (!stored) return;
      const parsed = JSON.parse(stored);
      if (parsed && typeof parsed === "object") {
        memory = { mask: String(parsed.mask || ""), preview: String(parsed.preview || "") };
      }
    } catch (_) {
      memory = { mask: "", preview: "" };
    }
  }

  function saveMemory() {
    try {
      global.localStorage.setItem(MASK_STORAGE_KEY, JSON.stringify(memory));
    } catch (_) {
      /* 隐私模式下写入失败不影响修图 */
    }
  }

  function currentImageName() {
    const link = global.document.querySelector("#result a[href^='/output']");
    const image = global.document.querySelector("#result img");
    const url = (link && link.getAttribute("href")) || (image && image.getAttribute("src")) || "";
    const match = /[?&]name=([^&]+)/.exec(url);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function outputUrl(name) {
    return name ? "/output?name=" + encodeURIComponent(name) : "";
  }

  async function uploadMaskBlob(blob, label, preview) {
    const form = new FormData();
    form.append("mask", blob, "flux_mask.png");
    setStatus("正在上传蒙版…");
    const response = await fetch("/api/upload-flux-mask", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "蒙版上传失败。");
    memory = { mask: String(data.mask || ""), preview: preview || label || memory.preview };
    saveMemory();
    renderMaskRow();
    setStatus("蒙版已就绪：" + (label || "已导入") + "；生成时会只改这块区域。");
    return memory.mask;
  }

  function dataUrlToBlob(dataUrl) {
    const [meta, payload] = String(dataUrl || "").split(",");
    const mime = (/data:([^;]+)/.exec(meta) || [, "image/png"])[1];
    const binary = global.atob(payload || "");
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return new Blob([bytes], { type: mime });
  }

  /** 蒙版预览：导入的图片要看得到缩略图，所以读成 data URL 存下来。 */
  function blobToDataUrl(blob) {
    return new Promise((resolve) => {
      try {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => resolve("");
        reader.readAsDataURL(blob);
      } catch (_) {
        resolve("");
      }
    });
  }

  function maskRowHtml() {
    const preview = memory.preview && /^data:/.test(memory.preview) ? memory.preview : "";
    return `
      <div class="fx-source">
        ${preview ? `<img class="fx-mask-preview" alt="当前蒙版" src="${esc(preview)}">` : ""}
        <div>
          <div class="small">${memory.mask ? "已选择蒙版" : "还没有蒙版（局部修复必需）"}</div>
          <div class="small fx-note">用「手部工作台」圈选后用其中的「✨ 发送到 FLUX 修图」，或直接导入黑白图（白=重绘区）。</div>
          <div class="fx-row">
            <button class="secondary" type="button" data-flux="draw">✋ 手部工作台圈选</button>
            <button class="secondary" type="button" data-flux="reuse" ${memory.mask ? "" : "disabled"}>↩ 最近一次蒙版</button>
            <label class="secondary" style="cursor:pointer">📁 导入蒙版<input type="file" accept="image/png,image/jpeg,image/webp" style="display:none" data-flux="file"></label>
            <button class="secondary" type="button" data-flux="clearmask" ${memory.mask ? "" : "disabled"}>清除</button>
          </div>
        </div>
      </div>`;
  }

  function renderMaskRow() {
    if (!dialog) return;
    const holder = dialog.querySelector('[data-flux="maskrow"]');
    if (holder) holder.innerHTML = maskRowHtml();
  }

  function render() {
    if (!dialog) return;
    const source = (handPrefill && handPrefill.image) || currentImageName();
    const mode = normalizeMode(dialog.dataset ? dialog.dataset.mode : "full");
    const strategy = normalizeStrategy(dialog.dataset ? dialog.dataset.strategy : "standard");
    dialog.innerHTML = `
      <div class="fx-head"><b>✨ FLUX 智能修图</b>
        <button class="secondary" type="button" data-flux="close">取消</button></div>
      <div class="small fx-note">用 FLUX.2 Klein 4B Distilled（4 步蒸馏 + 参考潜空间编辑）在<b>已有成品</b>上做细化或局部修复；结果会作为子版本记进作品库（父版本 = 被修的这张图）。</div>
      <div class="fx-block"><b>原图</b>
        <div class="fx-source">
          ${source ? `<img alt="原图" src="${esc(outputUrl(source))}">` : ""}
          <div>
            <div class="small">${source ? esc(source) : "没有可用的原图：请先生成一张图，或从作品库打开一张。"}</div>
          </div>
        </div>
      </div>
      <div class="fx-block"><b>修图模式</b>
        <div class="fx-row">
          ${MODES.map(([key, label]) => `<label class="small"><input type="radio" name="fluxMode" data-flux="mode" value="${key}"${key === mode ? " checked" : ""}> ${label}</label>`).join("")}
        </div>
      </div>
      <div class="fx-block" data-flux="maskrow">${maskRowHtml()}</div>
      <div class="fx-block"><b>修改描述</b>
        <textarea data-flux="instruction" rows="3" placeholder="refine hair strands and fabric texture">${esc(DEFAULT_INSTRUCTION[mode])}</textarea>
        <div class="small fx-note" style="margin-top:4px">用英文写更稳；不要重复描述角色身份（下面已经替你锁住了）。</div>
      </div>
      <div class="fx-grid">
        <div class="fx-block"><b>修图策略</b>
          <select data-flux="strategy">
            ${STRATEGIES.map(([key, label]) => `<option value="${key}"${key === strategy ? " selected" : ""}>${label}</option>`).join("")}
          </select>
          <div class="small fx-note" style="margin-top:4px">保守=只动点名的细节；标准=允许材质/光影细化；重构=允许改服装、发型、场景元素。这是面板的语义预设，不是模型的强度参数。</div>
        </div>
        <div class="fx-block"><b>保留内容</b>
          <div class="fx-row">
            ${PRESERVE_OPTIONS.map(([key, label]) => `<label class="small"><input type="checkbox" data-flux="preserve" value="${key}" checked> ${label}</label>`).join("")}
          </div>
        </div>
      </div>
      <div class="fx-block"><b>参考图（可选，最多 2 张）</b>
        <div class="fx-row">
          <select data-flux="reference"><option value="">— 从最近输出选择 —</option></select>
          <button class="secondary" type="button" data-flux="addref">＋ 添加参考图</button>
          <span class="small" data-flux="reflist"></span>
        </div>
      </div>
      <div class="fx-block"><button class="primary" type="button" data-flux="submit">生成修正版</button>
        <span class="small fx-note" style="margin-left:8px" data-flux="hint"></span></div>`;
    syncMode();
    renderReferences();
    loadReferenceOptions();
  }

  let references = [];

  function renderReferences() {
    if (!dialog) return;
    const list = dialog.querySelector('[data-flux="reflist"]');
    if (list) {
      list.innerHTML = references.length
        ? references.map((name, index) => `${esc(name)} <button class="secondary" type="button" data-flux="delref" data-index="${index}">×</button>`).join(" ")
        : "（不添加参考图时用原图自己作参考）";
    }
    const add = dialog.querySelector('[data-flux="addref"]');
    if (add) add.disabled = references.length >= 2;
  }

  async function loadReferenceOptions() {
    const select = dialog && dialog.querySelector('[data-flux="reference"]');
    if (!select || select.dataset.loaded === "1") return;
    try {
      const data = await (await fetch("/api/output-images")).json();
      const entries = Array.isArray(data.entries) ? data.entries : [];
      select.innerHTML = '<option value="">— 从最近输出选择 —</option>'
        + entries.slice(0, 40).map((item) => `<option value="${esc(item.name)}">${esc(item.name)}</option>`).join("");
      select.dataset.loaded = "1";
    } catch (_) {
      /* 输出列表拿不到就只留“不添加参考图” */
    }
  }

  function syncMode() {
    if (!dialog) return;
    const mode = normalizeMode(dialog.querySelector('[data-flux="mode"]:checked')?.value);
    dialog.dataset.mode = mode;
    const maskRow = dialog.querySelector('[data-flux="maskrow"]');
    if (maskRow) maskRow.hidden = mode !== "regional";
    const hint = dialog.querySelector('[data-flux="hint"]');
    if (hint) {
      hint.textContent = mode === "regional"
        ? "局部修复：后端会把蒙版 ROI 裁出来交给 Klein，修完羽化贴回原图（其余像素不变）。"
        : "整图细化：保持角色与构图，只提升细节。";
    }
  }

  function readEdit() {
    const mode = normalizeMode(dialog.querySelector('[data-flux="mode"]:checked')?.value);
    const preserve = [...dialog.querySelectorAll('[data-flux="preserve"]:checked')].map((item) => item.value);
    return normalizeEdit({
      mode,
      source: (handPrefill && handPrefill.image) || currentImageName(),
      mask: mode === "regional" ? memory.mask : "",
      instruction: dialog.querySelector('[data-flux="instruction"]')?.value || "",
      strategy: dialog.querySelector('[data-flux="strategy"]')?.value || "standard",
      preserve,
      references,
    });
  }

  async function openDialog(prefill) {
    handPrefill = prefill && typeof prefill === "object" ? prefill : null;
    injectStyle();
    loadMemory();
    if (!dialog) {
      dialog = global.document.createElement("dialog");
      dialog.id = "fluxEditDialog";
      dialog.className = "hires-compare flux-edit";
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) dialog.close();
      });
      dialog.addEventListener("click", handleClick);
      dialog.addEventListener("change", (event) => {
        const target = event.target.closest ? event.target.closest("[data-flux]") : null;
        if (!target) return;
        if (target.dataset.flux === "mode") syncMode();
        if (target.dataset.flux === "file") handleMaskFile(target);
      });
      global.document.body.appendChild(dialog);
    }
    references = [];
    render();
    if (!dialog.open) dialog.showModal();
  }

  async function handleMaskFile(input) {
    const file = input && input.files && input.files[0];
    if (!file) return;
    try {
      await uploadMaskBlob(file, file.name, await blobToDataUrl(file));
    } catch (error) {
      setStatus("蒙版上传失败：" + error.message, true);
    } finally {
      if (input) input.value = "";
    }
  }

  function handleClick(event) {
    const target = event.target.closest ? event.target.closest("[data-flux]") : null;
    if (!target) return;
    const action = target.dataset.flux;
    if (action === "close") dialog.close();
    else if (action === "draw") startHandWorkbench();
    else if (action === "reuse") {
      memory.mask = memory.mask || "";
      renderMaskRow();
      setStatus(memory.mask ? "已重新套用最近一次蒙版。" : "还没有用过蒙版。");
    } else if (action === "clearmask") {
      memory = { mask: "", preview: "" };
      saveMemory();
      renderMaskRow();
    } else if (action === "addref") {
      const select = dialog.querySelector('[data-flux="reference"]');
      const name = select && select.value;
      if (name && !references.includes(name) && references.length < 2) {
        references.push(name);
        renderReferences();
      }
    } else if (action === "delref") {
      references.splice(Number(target.dataset.index) || 0, 1);
      renderReferences();
    } else if (action === "submit") {
      submit();
    }
  }

  function startHandWorkbench() {
    if (typeof global.openHandWorkbench !== "function") {
      setStatus("手部工作台未加载；请刷新面板，或直接导入蒙版图片。", true);
      return;
    }
    dialog.close();
    setStatus("在手部工作台里圈出要修的区域，然后点「✨ 发送到 FLUX 修图」。");
    global.openHandWorkbench();
  }

  /** 手部工作台调用：拿到蒙版后回到 FLUX 对话框。 */
  async function useHandMask(payload) {
    const data = payload && typeof payload === "object" ? payload : {};
    if (!data.dataUrl) {
      setStatus("手部工作台里还没有选区；请先圈出要修的区域。", true);
      return false;
    }
    try {
      await uploadMaskBlob(dataUrlToBlob(data.dataUrl), "手部工作台选区", data.dataUrl);
      const prefilled = { image: String(data.image || "") };
      return await openWithMask(prefilled);
    } catch (error) {
      setStatus("蒙版上传失败：" + error.message, true);
      return false;
    }
  }

  async function openWithMask(prefill) {
    await openDialog(prefill);
    const radio = dialog.querySelector('[data-flux="mode"][value="regional"]');
    if (radio) {
      radio.checked = true;
      syncMode();
    }
    renderMaskRow();
    return true;
  }

  async function submit() {
    if (busy) return;
    const edit = readEdit();
    const errors = validateEdit(edit);
    if (errors.length) {
      setStatus(errors[0], true);
      return;
    }
    busy = true;
    const button = dialog.querySelector('[data-flux="submit"]');
    if (button) button.disabled = true;
    try {
      setStatus("正在提交 FLUX 修图任务…（首次运行要加载 Klein 4B + Qwen3-4B，会比较慢）");
      const base = typeof global.payload === "function" ? global.payload() : {};
      const body = buildRequestPayload(edit, base);
      const response = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      const promptId = data.prompt_id;
      if (!promptId) throw new Error("ComfyUI 没有返回任务编号。");
      if (typeof global.registerGenerationPrompt === "function") global.registerGenerationPrompt(promptId, data.plan);
      setStatus("FLUX 修图生成中…（" + describeEdit(edit) + "）");
      const output = await global.poll(promptId);
      if (typeof global.attachSnapshotOutputs === "function") {
        await global.attachSnapshotOutputs(data.snapshot_id, output);
      }
      if (typeof global.renderGeneratedImages === "function") global.renderGeneratedImages(output);
      setStatus("FLUX 修图完成：" + (output[0] && output[0].filename ? output[0].filename : "已生成新版本") + "（作品库里是新的子版本，父版本是原图）");
      dialog.close();
    } catch (error) {
      setStatus("FLUX 修图失败：" + readableError(error && error.message ? error.message : error), true);
    } finally {
      busy = false;
      if (button) button.disabled = false;
    }
  }

  global.easyPanelOpenFluxEdit = (prefill) => openDialog(prefill);
  global.easyPanelFluxUseHandMask = (payload) => useHandMask(payload);
})(typeof window !== "undefined" ? window : globalThis);
