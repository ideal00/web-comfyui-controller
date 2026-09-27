const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/assets/js/panel.js'), 'utf8');
function line(name) {
  const found = source.split('\n').find((item) => item.startsWith(`function ${name}(`));
  assert.ok(found, `missing ${name}`);
  return found;
}
function block(start, end) {
  const from = source.indexOf(`function ${start}(`);
  const to = source.indexOf(`function ${end}(`, from);
  assert.ok(from >= 0 && to > from);
  return source.slice(from, to);
}
function storage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
}

function desktopContext() {
  const fields = Object.fromEntries([
    'promptClothing', 'negative', 'safetyLevel', 'promptMode', 'status',
  ].map((id) => [id, { id, value: '', textContent: '', focus() { this.focusCount = (this.focusCount ?? 0) + 1; } }]));
  const context = vm.createContext({
    fields, sessionStorage: storage(), PROMPT_SECTION_IDS: { clothing: 'promptClothing' },
    OUTFIT_SECTIONS: [{ key: 'clothing', label: '服装' }],
    $: (id) => fields[id],
    collectPromptSections: () => ({ clothing: fields.promptClothing.value }),
    setFinalPromptText: () => {}, setFinalPromptMode: () => {}, syncMaturePrompt: () => {},
    applyPromptPreset: () => {}, renderLoraMemo: () => {},
    noteKey: (name) => name,
    outfitMainClass: () => 'clothing', outfitMainClassLabel: () => '服装',
    outfitSignature: (item) => item.clothing,
    outfitSectionSummary: (item) => item.clothing ? '服装' : '',
    activeOutfitSectionCount: () => 1,
    insertOutfitSections: (item) => {
      fields.promptClothing.value = item.clothing;
      return { active: { clothing: true }, added: { clothing: [item.clothing] }, removed: {} };
    },
    removeOutfitSections: (item) => {
      fields.promptClothing.value = fields.promptClothing.value.replace(item.clothing, '').trim();
    },
  });
  vm.runInContext(`let appliedOutfits=[];let currentPromptFamily='anima';let currentLoraName='character.safetensors';let finalPromptEdited=false;let modelCatalogLoaded=true;let memoOutfitOverwriteMode=false;let mobilePanelReady=false,mobilePanelRestoring=false;
    function promptEditorChanged(){savePromptFamilyState()}
    ${line('setAppliedOutfits')}
    ${line('collectPromptState')}
    ${line('savePromptFamilyState')}
    ${block('restorePromptFamilyState', 'selectedTriggerListClient')}
    ${line('applyMemoOutfit')}
    ${line('removeAppliedOutfitsForLora')}`, context);
  return { context, fields };
}

test('desktop refresh restores memo provenance, so clicking the memo again removes its terms', () => {
  const { context, fields } = desktopContext();
  const item = { name: 'swimsuit', clothing: 'white bikini' };
  context.item = item;
  vm.runInContext('applyMemoOutfit(item)', context);
  assert.equal(fields.promptClothing.value, 'white bikini');
  vm.runInContext("appliedOutfits=[];$('promptClothing').value='';restorePromptFamilyState('anima')", context);
  assert.equal(fields.promptClothing.value, 'white bikini');
  assert.equal(vm.runInContext('appliedOutfits.length', context), 1);
  vm.runInContext('applyMemoOutfit(item)', context);
  assert.equal(fields.promptClothing.value, '');
  assert.equal(vm.runInContext('appliedOutfits.length', context), 0);
});

test('desktop refresh keeps the LoRA removal linked to its memo terms', () => {
  const { context, fields } = desktopContext();
  context.item = { name: 'swimsuit', clothing: 'white bikini' };
  vm.runInContext("applyMemoOutfit(item);appliedOutfits=[];$('promptClothing').value='';restorePromptFamilyState('anima')", context);
  assert.equal(vm.runInContext("removeAppliedOutfitsForLora('character.safetensors')", context), 1);
  assert.equal(fields.promptClothing.value, '');
});

test('initial load keeps saved LoRAs and memo records until model and prompt restoration finishes', () => {
  const loadLine = source.split('\n').find((item) => item.startsWith('async function load('));
  assert.ok(loadLine);
  assert.ok(loadLine.indexOf('sessionStorage.getItem(MODEL_STATE_STORAGE)') < loadLine.indexOf('restoreLoraState()'));
  assert.ok(loadLine.indexOf('restoreLoraState()') < loadLine.indexOf('modelChanged();reconcileAppliedOutfitsAfterRestore()'));
  assert.ok(line('refreshLoraSelects').includes('initialLoraRestorePending||loraFamilyVisible'));
  const selected = [];
  const sessionStorage = storage();
  sessionStorage.setItem('easyPanelLorasV1', JSON.stringify([{ name: 'anima-character.safetensors', weight: '0.7' }]));
  const context = vm.createContext({
    sessionStorage, LORA_STATE_STORAGE: 'easyPanelLorasV1',
    catalog: { loras: ['anima-character.safetensors'], loraMeta: { 'anima-character.safetensors': { family: 'anima' } } },
    $: () => ({ set innerHTML(_value) {} }),
    addLora: (name) => selected.push(name), saveLoraState: () => {},
  });
  vm.runInContext(`let appliedOutfits=[{key:'anima-character.safetensors'}];${line('restoreLoraState')}`, context);
  vm.runInContext('restoreLoraState()', context);
  assert.deepEqual(selected, ['anima-character.safetensors']);
  assert.equal(vm.runInContext('appliedOutfits.length', context), 1);
});

test('Android WebView snapshot restores LoRA state and memo provenance together', () => {
  const localStorage = storage();
  let rows = [{ name: 'character.safetensors', weight: '0.7', enabled: true }];
  const loras = {
    get children() { return rows; },
    set innerHTML(value) { if (value === '') rows = []; },
  };
  const model = { options: [{ value: 'anima.safetensors' }] };
  const fields = { model, loras };
  const context = vm.createContext({
    localStorage, sessionStorage: storage(), location: { search: '?mobile=1' },
    $: (id) => fields[id],
    payload: () => ({ model: 'anima.safetensors', promptSections: { clothing: 'white bikini' } }),
    allLoraState: () => rows, addLora: (name, weight, enabled) => rows.push({ name, weight, enabled }),
    saveLoraState: () => {}, restorePayloadToPanel: (data) => { fields.prompt = data.promptSections.clothing; },
    promptEditorChanged: () => {}, renderLoraMemo: () => {}, noteKey: (value) => value,
    syncMemoOutfitModeControl: () => {}, selectLoraNote: (name) => { fields.activeLoraName = name; },
    document: { querySelectorAll: () => [{ value: 'character.safetensors' }] },
  });
  vm.runInContext(`let appliedOutfits=[{key:'character.safetensors',item:{clothing:'white bikini'},signature:'memo',state:{added:{clothing:['white bikini']}}}];
    let jobQueue=[],currentLoraName='character.safetensors',memoOutfitOverwriteMode=true,mobilePanelReady=false,mobilePanelRestoring=false;
    const MAX_LOGICAL_JOBS=10,MOBILE_PANEL_STATE_KEY='easyPanelMobilePersistV1';
    ${line('setAppliedOutfits')}
    ${line('reconcileAppliedOutfitsAfterRestore')}
    ${line('mobilePanelMode')}
    ${line('mobilePanelSnapshot')}
    ${line('saveMobilePanelState')}
    ${block('restoreMobilePanelState', 'startMobilePanelKeep')}`, context);
  localStorage.setItem('easyPanelMobilePersistV1', vm.runInContext('mobilePanelSnapshot()', context));
  rows = [];
  vm.runInContext('appliedOutfits=[];restoreMobilePanelState()', context);
  assert.equal(fields.prompt, 'white bikini');
  assert.equal(rows[0].name, 'character.safetensors');
  assert.equal(vm.runInContext('appliedOutfits.length', context), 1);
  assert.equal(fields.activeLoraName, 'character.safetensors');
  vm.runInContext('setAppliedOutfits([])', context);
  assert.equal(JSON.parse(localStorage.getItem('easyPanelMobilePersistV1')).appliedOutfits.length, 0);
  context.payload = () => { throw new Error('unfinished optional pose'); };
  context.selectedLoraPayload = () => rows;
  context.collectPromptSections = () => ({ clothing: fields.prompt });
  vm.runInContext("setAppliedOutfits([{key:'character.safetensors',item:{clothing:'white bikini'}}])", context);
  assert.equal(JSON.parse(localStorage.getItem('easyPanelMobilePersistV1')).appliedOutfits.length, 1);
});

test('programmatic memo and English insertions do not focus a prompt field', () => {
  const { context, fields } = desktopContext();
  context.item = { name: 'swimsuit', clothing: 'white bikini' };
  vm.runInContext('applyMemoOutfit(item)', context);
  assert.equal(fields.promptClothing.focusCount, undefined);
  context.promptField = () => fields.promptClothing;
  context.splitClientTerms = (value) => String(value || '').split(',').map((part) => part.trim()).filter(Boolean);
  context.normalizedClientTerm = (term) => term.toLowerCase();
  vm.runInContext(`let tokenHistory=[];${line('appendEnglish')}`, context);
  vm.runInContext("appendEnglish('white coat','clothing')", context);
  assert.equal(fields.promptClothing.focusCount, undefined);
});
