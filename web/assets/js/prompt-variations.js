/* Textareas remain the prompt source. This layer only previews and edits their contents. */
(function (global) {
  'use strict';
  const SECTIONS = {
    subject: 'promptSubject', appearance: 'promptAppearance', expression: 'promptExpression',
    clothing: 'promptClothing', pose: 'promptPose', composition: 'promptComposition',
    scene: 'promptScene', lighting: 'promptLighting', style: 'promptStyle'
  };
  const LABELS = {subject:'人物与角色',appearance:'外貌',expression:'表情',clothing:'服装与材质',pose:'姿势',composition:'构图与镜头',scene:'场景',lighting:'光线',style:'画风与上色'};
  const LOCK_KEY = 'easyPanelVariationLocksV1';
  const TAG_LOCK_KEY = 'easyPanelVariationTagLocksV1';
  const DEFAULT_LOCKS = {subject:true,appearance:true,clothing:true,style:true};
  let locks = {...DEFAULT_LOCKS};
  try { locks = {...locks, ...JSON.parse(localStorage.getItem(LOCK_KEY) || '{}')}; } catch (_) {}
  let pending = null;
  let history = [];
  let historyIndex = -1;
  let drag = null;
  let tagLocks = {};
  try {
    const saved = JSON.parse(localStorage.getItem(TAG_LOCK_KEY) || '{}') || {};
    Object.entries(saved).forEach(([key, values]) => { if (SECTIONS[key] && Array.isArray(values)) tagLocks[key] = values.filter(value => typeof value === 'string').map(value => value.trim().toLowerCase()); });
  } catch (_) {}
  const selection = {key:null, source:'', indices:new Set()};
  const chineseLabels = new Map();
  const queuedLabels = new Set();
  const attemptedLabels = new Set();
  let translationTimer = null;
  let editingChip = null;

  function translationSource(token) {
    const weighted = /^\((.+):[\d.]+\)$/.exec(token);
    return weighted ? weighted[1].trim() : token;
  }
  function protectedLabel(token) {
    const type = kind(token);
    const source = translationSource(token);
    if (type === 'lora') return 'LoRA 引用';
    if (type === 'embedding') return '嵌入词';
    if (type === 'structure') return '结构标记';
    if (/^score_\d/i.test(source)) return '质量标签';
    if (/^\d+\s*(?:girl|girls|boy|boys|other|others)$/i.test(source)) return '人数标签';
    const explain = global.EasyPanelPromptExplainer;
    return explain?.isProtectedToken(token) ? '结构标签' : '';
  }
  function queueTranslation(source) {
    if (attemptedLabels.has(source)) return;
    queuedLabels.add(source);
    if (translationTimer !== null) return;
    translationTimer = global.setTimeout(async () => {
      translationTimer = null;
      const batch = [...queuedLabels]; queuedLabels.clear();
      batch.forEach(value => attemptedLabels.add(value));
      try {
        const result = await global.EasyPanelPromptExplainer.translateLabels(batch);
        batch.forEach(value => chineseLabels.set(value, String(result[value] || '')));
      } catch (_) {
        batch.forEach(value => chineseLabels.set(value, ''));
      }
      renderAll();
    }, 0);
  }

  // Split only top-level separators. Parenthesized weights and LoRA syntax survive unchanged.
  function tokenize(value) {
    const source = String(value || '');
    const result = [];
    let part = '', depth = 0, angle = 0, square = 0;
    for (const char of source) {
      if (char === '(') depth++;
      else if (char === ')') depth = Math.max(0, depth - 1);
      else if (char === '<') angle++;
      else if (char === '>') angle = Math.max(0, angle - 1);
      else if (char === '[') square++;
      else if (char === ']') square = Math.max(0, square - 1);
      if ((char === ',' || char === ';' || char === '\n') && !depth && !angle && !square) {
        if (part.trim()) result.push(part.trim());
        part = '';
      } else part += char;
    }
    if (part.trim()) result.push(part.trim());
    return result;
  }
  function kind(token) {
    if (/^<(?:lora|lyco|hypernet|loha):/i.test(token)) return 'lora';
    if (/^<[^>]+>$/.test(token)) return 'embedding';
    if (/^(?:BREAK|AND)$/i.test(token)) return 'structure';
    if (/^\(.+:[\d.]+\)$/.test(token)) return 'weight';
    if (/[.!?]$/.test(token) && /\s/.test(token)) return 'phrase';
    return 'tag';
  }
  function serialize(tokens) { return tokens.map(x => x.trim()).filter(Boolean).join(', '); }
  function field(key) { return document.getElementById(SECTIONS[key]); }
  function normalized(token) { return String(token || '').trim().toLowerCase().replace(/\s+/g, ' '); }
  function isTagLocked(key, token) { return (tagLocks[key] || []).includes(normalized(token)); }
  function lockedTerms(key) { return tokenize(field(key).value).filter(token => isTagLocked(key, token)); }
  function persistTagLocks() { try { localStorage.setItem(TAG_LOCK_KEY, JSON.stringify(tagLocks)); } catch (_) {} }
  function toggleTagLock(key, token) {
    const values = new Set(tagLocks[key] || []), value = normalized(token);
    if (values.has(value)) values.delete(value); else values.add(value);
    tagLocks[key] = [...values]; persistTagLocks(); renderChips(key);
  }
  function clearSelection() { selection.key = null; selection.source = ''; selection.indices.clear(); renderSelectionToolbar(); }
  function status(message) { const node = document.getElementById('promptVariationStatus'); if (node) node.textContent = message; }
  function changed() {
    clearSelection();
    if (typeof global.promptEditorChanged === 'function') global.promptEditorChanged();
  }
  function write(key, tokens) { field(key).value = serialize(tokens); changed(); }
  function colorizedToken(value, modifier) {
    const color = global.EasyPanelColorModifier;
    if (!color || modifier === 'keep') return value;
    if (modifier) return color.compose(value, modifier);
    const info = color.analyze(value);
    if (info.modifierIndex < 0) return value;
    const parts = color.splitTag(value);
    parts.tokens.splice(info.modifierIndex, 1);
    return parts.tokens.join(parts.separator);
  }
  function openChipEditor(key, index) {
    const token = tokenize(field(key).value)[index]; if (!token) return;
    const dialog = document.getElementById('promptChipEditor'); if (!dialog) return;
    editingChip = {key,index,original:token};
    const weighted = /^\((.+):([\d.]+)\)$/.exec(token), base = weighted ? weighted[1] : token;
    dialog.querySelector('[data-chip="text"]').value = base;
    dialog.querySelector('[data-chip="zh"]').textContent = protectedLabel(token) || chineseLabels.get(translationSource(token)) || '翻译中…';
    const weightWrap = dialog.querySelector('[data-chip="weight-wrap"]'); weightWrap.hidden = !['tag','weight'].includes(kind(token));
    dialog.querySelector('[data-chip="weighted"]').checked = !!weighted;
    dialog.querySelector('[data-chip="weight"]').value = weighted ? weighted[2] : '1.0';
    const colorWrap = dialog.querySelector('[data-chip="color-wrap"]'), color = global.EasyPanelColorModifier;
    colorWrap.hidden = !color?.isColorTag(base);
    const info = color?.analyze(base), parts = color?.splitTag(base);
    dialog.querySelector('[data-chip="color"]').value = info?.modifierIndex >= 0 ? parts.tokens[info.modifierIndex].toLowerCase() : 'keep';
    dialog.querySelector('[data-chip="section"]').value = key;
    dialog.showModal();
  }
  function saveChipEditor() {
    if (!editingChip) return;
    const dialog = document.getElementById('promptChipEditor'), {key,index,original} = editingChip;
    const tokens = tokenize(field(key).value);
    if (tokens[index] !== original) { status('词条已变化，请重新打开编辑。'); dialog.close(); editingChip = null; return; }
    let next = dialog.querySelector('[data-chip="text"]').value.trim();
    if (!next) { status('词条不能为空；如需删除，请用删除按钮。'); return; }
    if (!dialog.querySelector('[data-chip="color-wrap"]').hidden) next = colorizedToken(next, dialog.querySelector('[data-chip="color"]').value);
    if (!dialog.querySelector('[data-chip="weight-wrap"]').hidden && dialog.querySelector('[data-chip="weighted"]').checked) {
      const weight = Number(dialog.querySelector('[data-chip="weight"]').value);
      if (!Number.isFinite(weight) || weight <= 0 || weight > 3) { status('权重请输入大于 0 且不超过 3 的数字。'); return; }
      next = `(${next}:${weight})`;
    }
    const target = dialog.querySelector('[data-chip="section"]').value;
    if (target === key) {
      tokens[index] = next;
      if (isTagLocked(key, original) && normalized(next) !== normalized(original)) {
        tagLocks[key] = [...new Set([...(tagLocks[key] || []).filter(value => value !== normalized(original)), normalized(next)])]; persistTagLocks();
      }
    }
    else {
      tokens.splice(index, 1);
      field(target).value = serialize([...tokenize(field(target).value), next]);
      if (isTagLocked(key, original)) { tagLocks[key] = (tagLocks[key] || []).filter(value => value !== normalized(original)); tagLocks[target] = [...new Set([...(tagLocks[target] || []), normalized(next)])]; persistTagLocks(); }
    }
    field(key).value = serialize(tokens);
    dialog.close(); editingChip = null; changed(); status(`已更新词条${target === key ? '' : `并移到${LABELS[target]}`}。`);
  }
  function renderChips(key) {
    const input = field(key), host = input?.parentElement.querySelector('.prompt-chip-list');
    if (!input || !host || host.hidden) return;
    host.replaceChildren();
    tokenize(input.value).forEach((token, index) => {
      const chip = document.createElement('span'); chip.className = 'prompt-chip prompt-chip-' + kind(token);
      chip.draggable = true; chip.title = '拖动排序或跨分区移动';
      chip.classList.toggle('selected', selection.key === key && selection.indices.has(index));
      chip.classList.toggle('locked', isTagLocked(key, token));
      const select = document.createElement('input'); select.type = 'checkbox'; select.className = 'prompt-chip-select';
      select.checked = selection.key === key && selection.indices.has(index); select.title = '多选词条';
      select.setAttribute('aria-label', `选择 ${token}`);
      select.onchange = () => {
        if (selection.key !== key) { selection.key = key; selection.source = input.value; selection.indices.clear(); }
        if (select.checked) selection.indices.add(index); else selection.indices.delete(index);
        if (!selection.indices.size) selection.key = null;
        renderAll(); renderSelectionToolbar();
      };
      const label = document.createElement('button'); label.type = 'button';
      const english = document.createElement('span'); english.className = 'prompt-chip-en'; english.textContent = token;
      const chinese = document.createElement('span'); chinese.className = 'prompt-chip-zh';
      const fixed = protectedLabel(token), source = translationSource(token);
      chinese.textContent = fixed || (chineseLabels.has(source) ? (chineseLabels.get(source) || '暂无译文') : '翻译中…');
      if (!fixed && !chineseLabels.has(source)) queueTranslation(source);
      label.append(english, chinese);
      label.title = '查看中文、编辑权重和颜色、移动分区'; label.onclick = () => openChipEditor(key, index);
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×';
      remove.title = '删除词条'; remove.onclick = () => { const tokens = tokenize(input.value); tokens.splice(index, 1); write(key, tokens); };
      const lock = document.createElement('button'); lock.type = 'button'; lock.className = 'prompt-chip-lock';
      lock.textContent = isTagLocked(key, token) ? '🔒' : '🔓'; lock.title = '锁定或解锁这个词条';
      lock.onclick = () => toggleTagLock(key, token);
      const dice = document.createElement('button'); dice.type = 'button'; dice.className = 'prompt-chip-dice'; dice.textContent = '🎲';
      dice.title = '只换这个词条'; dice.onclick = () => randomTagNow(key, index);
      const search = document.createElement('button'); search.type = 'button'; search.className = 'prompt-chip-search'; search.textContent = '⌕';
      search.title = '在可视化词条库中搜索'; search.onclick = () => {
        const library = global.EasyPanelVisualTags;
        if (!library?.open) return;
        const searchInput = document.getElementById('tagSearch');
        if (searchInput) searchInput.value = translationSource(token);
        library.open();
      };
      chip.append(select, label, lock, dice, search, remove);
      chip.ondragstart = event => { drag = {key, index}; event.dataTransfer.setData('text/plain', token); event.dataTransfer.effectAllowed = 'move'; };
      chip.ondragend = () => { drag = null; };
      chip.ondragover = event => { if (drag) event.preventDefault(); };
      chip.ondrop = event => { event.preventDefault(); if (drag) moveChip(drag.key, drag.index, key, index); drag = null; };
      host.append(chip);
    });
    const add = document.createElement('button'); add.type = 'button'; add.className = 'prompt-chip-add'; add.textContent = '＋ 添加标签';
    add.onclick = () => { const value = global.prompt('添加词条（可输入多个，用逗号分隔）', ''); if (value?.trim()) write(key, [...tokenize(input.value), ...tokenize(value)]); };
    host.append(add);
  }
  function moveChip(fromKey, fromIndex, toKey, toIndex) {
    const source = tokenize(field(fromKey).value), [item] = source.splice(fromIndex, 1);
    if (!item) return;
    if (fromKey === toKey) { source.splice(fromIndex < toIndex ? toIndex - 1 : toIndex, 0, item); field(fromKey).value = serialize(source); }
    else { const target = tokenize(field(toKey).value); target.splice(toIndex, 0, item); field(fromKey).value = serialize(source); field(toKey).value = serialize(target); if (isTagLocked(fromKey, item)) { tagLocks[fromKey] = (tagLocks[fromKey] || []).filter(value => value !== normalized(item)); tagLocks[toKey] = [...new Set([...(tagLocks[toKey] || []), normalized(item)])]; persistTagLocks(); } }
    changed();
  }
  function renderAll() {
    if (selection.key && field(selection.key).value !== selection.source) clearSelection();
    Object.keys(SECTIONS).forEach(renderChips);
  }
  function selectedTokens() {
    if (!selection.key) return [];
    const tokens = tokenize(field(selection.key).value);
    return [...selection.indices].sort((a,b) => a - b).map(index => tokens[index]).filter(Boolean);
  }
  function renderSelectionToolbar() {
    const bar = document.getElementById('promptChipSelectionBar');
    if (!bar) return;
    const count = selection.indices.size;
    bar.hidden = !count;
    bar.querySelector('.prompt-chip-selection-count').textContent = `已选择 ${count} 个 · ${LABELS[selection.key] || ''}`;
  }
  function deleteSelected() {
    if (!selection.key || !selection.indices.size) return;
    const key = selection.key, tokens = tokenize(field(key).value).filter((_, index) => !selection.indices.has(index));
    write(key, tokens); status('已删除所选词条。');
  }
  function moveSelected(targetKey) {
    if (!selection.key || !SECTIONS[targetKey] || targetKey === selection.key) return;
    const key = selection.key, selected = selectedTokens(), remaining = tokenize(field(key).value).filter((_, index) => !selection.indices.has(index));
    const target = tokenize(field(targetKey).value);
    field(key).value = serialize(remaining); field(targetKey).value = serialize([...target, ...selected]);
    selected.forEach(token => { if (isTagLocked(key, token)) { tagLocks[key] = (tagLocks[key] || []).filter(value => value !== normalized(token)); tagLocks[targetKey] = [...new Set([...(tagLocks[targetKey] || []), normalized(token)])]; } });
    persistTagLocks(); changed(); status(`已将 ${selected.length} 个词条移到${LABELS[targetKey]}。`);
  }
  async function copySelected() {
    const selected = selectedTokens(); if (!selected.length) return;
    try { await navigator.clipboard.writeText(serialize(selected)); status(`已复制 ${selected.length} 个词条。`); }
    catch (_) { status('无法写入剪贴板，请检查浏览器权限。'); }
  }
  function saveSelectedBundle() {
    const tokens = selectedTokens(), key = selection.key;
    if (!tokens.length) return;
    if (tokens.some(token => kind(token) !== 'tag' || protectedLabel(token) || !/^[\x20-\x7e]+$/.test(token))) {
      status('组件只能保存普通英文标签；请取消选择 LoRA、权重、结构词或自然语言。'); return;
    }
    const name = global.prompt('给这组标签命名', '');
    if (!name?.trim()) return;
    const component = global.EasyPanelPromptComponent;
    if (!component?.save) { status('提示词组件尚未就绪。'); return; }
    const result = component.save({name:name.trim(), category:key === 'style' ? 'artist' : key, tags:tokens});
    status(result.ok ? `已保存组件「${name.trim()}」（${tokens.length} 个标签）。` : (result.error || '组件保存失败。'));
    if (result.ok) clearSelection();
  }
  function pool(key) {
    // A preset or bundle is a complete variation unit; never assemble random individual tags.
    const presets = typeof userPromptPresets !== 'undefined' ? userPromptPresets : [];
    const values = [];
    presets.forEach(item => {
      if (item.category === key || (key === 'style' && item.category === 'artist')) values.push({name:item.name, text:typeof presetInsertText === 'function' ? presetInsertText(item) : item.content});
      else if (item.category === 'combo' && item.sections?.[key]) values.push({name:item.name, text:item.sections[key]});
    });
    const seen = new Set();
    return values.filter(item => { const text = String(item.text || '').trim(), normalized = text.toLowerCase(); if (!text || seen.has(normalized)) return false; seen.add(normalized); return true; });
  }
  function eligibleCandidates(key) {
    const current = field(key).value.trim().toLowerCase();
    const required = lockedTerms(key).map(normalized);
    return pool(key).filter(item => item.text.trim().toLowerCase() !== current && required.every(term => tokenize(item.text).some(candidate => normalized(candidate) === term)));
  }
  function candidate(key) {
    const options = eligibleCandidates(key);
    return options.length ? options[Math.floor(Math.random() * options.length)] : null;
  }
  function randomTagNow(key, index) {
    const terms = tokenize(field(key).value), current = terms[index];
    if (!current) return false;
    if (isTagLocked(key, current)) { status('这个词条已锁定，解锁后才能随机。'); return false; }
    if (kind(current) !== 'tag' || protectedLabel(current)) { status('结构词、LoRA、权重和自然语言不能单独随机。'); return false; }
    const existing = new Set(terms.map(normalized));
    const candidates = [...new Set(pool(key).flatMap(item => tokenize(item.text)).filter(token => kind(token) === 'tag' && !protectedLabel(token) && !existing.has(normalized(token))))];
    if (!candidates.length) { status('这个分区没有其他可用标签；先保存更多个人预设或组件。'); return false; }
    const next = candidates[Math.floor(Math.random() * candidates.length)];
    if (historyIndex < 0 || JSON.stringify(history[historyIndex]) !== JSON.stringify(snapshot())) record();
    terms[index] = next; field(key).value = serialize(terms); record(); changed();
    status(`已将「${current}」换为「${next}」；点击“上一个”可恢复。`);
    return true;
  }
  function stage(keys) {
    const changes = keys.map(key => ({key, before:field(key).value, choice:candidate(key)})).filter(item => item.choice);
    if (!changes.length) { status('这些分区没有可替换的个人预设或组件；先在“我的提示词预设”中保存对应分区内容。'); return; }
    pending = changes;
    const box = document.getElementById('promptVariationPreview'); box.hidden = false;
    const list = box.querySelector('.prompt-variation-list'); list.replaceChildren();
    changes.forEach(item => { const row = document.createElement('div'); row.textContent = `${LABELS[item.key]} · ${item.choice.name}\n${item.before || '（空）'} → ${item.choice.text}`; list.append(row); });
    status(`预览 ${changes.length} 个分区的变化；确认后才会写入。`);
  }
  function snapshot() { return Object.fromEntries(Object.entries(SECTIONS).map(([key,id]) => [key, document.getElementById(id).value])); }
  function record() { history = history.slice(0, historyIndex + 1); history.push(snapshot()); if (history.length > 12) history.shift(); historyIndex = history.length - 1; }
  function randomSectionNow(key) {
    const choice = candidate(key);
    if (!choice) { status(lockedTerms(key).length ? `${LABELS[key]}没有同时保留锁定词条的其他预设或组件。` : `${LABELS[key]}没有其他可用的个人预设或组件；先保存一个不同内容的预设。`); return false; }
    if (historyIndex < 0 || JSON.stringify(history[historyIndex]) !== JSON.stringify(snapshot())) record();
    field(key).value = choice.text;
    record();
    pending = null;
    const preview = document.getElementById('promptVariationPreview');
    if (preview) preview.hidden = true;
    changed();
    status(`已将${LABELS[key]}换成「${choice.name}」；点击“上一个”可恢复。`);
    return true;
  }
  function accept() {
    if (!pending) return;
    if (pending.some(item => field(item.key).value !== item.before)) { pending = null; document.getElementById('promptVariationPreview').hidden = true; status('分区内容已变化，请重新随机预览。'); return; }
    if (pending.some(item => lockedTerms(item.key).some(token => !tokenize(item.choice.text).some(candidate => normalized(candidate) === normalized(token))))) { pending = null; document.getElementById('promptVariationPreview').hidden = true; status('锁定词条已变化，请重新随机预览。'); return; }
    if (historyIndex < 0 || JSON.stringify(history[historyIndex]) !== JSON.stringify(snapshot())) record();
    pending.forEach(item => { field(item.key).value = item.choice.text; });
    record(); pending = null; document.getElementById('promptVariationPreview').hidden = true; changed(); status('已应用变体；可以用上一个恢复。');
  }
  function navigate(step) {
    const next = historyIndex + step; if (next < 0 || next >= history.length) return;
    historyIndex = next; Object.entries(history[next]).forEach(([key,value]) => { field(key).value = value; }); changed(); status(`已回到历史 ${next + 1}/${history.length}。`);
  }
  function randomUnlocked() {
    let keys = Object.keys(SECTIONS).filter(key => !locks[key] && eligibleCandidates(key).length);
    const strength = document.getElementById('promptVariationStrength').value;
    if (strength !== 'bold') {
      for (let index = keys.length - 1; index > 0; index--) { const other = Math.floor(Math.random() * (index + 1)); [keys[index], keys[other]] = [keys[other], keys[index]]; }
      keys = keys.slice(0, strength === 'light' ? 1 : 2 + Math.floor(Math.random() * 2));
    }
    stage(keys);
  }
  function initChipEditor() {
    if (document.getElementById('promptChipEditor')) return;
    const dialog = document.createElement('dialog'); dialog.id = 'promptChipEditor'; dialog.className = 'prompt-chip-editor';
    dialog.innerHTML = '<div class="prompt-chip-editor-head"><strong>编辑词条</strong><button type="button" data-chip="close">关闭</button></div><label>英文原文<input data-chip="text" type="text"></label><div class="prompt-chip-editor-zh">中文：<span data-chip="zh"></span></div><label data-chip="color-wrap">颜色修饰<select data-chip="color"></select></label><div data-chip="weight-wrap" class="prompt-chip-editor-weight"><label><input data-chip="weighted" type="checkbox"> 使用权重</label><input data-chip="weight" type="number" min="0.1" max="3" step="0.05"></div><label>分区<select data-chip="section"></select></label><div class="prompt-chip-editor-actions"><button type="button" data-chip="save">保存</button><button type="button" data-chip="copy">复制</button><button type="button" data-chip="search">搜索相关</button><button type="button" data-chip="delete">删除</button></div>';
    const color = dialog.querySelector('[data-chip="color"]');
    [['keep','保持原样'],['','无修饰'],...(global.EasyPanelColorModifier?.MODIFIERS || []).map(item => [item.key,item.label])].forEach(([value,label]) => { const option = document.createElement('option'); option.value = value; option.textContent = label; color.append(option); });
    const section = dialog.querySelector('[data-chip="section"]');
    Object.entries(LABELS).forEach(([key,label]) => { const option = document.createElement('option'); option.value = key; option.textContent = label; section.append(option); });
    dialog.querySelector('[data-chip="close"]').onclick = () => dialog.close();
    dialog.querySelector('[data-chip="save"]').onclick = saveChipEditor;
    dialog.querySelector('[data-chip="weight"]').oninput = () => { dialog.querySelector('[data-chip="weighted"]').checked = true; };
    dialog.querySelector('[data-chip="delete"]').onclick = () => {
      if (!editingChip) return;
      const {key,index,original} = editingChip, tokens = tokenize(field(key).value);
      if (tokens[index] !== original) { status('词条已变化，请重新打开编辑。'); dialog.close(); return; }
      tokens.splice(index, 1); field(key).value = serialize(tokens); dialog.close(); changed(); status('已删除词条。');
    };
    dialog.querySelector('[data-chip="copy"]').onclick = async () => {
      if (!editingChip) return;
      try { await navigator.clipboard.writeText(editingChip.original); status('已复制词条。'); }
      catch (_) { status('无法写入剪贴板，请检查浏览器权限。'); }
    };
    dialog.querySelector('[data-chip="search"]').onclick = () => {
      const library = global.EasyPanelVisualTags;
      if (!editingChip || !library?.open) return;
      const search = document.getElementById('tagSearch'); if (search) search.value = translationSource(editingChip.original);
      dialog.close(); library.open();
    };
    dialog.onclose = () => { editingChip = null; };
    document.body.append(dialog);
  }
  function init() {
    const grid = document.getElementById('promptSectionGrid'); if (!grid) return;
    initChipEditor();
    const bar = document.createElement('div'); bar.className = 'prompt-variation-bar';
    bar.innerHTML = '<button type="button" class="secondary" data-action="pose">🎲 换一个姿势</button><button type="button" data-action="scene">🎲 换一个画面</button><label>变化程度 <select id="promptVariationStrength"><option value="light">轻微 · 1 个分区</option><option value="normal" selected>标准 · 最多 3 个</option><option value="bold">大胆 · 所有未锁定分区</option></select></label><button type="button" class="secondary" data-action="prev">◀ 上一个</button><button type="button" class="secondary" data-action="next">下一个 ▶</button><span id="promptVariationStatus" class="small" role="status"></span>';
    grid.before(bar);
    const preview = document.createElement('div'); preview.id = 'promptVariationPreview'; preview.className = 'prompt-variation-preview'; preview.hidden = true;
    preview.innerHTML = '<div class="prompt-variation-list"></div><button type="button" data-action="accept">接受变体</button><button type="button" class="secondary" data-action="reroll">再随机</button><button type="button" class="secondary" data-action="cancel">取消</button>';
    bar.after(preview);
    const selectionBar = document.createElement('div'); selectionBar.id = 'promptChipSelectionBar'; selectionBar.className = 'prompt-chip-selection-bar'; selectionBar.hidden = true;
    selectionBar.innerHTML = '<strong class="prompt-chip-selection-count"></strong><button type="button" data-action="delete">删除</button><label>移动到 <select data-action="target"></select></label><button type="button" data-action="move">移动</button><button type="button" data-action="bundle">保存为组件</button><button type="button" data-action="copy">复制</button><button type="button" data-action="clear">取消选择</button>';
    const target = selectionBar.querySelector('[data-action="target"]');
    Object.entries(LABELS).forEach(([key,label]) => { const option = document.createElement('option'); option.value = key; option.textContent = label; target.append(option); });
    preview.after(selectionBar);
    selectionBar.querySelector('[data-action="delete"]').onclick = deleteSelected;
    selectionBar.querySelector('[data-action="move"]').onclick = () => moveSelected(target.value);
    selectionBar.querySelector('[data-action="bundle"]').onclick = saveSelectedBundle;
    selectionBar.querySelector('[data-action="copy"]').onclick = copySelected;
    selectionBar.querySelector('[data-action="clear"]').onclick = () => { clearSelection(); renderAll(); };
    bar.querySelector('[data-action="pose"]').onclick = () => randomSectionNow('pose');
    bar.querySelector('[data-action="scene"]').onclick = randomUnlocked;
    bar.querySelector('[data-action="prev"]').onclick = () => navigate(-1);
    bar.querySelector('[data-action="next"]').onclick = () => navigate(1);
    preview.querySelector('[data-action="accept"]').onclick = accept;
    preview.querySelector('[data-action="reroll"]').onclick = () => stage(pending.map(item => item.key));
    preview.querySelector('[data-action="cancel"]').onclick = () => { pending = null; preview.hidden = true; status('已取消变体预览。'); };
    Object.entries(SECTIONS).forEach(([key,id]) => {
      const input = document.getElementById(id), container = input?.parentElement; if (!input || !container) return;
      const title = container.querySelector('.field-title');
      const controls = document.createElement('span'); controls.className = 'prompt-chip-controls';
      const lock = document.createElement('button'); lock.type = 'button'; lock.title = '锁定后“换一个画面”不会修改此分区';
      const paintLock = () => { lock.textContent = locks[key] ? '🔒 已锁' : '🔓 可变'; lock.setAttribute('aria-pressed', String(!!locks[key])); };
      lock.onclick = () => { locks[key] = !locks[key]; try { localStorage.setItem(LOCK_KEY, JSON.stringify(locks)); } catch (_) {} paintLock(); };
      paintLock();
      const dice = document.createElement('button'); dice.type = 'button'; dice.textContent = '🎲'; dice.title = '立即从本分区的个人预设或组件换一个'; dice.onclick = () => randomSectionNow(key);
      const mode = document.createElement('button'); mode.type = 'button'; mode.textContent = '标签'; mode.setAttribute('aria-pressed', 'false');
      const chips = document.createElement('div'); chips.className = 'prompt-chip-list'; chips.hidden = true;
      mode.onclick = () => { chips.hidden = !chips.hidden; input.hidden = !chips.hidden; mode.textContent = chips.hidden ? '标签' : '源码'; mode.setAttribute('aria-pressed', String(!chips.hidden)); renderChips(key); };
      controls.append(lock, dice, mode); title.append(controls); input.after(chips);
      input.addEventListener('input', () => { if (!chips.hidden) renderChips(key); });
      chips.ondragover = event => { if (drag) event.preventDefault(); };
      chips.ondrop = event => { event.preventDefault(); if (drag) moveChip(drag.key, drag.index, key, tokenize(field(key).value).length); drag = null; };
    });
  }
  global.EasyPanelPromptVariations = {tokenize, serialize, kind, translationSource, protectedLabel, colorizedToken, pool, stage, accept, randomSectionNow, randomTagNow, navigate, randomUnlocked, renderAll, init};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})(window);
