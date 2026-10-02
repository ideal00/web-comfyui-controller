/* Add user reference images, including an output selected from the creative library. */
(function (global) {
  'use strict';
  const LABELS = {clothing:'服装',pose:'姿势',appearance:'外貌',expression:'表情',subject:'人物',scene:'场景',lighting:'光线',composition:'构图',style:'画风',positive:'全部英文正向词'};
  const MAX_IMAGE_BYTES = 20000000;
  function tagsFromText(text) {
    return [...new Set(String(text || '').split(/[,，\n]/).map(tag => tag.trim())
      .filter(tag => tag.length <= 120 && /^[A-Za-z0-9_@][A-Za-z0-9_ .()':@+/-]*$/.test(tag)
        && tag.split(/\s+/).length <= 6))].slice(0, 100).join(', ');
  }
  function promptSources(detail) {
    const snapshot = detail?.snapshot || {}, payload = snapshot.payload || {};
    const sections = payload.promptSections || {};
    const sources = {};
    Object.keys(LABELS).forEach(key => {
      const text = key === 'positive' ? (snapshot.compiled?.positive || payload.prompt || '') : sections[key];
      const tags = tagsFromText(text);
      if (tags) sources[key] = tags;
    });
    return sources;
  }
  const api = {tagsFromText, promptSources, MAX_IMAGE_BYTES};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (!global.document) return;
  const byId = id => global.document.getElementById(id);
  let source = null, previewUrl = '', busy = false, lastFocus = null;
  function notice(text) { byId('vtlAddNotice').textContent = text; }
  function clearPreview() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = '';
    byId('vtlAddPreview').removeAttribute('src');
  }
  function close() {
    if (busy) return;
    byId('vtlAddDialog').close();
  }
  function setSourceArtifact() {
    if (!source) return;
    const artifact = source.artifacts.find(item => item.artifact_id === byId('vtlAddOutput').value);
    const preview = byId('vtlAddPreview');
    if (!artifact?.url) { preview.removeAttribute('src'); return; }
    const url = new URL(artifact.url, global.location.origin);
    if (url.origin !== global.location.origin || url.pathname !== '/api/rpg/image') return;
    url.searchParams.set('preview', '1');
    preview.src = url.pathname + url.search;
  }
  function open(detail, selectedArtifact) {
    if (busy) return;
    build();
    lastFocus = global.document.activeElement;
    source = detail || null;
    byId('vtlAddForm').reset();
    clearPreview();
    notice('');
    const categories = global.EasyPanelVisualTags?.state?.categories || [];
    byId('vtlAddCategories').replaceChildren(...categories.map(name => {
      const item = document.createElement('option'); item.value = name; return item;
    }));
    byId('vtlAddCategory').value = '我的图库';
    byId('vtlAddFileRow').hidden = !!source;
    byId('vtlAddSourceRow').hidden = !source;
    byId('vtlAddFile').required = !source;
    byId('vtlAddPromptRow').hidden = !source;
    if (source) {
      byId('vtlAddName').value = '作品参考 · ' + source.generation_id.slice(0, 10);
      const outputs = source.artifacts.filter(item => item.exists !== false && item.url);
      byId('vtlAddOutput').replaceChildren(...outputs.map(item => {
        const option = document.createElement('option'); option.value = item.artifact_id;
        option.textContent = item.filename; return option;
      }));
      byId('vtlAddOutput').value = outputs.some(item => item.artifact_id === selectedArtifact?.artifact_id)
        ? selectedArtifact.artifact_id : outputs[0]?.artifact_id || '';
      const sources = promptSources(source);
      byId('vtlAddPromptSource').replaceChildren(...Object.keys(sources).map(key => {
        const option = document.createElement('option'); option.value = key; option.textContent = LABELS[key]; return option;
      }));
      const first = Object.keys(sources)[0];
      byId('vtlAddTags').value = sources[first] || '';
      byId('vtlAddPromptSource').disabled = !first;
      setSourceArtifact();
    }
    byId('vtlAddDialog').showModal();
    byId(source ? 'vtlAddTags' : 'vtlAddFile').focus();
  }
  function readImage(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('无法读取图片。'));
      reader.readAsDataURL(file);
    });
  }
  async function save(event) {
    event.preventDefault();
    if (busy) return;
    const payload = {tags:byId('vtlAddTags').value, name_zh:byId('vtlAddName').value,
      category:byId('vtlAddCategory').value, description:byId('vtlAddDescription').value};
    const tags = payload.tags.split(/[,，\n]/).map(tag => tag.trim()).filter(Boolean);
    if (!tags.length || tags.length > 100 || payload.tags.length > 4000
      || tags.some(tag => !/^[A-Za-z0-9_@][A-Za-z0-9_ .()':@+/-]*$/.test(tag))) {
      notice('请填写 1–100 个英文 Tag，中文名称和说明请填写在各自栏位。'); return;
    }
    const file = byId('vtlAddFile').files[0];
    if (!source && (!file || !/^image\/(png|jpeg|webp)$/.test(file.type) || file.size > MAX_IMAGE_BYTES)) {
      notice('请选择不超过 20 MB 的 PNG、JPEG 或 WebP 图片。'); return;
    }
    busy = true;
    byId('vtlAddSave').disabled = true;
    byId('vtlAddCancel').disabled = true;
    byId('vtlAddForm').querySelector('fieldset').disabled = true;
    notice('正在保存到电脑端图库…');
    try {
      if (source) {
        payload.generation_id = source.generation_id;
        payload.artifact_id = byId('vtlAddOutput').value;
      } else payload.image = await readImage(file);
      const response = await fetch('/api/visual-tags/add', {method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || '保存失败，请重试。');
      busy = false;
      close();
      global.document.dispatchEvent(new CustomEvent('easy-panel:visual-tag-added', {detail:result.entry}));
      if (source) {
        const libraryNotice = byId('creativeLibraryNotice');
        if (libraryNotice) libraryNotice.textContent = `已加入可视化图库：${result.entry.name_zh}。`;
      }
    } catch (error) {
      notice(error.message || '保存失败，请重试。');
    } finally {
      busy = false;
      byId('vtlAddSave').disabled = false;
      byId('vtlAddCancel').disabled = false;
      byId('vtlAddForm').querySelector('fieldset').disabled = false;
    }
  }
  function build() {
    if (byId('vtlAddDialog')) return;
    const dialog = document.createElement('dialog');
    dialog.id = 'vtlAddDialog'; dialog.className = 'vtl-add-dialog';
    dialog.innerHTML = `<form id="vtlAddForm">
      <h2>添加到可视化图库</h2><p>图片与对应词条保存在电脑端，手机和电脑都可以继续使用。</p>
      <fieldset>
        <label id="vtlAddFileRow">参考图片<input id="vtlAddFile" type="file" accept="image/png,image/jpeg,image/webp" required></label>
        <label id="vtlAddSourceRow" hidden>作品输出图<select id="vtlAddOutput"></select></label>
        <img id="vtlAddPreview" class="vtl-add-preview" alt="待添加的参考图">
        <label>显示名称<input id="vtlAddName" maxlength="100" placeholder="例如：白色衬衫与马甲"></label>
        <label>图库分类<input id="vtlAddCategory" list="vtlAddCategories" maxlength="60" placeholder="选择已有分类或输入新分类"><datalist id="vtlAddCategories"></datalist></label>
        <label id="vtlAddPromptRow" hidden>从作品词条带入<select id="vtlAddPromptSource"></select></label>
        <label>对应英文 Tag<textarea id="vtlAddTags" rows="4" maxlength="4000" placeholder="white_shirt, vest, pants" required></textarea></label>
        <small>用逗号或换行分隔；请检查并保留这张参考图对应的词条。保存时使用原形，插入提示词时按模型转换。</small>
        <label>说明（可选）<textarea id="vtlAddDescription" rows="2" maxlength="2000" placeholder="记录这张图展示的细节"></textarea></label>
      </fieldset>
      <p id="vtlAddNotice" role="status" aria-live="polite"></p>
      <div class="vtl-add-actions"><button id="vtlAddCancel" type="button" class="secondary">取消</button><button id="vtlAddSave" type="submit" class="primary">保存到图库</button></div>
    </form>`;
    document.body.appendChild(dialog);
    const style = document.createElement('style');
    style.textContent = `.vtl-add-dialog{width:min(580px,calc(100vw - 24px));box-sizing:border-box;max-height:calc(100dvh - 24px);padding:20px;background:#151a27;color:#f5f6fb;border:1px solid #56627d;border-radius:14px;overflow:auto}.vtl-add-dialog::backdrop{background:#050711b8}.vtl-add-dialog [hidden]{display:none!important}.vtl-add-dialog h2{margin:0 0 8px;font-size:20px}.vtl-add-dialog p,.vtl-add-dialog small{font-size:12px;color:#b8c4db;line-height:1.5}.vtl-add-dialog fieldset{display:grid;gap:12px;border:0;padding:0;margin:0;min-width:0}.vtl-add-dialog label{display:grid;gap:6px;font-size:13px}.vtl-add-dialog input,.vtl-add-dialog select,.vtl-add-dialog textarea{box-sizing:border-box;width:100%;min-height:44px}.vtl-add-preview{display:block;max-width:100%;height:140px;object-fit:contain;margin:auto}.vtl-add-preview:not([src]){display:none}.vtl-add-actions{display:flex;justify-content:flex-end;gap:10px}.vtl-add-actions button{width:auto;min-height:44px}#vtlAddNotice{color:#f1cc83;min-height:18px}`;
    document.head.appendChild(style);
    byId('vtlAddCancel').addEventListener('click', close);
    byId('vtlAddForm').addEventListener('submit', save);
    byId('vtlAddOutput').addEventListener('change', setSourceArtifact);
    byId('vtlAddPromptSource').addEventListener('change', () => {
      byId('vtlAddTags').value = promptSources(source)[byId('vtlAddPromptSource').value] || '';
    });
    byId('vtlAddFile').addEventListener('change', () => {
      clearPreview(); notice('');
      const file = byId('vtlAddFile').files[0];
      if (!file) return;
      if (!/^image\/(png|jpeg|webp)$/.test(file.type) || file.size > MAX_IMAGE_BYTES) {
        notice('请选择不超过 20 MB 的 PNG、JPEG 或 WebP 图片。'); return;
      }
      previewUrl = URL.createObjectURL(file); byId('vtlAddPreview').src = previewUrl;
    });
    dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
    dialog.addEventListener('close', () => { clearPreview(); lastFocus?.focus(); });
  }
  global.EasyPanelVisualTagEditor = {...api, open, openFromGeneration:open};
})(typeof window !== 'undefined' ? window : globalThis);
