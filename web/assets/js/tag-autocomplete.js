/* One tag search path for prompt textareas, Chip add, and advanced search. */
(function (global) {
  'use strict';
  const FIELD_KEYS = {
    promptSubject:'subject', promptAppearance:'appearance', promptExpression:'expression',
    promptClothing:'clothing', promptPose:'pose', promptComposition:'composition',
    promptScene:'scene', promptLighting:'lighting', promptStyle:'style',
    prompt:'manual', negative:'negative'
  };
  const MATCH = /(^|[,;\n]\s*)([^,;\n]{1,})$/;
  const cache = new Map();
  const previewCache = new Map();
  let chipPicker = null;
  let advancedSequence = 0;
  let previewSequence = 0;
  let previewTimer = null;

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }
  function normalized(value) { return String(value || '').trim().toLowerCase().replace(/_/g,' ').replace(/\s+/g,' '); }
  function searchable(value) { const term = String(value || '').trim(); return term.length >= 2 || /[\u3400-\u9fff]/.test(term); }
  function fieldForKey(key) { const id = Object.keys(FIELD_KEYS).find(candidate => FIELD_KEYS[candidate] === key); return id ? document.getElementById(id) : null; }
  function currentTerms(field) { return new Set(String(field?.value || '').split(/[,;\n]+/).map(normalized).filter(Boolean)); }
  function formatTag(item) {
    const canonical = String(item?.tag || '').trim().replace(/ /g,'_');
    const colored = global.EasyPanelColorModifier?.compose(canonical) || canonical;
    return global.EasyPanelDialect?.formatTag(colored, {kind:item?.category === '画师' || item?.kind === 'artist' ? 'artist' : undefined}) || colored;
  }
  function queryAtCursor(field) {
    const before = String(field?.value || '').slice(0, field?.selectionStart ?? 0);
    const after = String(field?.value || '').slice(field?.selectionEnd ?? 0);
    const match = before.match(MATCH);
    return match && /^\s*(?:[,;\n]|$)/.test(after) ? match[2].trim() : '';
  }
  function tagAtCursor(field) {
    const text = String(field?.value || ''), at = field?.selectionStart ?? 0;
    const left = Math.max(text.lastIndexOf(',', at - 1), text.lastIndexOf(';', at - 1), text.lastIndexOf('\n', at - 1)) + 1;
    const rightCandidates = [text.indexOf(',', at), text.indexOf(';', at), text.indexOf('\n', at)].filter(index => index >= 0);
    const right = rightCandidates.length ? Math.min(...rightCandidates) : text.length;
    return text.slice(left, right).trim().replace(/^\((.+):[\d.]+\)$/,'$1');
  }
  async function search(query) {
    const term = String(query || '').trim();
    if (!searchable(term)) return [];
    const key = term.toLowerCase();
    if (!cache.has(key)) {
      const read = async (url) => {
        try { const response = await fetch(url); if (!response.ok) return null; return await response.json(); }
        catch (_) { return null; }
      };
      const request = Promise.all([
        read('/api/visual-tags?' + new URLSearchParams({q:term,limit:'200'})),
        read('/api/tags?' + new URLSearchParams({q:term,limit:'120'}))
      ]).then(([visual, dictionary]) => mergeResults(visual?.results || [], dictionary?.tags || [], visual?.matched));
      cache.set(key, request);
      if (cache.size > 80) cache.delete(cache.keys().next().value);
    }
    return cache.get(key);
  }
  function mergeResults(local, dictionary, localMatched) {
    const seen = new Map();
    const featured = [];
    for (const entry of (Array.isArray(local) ? local : [])) {
      if (featured.length >= 60) break;
      if (!entry.tag || seen.has(normalized(entry.tag))) continue;
      const item = {tag:entry.tag,translation:entry.name_zh || '',category:entry.category || '',
        kind:entry.kind,description:entry.description || '',imageId:entry.image_status === 'ready' ? entry.id : '',source:'local',localMatched:Number(localMatched ?? local.length)};
      featured.push(item); seen.set(normalized(item.tag), item);
    }
    const rest = [];
    (Array.isArray(dictionary) ? dictionary : []).forEach(entry => {
      if (!entry.tag) return;
      const key = normalized(entry.tag), featuredItem = seen.get(key);
      if (featuredItem) { featuredItem.count = entry.count; if (!featuredItem.translation) featuredItem.translation = entry.translation || ''; return; }
      if (rest.some(item => normalized(item.tag) === key)) return;
      rest.push({...entry,source:'index'});
    });
    return [...featured, ...rest];
  }
  function resultMarkup(item) {
    const count = Number(item.count || item.post_count || 0).toLocaleString();
    const label = item.translation || item.category || item.kind || '';
    return `<span class="easy-tag-name">${escapeHtml(item.tag)}</span><small class="easy-tag-meta">${item.source === 'local' ? '本地图鉴 · ' : ''}${escapeHtml(label)}${count !== '0' ? ' · ' + count : ''}</small><span class="easy-tag-image" data-autocomplete-image="${escapeHtml(item.tag)}" title="在可视化图库查看" aria-label="查看 ${escapeHtml(item.tag)} 的图片">🖼</span>`;
  }
  function openVisual(item, completion) {
    completion?.hide();
    const tag = typeof item === 'string' ? item : item.tag;
    const source = item?.source === 'local' ? 'local' : 'cloud';
    if (global.EasyPanelVisualTags?.openTag) global.EasyPanelVisualTags.openTag(tag, source);
    else { const input = document.getElementById('tagSearch'); if (input) input.value = tag; global.EasyPanelVisualTags?.open(); }
  }
  function connectImageButtons(completion, field) {
    const listener = event => {
      const all = event.target.closest?.('[data-autocomplete-all]');
      if (all) {
        event.preventDefault(); event.stopPropagation();
        const query = queryAtCursor(field);
        if (query) openVisual({tag:query,source:'local'}, completion);
        return;
      }
      const button = event.target.closest?.('[data-autocomplete-image]');
      if (!button) return;
      event.preventDefault(); event.stopPropagation();
      const entry = completion.dropdown.items.find(item => item.searchResult.data.tag === button.dataset.autocompleteImage);
      if (entry) openVisual(entry.searchResult.data, completion);
    };
    completion.dropdown.el.addEventListener('mousedown', listener, true);
    completion.dropdown.el.addEventListener('touchstart', listener, true);
    completion.dropdown.el.addEventListener('click', listener, true);
  }
  function hidePreview() {
    previewSequence++;
    if (previewTimer !== null) { clearTimeout(previewTimer); previewTimer = null; }
    document.getElementById('easyTagPreview')?.remove();
  }
  async function previewFor(item) {
    if (item.imageId) return {url:'/api/visual-tags/image?' + new URLSearchParams({id:item.imageId,size:'thumb',px:'360'}),source:'本地可视化图库'};
    const key = normalized(item.tag);
    if (!previewCache.has(key)) {
      const request = (async () => {
        try {
          const response = await fetch('/api/visual-tags?' + new URLSearchParams({q:item.tag,limit:'8'}));
          if (response.ok) {
            const data = await response.json();
            const exact = (data.results || []).find(entry => normalized(entry.tag) === key && entry.image_status === 'ready');
            if (exact) {
              item.imageId = exact.id; item.source = 'local';
              return {url:'/api/visual-tags/image?' + new URLSearchParams({id:exact.id,size:'thumb',px:'360'}),source:'本地可视化图库'};
            }
          }
          const cloud = await fetch('/api/danbooru/posts?' + new URLSearchParams({tags:item.tag.replace(/ /g,'_'),limit:'1',rating:'general'}));
          if (cloud.ok) {
            const data = await cloud.json(), post = (data.results || [])[0];
            if (post?.post_id) return {url:'/api/danbooru/image?' + new URLSearchParams({post:String(post.post_id),kind:'preview'}),source:'Danbooru 示例图'};
          }
        } catch (_) { /* A missing image must not interrupt tag entry. */ }
        return null;
      })();
      previewCache.set(key, request);
      if (previewCache.size > 80) previewCache.delete(previewCache.keys().next().value);
    }
    return previewCache.get(key);
  }
  function showPreview(item, completion) {
    const key = normalized(item.tag);
    let box = document.getElementById('easyTagPreview');
    if (box?.dataset.tag === key) return;
    hidePreview();
    box = document.createElement('aside'); box.id = 'easyTagPreview'; box.className = 'easy-tag-preview'; box.dataset.tag = key;
    positionPreview(box, completion);
    const title = document.createElement('strong'); title.textContent = item.tag;
    const info = document.createElement('small'); info.textContent = `${item.translation || ''}${item.category ? ' · ' + item.category : ''}`;
    const body = document.createElement('div'); body.className = 'easy-tag-preview-body'; body.textContent = '正在查找参考图…';
    box.append(title, info, body); document.body.append(box);
    const sequence = previewSequence;
    const load = () => previewFor(item).then(result => {
      if (sequence !== previewSequence || !box.isConnected) return;
      body.replaceChildren();
      if (!result) { body.textContent = '本地图库和云端暂无参考图'; return; }
      const img = document.createElement('img'); img.src = result.url; img.alt = `${item.tag} 参考图`;
      img.onerror = () => { body.textContent = '参考图暂不可用'; };
      const source = document.createElement('small'); source.textContent = result.source;
      body.append(img, source);
      if (item.description) { const note = document.createElement('p'); note.textContent = item.description; box.append(note); }
    });
    if (item.imageId) load(); else previewTimer = setTimeout(load, 150);
  }
  function positionPreview(box, completion) {
    const rect = completion.dropdown.el.getBoundingClientRect(), width = Math.min(300, innerWidth - 16);
    const left = rect.right + width + 8 <= innerWidth ? rect.right + 8 : rect.left - width - 8;
    box.style.left = Math.max(8, Math.min(left, innerWidth - width - 8)) + 'px';
    box.style.top = Math.max(8, Math.min(rect.top, innerHeight - 300)) + 'px';
  }
  function connectPositioning(field, completion, editor) {
    const dropdown = completion.dropdown, viewport = field.closest('.studio-content-viewport');
    function position() {
      if (!dropdown.shown) return;
      const fieldRect = field.getBoundingClientRect();
      const viewRect = viewport?.getBoundingClientRect();
      const visibleTop = Math.max(8, viewRect?.top || 8);
      const visibleBottom = Math.min(innerHeight - 8, viewRect?.bottom || innerHeight - 8);
      if (fieldRect.bottom <= visibleTop || fieldRect.top >= visibleBottom) { completion.hide(); return; }
      const caret = editor.getCursorOffset();
      const caretTop = caret.top - scrollY;
      if (caretTop < visibleTop || caretTop > visibleBottom || caretTop < fieldRect.top || caretTop > fieldRect.bottom + 24) {
        completion.hide(); return;
      }
      const dock = viewport && document.getElementById('studioActionDock')?.getBoundingClientRect();
      const bottom = Math.min(visibleBottom, dock?.top || visibleBottom);
      const availableBelow = bottom - caretTop - 6;
      const availableAbove = caretTop - visibleTop - 6;
      const desiredHeight = Math.min(390, innerHeight * .65, dropdown.el.scrollHeight);
      const above = availableBelow < Math.min(desiredHeight, 180) && availableAbove > availableBelow;
      const room = Math.max(80, above ? availableAbove : availableBelow);
      dropdown.el.style.position = 'fixed';
      dropdown.el.style.right = 'auto'; dropdown.el.style.bottom = 'auto';
      dropdown.el.style.maxHeight = Math.min(desiredHeight, room) + 'px';
      const width = dropdown.el.getBoundingClientRect().width;
      const caretLeft = (caret.left ?? caret.right ?? fieldRect.left) - scrollX;
      dropdown.el.style.left = Math.max(8, Math.min(caretLeft, innerWidth - width - 8)) + 'px';
      dropdown.el.style.top = (above ? Math.max(visibleTop, caretTop - Math.min(desiredHeight, room) - 6) : caretTop + 6) + 'px';
      const preview = document.getElementById('easyTagPreview');
      if (preview) positionPreview(preview, completion);
    }
    dropdown.on('rendered', position);
    window.addEventListener('scroll', event => { if (event.target !== dropdown.el) position(); }, true);
    window.addEventListener('resize', position);
    field.addEventListener('click', position);
    field.addEventListener('keyup', position);
  }
  function activateWithoutScroll(item) {
    if (!item.active) {
      item.dropdown.getActiveItem()?.deactivate();
      item.dropdown.activeItem = item;
      item.active = true;
      item.el.className = item.activeClassName;
    }
    return item;
  }
  function keepActiveVisible(dropdown, item) {
    const viewport = dropdown.el.getBoundingClientRect(), row = item.el.getBoundingClientRect();
    const header = dropdown.el.querySelector('.textcomplete-header')?.getBoundingClientRect().height || 0;
    const footer = dropdown.el.querySelector('.textcomplete-footer')?.getBoundingClientRect().height || 0;
    if (row.top < viewport.top + header) dropdown.el.scrollTop += row.top - viewport.top - header;
    else if (row.bottom > viewport.bottom - footer) dropdown.el.scrollTop += row.bottom - viewport.bottom + footer;
  }
  function connectPreview(completion) {
    completion.dropdown.el.addEventListener('mousemove', event => {
      const row = event.target.closest?.('.textcomplete-item');
      const active = completion.dropdown.items.find(item => item.el === row);
      if (active) { active.activate(); showPreview(active.searchResult.data, completion); }
    });
    completion.dropdown.el.addEventListener('mouseleave', hidePreview);
    completion.dropdown.on('hidden', hidePreview);
    completion.dropdown.on('rendered', () => {
      completion.dropdown.items.forEach(item => {
        item.el.removeEventListener('mouseover', item.onMouseover);
        item.activate = () => activateWithoutScroll(item);
      });
      completion.dropdown.el.scrollTop = 0;
      hidePreview();
    });
  }
  function createCompletion(field, onChipInsert) {
    const Constructor = global.Textcomplete;
    if (!Constructor?.editors?.Textarea) return null;
    const editor = new Constructor.editors.Textarea(field);
    const completion = new Constructor(editor, {
      dropdown:{maxCount:180,className:'textcomplete-dropdown easy-tag-dropdown',
        header(items) {
          const local = items.find(item => item.source === 'local');
          const count = local ? `本地图鉴匹配 ${Number(local.localMatched || 0).toLocaleString()} 条 · ` : '';
          return `${count}已载入 ${items.length} 个候选 · 向下滚动查看更多`;
        },
        footer(items) {
          const local = items.find(item => item.source === 'local');
          return local ? `<button type="button" data-autocomplete-all="local">在本地图鉴查看全部 ${Number(local.localMatched || 0).toLocaleString()} 条匹配</button>` : '';
        }}
    });
    completion.register([{
      id:'easy-panel-tags', match:MATCH, index:2,
      search(term, callback) {
        const query = String(term || '').trim();
        if (field.dataset.composing === '1' || !searchable(query) || !/^\s*(?:[,;\n]|$)/.test(field.value.slice(field.selectionEnd))) { callback([]); return; }
        search(query).then(items => {
          const used = onChipInsert ? currentTerms(fieldForKey(onChipInsert)) : currentTerms(field);
          callback(items.slice(0, 180).map(item => ({...item, existing:used.has(normalized(item.tag))})));
        }, () => callback([]));
      },
      template(item) { return `<span class="easy-tag-result${item.existing ? ' existing' : ''}">${resultMarkup(item)}</span>`; },
      replace(item) {
        const trailing = /^\s*[,;\n]/.test(field.value.slice(field.selectionEnd)) ? '' : ', ';
        return '$1' + formatTag(item).replace(/\$/g,'$$$$') + trailing;
      }
    }]);
    completion.on('select', event => {
      const item = event.detail.searchResult.data;
      if (item.existing) { event.preventDefault(); completion.hide(); return; }
      if (onChipInsert) {
        event.preventDefault();
        global.EasyPanelPromptVariations?.addTag(onChipInsert, formatTag(item));
        closeChipPicker();
      }
    });
    connectImageButtons(completion, field);
    connectPreview(completion);
    connectPositioning(field, completion, editor);
    field.addEventListener('keydown', event => {
      if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && completion.dropdown.shown) {
        const active = completion.dropdown.getActiveItem();
        if (active) { keepActiveVisible(completion.dropdown, active); showPreview(active.searchResult.data, completion); }
      }
      if (event.key === 'Tab' && completion.dropdown.shown) {
        const active = completion.dropdown.getActiveItem() || completion.dropdown.items[0];
        if (active) { event.preventDefault(); completion.dropdown.select(active); }
      }
      if (!onChipInsert && event.ctrlKey && event.shiftKey && event.code === 'Space') { event.preventDefault(); showRelated(field, completion); }
    });
    field.addEventListener('compositionstart', () => { field.dataset.composing = '1'; completion.hide(); });
    field.addEventListener('compositionend', () => { field.dataset.composing = '0'; completion.trigger(field.value.slice(0, field.selectionStart)); });
    return completion;
  }
  function closeChipPicker() {
    if (!chipPicker) return;
    hidePreview();
    chipPicker.completion?.destroy();
    chipPicker.node.remove(); chipPicker = null;
  }
  function openChipPicker(key, anchor) {
    closeChipPicker();
    const node = document.createElement('div'); node.className = 'easy-chip-picker';
    node.innerHTML = '<textarea rows="1" placeholder="输入英文或中文标签…" aria-label="搜索并添加标签"></textarea><button type="button" data-picker="raw" title="添加未收录的英文标签">添加原文</button><button type="button" data-picker="close" aria-label="关闭">×</button>';
    document.body.append(node);
    const rect = anchor.getBoundingClientRect();
    node.style.left = Math.min(rect.left, window.innerWidth - Math.min(340, window.innerWidth - 16) - 8) + 'px';
    node.style.top = Math.min(rect.bottom + 5, window.innerHeight - 90) + 'px';
    const input = node.querySelector('textarea');
    const completion = createCompletion(input, key);
    chipPicker = {node,completion};
    node.querySelector('[data-picker="close"]').onclick = closeChipPicker;
    node.querySelector('[data-picker="raw"]').onclick = () => {
      const value = input.value.trim();
      if (!value || /[\u3400-\u9fff]/.test(value)) return;
      global.EasyPanelPromptVariations?.addTag(key, value); closeChipPicker();
    };
    input.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); closeChipPicker(); } });
    input.focus();
  }
  function collapseAdvancedSearch() {
    const block = document.querySelector('#promptComposer > .prompt-tag-search');
    if (!block || block.parentElement?.classList.contains('easy-advanced-tag-search')) return;
    const details = document.createElement('details'); details.className = 'easy-advanced-tag-search prompt-primary-search';
    const summary = document.createElement('summary'); summary.textContent = '🔍 高级标签搜索（Ctrl+K）';
    block.before(details); details.append(summary, block);
    block.classList.remove('prompt-primary-search');
  }
  async function renderAdvancedSearch() {
    const input = document.getElementById('tagSearch'), root = document.getElementById('tagResults');
    if (!input || !root) return;
    const query = input.value.trim(), sequence = ++advancedSequence;
    if (!query) { root.textContent = '输入英文或中文标签后选择结果。'; return; }
    const items = await search(query);
    if (sequence !== advancedSequence) return;
    root.replaceChildren();
    if (!items.length) { root.textContent = '没有找到匹配标签。'; return; }
    items.forEach(item => {
      const row = document.createElement('div'); row.className = 'easy-advanced-result';
      const insert = document.createElement('button'); insert.type = 'button';
      const name = document.createElement('span'); name.className = 'easy-tag-name'; name.textContent = item.tag;
      const meta = document.createElement('small'); meta.className = 'easy-tag-meta'; meta.textContent = `${item.translation || item.category || ''} · ${Number(item.count || 0).toLocaleString()}`;
      insert.append(name, meta);
      insert.onclick = () => {
        const section = document.getElementById('tagTarget')?.value || 'manual';
        global.appendEnglish?.(formatTag(item), section); input.value = ''; root.textContent = `已加入${global.sectionLabel?.(section) || section}。`;
      };
      const image = document.createElement('button'); image.type = 'button'; image.textContent = '🖼'; image.title = '查看图片与相关标签'; image.onclick = () => openVisual(item);
      row.append(insert,image); root.append(row);
    });
  }
  async function showRelated(field, completion) {
    const tag = tagAtCursor(field); if (!tag) return;
    let box = document.getElementById('easyTagRelated');
    if (!box) { box = document.createElement('div'); box.id = 'easyTagRelated'; box.className = 'easy-tag-related'; document.body.append(box); }
    completion?.hide();
    const rect = field.getBoundingClientRect();
    box.style.left = Math.max(8, Math.min(rect.left, innerWidth - 390)) + 'px';
    box.style.top = Math.min(rect.bottom + 6, innerHeight - 260) + 'px';
    box.hidden = false; box.textContent = `正在查找「${tag}」的相关标签…`;
    const expected = tag;
    try {
      const response = await fetch('/api/danbooru/related?' + new URLSearchParams({tag:tag.replace(/ /g,'_'),limit:'12'}));
      const data = await response.json();
      if (box.hidden || expected !== tagAtCursor(field)) return;
      if (data.error) throw Error(data.error);
      box.replaceChildren();
      const head = document.createElement('div'); head.className = 'easy-related-head'; head.textContent = `「${tag}」的相关标签`;
      const close = document.createElement('button'); close.type = 'button'; close.textContent = '×'; close.onclick = () => { box.hidden = true; field.focus(); }; head.append(close); box.append(head);
      (data.results || []).forEach(item => {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = item.tag.replace(/_/g,' ');
        button.onclick = () => {
          const formatted = formatTag(item);
          const key = FIELD_KEYS[field.id];
          if (key && global.appendEnglish) global.appendEnglish(formatted, key);
          box.hidden = true;
        };
        box.append(button);
      });
      if (!(data.results || []).length) box.append('暂无相关标签。');
    } catch (error) { box.textContent = `相关标签暂不可用：${error.message}`; }
  }
  function init() {
    collapseAdvancedSearch();
    Object.keys(FIELD_KEYS).forEach(id => { const field = document.getElementById(id); if (field) createCompletion(field); });
    global.searchTags = renderAdvancedSearch;
    document.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        const details = document.querySelector('.easy-advanced-tag-search'); if (details) details.open = true;
        document.getElementById('tagSearch')?.focus();
      }
    });
    document.addEventListener('pointerdown', event => {
      if (chipPicker && !chipPicker.node.contains(event.target) && !chipPicker.completion?.dropdown.el.contains(event.target)) closeChipPicker();
      const related = document.getElementById('easyTagRelated');
      if (related && !related.hidden && !related.contains(event.target)) related.hidden = true;
    });
  }
  global.EasyPanelTagAutocomplete = {search, mergeResults, searchable, formatTag, queryAtCursor, tagAtCursor, activateWithoutScroll, keepActiveVisible, openChipPicker, closeChipPicker, init};
  if (typeof module !== 'undefined' && module.exports) module.exports = global.EasyPanelTagAutocomplete;
  if (typeof document === 'undefined') return;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})(typeof window !== 'undefined' ? window : globalThis);
