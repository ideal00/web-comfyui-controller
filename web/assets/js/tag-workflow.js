/* Shared destination and personal tag shortcuts for both search surfaces. */
(function (global) {
  'use strict';
  const RECENT_KEY = 'easyPanelRecentTagsV1';
  const FAVORITE_KEY = 'easyPanelFavoriteTagsV1';
  const SECTION_IDS = {
    promptSubject:'subject', promptAppearance:'appearance', promptExpression:'expression',
    promptClothing:'clothing', promptPose:'pose', promptComposition:'composition',
    promptScene:'scene', promptLighting:'lighting', promptStyle:'style', prompt:'manual',
    promptNaturalLanguage:'naturalLanguage'
  };
  let lastSection = 'appearance';
  const read = key => { try { const value = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(value) ? value.filter(item => typeof item === 'string') : []; } catch (_) { return []; } };
  let recent = read(RECENT_KEY).slice(0, 16);
  let favorites = read(FAVORITE_KEY).slice(0, 32);
  const save = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {} };
  const byId = id => document.getElementById(id);
  function sectionFromElement(element) { return SECTION_IDS[element?.id] || element?.closest?.('[data-section-key]')?.dataset.sectionKey || ''; }
  function label(section) { return global.sectionLabel?.(section) || {subject:'人物与角色',appearance:'外貌',expression:'表情',clothing:'服装与材质',pose:'姿势',composition:'构图与镜头',scene:'场景',lighting:'光线',style:'画风与上色',naturalLanguage:'自然语言关系',manual:'其他补充'}[section] || section; }
  function syncAutoLabel() {
    for (const id of ['tagTarget', 'vtlTarget']) {
      const option = byId(id)?.querySelector('option[value="auto"]');
      if (option) option.textContent = `写入：自动（${label(lastSection)}）`;
    }
  }
  function target() { const selected = byId('tagTarget')?.value || 'auto'; return selected === 'auto' ? lastSection : selected; }
  function resolve(value) { return value && value !== 'auto' ? value : target(); }
  function record(tag) {
    const value = String(tag || '').trim(); if (!value) return;
    recent = [value, ...recent.filter(item => item.toLowerCase() !== value.toLowerCase())].slice(0, 16);
    save(RECENT_KEY, recent); render();
  }
  function toggleFavorite(tag) {
    const found = favorites.some(item => item.toLowerCase() === tag.toLowerCase());
    favorites = found ? favorites.filter(item => item.toLowerCase() !== tag.toLowerCase()) : [tag, ...favorites].slice(0, 32);
    save(FAVORITE_KEY, favorites); render();
  }
  function render() {
    const host = byId('tagRecent'); if (!host) return;
    host.replaceChildren();
    const title = document.createElement('span'); title.className = 'small'; title.textContent = '最近使用 / ★ 收藏'; host.append(title);
    const shown = [...favorites, ...recent.filter(item => !favorites.some(saved => saved.toLowerCase() === item.toLowerCase()))].slice(0, 20);
    shown.forEach(tag => {
      const chip = document.createElement('span'); chip.className = 'tag-recent-chip';
      const insert = document.createElement('button'); insert.type = 'button'; insert.textContent = tag; insert.title = `写入${label(target())}`;
      insert.onclick = () => { const formatted = global.EasyPanelTagAutocomplete?.formatTag({tag}) || global.EasyPanelDialect?.formatTag?.(tag) || tag; if (global.appendEnglish?.(formatted, target())) record(tag); };
      const saved = favorites.some(item => item.toLowerCase() === tag.toLowerCase());
      const star = document.createElement('button'); star.type = 'button'; star.textContent = saved ? '★' : '☆';
      star.title = saved ? '取消收藏' : '收藏标签'; star.setAttribute('aria-label', `${star.title} ${tag}`);
      star.onclick = () => toggleFavorite(tag);
      chip.append(insert, star); host.append(chip);
    });
  }
  function clearSearch() { const input = byId('tagSearch'); if (!input) return; input.value = ''; global.searchTags?.(); global.EasyPanelQuickActions?.finishClearFocus(input); }
  function init() {
    const select = byId('tagTarget'), input = byId('tagSearch'); if (!select || !input) return;
    if (!select.querySelector('option[value="auto"]')) {
      const option = document.createElement('option'); option.value = 'auto'; select.prepend(option); select.value = 'auto';
    }
    syncAutoLabel();
    document.addEventListener('focusin', event => { const section = sectionFromElement(event.target); if (section && section !== lastSection) { lastSection = section; syncAutoLabel(); } });
    const clear = document.createElement('button'); clear.type = 'button'; clear.className = 'tag-search-clear'; clear.textContent = '×'; clear.title = '清空标签搜索'; clear.setAttribute('aria-label', '清空标签搜索'); clear.onclick = clearSearch;
    input.after(clear);
    input.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); clearSearch(); } });
    const host = document.createElement('div'); host.id = 'tagRecent'; host.className = 'tag-recent'; select.closest('.tag-target')?.before(host);
    render();
  }
  global.EasyPanelTagWorkflow = {sectionFromElement, target, resolve, record, toggleFavorite, recent: () => recent.slice(), favorites: () => favorites.slice(), render, init};
  if (typeof module !== 'undefined' && module.exports) module.exports = global.EasyPanelTagWorkflow;
  if (typeof document === 'undefined') return;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})(typeof window !== 'undefined' ? window : globalThis);
