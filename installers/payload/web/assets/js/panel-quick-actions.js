(function (global) {
  'use strict';
  const byId = id => document.getElementById(id);
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
      const mode = document.createElement('select'); mode.className = 'prompt-section-paste-mode'; mode.dataset.field = id;
      mode.title = '粘贴方式'; mode.setAttribute('aria-label', `${id} 粘贴方式`);
      [['append', '追加'], ['replace', '覆盖'], ['dedupe', '去重']].forEach(([value, label]) => {
        const option = document.createElement('option'); option.value = value; option.textContent = label; mode.append(option);
      });
      button.after(mode);
      const clean = document.createElement('button'); clean.type = 'button';
      clean.className = 'prompt-section-clean'; clean.textContent = '清洗格式';
      clean.title = '按当前模型方言整理分隔符和标签写法';
      clean.setAttribute('aria-label', `${id} 清洗为当前模型标签格式`);
      clean.onclick = () => cleanPromptField(id);
      mode.after(clean);
    });
    ['animaHardTags', 'animaSoftPhrases', 'animaNLTags'].forEach(id => {
      const field = byId(id), label = field?.previousElementSibling?.querySelector?.('span');
      if (!label || label.querySelector('.prompt-section-clean')) return;
      const clean = document.createElement('button'); clean.type = 'button';
      clean.className = 'prompt-section-clean'; clean.textContent = '清洗格式';
      clean.title = '按当前模型方言清洗此提示词框';
      clean.onclick = () => cleanPromptField(id);
      label.append(clean);
    });
  }
  global.EasyPanelQuickActions = {seedFromHistory, recordGeneratedSeed, setSeed, restorePreviousSeed, finishClearFocus, readFirstClipboardText, cleanPromptText, cleanPromptField, init};
  if (typeof module !== 'undefined' && module.exports) module.exports = global.EasyPanelQuickActions;
  if (typeof document === 'undefined') return;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})(typeof window !== 'undefined' ? window : globalThis);
