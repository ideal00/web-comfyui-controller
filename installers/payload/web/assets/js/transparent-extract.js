/* 上传图片 → 算法抠图提取透明 PNG（RmBgUltra），只做背景移除，不重绘画面。 */
(function (global) {
  'use strict';

  var DIALOG_ID = 'transparentExtractDialog';
  var state = { file: null, previewUrl: '', uploaded: '', result: null, busy: false };

  function $(id) { return document.getElementById(id); }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function message(text) {
    var node = $('transparentExtractStatus');
    if (node) node.textContent = text || '';
  }

  function busy(value) {
    state.busy = value;
    ['transparentExtractRunBtn', 'transparentExtractClearBtn', 'transparentExtractCloseBtn']
      .forEach(function (id) {
        var node = $(id);
        if (node) node.disabled = value;
      });
    var run = $('transparentExtractRunBtn');
    if (run) run.textContent = value ? '正在抠图…' : '提取透明 PNG';
  }

  function setEnabled(id, enabled) {
    var node = $(id);
    if (node) node.disabled = !enabled;
  }

  function showSource(url, label) {
    var image = $('transparentExtractSourcePreview');
    if (image) {
      image.src = url || '';
      image.alt = label || '';
    }
  }

  function showResult(result) {
    state.result = result || null;
    var image = $('transparentExtractResultPreview');
    if (image) image.src = result && result.url ? result.url : '';
    setEnabled('transparentExtractDownloadBtn', Boolean(result));
    setEnabled('transparentExtractManualBtn', Boolean(result));
  }

  function resetAll() {
    state.file = null;
    state.uploaded = '';
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = '';
    var file = $('transparentExtractFile');
    if (file) file.value = '';
    var output = $('transparentExtractOutput');
    if (output) output.value = '';
    showSource('', '');
    showResult(null);
    message('选择一张图片（或最近输出），再点“提取透明 PNG”。');
  }

  async function refreshOutputs() {
    var select = $('transparentExtractOutput');
    if (!select) return;
    try {
      var response = await fetch('/api/output-images');
      var data = await response.json();
      var entries = (data && data.entries) || [];
      var current = select.value;
      select.innerHTML = '<option value="">— 选择已生成图 —</option>' + entries.map(function (entry) {
        return '<option value="' + esc(entry.name) + '">' + esc(entry.name) + '</option>';
      }).join('');
      if (current) select.value = current;
    } catch (error) {
      message('读取最近输出失败：' + error.message);
    }
  }

  function pickFile(file) {
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/i.test(file.type || '')) {
      message('只支持 PNG / JPG / WEBP 图片。');
      return;
    }
    state.file = file;
    state.uploaded = '';
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = URL.createObjectURL(file);
    showSource(state.previewUrl, file.name);
    var output = $('transparentExtractOutput');
    if (output) output.value = '';
    showResult(null);
    message('已选择：' + file.name + '，点“提取透明 PNG”开始算法抠图。');
  }

  function pickOutput(name) {
    if (!name) return;
    state.file = null;
    state.uploaded = '';
    var file = $('transparentExtractFile');
    if (file) file.value = '';
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = '';
    state.sourceOutput = name;
    showSource('/output?name=' + encodeURIComponent(name), name);
    showResult(null);
    message('已选择最近输出：' + name);
  }

  async function uploadSource() {
    if (state.uploaded) return state.uploaded;
    if (!state.file) return '';
    var form = new FormData();
    form.append('image', state.file, state.file.name || 'reference.png');
    var response = await fetch('/api/upload-transparent-source', { method: 'POST', body: form });
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok || data.error) throw new Error(data.error || ('上传失败：' + response.status));
    state.uploaded = data.image || '';
    return state.uploaded;
  }

  async function runExtract() {
    if (state.busy) return;
    var outputName = ($('transparentExtractOutput') || {}).value || '';
    if (!state.file && !outputName) {
      message('请先选择一张本地图片，或从最近输出里选一张。');
      return;
    }
    busy(true);
    try {
      var source = state.file ? await uploadSource() : 'output:' + outputName;
      if (!source) throw new Error('图片上传失败，请重试。');
      var preset = ($('transparentExtractMode') || {}).value || 'detail';
      message(preset === 'hair' ? '正在做发丝增强抠图（边缘细化 + 补断裂发丝，第一次会慢一些）…'
        : preset === 'detail' ? '正在做精细边缘抠图（发丝 / 飘带）…' : '正在做自动抠图…');
      var response = await fetch('/api/transparent-extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image: source,
          preset: preset,
          detailMethod: ($('transparentExtractMethod') || {}).value || 'PyMatting',
          detailErode: Number(($('transparentExtractErode') || {}).value || 6),
          detailDilate: Number(($('transparentExtractDilate') || {}).value || 6),
          maskGrow: Number(($('transparentExtractGrow') || {}).value || 12),
          fixGap: Number(($('transparentExtractFixGap') || {}).value || 16),
          fixThreshold: Number(($('transparentExtractFixThreshold') || {}).value || 0.75),
          blackPoint: Number(($('transparentExtractBlack') || {}).value || 0.01),
          whitePoint: Number(($('transparentExtractWhite') || {}).value || 0.99),
          maxMegapixels: Number(($('transparentExtractMegapixels') || {}).value || 4),
        }),
      });
      var data = await response.json().catch(function () { return {}; });
      if (!response.ok || data.error) throw new Error(data.error || ('抠图失败：' + response.status));
      showResult(data);
      message('已生成透明 PNG：' + data.filename + '（棋盘格区域为透明）');
    } catch (error) {
      message(error.message);
    } finally {
      busy(false);
    }
  }

  function download() {
    if (!state.result || !state.result.url) return;
    var name = String(state.result.filename || 'EasyPanel_Transparent.png');
    var link = document.createElement('a');
    link.href = state.result.url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    message('已开始下载：' + name);
  }

  function continueManual() {
    if (!state.result || typeof global.openTransparentMaskEditor !== 'function') return;
    var transparentSrc = state.result.url;
    var originalSrc = state.previewUrl
      || ('/output?name=' + encodeURIComponent(state.sourceOutput || state.result.filename));
    // transparentResultPairs 是另一个脚本里的顶层 let，只在全局词法环境里可见。
    if (typeof transparentResultPairs !== 'undefined' && Array.isArray(transparentResultPairs)) {
      transparentResultPairs.push({
        name: state.result.filename, transparentSrc: transparentSrc,
        originalSrc: originalSrc, hasOriginal: Boolean(originalSrc),
      });
    }
    closeDialog();
    global.openTransparentMaskEditor();
  }

  function togglePreset() {
    var preset = ($('transparentExtractMode') || {}).value || 'detail';
    var detail = $('transparentExtractDetail');
    if (detail) detail.style.display = preset === 'detail' ? 'block' : 'none';
    var hair = $('transparentExtractHair');
    if (hair) hair.style.display = preset === 'hair' ? 'block' : 'none';
    var method = $('transparentExtractMethod');
    if (method && preset === 'hair' && !method.value) method.value = 'PyMatting';
  }

  function dialog() {
    var found = $(DIALOG_ID);
    if (found) return found;
    var element = document.createElement('dialog');
    element.id = DIALOG_ID;
    element.className = 'transparent-extract-dialog';
    element.innerHTML = ''
      + '<header class="transparent-editor-head"><div>'
      + '<span class="studio-kicker">算法抠图</span><h2>上传图片提取透明 PNG</h2>'
      + '<p>只做背景移除，不重绘画面：原图像素直接保留，发丝与半透明边缘交给 RmBgUltra 处理。</p></div>'
      + '<button class="secondary" type="button" id="transparentExtractCloseBtn">关闭</button></header>'
      + '<div class="transparent-extract-body">'
      + '<div class="two">'
      + '  <div>'
      + '    <div class="field-title"><span>选择本地图片</span><span class="small">PNG / JPG / WEBP</span></div>'
      + '    <input id="transparentExtractFile" type="file" accept="image/png,image/jpeg,image/webp">'
      + '    <div class="field-title"><span>或使用最近输出</span></div>'
      + '    <select id="transparentExtractOutput"><option value="">— 选择已生成图 —</option></select>'
      + '  </div>'
      + '  <div>'
      + '    <div class="field-title"><span>抠图模式</span></div>'
      + '    <select id="transparentExtractMode">'
      + '      <option value="fast">通用自动（快，硬边）</option>'
      + '      <option value="detail" selected>精细边缘（真实 alpha，推荐）</option>'
      + '      <option value="hair">发丝增强（补断裂发丝，最慢）</option></select>'
      + '    <div class="field-title"><span>边缘算法</span><span class="small">发丝偏假就换 PyMatting</span></div>'
      + '    <select id="transparentExtractMethod">'
      + '      <option value="PyMatting">PyMatting（推荐：真实 alpha，首次较慢）</option>'
      + '      <option value="GuidedFilter">GuidedFilter（快，边缘偏柔）</option></select>'
      + '    <div id="transparentExtractDetail" style="display:none">'
      + '      <div class="two">'
      + '        <label>腐蚀<input id="transparentExtractErode" type="number" min="1" max="255" step="1" value="6"></label>'
      + '        <label>膨胀<input id="transparentExtractDilate" type="number" min="1" max="255" step="1" value="6"></label>'
      + '      </div>'
      + '    </div>'
      + '    <div id="transparentExtractHair" style="display:none">'
      + '      <div class="two">'
      + '        <label>边缘扩张<input id="transparentExtractGrow" type="number" min="0" max="256" step="1" value="12"></label>'
      + '        <label>断裂修补<input id="transparentExtractFixGap" type="number" min="0" max="32" step="1" value="16"></label>'
      + '      </div>'
      + '      <label>修补阈值<input id="transparentExtractFixThreshold" type="number" min="0.01" max="0.99" step="0.01" value="0.75"></label>'
      + '      <div class="small">发丝被吃掉：把白点降到 0.92~0.96 或加大断裂修补；背景雾多：把黑点提到 0.05~0.15。</div>'
      + '    </div>'
      + '    <div class="two">'
      + '      <label>黑点<input id="transparentExtractBlack" type="number" min="0.01" max="0.98" step="0.01" value="0.01"></label>'
      + '      <label>白点<input id="transparentExtractWhite" type="number" min="0.02" max="0.99" step="0.01" value="0.99"></label>'
      + '    </div>'
      + '    <label>最大像素（MP，越大越保细节、越吃显存）<input id="transparentExtractMegapixels" type="number" min="1" max="16" step="0.5" value="4"></label>'
      + '  </div>'
      + '</div>'
      + '<div class="transparent-extract-preview">'
      + '  <figure><figcaption>原图</figcaption><img id="transparentExtractSourcePreview" alt=""></figure>'
      + '  <figure><figcaption>透明 PNG</figcaption><img id="transparentExtractResultPreview" class="transparent-result" alt=""></figure>'
      + '</div>'
      + '<div class="actions">'
      + '  <button class="secondary" type="button" id="transparentExtractClearBtn">清空</button>'
      + '  <button class="secondary" type="button" id="transparentExtractManualBtn" disabled>继续手动修正</button>'
      + '  <button class="secondary" type="button" id="transparentExtractDownloadBtn" disabled>下载 PNG</button>'
      + '  <button class="primary" type="button" id="transparentExtractRunBtn">提取透明 PNG</button>'
      + '</div>'
      + '<div id="transparentExtractStatus" class="small" role="status"></div>'
      + '</div>';
    document.body.appendChild(element);
    var fileInput = element.querySelector('#transparentExtractFile');
    fileInput?.addEventListener('change', function (event) {
      pickFile(event.target.files && event.target.files[0]);
    });
    element.querySelector('#transparentExtractOutput')?.addEventListener('change', function (event) {
      pickOutput(event.target.value);
    });
    element.querySelector('#transparentExtractMode')?.addEventListener('change', togglePreset);
    element.querySelector('#transparentExtractRunBtn')?.addEventListener('click', function () {
      void runExtract();
    });
    element.querySelector('#transparentExtractDownloadBtn')?.addEventListener('click', download);
    element.querySelector('#transparentExtractManualBtn')?.addEventListener('click', continueManual);
    element.querySelector('#transparentExtractClearBtn')?.addEventListener('click', resetAll);
    element.querySelector('#transparentExtractCloseBtn')?.addEventListener('click', closeDialog);
    return element;
  }

  function openDialog() {
    var element = dialog();
    if (!element.open) element.showModal();
    togglePreset();
    void refreshOutputs();
    if (!state.file && !state.result) {
      message('选择一张图片（或最近输出），再点“提取透明 PNG”。');
    }
  }

  function closeDialog() {
    var element = $(DIALOG_ID);
    if (element && element.open) element.close();
  }

  function init() {
    var button = $('transparentExtractOpen');
    if (button) button.addEventListener('click', openDialog);
    global.openTransparentExtractDialog = openDialog;
    global.closeTransparentExtractDialog = closeDialog;
    global.__transparentExtract = {
      open: openDialog, close: closeDialog, run: runExtract, reset: resetAll,
      pickFile: pickFile, pickOutput: pickOutput, state: state,
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
