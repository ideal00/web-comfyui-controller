const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(file, ids = {}) {
  const stored = new Map();
  const listeners = {};
  const context = {
    window: null,
    document: {
      readyState: 'loading',
      addEventListener(name, handler) { listeners[name] = handler; },
      getElementById(id) { return ids[id] || null; }
    },
    localStorage: {getItem(key) { return stored.get(key) || null; }, setItem(key, value) { stored.set(key, value); }},
    sessionStorage: {getItem(key) { return stored.get(key) || null; }, setItem(key, value) { stored.set(key, value); }},
    setTimeout, clearTimeout
  };
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/assets/js', file), 'utf8'), context);
  return {context, stored, listeners};
}

test('recent tags stay deduplicated, bounded, and share the automatic target', () => {
  const target = {value: 'auto'};
  const {context, stored} = load('tag-workflow.js', {tagTarget: target});
  const tags = context.EasyPanelTagWorkflow;
  assert.equal(tags.sectionFromElement({id:'promptClothing'}), 'clothing');
  assert.equal(tags.resolve('auto'), 'appearance');
  target.value = 'pose';
  assert.equal(tags.target(), 'pose');
  tags.record('black pantyhose');
  tags.record('standing');
  tags.record('BLACK PANTYHOSE');
  assert.deepEqual(Array.from(tags.recent()), ['BLACK PANTYHOSE', 'standing']);
  assert.deepEqual(JSON.parse(stored.get('easyPanelRecentTagsV1')), ['BLACK PANTYHOSE', 'standing']);
  tags.toggleFavorite('standing');
  assert.deepEqual(Array.from(tags.favorites()), ['standing']);
});

test('last generated seed uses the exact server string, including 63-bit values', () => {
  const {context, stored} = load('panel-quick-actions.js');
  const quick = context.EasyPanelQuickActions;
  const seed = '734729834729834729';
  assert.equal(quick.recordGeneratedSeed(seed), seed);
  assert.equal(stored.get('easyPanelLastGeneratedSeedV1'), seed);
  assert.equal(quick.seedFromHistory({prompt:[0,'id',{'3':{class_type:'KSampler',inputs:{seed:1234}}}]}), '1234');
});

test('clear buttons dismiss the mobile keyboard and keep desktop focus', () => {
  const {context} = load('panel-quick-actions.js');
  const calls = [];
  const field = {blur: () => calls.push('blur'), focus: () => calls.push('focus')};
  context.navigator = {maxTouchPoints: 1};
  context.EasyPanelQuickActions.finishClearFocus(field);
  context.navigator = {maxTouchPoints: 0};
  context.matchMedia = () => ({matches: false});
  context.EasyPanelQuickActions.finishClearFocus(field);
  assert.deepEqual(calls, ['blur', 'focus']);
});

test('paste reads only the first clipboard item, preferring the Android bridge', async () => {
  const {context} = load('panel-quick-actions.js');
  context.EasyPanelClipboard = {readText: () => 'first Android clip'};
  context.navigator = {clipboard: {readText: async () => { throw new Error('browser clipboard should not run'); }}};
  assert.equal(await context.EasyPanelQuickActions.readFirstClipboardText(), 'first Android clip');
  delete context.EasyPanelClipboard;
  context.navigator.clipboard = {read: async () => [
    {types:['text/plain'], getType: async () => ({text: async () => 'first browser clip'})},
    {types:['text/plain'], getType: async () => ({text: async () => 'second browser clip'})}
  ]};
  assert.equal(await context.EasyPanelQuickActions.readFirstClipboardText(), 'first browser clip');
});

test('clean uses the existing model dialect and keeps LoRA references intact', () => {
  const {context} = load('panel-quick-actions.js');
  context.modelFamilyClient = () => 'anima';
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/assets/js/prompt-dialect.js'), 'utf8'), context);
  assert.equal(context.EasyPanelQuickActions.cleanPromptText(' long_hair； score_9, <lora:abc_def:0.8> ', 'promptPose'),
    'long hair, score_9, <lora:abc_def:0.8>');
  assert.equal(context.EasyPanelQuickActions.cleanPromptText('A_person speaks.\nB_person listens.', 'promptNaturalLanguage'),
    'A person speaks.\nB person listens.');
});

test('global history restores the previous prompt and seed as one action', () => {
  const ids = {promptPose: {value:'standing'}, seed: {value:'-1'}};
  const {context} = load('panel-history.js', ids);
  context.mobilePanelSnapshot = () => JSON.stringify({appliedOutfits:[], activeLoraName:''});
  context.allLoraState = () => [];
  const history = context.EasyPanelHistory;
  history.record();
  ids.promptPose.value = 'kneeling'; ids.seed.value = '123';
  history.record();
  assert.equal(history.step(-1), true);
  assert.equal(ids.promptPose.value, 'standing');
  assert.equal(ids.seed.value, '-1');
  assert.equal(history.step(1), true);
  assert.equal(ids.promptPose.value, 'kneeling');
  assert.equal(ids.seed.value, '123');
});
