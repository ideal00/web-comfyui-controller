const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/assets/js/panel.js'),'utf8');
const definition=name=>source.split('\n').find(line=>line.startsWith('function '+name+'('));
function navigation({mobile=false,tool=false}={}) {
  const calls=[],rail={scrollTo:()=>calls.push('rail-reset'),scrollIntoView:()=>calls.push('rail-visible')};
  const target={closest:selector=>selector==='.studio-lora'?rail:selector==='#studioToolDrawerContent'&&tool?{}:null,scrollIntoView:()=>calls.push('target-visible')};
  const context={$:()=>target,window:{matchMedia:()=>({matches:mobile})},document:{documentElement:{classList:{contains:()=>false}}},setStudioCreationTab:tab=>calls.push(tab),toggleStudioToolDrawer:open=>calls.push(['drawer',open]),toggleResourcePanel:()=>calls.push('resource-open'),toggleLeftRail(){},scrollStudioContentToTop:()=>calls.push('outer-reset'),panelScrollBehavior:()=> 'auto',highlightPanelTarget(){}};
  vm.runInNewContext(definition('jumpToPanelSection'),context);
  return {calls,jump:context.jumpToPanelSection};
}
test('model navigation reveals the stacked resource panel without resetting outer scroll',()=>{
  const {calls,jump}=navigation();jump('loraSection');
  assert.ok(calls.includes('rail-reset'));assert.ok(calls.includes('rail-visible'));assert.ok(!calls.includes('outer-reset'));assert.deepEqual(calls[0],['drawer',false]);
});
test('mobile prompt navigation dismisses the tool drawer and reveals the requested section',()=>{
  const {calls,jump}=navigation({mobile:true});jump('promptComposer');
  assert.equal(calls[0],'prompt');assert.deepEqual(calls[1],['drawer',false]);assert.ok(calls.includes('target-visible'));
});
test('navigating to an advanced tool keeps its drawer open',()=>{
  const {calls,jump}=navigation({tool:true});jump('poseMemo');assert.deepEqual(calls[0],['drawer',true]);
});
test('quick navigation toggle exposes and dismisses its actions with accurate accessible state',()=>{
  const classes=new Set(),attrs={};let reposition=0;
  const nav={classList:{contains:name=>classes.has(name),toggle:(name,on)=>on?classes.add(name):classes.delete(name)}},button={setAttribute:(key,value)=>attrs[key]=value};
  const context={document:{querySelector:()=>nav},$:()=>button,updatePanelQuickJumpPosition:()=>reposition++};
  vm.runInNewContext(definition('togglePanelQuickJumps'),context);
  context.togglePanelQuickJumps();assert.equal(attrs['aria-expanded'],'true');assert.match(attrs['aria-label'],/收起/);
  context.togglePanelQuickJumps(false);assert.equal(attrs['aria-expanded'],'false');assert.match(attrs['aria-label'],/展开/);assert.equal(classes.size,0);assert.equal(reposition,2);
});
