const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(presets = [], saved = {}) {
  const elements = Object.fromEntries([
    'promptSubject', 'promptAppearance', 'promptExpression', 'promptClothing', 'promptPose',
    'promptComposition', 'promptScene', 'promptLighting', 'promptStyle'
  ].map(id => [id, {value: ''}]));
  elements.promptVariationStatus = {textContent: ''};
  const context = {
    window: {},
    document: {readyState: 'loading', addEventListener() {}, getElementById(id) { return elements[id]; }},
    localStorage: {getItem(key) { return saved[key] || null; }, setItem(key, value) { saved[key] = value; }},
    userPromptPresets: presets,
    presetInsertText(item) { return item.tags?.join(', ') || item.content; },
    Math
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/assets/js/prompt-variations.js'), 'utf8'), context);
  return {api: context.window.EasyPanelPromptVariations, elements, context};
}

test('weighted groups and LoRA tokens remain intact when split', () => {
  const {api} = load();
  assert.deepEqual(Array.from(api.tokenize('1girl, (blue hair, long hair:1.2), <lora:name:0.8>, BREAK\nA sentence.')),
    ['1girl', '(blue hair, long hair:1.2)', '<lora:name:0.8>', 'BREAK', 'A sentence.']);
  assert.equal(api.kind('<lora:name:0.8>'), 'lora');
  assert.equal(api.kind('(blue hair:1.2)'), 'weight');
  assert.equal(api.kind('BREAK'), 'structure');
  assert.equal(api.translationSource('(blue hair:1.2)'), 'blue hair');
  assert.equal(api.protectedLabel('<lora:name:0.8>'), 'LoRA 引用');
  assert.equal(api.protectedLabel('1girl'), '人数标签');
  assert.equal(api.protectedLabel('(score_9:1.2)'), '质量标签');
});

test('variation pool uses whole presets and bundle dialect text', () => {
  const {api} = load([
    {category: 'pose', name: 'Chair', content: 'sitting, legs crossed'},
    {category: 'pose', name: 'Chair copy', content: 'sitting, legs crossed'},
    {category: 'pose', name: 'Window', tags: ['leaning on window', 'looking away']},
    {category: 'combo', name: 'Room', sections: {pose: 'kneeling, looking back', composition: 'full body'}},
    {category: 'artist', name: 'Style', content: 'line art'}
  ]);
  assert.deepEqual(Array.from(api.pool('pose'), item => item.text),
    ['sitting, legs crossed', 'leaning on window, looking away', 'kneeling, looking back']);
  assert.equal(api.pool('style')[0].text, 'line art');
});

test('section dice replaces its own field immediately and history restores it', () => {
  const {api, elements} = load([{category: 'pose', name: 'Sit', content: 'sitting, legs crossed'}]);
  elements.promptPose.value = 'standing';
  elements.promptScene.value = 'beach';
  assert.equal(api.randomSectionNow('pose'), true);
  assert.equal(elements.promptPose.value, 'sitting, legs crossed');
  assert.equal(elements.promptScene.value, 'beach');
  api.navigate(-1);
  assert.equal(elements.promptPose.value, 'standing');
  assert.equal(api.randomSectionNow('scene'), false);
  assert.equal(elements.promptScene.value, 'beach');
});

test('tag dice changes only one token and locked tags constrain section variants', () => {
  const presets = [{category:'pose', name:'Sit', content:'sitting, looking at viewer'}];
  const {api, elements} = load(presets, {
    easyPanelVariationTagLocksV1: JSON.stringify({pose:['looking at viewer']})
  });
  elements.promptPose.value = 'standing, looking at viewer';
  assert.equal(api.randomTagNow('pose', 1), false);
  assert.equal(api.randomTagNow('pose', 0), true);
  assert.equal(elements.promptPose.value, 'sitting, looking at viewer');
  api.navigate(-1);
  assert.equal(elements.promptPose.value, 'standing, looking at viewer');
  assert.equal(api.randomSectionNow('pose'), true);
  assert.equal(elements.promptPose.value, 'sitting, looking at viewer');
});

test('section dice refuses variants that would discard a locked tag', () => {
  const {api, elements} = load([{category:'pose', name:'Sit', content:'sitting, legs crossed'}], {
    easyPanelVariationTagLocksV1: JSON.stringify({pose:['looking at viewer']})
  });
  elements.promptPose.value = 'standing, looking at viewer';
  assert.equal(api.randomSectionNow('pose'), false);
  assert.equal(elements.promptPose.value, 'standing, looking at viewer');
});

test('chip editor reuses the color modifier for replacement and removal', () => {
  global.window = global;
  const modifier = require(path.join(__dirname, '../web/assets/js/color-modifier.js'));
  const {api, context} = load();
  context.window.EasyPanelColorModifier = modifier;
  assert.equal(api.colorizedToken('blue hair', 'dark'), 'dark blue hair');
  assert.equal(api.colorizedToken('dark blue hair', 'light'), 'light blue hair');
  assert.equal(api.colorizedToken('dark blue hair', ''), 'blue hair');
});

test('chip translations reuse the explainer glossary and skip protected tokens', async () => {
  const stored = new Map([['easyPanelPromptGlossaryV1', JSON.stringify({'standing':'站立'})]]);
  const calls = [];
  const context = {
    window: null,
    document: {},
    localStorage: {getItem(key) { return stored.get(key) || null; }, setItem(key, value) { stored.set(key, value); }},
    chineseMap: {'蓝色头发':'blue hair'},
    easyPanelArgosBatch: async values => { calls.push(...values); return values.map(() => '微笑'); }
  };
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/assets/js/prompt-explain.js'), 'utf8'), context);
  const result = await context.EasyPanelPromptExplainer.translateLabels(['standing', 'blue hair', 'smile', '<lora:x:0.8>']);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    standing: '站立', 'blue hair': '蓝色头发', smile: '微笑', '<lora:x:0.8>': ''
  });
  assert.deepEqual(calls, ['smile']);
  assert.equal(JSON.parse(stored.get('easyPanelPromptGlossaryV1')).smile, '微笑');
});
