const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/assets/js/panel.js'),'utf8');
const definition=name=>source.split('\n').find(line=>line.startsWith('async function '+name+'('));
function load({native=false,fallback=true,bridge=false}={}) {
  const status={textContent:''},button={textContent:'复制 TXT'},calls={native:0,fallback:0,focus:0,removed:0};
  const context={window:{EasyPanelClipboard:bridge?{copyText:()=>true}:null},navigator:{clipboard:native?{writeText:async()=>{calls.native++;throw Error('Permission denied');}}:null},document:{activeElement:{focus:()=>calls.focus++},createElement:()=>({style:{},focus(){},select(){},remove(){calls.removed++;}}),body:{appendChild(){}},execCommand:()=>{calls.fallback++;return fallback;}},$:()=>status,selectedSidecar:()=>({content:'verified source text'}),setTimeout(){}};
  vm.runInNewContext(definition('copyDeepSeekInstruction')+'\n'+definition('copyLoraSidecarText'),context);
  return {context,status,button,calls};
}
test('denied modern clipboard falls back and restores focus on LAN pages',async()=>{
  const {context,status,button,calls}=load({native:true});await context.copyLoraSidecarText(button);
  assert.equal(calls.native,1);assert.equal(calls.fallback,1);assert.equal(calls.focus,1);assert.equal(calls.removed,1);assert.equal(button.textContent,'已复制');assert.match(status.textContent,/已复制/);
});
test('failed LAN copy never displays success',async()=>{
  const {context,status,button,calls}=load({fallback:false});await context.copyLoraSidecarText(button);
  assert.equal(button.textContent,'复制 TXT');assert.match(status.textContent,/复制失败/);assert.doesNotMatch(status.textContent,/已复制/);assert.equal(calls.removed,1);assert.equal(calls.focus,1);
});
test('Android clipboard bridge is used before browser fallbacks',async()=>{
  const {context,calls}=load({bridge:true,native:true,fallback:false});await context.copyDeepSeekInstruction('model/path.safetensors');assert.equal(calls.native,0);assert.equal(calls.fallback,0);
});
