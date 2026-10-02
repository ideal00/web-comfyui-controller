const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function load(presets) {
  const fields = {};
  for (const id of ['promptSubject','promptAppearance','promptExpression','promptClothing','promptPose','promptComposition','promptScene','promptLighting','promptStyle','promptNaturalLanguage','prompt','negative']) fields[id] = {
    value:'',selectionStart:0,selectionEnd:0,events:[],
    dispatchEvent(event) { this.events.push(event.type); },setSelectionRange(a,b) { this.selectionStart=a; this.selectionEnd=b; }
  };
  fields.promptVariationStatus={textContent:''};
  const shown={},history=[];
  const context = {window:{EasyPanelHistory:{record(){history.push('record');}},EasyPanelPresetExamples:{showSection(key,choice){shown[key]=choice;}},promptEditorChanged(){}},
    document:{readyState:'loading',addEventListener(){},getElementById:id=>fields[id]},
    userPromptPresets:presets,Event:class Event {constructor(type){this.type=type;}},
    presetInsertText(item,key) { return (key ? item.sections[key] : item.tags?.join(', ') || item.content).replace(/_/g,' '); }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/assets/js/preset-search.js'),'utf8'),context);
  return {api:context.window.EasyPanelPresetSearch,fields,shown,history,context};
}

test('each input searches only its category or the corresponding combination section',()=>{
  const {api}=load([
    {id:'pose',name:'坐姿',category:'pose',content:'sitting, crossed_legs',description:'椅子上'},
    {id:'outfit',name:'裙子',category:'clothing',content:'white_dress'},
    {id:'combo',name:'室内组合',category:'combo',sections:{pose:'kneeling',scene:'bedroom',artist:'line_art'}},
    {id:'negative',name:'质量负面',category:'negative',content:'low_quality'},
    {id:'natural',name:'双人互动',category:'naturalLanguage',content:'Two adults are talking.'},
    {id:'manual',name:'其他补充',category:'manual',content:'sparkles'}
  ]);
  assert.deepEqual(Array.from(api.candidates('promptPose','椅子'),x=>x.id),['pose']);
  assert.equal(api.candidates('promptPose','crossed legs')[0].text,'sitting, crossed legs');
  assert.equal(api.candidates('promptScene','组合')[0].text,'bedroom');
  assert.equal(api.candidates('promptStyle','组合')[0].text,'line art');
  assert.equal(api.candidates('promptClothing','sitting').length,0);
  assert.equal(api.candidates('promptNaturalLanguage','')[0].id,'natural');
  assert.equal(api.candidates('prompt','')[0].id,'manual');
  assert.equal(api.candidates('negative','')[0].id,'negative');
  assert.equal(Object.keys(api.FIELDS).length,12);
});

test('completion replaces only the current search phrase and preserves following tokens',()=>{
  const image='a'.repeat(64);
  const {api,fields,shown,history}=load([{id:'pose',name:'坐姿',category:'pose',content:'sitting, crossed_legs',exampleImage:image}]);
  const field=fields.promptPose;field.value='looking at viewer, 坐姿, smile';field.selectionStart=field.selectionEnd=21;
  const range=api.queryRange(field);
  assert.equal(range.before.slice(range.start,range.end),'坐姿');
  assert.equal(api.apply(api.candidates('promptPose','')[0],'promptPose','complete',range),true);
  assert.equal(field.value,'looking at viewer, sitting, crossed legs, smile');
  assert.equal(shown.pose.exampleImage,image);assert.equal(history.length,1);
  assert.equal(fields.promptScene.value,'');
});

test('whole-section replacement from a combo touches only the selected field',()=>{
  const {api,fields}=load([{id:'combo',name:'室内组合',category:'combo',sections:{pose:'sitting',scene:'bedroom'}}]);
  fields.promptPose.value='standing';fields.promptScene.value='forest';
  assert.equal(api.apply(api.candidates('promptPose','')[0],'promptPose','replace'),true);
  assert.equal(fields.promptPose.value,'sitting');assert.equal(fields.promptScene.value,'forest');
});

test('locked fields, deleted presets, and stale caret ranges refuse insertion',()=>{
  const {api,fields,history,context}=load([{id:'pose',name:'坐姿',category:'pose',content:'sitting'}]);
  const field=fields.promptPose,choice=api.candidates('promptPose','')[0];field.value='坐姿';field.selectionStart=field.selectionEnd=2;
  field.readOnly=true;assert.equal(api.apply(choice,'promptPose','replace'),false);assert.equal(history.length,0);
  field.readOnly=false;const range=api.queryRange(field);field.value='standing';assert.equal(api.apply(choice,'promptPose','complete',range),false);
  field.value='坐姿';field.selectionStart=field.selectionEnd=1;assert.equal(api.apply(choice,'promptPose','complete',range),false);
  context.userPromptPresets=[];assert.equal(api.apply(choice,'promptPose','replace'),false);assert.equal(history.length,0);
});

test('natural language inserts sentences without tag commas and never searches manual presets',()=>{
  const {api,fields}=load([{id:'natural',name:'对话',category:'naturalLanguage',content:'Two adults are talking.'}]);
  const choice=api.candidates('promptNaturalLanguage','')[0],field=fields.promptNaturalLanguage;
  field.value='They are in a cafe.';api.apply(choice,'promptNaturalLanguage','append');
  assert.equal(field.value,'They are in a cafe.\nTwo adults are talking.');
  field.value='对话';field.selectionStart=field.selectionEnd=2;api.apply(choice,'promptNaturalLanguage','complete',api.queryRange(field));
  assert.equal(field.value,'Two adults are talking.');
});


test('illustrated gallery components join only their assigned field and insert English text',()=>{
  const {api,fields,shown,context}=load([]);
  context.window.EasyPanelVisualPresetSource={candidates(category,query){return category==='clothing'?[{id:'visual:vt123456789abc:clothing',name:'海盗',category:'身份设定',text:'pirate_hat, coat',origin:'visual',split:true,exampleImage:{source:'visual',id:'vt123456789abc'}}]:[];}};
  assert.equal(api.candidates('promptSubject').length,0);
  const choice=api.candidates('promptClothing')[0];
  assert.equal(choice.libraryCategory,'身份设定');
  assert.equal(api.apply(choice,'promptClothing','replace'),true);
  assert.equal(fields.promptClothing.value,'pirate_hat, coat');
  assert.equal(fields.promptSubject.value,'');
  assert.equal(shown.clothing.exampleImage.id,'vt123456789abc');
});
