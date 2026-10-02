const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function load(fetch){
  const events=[];
  const context={window:{EasyPanelDialect:{formatTags:tags=>tags.map(t=>t.replace(/_/g,' '))},dispatchEvent:e=>events.push(e.type)},fetch,Event:class{constructor(type){this.type=type;}},Promise};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/assets/js/visual-preset-source.js'),'utf8'),context);
  return {api:context.window.EasyPanelVisualPresetSource,context,events};
}
const rows=[{id:'visual:one:clothing',visualId:'vt123456789abc',section:'clothing',name:'海盗',tags:['pirate_hat','coat'],category:'身份设定',group:'航海',image:true,split:true},
            {id:'visual:one:subject',visualId:'vt123456789abc',section:'subject',name:'海盗',tags:['pirate'],category:'身份设定',image:true,split:true}];
test('load once, search Chinese and English by section, and format for the current dialect',async()=>{
  let calls=0;const {api,context,events}=load(async()=>{calls++;return {ok:true,json:async()=>({ok:true,results:rows})};});
  await Promise.all([api.ensure(),api.ensure()]);assert.equal(calls,1);assert.equal(api.loaded,true);
  assert.equal(api.candidates('clothing','海盗')[0].text,'pirate hat, coat');
  assert.equal(api.candidates('clothing','pirate hat')[0].origin,'visual');
  assert.equal(api.candidates('pose').length,0);
  assert.equal(api.candidates('subject')[0].text,'pirate');
  assert.equal(api.candidates('clothing')[0].exampleImage.id,'vt123456789abc');
  context.window.EasyPanelDialect.formatTags=tags=>tags;
  assert.equal(api.candidates('clothing')[0].text,'pirate_hat, coat');
  await api.ensure();assert.equal(calls,1);assert.equal(events.length,1);
});
test('failure permits retry and force reload replaces removed entries',async()=>{
  let calls=0;const {api}=load(async()=>{calls++;if(calls===1)throw Error('offline');return {ok:true,json:async()=>({ok:true,results:calls===2?rows:[]})};});
  await assert.rejects(api.ensure(),/offline/);assert.equal(api.loaded,false);assert.equal(api.error,'offline');
  await api.ensure();assert.equal(api.error,'');assert.equal(api.candidates('subject').length,1);
  await api.ensure(true);assert.equal(api.candidates('subject').length,0);
});
