/* Action-level undo/redo for the current creation panel. */
(function (global) {
  'use strict';
  const PROMPT_IDS = ['promptSubject','promptAppearance','promptExpression','promptClothing','promptPose',
    'promptComposition','promptScene','promptLighting','promptStyle','promptNaturalLanguage','prompt','negative',
    'animaHardTags','animaSoftPhrases','animaNLTags'];
  const CONTROL_IDS = ['size','seed','sampler','scheduler','steps','cfg','illustriousMode','hiresScale',
    'hiresDenoise','hiresPurpose','hiresSteps','hiresCfg','hiresSampler','hiresScheduler','hiresPromptMode',
    'hiresPositive','hiresNegative','hiresCompositionLock'];
  const byId = id => document.getElementById(id);
  let states = [], index = -1, timer = null, restoring = false, inputEvent = false, armed = false;
  function snapshot() {
    const values = {};
    [...PROMPT_IDS, ...CONTROL_IDS].forEach(id => {
      const node = byId(id);
      if (node) values[id] = node.type === 'checkbox' ? !!node.checked : node.value;
    });
    let outfits = [], activeLoraName = '';
    try { const saved = JSON.parse(global.mobilePanelSnapshot?.() || '{}'); outfits = saved.appliedOutfits || []; activeLoraName = saved.activeLoraName || ''; } catch (_) {}
    return {values, loras:global.allLoraState?.() || [], outfits, activeLoraName};
  }
  function updateButtons() {
    const undo = byId('panelUndo'), redo = byId('panelRedo');
    if (undo) undo.disabled = index <= 0;
    if (redo) redo.disabled = index < 0 || index >= states.length - 1;
  }
  function record() {
    if (restoring) return false;
    const next = snapshot();
    if (index >= 0 && JSON.stringify(states[index]) === JSON.stringify(next)) return false;
    states = states.slice(0, index + 1);
    states.push(next);
    if (states.length > 30) states.shift();
    index = states.length - 1;
    updateButtons();
    return true;
  }
  function schedule() {
    if (!armed || restoring || inputEvent) return;
    clearTimeout(timer); timer = setTimeout(record, 90);
  }
  function restore(state) {
    restoring = true; clearTimeout(timer);
    global.EasyPanelPromptVariations?.beginTrustedRestore?.();
    try {
      const root = byId('loras');
      if (root && typeof global.addLora === 'function') {
        root.replaceChildren();
        if (state.loras.length) state.loras.forEach(item => global.addLora(item.name, item.weight, item.enabled));
        else global.addLora();
        global.setAppliedOutfits?.(JSON.parse(JSON.stringify(state.outfits)));
        if (state.activeLoraName) global.selectLoraNote?.(state.activeLoraName);
      }
      Object.entries(state.values).forEach(([id,value]) => {
        const node = byId(id);
        if (!node) return;
        if (node.type === 'checkbox') node.checked = !!value;
        else if (id !== 'size') node.value = value;
      });
      if (state.values.size) {
        const [width,height] = state.values.size.split('x').map(Number);
        if (width && height && global.EasyPanelSizeSelector?.applySize)
          global.EasyPanelSizeSelector.applySize(width,height,{remember:false});
        else if (byId('size')) byId('size').value = state.values.size;
      }
      global.applyIllustriousMode?.();
      global.updateSizeInfo?.();
      global.renderLoraMemo?.();
      global.renderExperimentControls?.();
      global.promptEditorChanged?.();
      states[index] = snapshot();
      updateButtons();
    } finally { global.EasyPanelPromptVariations?.endTrustedRestore?.(); restoring = false; }
  }
  function step(direction) {
    clearTimeout(timer);
    record();
    const next = index + direction;
    if (next < 0 || next >= states.length) return false;
    index = next; restore(states[index]);
    return true;
  }
  function wrap(name) {
    const original = global[name]; if (typeof original !== 'function') return;
    global[name] = function () {
      const result = original.apply(this, arguments);
      schedule();
      return result;
    };
  }
  function init() {
    if (byId('panelUndo') || !byId('promptSectionGrid')) return;
    const host = document.querySelector('.studio-header-actions') || byId('studioActionDock');
    if (!host) return;
    for (const [id,text,title,direction] of [['panelUndo','↶','撤销面板上一步',-1],['panelRedo','↷','重做面板下一步',1]]) {
      const button = document.createElement('button'); button.id = id; button.type = 'button';
      button.className = 'panel-history-button'; button.textContent = text; button.title = title;
      button.setAttribute('aria-label', title); button.onclick = () => step(direction);
      host.insertBefore(button, host.querySelector('.studio-more') || host.firstChild);
    }
    record();
    const arm = () => {
      if (armed) return;
      states = [snapshot()]; index = 0; armed = true; updateButtons();
    };
    document.addEventListener('pointerdown', arm, true);
    document.addEventListener('keydown', arm, true);
    wrap('promptEditorChanged');
    wrap('saveLoraState');
    wrap('updateSizeInfo');
    document.addEventListener('input', () => {
      inputEvent = true;
      queueMicrotask(() => { inputEvent = false; });
    }, true);
    document.addEventListener('change', event => {
      if (event.target?.closest?.('#promptSectionGrid, #loras, #generationSection')) schedule();
    });
    document.addEventListener('click', event => {
      if (event.target?.closest?.('button:not(#panelUndo):not(#panelRedo)')) record();
    }, true);
    document.addEventListener('click', event => {
      if (event.target?.closest?.('#panelUndo, #panelRedo')) return;
      if (event.target?.closest?.('button')) schedule();
    });
  }
  global.EasyPanelHistory = {snapshot, record, step, init};
  if (typeof module !== 'undefined' && module.exports) module.exports = global.EasyPanelHistory;
  if (typeof document === 'undefined') return;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => setTimeout(init, 0));
  else setTimeout(init, 0);
})(typeof window !== 'undefined' ? window : globalThis);
