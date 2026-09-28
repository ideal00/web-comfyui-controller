/* Shared destination and personal tag shortcuts for both search surfaces. */
(function (global) {
  'use strict';
  const RECENT_KEY = 'easyPanelRecentTagsV1';
  const USAGE_KEY = 'easyPanelTagUsageV2';
  const FAVORITE_KEY = 'easyPanelFavoriteTagsV1';
  const SECTION_IDS = {
    promptSubject:'subject', promptAppearance:'appearance', promptExpression:'expression',
    promptClothing:'clothing', promptPose:'pose', promptComposition:'composition',
    promptScene:'scene', promptLighting:'lighting', promptStyle:'style', prompt:'manual',
    promptNaturalLanguage:'naturalLanguage'
  };
  let lastSection = 'appearance';
  const read = key => { try { const value = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(value) ? value.filter(item => typeof item === 'string') : []; } catch (_) { return []; } };
  const save = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {} };
  function readUsage() {
    try {
      const value = JSON.parse(localStorage.getItem(USAGE_KEY) || '[]');
      if (Array.isArray(value)) return value.filter(item => item && typeof item.tag === 'string' && typeof item.section === 'string')
        .map(item => ({tag:item.tag, section:item.section, count:Math.max(1, Number(item.count) || 1), lastUsed:Number(item.lastUsed) || 0}));
    } catch (_) {}
    return [];
  }
  let usage = readUsage();
  if (!usage.length) {
    usage = read(RECENT_KEY).slice(0, 16).map((tag,index) => ({tag, section:'manual', count:1, lastUsed:Date.now() - index}));
    if (usage.length) save(USAGE_KEY, usage);
  }
  let favorites = read(FAVORITE_KEY).slice(0, 32);
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
  function record(tag, section = target()) {
    const value = String(tag || '').trim(); if (!value) return;
    const key = String(section || 'manual');
    const found = usage.find(item => item.tag.toLowerCase() === value.toLowerCase() && item.section === key);
    if (found) { found.tag = value; found.count++; found.lastUsed = Date.now(); }
    else usage.push({tag:value, section:key, count:1, lastUsed:Date.now()});
    usage.sort((a,b) => b.lastUsed - a.lastUsed);
    usage = usage.slice(0, 200);
    save(USAGE_KEY, usage); render();
  }
  function toggleFavorite(tag) {
    const found = favorites.some(item => item.toLowerCase() === tag.toLowerCase());
    favorites = found ? favorites.filter(item => item.toLowerCase() !== tag.toLowerCase()) : [tag, ...favorites].slice(0, 32);
    save(FAVORITE_KEY, favorites); render();
  }
  function render() {
    for (const host of [byId('tagRecent'), byId('vtlFrequent')].filter(Boolean)) {
      host.replaceChildren();
      const current = host.id === 'vtlFrequent' ? resolve(byId('vtlTarget')?.value) : target();
      const ranked = usage.filter(item => item.section === current).sort((a,b) => b.count - a.count || b.lastUsed - a.lastUsed).slice(0, 12);
      const addTitle = value => { const title = document.createElement('span'); title.className = 'small'; title.textContent = value; host.append(title); };
      const addChip = tag => {
      const chip = document.createElement('span'); chip.className = 'tag-recent-chip';
      const insert = document.createElement('button'); insert.type = 'button'; insert.textContent = tag; insert.title = `写入${label(current)}`;
      insert.onclick = () => { const formatted = global.EasyPanelTagAutocomplete?.formatTag({tag}) || global.EasyPanelDialect?.formatTag?.(tag) || tag; if (global.appendEnglish?.(formatted, current)) record(tag, current); };
      const saved = favorites.some(item => item.toLowerCase() === tag.toLowerCase());
      const star = document.createElement('button'); star.type = 'button'; star.textContent = saved ? '★' : '☆';
      star.title = saved ? '取消收藏' : '收藏标签'; star.setAttribute('aria-label', `${star.title} ${tag}`);
      star.onclick = () => toggleFavorite(tag);
      chip.append(insert, star); host.append(chip);
      };
      addTitle(`${label(current)}常用`);
      ranked.forEach(item => addChip(item.tag));
      if (favorites.length) { addTitle('★ 全部收藏'); favorites.slice(0, 20).forEach(addChip); }
    }
  }
  function clearSearch() { const input = byId('tagSearch'); if (!input) return; input.value = ''; global.searchTags?.(); global.EasyPanelQuickActions?.finishClearFocus(input); }
  function init() {
    const select = byId('tagTarget'), input = byId('tagSearch'); if (!select || !input) return;
    if (!select.querySelector('option[value="auto"]')) {
      const option = document.createElement('option'); option.value = 'auto'; select.prepend(option); select.value = 'auto';
    }
    syncAutoLabel();
    document.addEventListener('focusin', event => { const section = sectionFromElement(event.target); if (section && section !== lastSection) { lastSection = section; syncAutoLabel(); render(); } });
    select.addEventListener('change', render);
    byId('vtlTarget')?.addEventListener('change', render);
    const clear = document.createElement('button'); clear.type = 'button'; clear.className = 'tag-search-clear'; clear.textContent = '×'; clear.title = '清空标签搜索'; clear.setAttribute('aria-label', '清空标签搜索'); clear.onclick = clearSearch;
    input.after(clear);
    input.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); clearSearch(); } });
    const host = document.createElement('div'); host.id = 'tagRecent'; host.className = 'tag-recent'; select.closest('.tag-target')?.before(host);
    render();
  }
  global.EasyPanelTagWorkflow = {sectionFromElement, target, resolve, record, recent: () => usage.slice(), favorites: () => favorites.slice(), toggleFavorite, render, init};
  if (typeof module !== 'undefined' && module.exports) module.exports = global.EasyPanelTagWorkflow;
  if (typeof document === 'undefined') return;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})(typeof window !== 'undefined' ? window : globalThis);
