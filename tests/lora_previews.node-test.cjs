const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ref = {imageId:'a'.repeat(64),weight:0.8,width:768,height:1024,steps:30};
const name = 'Anima/Style.safetensors';

function load(rows = []) {
  class Element {
    constructor(tag) { this.tagName=tag; this.children=[]; this.dataset={}; this.textContent=''; this.replacements=0; }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children=items; this.replacements++; }
    setAttribute(key,value) { this[key]=value; }
    addEventListener() {}
    showModal() { this.open=true; }
    close() { this.open=false; }
  }
  const nodes = {};
  for (const id of ['loraReferenceList','loraSelectedReference','loraReferenceCount','loraReferenceDialog','loraReferenceImage','loraReferenceTitle','loraReferenceSettings','loraReferenceClose','status']) nodes[id]=new Element('div');
  const calls=[];
  const window={addLora:(...args)=>calls.push(['add',...args]),selectLoraNote:(...args)=>calls.push(['select',...args]),toggleLoraEnabled:(...args)=>calls.push(['enable',...args])};
  const context={window,document:{getElementById:id=>nodes[id],createElement:tag=>new Element(tag),querySelectorAll:()=>rows}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/assets/js/lora-previews.js'),'utf8'),context);
  return {api:window.EasyPanelLoraPreviews,nodes,calls};
}

test('LoRA references accept managed image IDs and normalize path separators',()=>{
  const {api}=load();
  assert.equal(api.referenceFor('Anima\\Style.safetensors',{[name]:{referenceImage:ref}}),ref);
  for (const imageId of ['https://example.com/x','../secret','javascript:alert(1)','b'.repeat(63)]) assert.equal(api.imageUrl({imageId}),'');
  assert.equal(api.referenceFor(name,{[name]:{referenceImage:{imageId:'bad'}},'Style.safetensors':{referenceImage:ref}}),null);
});

test('gallery follows current family, folder and search candidates',()=>{
  const {api}=load();
  const notes={[name]:{referenceImage:ref},'Other.safetensors':{referenceImage:ref}};
  assert.equal(api.candidates([name,'NoImage.safetensors'],notes).length,1);
  assert.equal(api.candidates([],notes).length,0);
});

test('unchanged rendering preserves cards and selected reference uses its own image',()=>{
  const {api,nodes}=load(); const notes={[name]:{referenceImage:ref}};
  api.render([name],notes,name); const card=nodes.loraReferenceList.children[0];
  api.render([name],notes,name);
  assert.equal(nodes.loraReferenceList.children[0],card); assert.equal(nodes.loraReferenceList.replacements,1);
  assert.equal(nodes.loraReferenceCount.textContent,'1'); assert.equal(nodes.loraSelectedReference.hidden,false);
  assert.match(nodes.loraSelectedReference.children[0].children[0].src,/^\/api\/preset-examples\/image\?id=a{64}$/);
  api.render([],notes,''); assert.equal(nodes.loraSelectedReference.hidden,true);
});

test('reference image opens in a dialog with the test parameters',()=>{
  const {api,nodes}=load(); api.openImage(name,ref);
  assert.equal(nodes.loraReferenceDialog.open,true); assert.equal(nodes.loraReferenceTitle.textContent,'Style');
  assert.match(nodes.loraReferenceSettings.textContent,/0.8.*768×1024.*30/);
  nodes.loraReferenceClose.onclick(); assert.equal(nodes.loraReferenceDialog.open,false);
});

test('choosing an already loaded reference updates its weight without duplicating LoRA',()=>{
  let saved=0; const input={value:'0.7',oninput:()=>saved++},select={value:'Anima\\Style.safetensors'};
  const row={dataset:{enabled:'false'},querySelector:selector=>selector==='.lora-select'?select:input};
  const {api,calls}=load([row]); api.addReferenceLora(name,ref);
  assert.equal(input.value,'0.8'); assert.equal(saved,1); assert.equal(calls.some(call=>call[0]==='add'),false);
  assert.equal(calls.filter(call=>call[0]==='enable').length,1);
});

test('editing a memo preserves the reference metadata sent to the server',async()=>{
  const code=fs.readFileSync(path.join(__dirname,'../web/assets/js/panel.js'),'utf8').split('\n').find(line=>line.startsWith('async function saveLoraMemo()'));
  const old={title:'old',referenceImage:ref,outfits:[]}; let body;
  const nodes={memoTitle:{value:'new'},memoBase:{value:'Anima'},memoWeight:{value:'0.8'},memoTrigger:{value:''},memoUrl:{value:''},status:{}};
  const context={currentNoteKey:name,loraNotes:{[name]:old},noteData:()=>old,$:id=>nodes[id],document:{querySelectorAll:()=>[]},memoOutfitRowData:()=>{},OUTFIT_SECTIONS:[],renderLoraMemo(){},closeLoraMemoEditor(){},fetch:async(url,options)=>{body=JSON.parse(options.body);return {json:async()=>({ok:true})}}};
  vm.runInNewContext(code,context); await context.saveLoraMemo();
  assert.equal(body.notes[name].title,'new'); assert.deepEqual(body.notes[name].referenceImage,ref);
});
