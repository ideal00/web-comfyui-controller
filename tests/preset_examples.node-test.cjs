const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const imageId = 'a'.repeat(64);

function load(saved = {}) {
  const nodes = {};
  class Element {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.value = ''; }
    set id(id) { this._id = id; nodes[id] = this; }
    get id() { return this._id; }
    setAttribute(key,value) { this[key]=value; }
    append(...items) { this.children.push(...items); }
    after(element) { this.next = element; }
    before(element) { this.previous = element; }
    replaceChildren(...items) { this.children = items; }
  }
  for (const id of ['userPresetStatus','promptPose','promptScene','userPresetSave']) { const n = new Element('div'); n.id = id; }
  const context = {window:{localStorage:{getItem:key=>saved[key],setItem(key,value){saved[key]=value;}}}, document:{readyState:'loading',addEventListener(){},getElementById:id=>nodes[id],createElement:tag=>new Element(tag),querySelectorAll:()=>[]},URL};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/assets/js/preset-examples.js'),'utf8'),context);
  return {api:context.window.EasyPanelPresetExamples,nodes,context,saved};
}

test('image links accept only managed IDs and escape display labels', () => {
  const {api} = load();
  assert.equal(api.normalize(imageId),imageId);
  for (const input of ['../../file','https://example.com/image.png','javascript:alert(1)',{},'a'.repeat(63)]) {
    assert.equal(api.normalize(input),''); assert.equal(api.url(input),''); assert.equal(api.markup(input,'x'),'');
  }
  assert.match(api.markup(imageId,'<test>'), /&lt;test&gt;/);
  assert.equal(api.url(imageId),'/api/preset-examples/image?id='+imageId);
});

test('editor keeps an attached image until reset or explicit removal', () => {
  const {api,nodes} = load(); api.init(); api.setEditor(imageId);
  assert.equal(api.getEditor(),imageId);
  const preview = nodes.userPresetExamplePreview.children[0];
  assert.equal(preview.children[0].children[0].src,api.url(imageId));
  nodes.userPresetExampleRemove.onclick();
  assert.equal(api.getEditor(),'');
  assert.equal(nodes.userPresetExamplePreview.children[0].children[0].textContent,'未绑定例图');
  api.setEditor(imageId); api.setEditor(''); assert.equal(api.getEditor(),'');
});

test('section example changes with its random choice and hides on manual editing', () => {
  const {api,nodes} = load();
  api.showSection('pose',{name:'Chair',exampleImage:imageId});
  const host=nodes.promptPresetExample_pose;
  assert.equal(nodes.promptPresetExampleBody_pose.children[0].children[0].children[0].src,api.url(imageId));
  assert.equal(nodes.promptPresetExampleBody_pose.hidden,true);
  api.showSection('pose',{name:'Standing',exampleImage:''});
  assert.equal(host.hidden,true); assert.equal(host.children.length,0);
  api.showSection('pose',null); assert.equal(host.hidden,true); assert.equal(host.children.length,0);
});


test('visual-library examples accept only local entry IDs without changing durable attachment validation',()=>{
  const {api}=load();
  assert.equal(api.url({source:'visual',id:'vt123456789abc'}),'/api/visual-tags/image?id=vt123456789abc');
  assert.equal(api.url({source:'visual',id:'../../other'}),'');
  assert.equal(api.url({source:'visual',id:'https://example.com'}),'');
  assert.equal(api.normalize({source:'visual',id:'vt123456789abc'}),'');
});


test('section examples start collapsed and remember visibility through rerolls and reload',()=>{
  const saved={}, {api,nodes}=load(saved);
  api.showSection('pose',{name:'Sit',exampleImage:imageId});
  assert.equal(nodes.promptPresetExampleBody_pose.hidden,true);
  assert.equal(nodes.promptPresetExampleToggle_pose.textContent,'显示例图');
  nodes.promptPresetExampleToggle_pose.onclick();
  assert.equal(nodes.promptPresetExampleBody_pose.hidden,false);
  api.showSection('pose',{name:'Wave',exampleImage:'b'.repeat(64)});
  assert.equal(nodes.promptPresetExampleBody_pose.hidden,false);
  assert.equal(nodes.promptPresetExampleToggle_pose.textContent,'收起例图');
  const again=load(saved);assert.equal(again.api.isSectionVisible('pose'),true);
  api.toggleSection('pose');assert.equal(nodes.promptPresetExampleBody_pose.hidden,true);
  api.showSection('pose',{name:'Next',exampleImage:imageId});assert.equal(nodes.promptPresetExampleBody_pose.hidden,true);
});

test('global example switch controls every section and clears overrides',()=>{
  const {api,nodes}=load();
  api.attachVisibilityControl(nodes.userPresetStatus);
  api.showSection('pose',{name:'Sit',exampleImage:imageId});
  api.showSection('scene',{name:'Forest',exampleImage:imageId});
  assert.equal(nodes.promptExampleVisibility.textContent,'例图：关闭');
  nodes.promptExampleVisibility.onclick();
  assert.equal(nodes.promptPresetExampleBody_pose.hidden,false);
  assert.equal(nodes.promptPresetExampleBody_scene.hidden,false);
  api.toggleSection('pose');assert.equal(nodes.promptExampleVisibility.textContent,'例图：部分开启');
  nodes.promptExampleVisibility.onclick();
  assert.equal(nodes.promptPresetExampleBody_scene.hidden,true);
  assert.equal(nodes.promptExampleVisibility.textContent,'例图：关闭');
});


test('random preview examples follow the same section and global visibility switches',()=>{
  const {api,nodes}=load();
  const preview=api.previewFigure('pose',{name:'Chair',exampleImage:imageId});
  const body=preview.children[1];assert.equal(body.hidden,true);
  preview.children[0].onclick();assert.equal(body.hidden,false);
  api.showSection('pose',{name:'Chair',exampleImage:imageId});
  assert.equal(nodes.promptPresetExampleBody_pose.hidden,false);
  api.setAllVisible(false);assert.equal(body.hidden,true);assert.equal(nodes.promptPresetExampleBody_pose.hidden,true);
});
