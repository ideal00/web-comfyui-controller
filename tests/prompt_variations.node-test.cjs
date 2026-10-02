const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(presets = [], saved = {}, examples = undefined) {
  const elements = Object.fromEntries([
    'promptSubject', 'promptAppearance', 'promptExpression', 'promptClothing', 'promptPose',
    'promptComposition', 'promptScene', 'promptLighting', 'promptStyle'
  ].map(id => [id, {value: '', parentElement: {querySelector() { return null; }}}]));
  elements.promptVariationStatus = {textContent: ''};
  elements.promptPresetName_pose = {textContent: '', hidden: true};
  const context = {
    window: {EasyPanelPresetExamples:examples},
    document: {readyState: 'loading', addEventListener() {}, getElementById(id) { return elements[id]; }},
    localStorage: {getItem(key) { return saved[key] || null; }, setItem(key, value) { saved[key] = value; }},
    userPromptPresets: presets,
    presetInsertText(item, section) { return section ? item.sections?.[section] : (item.tags?.join(', ') || item.content); },
    Math, setTimeout, clearTimeout
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/assets/js/prompt-variations.js'), 'utf8'), context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/assets/js/panel-history.js'), 'utf8'), context);
  return {api: context.window.EasyPanelPromptVariations, history: context.window.EasyPanelHistory, elements, context};
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
  const {api, history, elements} = load([{category: 'pose', name: 'Sit', content: 'sitting, legs crossed'}]);
  elements.promptPose.value = 'standing';
  elements.promptScene.value = 'beach';
  assert.equal(api.randomSectionNow('pose'), true);
  assert.equal(elements.promptPose.value, 'sitting, legs crossed');
  assert.equal(api.presetName('pose'), 'Sit');
  assert.equal(elements.promptPresetName_pose.textContent, '预设：Sit');
  assert.equal(elements.promptPresetName_pose.hidden, false);
  assert.equal(elements.promptScene.value, 'beach');
  history.step(-1);
  assert.equal(elements.promptPose.value, 'standing');
  history.step(1);
  assert.equal(elements.promptPose.value, 'sitting, legs crossed');
  assert.equal(api.presetName('pose'), 'Sit');
  elements.promptPose.value = 'sitting, legs crossed, smiling';
  api.renderAll();
  assert.equal(api.presetName('pose'), '');
  assert.equal(elements.promptPresetName_pose.hidden, true);
  assert.equal(api.randomSectionNow('scene'), false);
  assert.equal(elements.promptScene.value, 'beach');
});

test('clothing dice excludes pose-led combo overrides and changes only clothing', () => {
  const {api, elements} = load([
    {category:'pose', name:'Sitting', content:'sitting'},
    {category:'combo', name:'Chair pose', sections:{pose:'sitting, legs crossed',clothing:'dress'}},
    {category:'clothing', name:'Office suit', content:'blazer, pencil skirt'},
  ], {easyPanelVariationLocksV1:JSON.stringify({clothing:false})});
  assert.deepEqual(Array.from(api.pool('clothing'), item => item.name), ['Office suit']);
  assert.equal(api.pool('pose').some(item => item.name === 'Chair pose'), true);
  elements.promptPose.value = 'standing';
  elements.promptClothing.value = 'hoodie';
  assert.equal(api.randomSectionNow('clothing'), true);
  assert.equal(elements.promptClothing.value, 'blazer, pencil skirt');
  assert.equal(elements.promptPose.value, 'standing');
  assert.equal(api.presetName('clothing'), 'Office suit');
});

test('tag dice changes only one token and locked tags constrain section variants', () => {
  const presets = [{category:'pose', name:'Sit', content:'sitting, looking at viewer'}];
  const {api, history, elements} = load(presets, {
    easyPanelVariationTagLocksV1: JSON.stringify({pose:['looking at viewer']})
  });
  elements.promptPose.value = 'standing, looking at viewer';
  assert.equal(api.randomTagNow('pose', 1), false);
  assert.equal(api.randomTagNow('pose', 0), true);
  assert.equal(elements.promptPose.value, 'sitting, looking at viewer');
  history.step(-1);
  assert.equal(elements.promptPose.value, 'standing, looking at viewer');
  assert.equal(api.randomSectionNow('pose'), true);
  assert.equal(elements.promptPose.value, 'looking at viewer, sitting');
});

test('section dice retains locked tags while drawing a source that does not contain them', () => {
  const {api, elements} = load([{category:'pose', name:'Sit', content:'sitting, legs crossed'}], {
    easyPanelVariationTagLocksV1: JSON.stringify({pose:['looking at viewer']})
  });
  elements.promptPose.value = 'standing, looking at viewer';
  assert.equal(api.randomSectionNow('pose'), true);
  assert.equal(elements.promptPose.value, 'looking at viewer, sitting, legs crossed');
});

test('locking a section blocks direct randomization and tag insertion', () => {
  const {api, elements} = load([{category:'pose', name:'Sit', content:'sitting'}], {
    easyPanelVariationLocksV1: JSON.stringify({pose:true})
  });
  elements.promptPose.value = 'standing';
  assert.equal(api.isLocked('pose'), true);
  assert.equal(api.randomSectionNow('pose'), false);
  assert.equal(api.addTag('pose', 'looking at viewer'), false);
  assert.equal(elements.promptPose.value, 'standing');
  api.beginTrustedRestore();
  elements.promptPose.value = 'kneeling';
  api.restoreLocked();
  assert.equal(elements.promptPose.value, 'kneeling');
  api.endTrustedRestore();
  elements.promptPose.value = 'running';
  api.restoreLocked();
  assert.equal(elements.promptPose.value, 'kneeling');
});

test('global history restores a locked section through the trusted restore path', () => {
  const {api, history, elements} = load([], {easyPanelVariationLocksV1: JSON.stringify({pose:true})});
  elements.promptPose.value = 'standing';
  api.beginTrustedRestore(); api.endTrustedRestore();
  history.record();
  elements.promptPose.value = 'sitting';
  history.record();
  assert.equal(history.step(-1), true);
  assert.equal(elements.promptPose.value, 'standing');
  api.renderAll();
  assert.equal(elements.promptPose.value, 'standing');
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


test('random section and staged preview carry the matching preset example', () => {
  const image = 'a'.repeat(64), seen = {};
  const examples = {showSection(key,choice) { seen[key] = choice; }, figure(id,name) { return {image:id,name}; }};
  const {api,elements,context} = load([
    {id:'chair',category:'pose',name:'Chair',content:'sitting',exampleImage:image},
    {id:'combo',category:'combo',name:'Room',sections:{scene:'bedroom'},exampleImage:image}
  ], {}, examples);
  assert.equal(api.pool('pose')[0].exampleImage,image);
  assert.equal(api.pool('scene')[0].id,'combo');
  assert.equal(api.randomSectionNow('pose'),true);
  assert.equal(seen.pose.exampleImage,image);
  elements.promptPose.value='standing'; api.renderAll();
  assert.equal(seen.pose,null);
  const list={rows:[],replaceChildren(){this.rows=[];},append(row){this.rows.push(row);}};
  elements.promptVariationPreview={hidden:true,querySelector(){return list;}};
  context.document.createElement=()=>({children:[],append(item){this.children.push(item);}});
  api.stage(['scene']);
  assert.equal(elements.promptScene.value,'');
  assert.equal(elements.promptVariationPreview.hidden,false);
  assert.equal(list.rows[0].children[0].image,image);
  api.accept();
  assert.equal(elements.promptScene.value,'bedroom');
  assert.equal(seen.scene.exampleImage,image);
});


test('section and single-tag dice include illustrated gallery choices and show their image',()=>{
  const calls=[];
  const {api,elements,context}=load([],{}, {showSection(key,choice){if(choice)calls.push({key,choice});}});
  context.window.EasyPanelVisualPresetSource={loaded:true,candidates(key){return key==='pose'?[{id:'visual:vt123456789abc:pose',name:'坐姿图库',text:'sitting',exampleImage:{source:'visual',id:'vt123456789abc'}}]:[];}};
  elements.promptPose.value='standing';
  assert.equal(api.randomSectionNow('pose'),true);
  assert.equal(elements.promptPose.value,'sitting');
  assert.equal(calls.at(-1).choice.exampleImage.id,'vt123456789abc');
  elements.promptPose.value='standing, hands_up';
  assert.equal(api.randomTagNow('pose',0),true);
  assert.equal(elements.promptPose.value,'sitting, hands_up');
  assert.equal(calls.at(-1).choice.name,'坐姿图库');
});


test('a locked single-tag gallery result leaves the dice able to draw a next tag',()=>{
  const calls=[];
  const {api,elements,history,context}=load([], {easyPanelVariationTagLocksV1:JSON.stringify({pose:['sitting']})}, {showSection(key,choice){if(choice)calls.push(choice);}});
  context.window.EasyPanelVisualPresetSource={loaded:true,candidates(section){return section==='pose'?[{id:'sit',name:'坐姿',text:'sitting'},{id:'wave',name:'挥手',text:'waving',exampleImage:'a'.repeat(64)}]:[];}};
  elements.promptPose.value='sitting';
  assert.equal(api.randomSectionNow('pose'),true);
  assert.equal(elements.promptPose.value,'sitting, waving');
  assert.equal(calls.at(-1).name,'挥手');
  assert.equal(calls.at(-1).presetText,'waving');
  history.step(-1);assert.equal(elements.promptPose.value,'sitting');
  assert.equal(api.randomSectionNow('pose'),true);
  assert.equal(elements.promptPose.value,'sitting, waving');
});

test('locked weighted terms keep their original weight without duplicate unweighted tags',()=>{
  const {api,elements}=load([{category:'pose',name:'Wave',content:'sitting, waving'}], {easyPanelVariationTagLocksV1:JSON.stringify({pose:['(sitting:1.2)']})});
  elements.promptPose.value='(sitting:1.2), standing';
  assert.equal(api.randomSectionNow('pose'),true);
  assert.equal(elements.promptPose.value,'(sitting:1.2), waving');
});

test('a pool containing only locked terms leaves input intact',()=>{
  const {api,elements}=load([{category:'pose',name:'Sit',content:'sitting'}], {easyPanelVariationTagLocksV1:JSON.stringify({pose:['sitting']})});
  elements.promptPose.value='sitting';assert.equal(api.randomSectionNow('pose'),false);assert.equal(elements.promptPose.value,'sitting');
});
