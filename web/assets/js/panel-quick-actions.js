(function (global) {
  'use strict';
  const byId = id => document.getElementById(id);
  const PASTE_MODE_KEY = 'easyPanelPasteModeV1';
  const pasteModes = ['append', 'replace', 'dedupe'];
  function pasteMode() { try { const value = localStorage.getItem(PASTE_MODE_KEY); return pasteModes.includes(value) ? value : 'append'; } catch (_) { return 'append'; } }
  function setPasteMode(value) { if (!pasteModes.includes(value)) return; try { localStorage.setItem(PASTE_MODE_KEY, value); } catch (_) {} }
  let lastGeneratedSeed = '';
  let previousSeed = '';
  try { lastGeneratedSeed = sessionStorage.getItem('easyPanelLastGeneratedSeedV1') || ''; } catch (_) {}

  function finishClearFocus(field) {
    if (!field) return;
    if (Number(global.navigator?.maxTouchPoints || 0) > 0 || global.matchMedia?.('(pointer: coarse)')?.matches) field.blur();
    else field.focus();
  }

  async function readFirstClipboardText() {
    const bridge = global.EasyPanelClipboard;
    if (typeof bridge?.readText === 'function') {
      const value = bridge.readText();
      if (typeof value === 'string') return value;
    }
    const clipboard = global.navigator?.clipboard;
    if (typeof clipboard?.read === 'function') {
      try {
        const items = await clipboard.read();
        const first = items?.[0];
        if (first?.types?.includes('text/plain')) return await (await first.getType('text/plain')).text();
      } catch (_) { /* Browser permission may allow readText but not read. */ }
    }
    if (typeof clipboard?.readText === 'function') return clipboard.readText();
    throw new Error('clipboard-unavailable');
  }

  function cleanPromptText(value, fieldId) {
    let text = String(value || '').trim();
    if (!['promptNaturalLanguage', 'animaNLTags'].includes(fieldId)) {
      text = text.replace(/[\r\n，、；;]+/g, ',').replace(/\s*,\s*/g, ', ')
        .replace(/(?:,\s*){2,}/g, ', ').replace(/^,\s*|,\s*$/g, '');
    }
    return global.EasyPanelDialect?.formatText?.(text) ?? text;
  }

  function cleanPromptField(fieldId) {
    const field = byId(fieldId);
    if (!field) return false;
    const hint = byId('tokenHint');
    if (global.EasyPanelPromptVariations?.isFieldLocked(fieldId)) {
      if (hint) hint.textContent = '该分区已锁定，请先解锁。';
      return false;
    }
    const cleaned = cleanPromptText(field.value, fieldId);
    if (cleaned === field.value) {
      if (hint) hint.textContent = '当前内容已符合模型标签格式。';
      return false;
    }
    field.value = cleaned;
    global.promptEditorChanged?.();
    if (hint) hint.textContent = `已清洗为${global.EasyPanelDialect?.describe?.() || '当前模型'}格式。`;
    return true;
  }
  function cleanBeforeGenerate() {
    let changed = false;
    global.EasyPanelPromptVariations?.beginTrustedRestore?.();
    try {
      for (const id of ['promptSubject','promptAppearance','promptExpression','promptClothing','promptPose',
        'promptComposition','promptScene','promptLighting','promptStyle','prompt','negative','animaHardTags','animaSoftPhrases']) {
        const field = byId(id); if (!field) continue;
        const next = cleanPromptText(field.value, id);
        if (next !== field.value) { if (!changed) global.EasyPanelHistory?.record(); field.value = next; changed = true; }
      }
      if (changed) global.promptEditorChanged?.();
    } finally { global.EasyPanelPromptVariations?.endTrustedRestore?.(); }
    return changed;
  }
  const SECTION_FIELDS = {subject:'promptSubject',appearance:'promptAppearance',expression:'promptExpression',
    clothing:'promptClothing',pose:'promptPose',composition:'promptComposition',scene:'promptScene',
    lighting:'promptLighting',style:'promptStyle',manual:'prompt'};
  function terms(value) { return String(value || '').split(/[,;\n]+/).map(item => item.trim()).filter(Boolean); }
  async function organizePromptField(id) {
    const source = byId(id), hint = byId('tokenHint');
    if (!source || !Object.values(SECTION_FIELDS).includes(id) || !source.value.trim()) return;
    const before = source.value, input = terms(before);
    try {
      const response = await fetch('/api/classify-tags', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({tags:input})});
      const data = await response.json();
      if (!response.ok || data.error || !Array.isArray(data.results)) throw Error(data.error || '分类失败');
      if (source.value !== before) { if (hint) hint.textContent = '内容已变化，请重新整理。'; return; }
      const affected = Object.values(SECTION_FIELDS);
      const baseline = Object.fromEntries(affected.map(fieldId => [fieldId, byId(fieldId)?.value || '']));
      const planned = Object.fromEntries(affected.map(fieldId => [fieldId, fieldId === id ? [] : terms(baseline[fieldId])]));
      const groups = new Map();
      data.results.forEach((item,index) => {
        const tag = input[index]; if (!tag) return;
        let destination = SECTION_FIELDS[item.section] || SECTION_FIELDS.manual;
        const key = tag.toLowerCase().replace(/_/g,' ').replace(/\s+/g,' ');
        if (!planned[destination].some(existing => existing.toLowerCase().replace(/_/g,' ').replace(/\s+/g,' ') === key)) planned[destination].push(tag);
        if (!groups.has(destination)) groups.set(destination, []);
        groups.get(destination).push(tag);
      });
      const changes = affected.filter(fieldId => planned[fieldId].join(', ') !== terms(baseline[fieldId]).join(', '));
      if (!changes.length) { if (hint) hint.textContent = '这些标签已在合适的分区。'; return; }
      const dialog = document.createElement('dialog'); dialog.className = 'prompt-organize-preview';
      const heading = document.createElement('h3'); heading.textContent = '整理到分区 · 预览'; dialog.append(heading);
      groups.forEach((values,fieldId) => { const row = document.createElement('p'); row.textContent = `${global.sectionLabel?.(Object.keys(SECTION_FIELDS).find(key => SECTION_FIELDS[key] === fieldId)) || fieldId}：${values.join(', ')}`; dialog.append(row); });
      const actions = document.createElement('div'); actions.className = 'actions';
      const confirm = document.createElement('button'); confirm.type = 'button'; confirm.textContent = '确认整理';
      const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'secondary'; cancel.textContent = '取消';
      confirm.onclick = () => {
        if (affected.some(fieldId => (byId(fieldId)?.value || '') !== baseline[fieldId])) { if (hint) hint.textContent = '分区内容已变化，请重新整理。'; dialog.close(); return; }
        global.EasyPanelHistory?.record();
        global.EasyPanelPromptVariations?.beginTrustedRestore?.();
        try {
          changes.forEach(fieldId => { byId(fieldId).value = planned[fieldId].join(', '); });
          global.promptEditorChanged?.();
        } finally { global.EasyPanelPromptVariations?.endTrustedRestore?.(); }
        dialog.close();
        if (hint) hint.textContent = `已整理 ${input.length} 个标签；未识别的保留在其他补充。`;
      };
      cancel.onclick = () => dialog.close(); dialog.onclose = () => dialog.remove();
      actions.append(confirm,cancel); dialog.append(actions); document.body.append(dialog); dialog.showModal();
    } catch (error) { if (hint) hint.textContent = `整理失败：${error.message}`; }
  }

  function seedFromHistory(entry) {
    const workflow = Array.isArray(entry?.prompt) ? entry.prompt[2] : entry?.prompt;
    if (!workflow || typeof workflow !== 'object') return '';
    const sampler = Object.values(workflow).find(node =>
      /^(?:KSampler|KSamplerAdvanced|SamplerCustom|SamplerCustomAdvanced)$/.test(node?.class_type || '') &&
      Number.isSafeInteger(Number(node?.inputs?.seed)) && Number(node.inputs.seed) >= 0);
    return sampler ? String(sampler.inputs.seed) : '';
  }
  function recordGeneratedSeed(entry) {
    const value = typeof entry === 'string' && /^\d+$/.test(entry) ? entry : seedFromHistory(entry);
    if (!value) return '';
    lastGeneratedSeed = value;
    try { sessionStorage.setItem('easyPanelLastGeneratedSeedV1', value); } catch (_) {}
    const pin = byId('seedPinRecent'); if (pin) pin.disabled = false;
    return value;
  }
  function setSeed(value) {
    const input = byId('seed'); if (!input || String(input.value) === String(value)) return false;
    previousSeed = String(input.value);
    input.value = String(value);
    global.promptEditorChanged?.();
    const undo = byId('seedPrevious'); if (undo) undo.disabled = false;
    return true;
  }
  function restorePreviousSeed() {
    if (!previousSeed) return false;
    const value = previousSeed;
    return setSeed(value);
  }
  function init() {
    const input = byId('seed'); if (!input || byId('seedQuickActions')) return;
    const row = document.createElement('div'); row.id = 'seedQuickActions'; row.className = 'seed-quick-actions';
    input.before(row); row.append(input);
    for (const [id, text, title, action] of [
      ['seedRandom', '🎲', '使用随机 Seed（-1）', () => setSeed('-1')],
      ['seedPinRecent', '📌', '填入最近一次实际生成的 Seed', () => setSeed(lastGeneratedSeed)],
      ['seedPrevious', '↩', '恢复上一个输入的 Seed', restorePreviousSeed]
    ]) {
      const button = document.createElement('button'); button.id = id; button.type = 'button'; button.className = 'secondary';
      button.textContent = text; button.title = title; button.setAttribute('aria-label', title); button.onclick = action;
      if (id === 'seedPinRecent') button.disabled = !lastGeneratedSeed;
      if (id === 'seedPrevious') button.disabled = true;
      row.append(button);
    }
    document.querySelectorAll('.prompt-section-paste').forEach(button => {
      const id = /pastePromptSection\('([^']+)'/.exec(button.getAttribute('onclick') || '')?.[1];
      if (!id || !byId(id)) return;
      const menu = document.createElement('details'); menu.className = 'prompt-section-more';
      const summary = document.createElement('summary'); summary.textContent = '⋯'; summary.title = '更多分区操作';
      const actions = document.createElement('div'); actions.className = 'prompt-section-more-actions';
      if (id !== 'promptNaturalLanguage') {
        const clean = document.createElement('button'); clean.type = 'button'; clean.className = 'prompt-section-clean';
        clean.textContent = '清洗格式'; clean.onclick = () => { cleanPromptField(id); menu.open = false; };
        actions.append(clean);
      }
      if (Object.values(SECTION_FIELDS).includes(id)) {
        const organize = document.createElement('button'); organize.type = 'button'; organize.textContent = '整理到分区';
        organize.onclick = () => { menu.open = false; organizePromptField(id); }; actions.append(organize);
      }
      const modeLabel = document.createElement('span'); modeLabel.className = 'small'; modeLabel.textContent = '粘贴方式'; actions.append(modeLabel);
      [['append', '追加'], ['replace', '覆盖'], ['dedupe', '去重']].forEach(([value, label]) => {
        const option = document.createElement('button'); option.type = 'button'; option.textContent = (pasteMode() === value ? '✓ ' : '') + label;
        option.dataset.pasteMode = value; option.onclick = () => {
          setPasteMode(value);
          document.querySelectorAll('.prompt-section-more [data-paste-mode]').forEach(button => {
            button.textContent = (button.dataset.pasteMode === value ? '✓ ' : '') + ({append:'追加',replace:'覆盖',dedupe:'去重'}[button.dataset.pasteMode] || '');
          });
          menu.open = false;
        };
        actions.append(option);
      });
      menu.append(summary, actions); button.after(menu);
      button.addEventListener('contextmenu', event => { event.preventDefault(); menu.open = true; });
      let hold;
      button.addEventListener('pointerdown', event => { if (event.pointerType === 'touch') hold = setTimeout(() => { button.dataset.longPress = '1'; menu.open = true; }, 500); });
      ['pointerup','pointercancel','pointerleave'].forEach(name => button.addEventListener(name, () => clearTimeout(hold)));
      button.addEventListener('click', event => { if (button.dataset.longPress) { event.preventDefault(); event.stopImmediatePropagation(); delete button.dataset.longPress; } }, true);
    });
    const closeMoreOnOutside = event => {
      document.querySelectorAll('.prompt-section-more[open]').forEach(menu => {
        if (!menu.contains(event.target)) menu.open = false;
      });
    };
    document.addEventListener('pointerdown', closeMoreOnOutside);
    document.addEventListener('click', closeMoreOnOutside);
  }
  global.EasyPanelQuickActions = {seedFromHistory, recordGeneratedSeed, setSeed, restorePreviousSeed, finishClearFocus, readFirstClipboardText, cleanPromptText, cleanPromptField, cleanBeforeGenerate, organizePromptField, pasteMode, setPasteMode, init};
  if (typeof module !== 'undefined' && module.exports) module.exports = global.EasyPanelQuickActions;
  if (typeof document === 'undefined') return;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})(typeof window !== 'undefined' ? window : globalThis);
