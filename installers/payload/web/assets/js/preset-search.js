/* Search personal presets by section; a combination contributes only that section. */
(function (g) {
  'use strict';
  const FIELDS = {
    promptSubject:'subject',promptAppearance:'appearance',promptExpression:'expression',
    promptClothing:'clothing',promptPose:'pose',promptComposition:'composition',
    promptScene:'scene',promptLighting:'lighting',promptStyle:'artist',
    promptNaturalLanguage:'naturalLanguage',prompt:'manual',negative:'negative'
  };
  const LABELS = {subject:'人物与角色',appearance:'外貌',expression:'表情',clothing:'服装与材质',pose:'姿势',composition:'构图与镜头',scene:'场景',lighting:'光线',artist:'画师 / 画风',naturalLanguage:'自然语言',manual:'其他补充',negative:'负面词'};
  const byId = id => document.getElementById(id);
  const norm = text => String(text || '').trim().toLowerCase().replace(/_/g,' ').replace(/\s+/g,' ');
  const sectionKey = id => FIELDS[id] === 'artist' ? 'style' : FIELDS[id];
  let popup = null, current = null;
  const extraExamples = {};
  function presets() { return typeof userPromptPresets !== 'undefined' && Array.isArray(userPromptPresets) ? userPromptPresets : []; }
  function candidates(fieldId, query = '', limit = 50) {
    const category = FIELDS[fieldId]; if (!category) return [];
    const words = norm(query).split(' ').filter(Boolean), results = [];
    for (const item of presets()) {
      const combo = item.category === 'combo';
      const raw = combo ? item.sections?.[category] : item.category === category ? item.content || item.tags?.join(', ') : '';
      if (!raw) continue;
      const haystack = norm([item.name,item.description,raw].join(' '));
      if (!words.every(word => haystack.includes(word))) continue;
      const text = category === 'naturalLanguage' ? raw : typeof presetInsertText === 'function' ? presetInsertText(item,combo ? category : undefined) : raw;
      if (!String(text || '').trim()) continue;
      results.push({source:'preset',id:item.id,name:item.name,tag:item.name,translation:LABELS[category],category:LABELS[category],description:item.description || '',text,exampleImage:item.exampleImage,combo,fieldId,updatedAt:Number(item.updatedAt)||0});
    }
    results.push(...(g.EasyPanelVisualPresetSource?.candidates(category,query,limit) || []).map(item=>({...item,fieldId,libraryCategory:item.category,category:LABELS[category]})));
    return results.sort((a,b) => {
      const q = norm(query), rank = item => norm(item.name) === q ? 0 : norm(item.name).startsWith(q) ? 1 : 2;
      return rank(a) - rank(b) || b.updatedAt - a.updatedAt;
    }).slice(0,limit);
  }
  function queryRange(field) {
    if (!field || field.selectionStart !== field.selectionEnd) return null;
    const end = field.selectionStart, before = field.value;
    if (!/^\s*(?:[,;\n]|$)/.test(before.slice(end))) return null;
    const match = /(^|[,;\n]\s*)([^,;\n]+)$/.exec(before.slice(0,end));
    return match ? {start:end-match[2].length,end,before} : null;
  }
  function completedValue(fieldId, range, text) {
    const suffix = range.before.slice(range.end);
    const trailing = FIELDS[fieldId] === 'naturalLanguage' || /^\s*[,;\n]/.test(suffix) ? '' : ', ';
    return range.before.slice(0,range.start) + text + trailing + suffix;
  }
  function status(text) {
    if (popup && !popup.hidden) byId('presetSearchStatus').textContent = text;
    const target = byId('promptVariationStatus') || byId('userPresetStatus');
    if (target) target.textContent = text;
  }
  function remember(fieldId, choice) {
    const key = sectionKey(fieldId);
    if (g.EasyPanelPromptVariations?.rememberPreset?.(key,choice)) return;
    extraExamples[fieldId] = {value:byId(fieldId).value,choice};
    g.EasyPanelPresetExamples?.showSection(key,choice);
  }
  function apply(choice, fieldId, mode = 'append', range = null) {
    const field = byId(fieldId);
    if (!field || !FIELDS[fieldId]) return false;
    if (field.readOnly || field.disabled || g.EasyPanelPromptVariations?.isFieldLocked(fieldId)) { status(LABELS[FIELDS[fieldId]]+'已锁定，请先解锁。'); return false; }
    // Refresh the source so edits/sync while a picker is open cannot insert stale text.
    const item = candidates(fieldId,'',Infinity).find(item => item.id === choice.id);
    if (!item) { status('预设已变化或删除，请重新搜索。'); return false; }
    if (mode === 'complete' && (!range || field.value !== range.before || field.selectionStart !== range.end || field.selectionEnd !== range.end)) { status('输入内容或光标已变化，请重新选择预设。'); return false; }
    g.EasyPanelHistory?.record();
    if (mode === 'replace') field.value = item.text;
    else if (mode === 'complete') {
      field.value = completedValue(fieldId,range,item.text);
      const caret = field.value.length - range.before.slice(range.end).length;
      field.setSelectionRange(caret,caret);
    }
    else if (FIELDS[fieldId] === 'naturalLanguage') {
      const before = field.value.trim();
      if (!before.includes(item.text)) field.value = before ? before + '\n' + item.text : item.text;
    } else if (typeof g.batchAppendToField === 'function') g.batchAppendToField(fieldId,item.text);
    else field.value = field.value.trim() ? field.value.trim() + ', ' + item.text : item.text;
    field.dispatchEvent(new Event('input',{bubbles:true}));
    g.promptEditorChanged?.();
    remember(fieldId,item);
    status(`已${mode==='replace'?'替换':mode==='complete'?'补全':'追加'}「${item.name}」到${LABELS[FIELDS[fieldId]]}${item.combo||item.split?'（只提取本分区）':''}。`);
    return true;
  }
  const el = (tag,cls,text) => { const node=document.createElement(tag); if(cls)node.className=cls; if(text)node.textContent=text; return node; };
  function close() {
    if (!popup) return;
    popup.hidden = true;
    if (current) byId(current.fieldId)?.setAttribute('aria-expanded','false');
    current = null;
  }
  function position() {
    if (!popup || popup.hidden || !current) return;
    const rect = current.anchor.getBoundingClientRect();
    const width = Math.min(650,g.innerWidth-20), height = Math.min(470,g.innerHeight-24);
    popup.style.width=width+'px'; popup.style.maxHeight=height+'px';
    popup.style.left=Math.max(10,Math.min(rect.left,g.innerWidth-width-10))+'px';
    popup.style.top=Math.max(10,Math.min(rect.bottom+5,g.innerHeight-height-10))+'px';
  }
  function activate(index) {
    if (!current || !current.items.length) return;
    current.index=(index+current.items.length)%current.items.length;
    const rows=popup.querySelectorAll('[role="option"]');
    rows.forEach((row,i)=>{row.classList.toggle('active',i===current.index);row.setAttribute('aria-selected',String(i===current.index));});
    const selected=rows[current.index]; selected?.scrollIntoView({block:'nearest'});
    byId('presetSearchQuery').setAttribute('aria-activedescendant',selected?.id||'');
    const preview=byId('presetSearchImage'); preview.replaceChildren();
    if(g.EasyPanelPresetExamples)preview.append(g.EasyPanelPresetExamples.figure(current.items[current.index].exampleImage,current.items[current.index].name));
  }
  function render() {
    if (!current) return;
    const all=candidates(current.fieldId,byId('presetSearchQuery').value,Infinity);
    current.items=all.slice(0,50); current.index=0;
    const list=byId('presetSearchResults'); list.replaceChildren();
    byId('presetSearchStatus').textContent=all.length?`找到 ${all.length} 条${all.length>50?'，显示前 50 条；输入更多关键词缩小范围':''}`:(g.EasyPanelVisualPresetSource && !g.EasyPanelVisualPresetSource.loaded ? (g.EasyPanelVisualPresetSource.error || '正在载入可视化图库…') : '本分区没有匹配预设或图库词条。');
    byId('presetSearchImage').replaceChildren();
    byId('presetSearchQuery').removeAttribute('aria-activedescendant');
    current.items.forEach((item,index)=>{
      const row=el('div','preset-search-result');row.id='presetSearchOption_'+index;row.setAttribute('role','option');
      const image=g.EasyPanelPresetExamples?.url(item.exampleImage);
      if(image){const img=el('img','preset-search-thumb');img.src=image;img.alt=item.name+'的例图';img.loading='lazy';img.onerror=()=>{img.hidden=true;};row.append(img);}
      const content=el('div','preset-search-copy');content.append(el('strong','',item.name),el('small','',item.origin==='visual'?'图库 · '+item.libraryCategory+(item.split?' · 只提取本分区':''):item.combo?'组合预设 · 只提取'+LABELS[FIELDS[current.fieldId]]:'个人预设 · '+LABELS[FIELDS[current.fieldId]]),el('p','',item.text.slice(0,160)));
      if(item.description)content.append(el('small','',item.description));row.append(content);
      row.onpointermove=()=>{if(current && current.index!==index)activate(index);};
      row.onclick=()=>{if(!current)return;const fieldId=current.fieldId;if(apply(item,fieldId,byId('presetSearchMode').value)){close();byId(fieldId).focus({preventScroll:true});}};
      list.append(row);
    });
    if(current.items.length)activate(0);
    position();
  }
  function ensurePopup() {
    if(popup)return;
    popup=el('section','preset-search-popup');popup.id='presetSearchPopup';popup.hidden=true;popup.setAttribute('aria-label','分区预设搜索');
    const header=el('div','preset-search-head'),title=el('strong');title.id='presetSearchTitle';
    const dismiss=el('button','secondary','×');dismiss.type='button';dismiss.setAttribute('aria-label','关闭预设搜索');dismiss.onclick=close;header.append(title,dismiss);
    const controls=el('div','preset-search-tools'),input=el('input');input.id='presetSearchQuery';input.type='search';input.placeholder='搜索名称、提示词或说明…';input.setAttribute('aria-label','搜索本分区预设');input.setAttribute('role','combobox');input.setAttribute('aria-controls','presetSearchResults');input.setAttribute('aria-expanded','true');input.setAttribute('aria-autocomplete','list');
    const mode=el('select');mode.id='presetSearchMode';mode.setAttribute('aria-label','预设写入方式');
    for(const [value,label] of [['append','追加到本区'],['replace','替换本区']]){const option=el('option','',label);option.value=value;mode.append(option);}controls.append(input,mode);
    const body=el('div','preset-search-body'),list=el('div','preset-search-results');list.id='presetSearchResults';list.setAttribute('role','listbox');list.setAttribute('aria-label','本分区预设候选');
    const preview=el('aside','preset-search-image');preview.id='presetSearchImage';body.append(list,preview);
    const notice=el('p','small');notice.id='presetSearchStatus';notice.setAttribute('role','status');
    popup.append(header,controls,body,notice);document.body.append(popup);
    input.oninput=()=>{if(input.dataset.composing!=='1')render();};
    input.addEventListener('compositionstart',()=>{input.dataset.composing='1';});
    input.addEventListener('compositionend',()=>{input.dataset.composing='0';render();});
    input.onkeydown=event=>{
      if(event.isComposing||input.dataset.composing==='1')return;
      if(['ArrowDown','ArrowUp','Enter','Escape'].includes(event.key)){event.preventDefault();event.stopPropagation();}
      if(event.key==='Escape')close();
      else if(event.key==='ArrowDown')activate(current.index+1);
      else if(event.key==='ArrowUp')activate(current.index-1);
      else if(event.key==='Enter'&&current?.items[current.index]){const id=current.fieldId;if(apply(current.items[current.index],id,mode.value)){close();byId(id).focus({preventScroll:true});}}
    };
    document.addEventListener('pointerdown',event=>{if(current&&!popup.contains(event.target)&&!current.anchor.contains(event.target))close();});
    document.addEventListener('scroll',event=>{if(current&&!popup.contains(event.target))close();},true);
    g.addEventListener('resize',position);
  }
  function open(fieldId, anchor) {
    const field=byId(fieldId);if(!field||!FIELDS[fieldId])return;
    ensurePopup();g.EasyPanelTagAutocomplete?.hideField?.(fieldId);
    current={fieldId,anchor:anchor||field,items:[],index:0};popup.hidden=false;
    byId('presetSearchTitle').textContent=LABELS[FIELDS[fieldId]]+'预设';byId('presetSearchQuery').value='';
    byId('presetSearchMode').value='append';render();byId('presetSearchQuery').focus({preventScroll:true});
    g.EasyPanelVisualPresetSource?.ensure().then(()=>{if(current?.fieldId===fieldId)render();}).catch(()=>{if(current?.fieldId===fieldId)render();});
  }
  async function random(fieldId) {
    const field=byId(fieldId);if(!field)return false;
    const before=field.value;
    try { await g.EasyPanelVisualPresetSource?.ensure(); } catch(error) { status(error.message); return false; }
    if(field.value!==before){status('输入内容已变化，请重新随机。');return false;}
    const options=candidates(fieldId,'',Infinity).filter(item=>norm(item.text)!==norm(before));
    if(!options.length){status('本区没有其他可用预设或图库词条。');return false;}
    return apply(options[Math.floor(Math.random()*options.length)],fieldId,'replace');
  }
  function init() {
    for(const id of Object.keys(FIELDS)){
      const field=byId(id);if(!field)continue;
      const container=field.closest('[data-prompt-group]');
      let button=container?.querySelector('.section-preset-browse');
      if(!button){button=el('button','section-preset-browse');button.type='button';const header=field.previousElementSibling;if(header?.classList.contains('field-title'))header.append(button);else field.before(button);}
      button.textContent='搜索预设';button.title='搜索'+LABELS[FIELDS[id]]+'预设与例图';button.onclick=()=>open(id,button);
      if(!['naturalLanguage','manual','negative'].includes(FIELDS[id]))continue;
      if (id==='prompt') { const dice=el('button','section-preset-random','🎲'); dice.type='button'; dice.title='随机其他补充预设或图库道具'; dice.onclick=()=>random(id); button.after(dice); }
      field.addEventListener('input',()=>{const saved=extraExamples[id];if(saved&&field.value!==saved.value){delete extraExamples[id];g.EasyPanelPresetExamples?.showSection(sectionKey(id),null);}});
    }
  }
  g.EasyPanelPresetSearch={FIELDS,candidates,ready:()=>g.EasyPanelVisualPresetSource?.ensure() || Promise.resolve(),queryRange,completedValue,apply,remember,open,close,random,init};
  if(typeof module!=='undefined'&&module.exports)module.exports=g.EasyPanelPresetSearch;
  if(typeof document==='undefined')return;
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})(typeof window!=='undefined'?window:globalThis);
