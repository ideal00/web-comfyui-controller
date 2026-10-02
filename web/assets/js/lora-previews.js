/* Managed local reference images for selecting and inspecting LoRAs. */
(function (g) {
  'use strict';
  const byId = id => document.getElementById(id);
  const normalizeName = value => String(value || '').replace(/\\/g, '/').replace(/^\.\//, '');
  const imageId = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value) ? value : '';
  const imageUrl = reference => imageId(reference?.imageId) ? '/api/preset-examples/image?id=' + reference.imageId : '';
  const node = (tag, cls, text) => { const el = document.createElement(tag); if (cls) el.className = cls; if (text) el.textContent = text; return el; };
  let gallerySignature = '', selectedSignature = '';

  function referenceFor(name, notes) {
    const full = normalizeName(name), base = full.split('/').pop();
    const reference = (notes[full] || notes[base] || {}).referenceImage;
    return imageUrl(reference) ? reference : null;
  }
  function candidates(names, notes) {
    return names.map(name => ({name, reference: referenceFor(name, notes)})).filter(item => item.reference);
  }
  function settings(reference) {
    const details = [];
    if (Number.isFinite(reference.weight)) details.push('测试权重 ' + reference.weight);
    if (Number.isInteger(reference.width) && Number.isInteger(reference.height)) details.push(reference.width + '×' + reference.height);
    if (Number.isInteger(reference.steps)) details.push(reference.steps + ' 步');
    return details.join(' · ');
  }
  function openImage(name, reference) {
    const dialog = byId('loraReferenceDialog'), image = byId('loraReferenceImage');
    if (!dialog || !image || !imageUrl(reference)) return;
    byId('loraReferenceTitle').textContent = normalizeName(name).split('/').pop().replace(/\.safetensors$/i, '');
    byId('loraReferenceSettings').textContent = settings(reference);
    image.src = imageUrl(reference); image.alt = byId('loraReferenceTitle').textContent + '的画风参考图';
    if (!dialog.open) dialog.showModal();
  }
  function addReferenceLora(name, reference) {
    const row = Array.from(document.querySelectorAll('#loras .lora-row')).find(item => normalizeName(item.querySelector('.lora-select')?.value) === normalizeName(name));
    const weight = Number.isFinite(reference.weight) ? String(reference.weight) : '0.8';
    if (row) {
      const input = row.querySelector('.lora-strength'); input.value = weight; input.oninput?.();
      if (row.dataset.enabled === 'false') g.toggleLoraEnabled(row);
      g.selectLoraNote(name, row.querySelector('.lora-select'));
    } else g.addLora(name, weight);
    const status = byId('status'); if (status) status.textContent = '已加入画风 LoRA，权重 ' + weight + '；需要的触发词可从下方备忘或同名 TXT 选用。';
  }
  function imageButton(name, reference, cls) {
    const button = node('button', cls); button.type = 'button'; button.title = '查看画风大图';
    button.setAttribute('aria-label', '查看 ' + normalizeName(name).split('/').pop() + ' 的画风大图');
    const image = node('img'); image.src = imageUrl(reference); image.loading = 'lazy'; image.decoding = 'async';
    image.alt = normalizeName(name).split('/').pop() + '的画风参考图';
    button.append(image); button.onclick = () => openImage(name, reference); return button;
  }
  function render(names, notes, selectedName) {
    const root = byId('loraReferenceList'), selected = byId('loraSelectedReference');
    if (!root || !selected) return;
    const items = candidates(names, notes), signature = JSON.stringify(items);
    if (signature !== gallerySignature) {
      gallerySignature = signature; root.replaceChildren();
      for (const item of items) {
        const card = node('article', 'lora-reference-card');
        card.append(imageButton(item.name, item.reference, 'lora-reference-thumb'));
        const title = node('b', '', normalizeName(item.name).split('/').pop().replace(/\.safetensors$/i, '')); title.title = title.textContent;
        const add = node('button', 'secondary', '加入 LoRA'); add.type = 'button'; add.onclick = () => addReferenceLora(item.name, item.reference);
        card.append(title, node('small', '', settings(item.reference)), add); root.append(card);
      }
      if (!items.length) root.append(node('p', 'small', '当前模型族或筛选条件下没有已绑定的参考图。'));
    }
    const count = byId('loraReferenceCount'), countText = String(items.length);
    if (count && count.textContent !== countText) count.textContent = countText;
    const reference = referenceFor(selectedName, notes), selectedKey = selectedName + ':' + JSON.stringify(reference);
    if (selectedKey !== selectedSignature) {
      selectedSignature = selectedKey; selected.replaceChildren(); selected.hidden = !reference;
      if (reference) selected.append(imageButton(selectedName, reference, 'lora-selected-reference-image'), node('small', '', settings(reference) + ' · 点击放大'));
    }
  }
  const close = byId('loraReferenceClose'), dialog = byId('loraReferenceDialog');
  if (close && dialog) close.onclick = () => dialog.close();
  if (dialog) dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  g.EasyPanelLoraPreviews = {render, referenceFor, candidates, imageUrl, settings, addReferenceLora, openImage};
})(window);
