/* Browser-local panel colors; restore before first paint, never touch generation state. */
(function (g) {
  'use strict';
  const KEY = 'easyPanelColorsV1', fields = ['background', 'panel', 'input', 'text', 'accent'];
  const presets = {
    gray: {label:'柔和灰', background:'#242628', panel:'#2e3133', input:'#252729', text:'#d6d7d2', accent:'#a8b5ad'},
    warm: {label:'暖灰夜间', background:'#292622', panel:'#34302b', input:'#25231f', text:'#dbd4c5', accent:'#b5a68a'},
    sage: {label:'浅色鼠尾草', background:'#dde4db', panel:'#e8ede5', input:'#f2f5ed', text:'#28382d', accent:'#55715e'},
    paper: {label:'暖色纸张', background:'#e8e2d5', panel:'#f2edde', input:'#faf6eb', text:'#3e3931', accent:'#786648'}
  };
  const valid = value => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
  const rgb = color => [1,3,5].map(i => parseInt(color.slice(i,i+2),16));
  function mix(a,b,amount) { return '#' + rgb(a).map((n,i)=>Math.round(n*(1-amount)+rgb(b)[i]*amount).toString(16).padStart(2,'0')).join(''); }
  function luminance(color) { return rgb(color).map(n=>{n/=255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4;}).reduce((sum,n,i)=>sum+n*[.2126,.7152,.0722][i],0); }
  function contrast(a,b) { const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05); }
  function normalize(saved) {
    if (saved?.preset === 'original') return {preset:'original',...presets.gray};
    if (!saved || !fields.every(key=>valid(saved[key]))) return {preset:'gray',...presets.gray};
    const result={preset: Object.hasOwn(presets,saved.preset)?saved.preset:'custom'};
    fields.forEach(key=>result[key]=saved[key].toLowerCase()); return result;
  }
  let state;
  try { state=normalize(JSON.parse(g.localStorage.getItem(KEY))); } catch { state=normalize(null); }
  const root=document.documentElement;
  function apply() {
    if (state.preset==='original') {
      root.removeAttribute('data-panel-theme');
      ['color-scheme','--bg','--card','--panel','--line','--border','--text','--muted','--accent','--accent2','--token',...['background','panel','input','text','accent','muted','line','raised','button','soft','contrast'].map(key=>'--theme-'+key)].forEach(key=>root.style.removeProperty(key));
      return;
    }
    root.dataset.panelTheme=state.preset;
    const dark=luminance(state.background)<.35;
    root.style.setProperty('color-scheme',dark?'dark':'light');
    const colors={...state,muted:mix(state.text,state.panel,.25),line:mix(state.panel,state.text,.22),raised:mix(state.panel,state.text,.045),button:mix(state.panel,state.text,.075),soft:mix(state.panel,state.accent,.18),contrast:contrast(state.accent,'#171919')>=contrast(state.accent,'#fafaf5')?'#171919':'#fafaf5'};
    Object.entries(colors).filter(([key])=>key!=='preset'&&key!=='label').forEach(([key,value])=>root.style.setProperty('--theme-'+key,value));
    root.style.setProperty('--bg',state.background); root.style.setProperty('--card',state.panel); root.style.setProperty('--panel',state.input); root.style.setProperty('--line',colors.line); root.style.setProperty('--border',colors.line); root.style.setProperty('--text',state.text); root.style.setProperty('--muted',colors.muted); root.style.setProperty('--accent',state.accent); root.style.setProperty('--accent2',state.accent); root.style.setProperty('--token',colors.button);
  }
  function sync() {
    const preset=document.getElementById('panelThemePreset'); if (!preset) return;
    preset.value=state.preset;
    for (const key of fields) {
      const color=document.getElementById('panelColor-'+key),hex=document.getElementById('panelHex-'+key);
      color.value=state[key]; hex.value=state[key]; hex.removeAttribute('aria-invalid');
      color.disabled=hex.disabled=state.preset==='original';
    }
    const minimum=Math.min(...['background','panel','input'].map(key=>contrast(state.text,state[key])));
    document.getElementById('panelThemeStatus').textContent=state.preset==='original'?'已恢复原来的蓝色配色。':minimum<4.5?'已保存。文字与背景较接近，可以调亮文字或调暗背景。':'已保存到当前浏览器；刷新、退出再进入会保留。';
  }
  function save(next) { state=normalize(next); apply(); let stored=true; try{g.localStorage.setItem(KEY,JSON.stringify(state));}catch{stored=false;} sync(); if(!stored&&document.getElementById('panelThemeStatus'))document.getElementById('panelThemeStatus').textContent='配色已生效，但浏览器未允许保存，刷新后可能恢复默认。'; }
  function selectPreset(name) { if(name==='original')save({preset:name});else if(presets[name])save({preset:name,...presets[name]}); }
  function setColor(key,value) { if(!fields.includes(key)||!valid(value))return false; save({...state,preset:'custom',[key]:value}); return true; }
  function open() { const dialog=document.getElementById('panelThemeDialog'); sync(); if(!dialog.open)dialog.showModal(); }
  function install() {
    const dialog=document.getElementById('panelThemeDialog'); if(!dialog)return;
    document.querySelectorAll('[data-panel-theme-open]').forEach(button=>button.addEventListener('click',open));
    document.getElementById('panelThemeClose').onclick=()=>dialog.close();
    document.getElementById('panelThemeReset').onclick=()=>selectPreset('gray');
    document.getElementById('panelThemePreset').onchange=event=>selectPreset(event.target.value);
    for(const key of fields) {
      document.getElementById('panelColor-'+key).oninput=event=>setColor(key,event.target.value);
      document.getElementById('panelHex-'+key).oninput=event=>{if(valid(event.target.value.trim()))setColor(key,event.target.value.trim());};
      document.getElementById('panelHex-'+key).onchange=event=>{if(!setColor(key,event.target.value.trim())){event.target.setAttribute('aria-invalid','true');document.getElementById('panelThemeStatus').textContent='请输入完整颜色代码，例如 #2e3133。';}};
    }
    sync();
  }
  g.EasyPanelTheme={normalize,mix,luminance,contrast,selectPreset,setColor,getState:()=>({...state}),open};
  apply();
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
})(window);
