/* Personal preset examples are durable attachments, never prompt text. */
(function (g) {
  'use strict';
  const byId = id => document.getElementById(id);
  const normalize = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value) ? value : '';
  const url = value => value?.source === 'visual' && /^(?:vt[0-9a-f]{12}|vu[0-9a-f]{32})$/.test(value.id || '') ? '/api/visual-tags/image?id=' + encodeURIComponent(value.id) : normalize(value) ? '/api/preset-examples/image?id=' + normalize(value) : '';
  const esc = text => String(text || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let editorImage = '', revision = 0, busy = false;
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const status = text => { const n = byId('userPresetStatus'); if (n) n.textContent = text; };
  const VISIBILITY_KEY = 'easyPanelPresetExampleVisibilityV1';
  let visibility = {all:false,sections:{}};
  try {
    const stored = JSON.parse(g.localStorage?.getItem(VISIBILITY_KEY) || '{}');
    visibility.all = stored.all === true;
    for (const [key,value] of Object.entries(stored.sections || {})) if (typeof value === 'boolean') visibility.sections[key] = value;
  } catch (_) {}
  const sectionViews = new Map();
  const isSectionVisible = key => visibility.sections[key] ?? visibility.all;
  function saveVisibility() { try { g.localStorage?.setItem(VISIBILITY_KEY,JSON.stringify(visibility)); } catch (_) {} }
  function paintVisibility() {
    for (const view of sectionViews.values()) {
      const visible = isSectionVisible(view.section);
      view.body.hidden = !visible;
      view.button.textContent = visible ? '收起例图' : '显示例图';
      view.button.setAttribute('aria-expanded',String(visible));
      view.button.title = (visible ? '收起' : '显示') + view.name + '的例图';
    }
    const all = byId('promptExampleVisibility');
    if (all) {
      const overrides = Object.values(visibility.sections);
      const any = visibility.all || overrides.includes(true);
      all.textContent = '例图：' + (overrides.some(value => value !== visibility.all) ? '部分开启' : visibility.all ? '开启' : '关闭');
      all.setAttribute('aria-pressed',String(any));
      all.title = any ? '收起所有分区例图' : '显示所有分区例图';
    }
  }
  function setAllVisible(value) { visibility = {all:!!value,sections:{}}; saveVisibility(); paintVisibility(); }
  function toggleSection(key) { visibility.sections[key] = !isSectionVisible(key); saveVisibility(); paintVisibility(); }
  function attachVisibilityControl(anchor) {
    if (!anchor || byId('promptExampleVisibility')) return;
    const button = node('button','secondary'); button.id = 'promptExampleVisibility'; button.type = 'button';
    button.onclick = () => setAllVisible(!(visibility.all || Object.values(visibility.sections).includes(true)));
    anchor.append(button); paintVisibility();
  }
  function previewFigure(key,choice) {
    if (!url(choice.exampleImage)) return figure(choice.exampleImage,choice.name);
    const root = node('div','prompt-preset-example');
    const button = node('button','secondary preset-example-toggle'); button.type = 'button';
    const body = node('div','preset-example-body'); body.id = 'promptVariationExampleBody_' + key;
    button.setAttribute('aria-controls',body.id); button.onclick = () => toggleSection(key);
    body.append(figure(choice.exampleImage,choice.name)); root.append(button,body);
    sectionViews.set('preview_' + key,{section:key,button,body,name:choice.name}); paintVisibility();
    return root;
  }

  function markup(image, name) {
    const src = url(image);
    return src ? `<figure class="preset-example"><a href="${src}" target="_blank" rel="noreferrer" title="查看例图"><img src="${src}" loading="lazy" alt="${esc(name)}的预设例图"></a><figcaption>预设例图 · <a href="${src}" download="preset-example.webp">下载例图</a></figcaption></figure>` : '';
  }
  function figure(image, name) {
    const root = node('figure', 'preset-example');
    const src = url(image);
    if (!src) { root.append(node('figcaption', 'small', '未绑定例图')); return root; }
    const link = node('a'); link.href = src; link.target = '_blank'; link.rel = 'noreferrer'; link.title = '查看例图';
    const img = node('img'); img.src = src; img.alt = (name || '预设') + '的例图'; img.loading = 'lazy';
    link.append(img); root.append(link);
    const caption = node('figcaption', '', '预设例图 · '), download = node('a', '', '下载例图');
    download.href = src; download.download = 'preset-example.webp'; caption.append(download); root.append(caption);
    return root;
  }
  function showSection(key, choice) {
    const field = byId({subject:'promptSubject',appearance:'promptAppearance',expression:'promptExpression',clothing:'promptClothing',pose:'promptPose',composition:'promptComposition',scene:'promptScene',lighting:'promptLighting',style:'promptStyle',naturalLanguage:'promptNaturalLanguage',manual:'prompt',negative:'negative'}[key]);
    if (!field) return;
    let host = byId('promptPresetExample_' + key);
    if (!host && !choice) return;
    if (!host) { host = node('div', 'prompt-preset-example'); host.id = 'promptPresetExample_' + key; field.after(host); }
    host.hidden = !choice || !url(choice.exampleImage);
    const signature = choice ? choice.name + ':' + url(choice.exampleImage) : '';
    if (host.dataset.exampleSignature === signature) return;
    host.dataset.exampleSignature = signature;
    host.replaceChildren();
    sectionViews.delete(key);
    if (choice && url(choice.exampleImage)) {
      const button = node('button','secondary preset-example-toggle'); button.id = 'promptPresetExampleToggle_' + key; button.type = 'button';
      const body = node('div','preset-example-body'); body.id = 'promptPresetExampleBody_' + key;
      button.setAttribute('aria-controls',body.id); button.onclick = () => toggleSection(key);
      body.append(figure(choice.exampleImage,choice.name)); host.append(button,body);
      sectionViews.set(key,{section:key,button,body,name:choice.name}); paintVisibility();
    }
  }
  function paintEditor() {
    const preview = byId('userPresetExamplePreview');
    if (preview) { preview.replaceChildren(figure(editorImage, '当前预设')); }
  }
  function controls() {
    ['userPresetExampleFile','userPresetExampleOutput','userPresetExampleRemove','userPresetSave'].forEach(id => { const n = byId(id); if (n) n.disabled = busy; });
  }
  function setEditor(value) {
    revision++; busy = false; editorImage = normalize(value); controls(); paintEditor();
    const file = byId('userPresetExampleFile'); if (file) file.value = '';
  }
  async function upload(file) {
    if (!file || !file.size || file.size > 20 * 1024 * 1024) throw Error('请选择不超过 20 MB 的 PNG、JPG 或 WebP。');
    const body = new FormData(); body.append('image', file, file.name || 'example.png');
    const response = await fetch('/api/preset-examples/upload', {method:'POST',body});
    const result = await response.json();
    if (!response.ok || !normalize(result.exampleImage)) throw Error(result.error || '例图保存失败。');
    return result.exampleImage;
  }
  async function attach(getFile) {
    if (busy) return;
    const token = ++revision; busy = true; controls(); status('正在保存例图…');
    try {
      const id = await upload(await getFile());
      if (token !== revision) return;
      editorImage = id; paintEditor(); status('例图已载入，请点击“保存新预设”或“保存修改”绑定。');
    } catch (error) { if (token === revision) status(error.message); }
    finally { if (token === revision) { busy = false; controls(); } }
  }
  function refreshOutputs() {
    const select = byId('userPresetExampleOutputSelect'); if (!select) return;
    const selected = select.value;
    const images = Array.from(document.querySelectorAll('#result img'));
    select.replaceChildren();
    images.forEach((img, index) => { const option = node('option', '', '当前结果第 ' + (index + 1) + ' 张'); option.value = img.src; select.append(option); });
    if (images.some(img => img.src === selected)) select.value = selected;
    select.hidden = images.length <= 1;
  }
  function init() {
    const anchor = byId('userPresetStatus'); if (!anchor || byId('userPresetExampleEditor')) return;
    const root = node('section', 'preset-example-editor'); root.id = 'userPresetExampleEditor';
    root.append(node('b', '', '预设例图（可选）'), node('p', 'small', '上传或选用当前生成结果；随机抽中时展示这张例图。'));
    const actions = node('div', 'actions');
    const label = node('label', 'preset-example-upload', '上传例图 '), file = node('input');
    file.type = 'file'; file.id = 'userPresetExampleFile'; file.accept = 'image/png,image/jpeg,image/webp';
    file.onchange = () => { const chosen = file.files?.[0]; if (chosen) void attach(() => chosen); }; label.append(file);
    const select = node('select'); select.id = 'userPresetExampleOutputSelect'; select.hidden = true;
    const output = node('button', 'secondary', '使用当前结果'); output.type = 'button'; output.id = 'userPresetExampleOutput';
    output.onclick = () => { refreshOutputs(); void attach(async () => {
      const src = select.value; if (!src) throw Error('当前没有可用的生成结果，请先生成图片或上传例图。');
      const parsed = new URL(src, g.location.href);
      if (parsed.protocol !== 'blob:' && (parsed.origin !== g.location.origin || !['/output','/api/rpg/image'].includes(parsed.pathname))) throw Error('当前图片来源不可用，请下载后上传。');
      const response = await fetch(src); if (!response.ok) throw Error('读取当前生成结果失败。');
      return response.blob();
    }); };
    const remove = node('button', 'secondary', '移除例图'); remove.type = 'button'; remove.id = 'userPresetExampleRemove';
    remove.onclick = () => { setEditor(''); status('已从编辑草稿移除例图，保存预设后生效。'); };
    actions.append(label, select, output, remove);
    const preview = node('div'); preview.id = 'userPresetExamplePreview'; root.append(actions, preview); anchor.before(root);
    paintEditor(); refreshOutputs();
    if (g.MutationObserver && byId('result')) new g.MutationObserver(refreshOutputs).observe(byId('result'), {childList:true,subtree:true,attributes:true,attributeFilter:['src']});
    document.addEventListener('error', event => {
      const img = event.target;
      if (img?.tagName !== 'IMG') return;
      const root = img.closest('.preset-example');
      if (root) root.replaceChildren(node('figcaption', 'small', '例图暂时无法读取，请编辑预设重新绑定。'));
    }, true);
  }
  g.EasyPanelPresetExamples = {normalize, url, markup, figure, previewFigure, showSection, isSectionVisible, setAllVisible, toggleSection, attachVisibilityControl, setEditor, getEditor:() => editorImage, isBusy:() => busy, upload, init};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})(window);
