const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/assets/js/panel-theme.js'),'utf8');
function load(saved,blocked=false) {
  const storage={value:saved},style=new Map([['--input-font-size','19px']]),root={dataset:{},style:{setProperty:(k,v)=>style.set(k,v),removeProperty:k=>style.delete(k)},removeAttribute:()=>delete root.dataset.panelTheme};
  const nodes={panelThemeStatus:{textContent:''}};
  const window={localStorage:{getItem(){if(blocked)throw Error('blocked');return storage.value;},setItem(k,v){if(blocked)throw Error('blocked');storage.value=v;}}};
  vm.runInNewContext(source,{window,document:{documentElement:root,readyState:'loading',addEventListener(){},getElementById:id=>nodes[id]||null}});
  return {api:window.EasyPanelTheme,storage,style,root,nodes};
}
test('invalid stored colors and malformed JSON fall back safely',()=>{
  for(const saved of ['broken',JSON.stringify({preset:'gray',background:'url(https://example.com)'})])assert.equal(load(saved).root.dataset.panelTheme,'gray');
  const {api}=load(); assert.equal(api.setColor('background','red; display:none'),false); assert.equal(api.setColor('unknown','#123456'),false);
});
test('custom colors persist and restore before DOM initialization',()=>{
  const a=load(); a.api.setColor('background','#312b25');
  const b=load(a.storage.value); assert.equal(b.root.dataset.panelTheme,'custom'); assert.equal(b.style.get('--theme-background'),'#312b25');
  assert.equal(b.style.get('--input-font-size'),'19px');
});
test('presets and reset keep text readable on all surfaces',()=>{
  const {api,style}=load();
  for(const preset of ['gray','warm','sage','paper']){
    api.selectPreset(preset); const state=api.getState();
    for(const key of ['background','panel','input'])assert.ok(api.contrast(state.text,state[key])>=4.5,preset+' '+key);
    assert.ok(api.contrast(state.accent,style.get('--theme-contrast'))>=4.5);
  }
  api.selectPreset('gray'); assert.equal(api.getState().preset,'gray');
});
test('original colors remove theme overrides and preserve unrelated preferences',()=>{
  const {api,root,style,storage}=load(); api.selectPreset('paper'); api.selectPreset('original');
  assert.equal(root.dataset.panelTheme,undefined); assert.equal(style.has('--accent'),false); assert.equal(style.has('--theme-background'),false); assert.equal(style.has('color-scheme'),false); assert.equal(style.get('--input-font-size'),'19px');
  assert.equal(load(storage.value).root.dataset.panelTheme,undefined);
});
test('storage unavailable still applies colors and explains that saving failed',()=>{
  const {api,root,nodes}=load(null,true); assert.doesNotThrow(()=>api.selectPreset('warm'));
  assert.equal(root.dataset.panelTheme,'warm'); assert.match(nodes.panelThemeStatus.textContent,/未允许保存/);
});
