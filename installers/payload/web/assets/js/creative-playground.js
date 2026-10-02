/* A reversible playground on top of the existing prompt editor and job queue. */
(function (g) {
  'use strict';
  const D = g.EasyPanelPlaygroundData, C = g.EasyPanelPlaygroundCore;
  const fields = {subject:'promptSubject',appearance:'promptAppearance',clothing:'promptClothing',pose:'promptPose',expression:'promptExpression',composition:'promptComposition',scene:'promptScene',lighting:'promptLighting',style:'promptStyle',manual:'prompt',naturalLanguage:'promptNaturalLanguage'};
  const labels = {subject:'人物',appearance:'外貌',clothing:'服装',pose:'姿势',expression:'表情',composition:'构图',scene:'场景',lighting:'光线',style:'画风',manual:'其他补充',naturalLanguage:'自然语言'};
  const KEY = 'easyPanelPlaygroundV1';
  const state = {tab:'free',pending:null,prepared:null,blind:null,busy:false};
  let saved = {shots:[],votes:[]}, storageError = '';
  try {const x=JSON.parse(localStorage.getItem(KEY)||'{}'); saved.shots=Array.isArray(x.shots)?x.shots.filter(x=>x?.id&&x?.name&&typeof x.sections?.composition==='string').slice(0,40):[]; saved.votes=Array.isArray(x.votes)?x.votes.slice(-200):[]; if(x.draft?.draft&&typeof x.draft.draft==='object'&&!Array.isArray(x.draft.draft))saved.draft=x.draft;} catch (_) {storageError='本机玩法记录读取失败；导出当前记录后再处理浏览器存储。';}
  const $ = id=>document.getElementById(id);
  const el = (tag,cls,text)=>{const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n;};
  const button = (text,fn,cls='secondary')=>{const n=el('button',cls,text);n.type='button';n.onclick=()=>Promise.resolve().then(fn).catch(error=>status(error.message,true));return n;};
  const esc = x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function status(text,error=false){const n=$('playStatus');if(n){n.textContent=text;n.classList.toggle('play-error',error);}}
  function persist(){try{localStorage.setItem(KEY,JSON.stringify(saved));return true;}catch(_){status('浏览器存储已满或不可用；本次记录仍在当前页面，请导出保存。',true);return false;}}
  function sections(){return Object.fromEntries(Object.entries(fields).map(([k,id])=>[k,$(id)?.value||'']));}
  function locks(){return Object.keys(fields).filter(k=>g.EasyPanelPromptVariations?.isFieldLocked(fields[k]));}
  function download(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function note(text){return el('p','play-note',text);}
  function area(label,value,readOnly=false){const l=el('label','play-field',label),t=el('textarea');t.value=value||'';t.readOnly=readOnly;l.append(t);return {node:l,input:t};}
  function row(...children){const n=el('div','play-actions');n.append(...children);return n;}
  function select(label,items){const l=el('label','play-field',label),n=el('select');items.forEach(x=>{const o=el('option','',x.name);o.value=x.id;n.append(o);});l.append(n);return {node:l,input:n};}
  function currentBase(){if(typeof g.payload!=='function')throw Error('生成面板尚未就绪。');const base=C.clone(g.payload());if(!base.model)throw Error('请先在主面板选择模型，再建立实验。');return base;}
  async function compile(base){const r=await fetch('/api/prompt-compile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(base)});if(!r.ok)throw Error(`编译请求失败（${r.status}）。`);const result=await r.json();if(result.error||result.errors?.length)throw Error(result.error||result.errors.join('；'));if(!result.positive?.trim())throw Error('编译得到空提示词。');return result;}
  function queueJobs(jobs){
    if(typeof jobQueue==='undefined'||typeof saveJobQueue!=='function'||typeof renderJobQueue!=='function')throw Error('面板任务队列尚未就绪。');
    C.queueCapacity(jobQueue,jobs);
    jobQueue.push(...C.clone(jobs));saveJobQueue();renderJobQueue();
    status(`已暂存 ${jobs.length} 个任务。参数和种子已冻结；关闭游乐场后点底部“发送队列”开始生成。`);
  }
  function rememberDraft(){if(state.pending){saved.draft={name:state.pending.name,draft:C.clone(state.pending.draft)};persist();}}
  function stage(name,proposed,options={}){
      const previous=options.fresh?{}:state.pending?.draft||{};
      const draft=Object.fromEntries(Object.keys(fields).map(key=>[key,previous[key]?.text?{...previous[key]}:{mode:'keep',text:String(proposed[key]||'')}]));
    // Whole recipes are suggestions. Only pose is armed by default; all other
    // sections stay unchanged. Single-section tools arm only that section.
    const keys=Object.keys(proposed).filter(k=>fields[k]);
    const selected=options.selected|| (keys.length===1?keys:keys.includes('pose')?['pose']:[]);
      for(const key of selected)if(draft[key])draft[key]={text:String(proposed[key]||''),mode:options.mode||'append'};
    state.pending={name,draft,before:sections()};rememberDraft();renderEditor();
    status('内容已放入可编辑草稿；每区可选保留、追加或替换，尚未写入主面板。');
  }
  function draftPlan(){return C.composeDraft(sections(),state.pending?.draft||{},locks());}
  function updateDraftSummary(){
    const box=$('playDraftSummary');if(!box||!state.pending)return;box.replaceChildren();
    const plan=draftPlan(),merged={...sections(),...Object.fromEntries(plan.changes.map(x=>[x.key,x.after]))};
    const counter=el('strong','play-change-count',plan.changes.length?`${plan.changes.length} 个分区待应用`:'尚未选择要修改的分区');box.append(counter);
    box.append(note(plan.changes.length?'将写入：'+plan.changes.map(x=>`${labels[x.key]}（${x.mode==='append'?'追加':'替换'}）`).join('、'):'当前所有分区保持原样。'));
    if(plan.skipped.length)box.append(note('已锁定，将跳过：'+plan.skipped.map(x=>labels[x]).join('、')));
    const issues=C.check(merged);if(issues.length)box.append(note('搭配提示：'+issues.map(x=>x.message).join('；')));
    if(plan.changes.length){const preview=el('details','play-diff');preview.append(el('summary','','查看应用前后内容'));for(const change of plan.changes){const group=el('div','play-diff-row');group.append(el('strong','',labels[change.key]),area('应用前',change.before,true).node,area('应用后',change.after,true).node);preview.append(group);}box.append(preview);}
  }
  function renderEditor(){
    if(!state.pending)return;
    const host=$('playPreview');host.replaceChildren();host.hidden=false;
    host.append(el('h3','','自由分区草稿'),note('文字可直接改；每区单独选保留、追加、替换。选择“保留”的分区不会写入。追加旧姿势可能产生冲突，需要换动作时只把姿势设为替换。'));
    const name=el('input');name.value=state.pending.name;name.setAttribute('aria-label','草稿名称');name.oninput=()=>{state.pending.name=name.value;rememberDraft();};host.append(name);
    const grid=el('div','play-draft-grid');
    const presets=g.EasyPanelSharedStateBridge?.read()?.promptPresets||[];
    for(const key of Object.keys(fields)){
      const item=state.pending.draft[key]||(state.pending.draft[key]={mode:'keep',text:''});
      const card=el('details','play-draft-field');card.open=item.mode!=='keep';card.dataset.section=key;
      const heading=el('summary','play-field-heading'),badge=el('span','play-mode-badge');heading.append(el('span','',labels[key]),badge);card.append(heading);
      const refreshBadge=()=>{const locked=locks().includes(key);badge.textContent=locked?'已锁定':({keep:'保留',append:'追加',replace:'替换'})[item.mode];card.dataset.mode=locked?'locked':item.mode;};refreshBadge();
      const mode=select(labels[key]+'应用方式',[{id:'keep',name:'保留主面板（不写入）'},{id:'append',name:'追加这段文字'},{id:'replace',name:'只替换这个分区'}]);mode.input.value=item.mode;mode.input.dataset.draftMode=key;
      const text=area(labels[key]+'草稿',item.text);text.input.dataset.draftText=key;
      mode.input.onchange=()=>{item.mode=mode.input.value;refreshBadge();rememberDraft();updateDraftSummary();};
      text.input.oninput=()=>{item.text=text.input.value;rememberDraft();updateDraftSummary();};
      const target=key==='style'?'artist':key;
      const pool=presets.flatMap(p=>{const content=p.category==='combo'?p.sections?.[target]:p.category===target?p.content:'';return content?[{id:p.id,name:p.name,content,description:p.description||''}]:[];});
      const search=el('input','play-preset-search');search.type='search';search.placeholder='搜索名称或英文提示词…';search.setAttribute('aria-label',labels[key]+'预设搜索');
      const source=select(labels[key]+'个人预设',[{id:'',name:'从我的预设选择…'},...pool]);
      const sourceInfo=note(`可选 ${pool.length} 条，只提取${labels[key]}分区。`);sourceInfo.classList.add('play-source-info');
      source.input.onchange=()=>{const p=pool.find(p=>p.id===source.input.value);sourceInfo.textContent=p?(p.description||'此预设没有使用说明。'):`可选 ${pool.length} 条，只提取${labels[key]}分区。`;};
      search.oninput=()=>{const q=search.value.trim().toLocaleLowerCase(),selected=source.input.value,results=pool.filter(p=>(p.name+' '+p.content+' '+p.description).toLocaleLowerCase().includes(q));source.input.replaceChildren();for(const p of [{id:'',name:results.length?`找到 ${results.length} 条，选择预设…`:'没有匹配的预设'},...results]){const o=el('option','',p.name);o.value=p.id;source.input.append(o);}if(results.some(p=>p.id===selected))source.input.value=selected;sourceInfo.textContent=`找到 ${results.length} 条；搜索不会修改草稿。`;};
      const sourceRow=row(source.node,button('载入到草稿',()=>{const p=pool.find(p=>p.id===source.input.value);if(!p)throw Error('先选择一个预设。');text.input.value=p.content;item.text=p.content;rememberDraft();updateDraftSummary();status('只载入草稿文字；应用方式保持你的选择。');}));
      const current=el('details');current.append(el('summary','','查看主面板当前内容'),area('当前'+labels[key],sections()[key],true).node);
      card.append(mode.node,text.node,search,sourceRow,sourceInfo,row(button('读取当前'+labels[key],()=>{item.text=sections()[key];text.input.value=item.text;rememberDraft();updateDraftSummary();})),current);grid.append(card);
    }
    const summary=el('div');summary.id='playDraftSummary';
    const actions=row(button('应用选中分区',apply,'play-primary'),button('全部设为保留',()=>{Object.values(state.pending.draft).forEach(x=>x.mode='keep');state.pending.lastApplied=[];rememberDraft();renderEditor();}),button('另存为我的预设',saveDraftPreset),button('收起草稿',()=>{host.hidden=true;}));actions.classList.add('play-editor-actions');
    host.append(grid,summary,actions);
    updateDraftSummary();
  }
  async function saveDraftPreset(){
    if(!state.pending?.name.trim())throw Error('请填写草稿名称。');
    const parts={};
      const selected=Object.keys(state.pending.draft).filter(key=>state.pending.draft[key].mode!=='keep');
      const saveKeys=selected.length?selected:state.pending.lastApplied||[];
      for(const [key,item] of Object.entries(state.pending.draft))if(saveKeys.includes(key)&&item.text.trim()){
      const target=key==='style'?'artist':key;
      parts[target]=[parts[target],item.text.trim()].filter(Boolean).join('\n');
    }
    const keys=Object.keys(parts);if(!keys.length)throw Error('至少选择一个有文字的分区。');if(keys.length>10)throw Error('一个组合最多保存 10 个分区。');
      if(Object.values(parts).some(text=>/[^\x00-\x7f]/.test(text)))throw Error('提示词请写英文；中文说明可以写在名称里。');
      if(Object.values(parts).some(text=>text.length>12000))throw Error('单个分区最多保存 12000 个字符，请缩短后再保存。');
    if(typeof userPromptPresets==='undefined'||typeof persistUserPromptPresets!=='function')throw Error('个人预设尚未加载。');
    if(userPromptPresets.length>=1000)throw Error('个人预设已达 1000 条上限。');
    const id='play_custom_'+Date.now()+'_'+Math.random().toString(36).slice(2,8);
    const item={id,name:state.pending.name.trim().slice(0,80),category:keys.length===1?keys[0]:'combo',content:Object.values(parts).join('\n'),sections:keys.length===1?{}:parts,tags:[],mode:'append',model:'',description:'自由分区草稿；主面板用追加/覆盖按钮选择应用方式。',updatedAt:Date.now()};
    userPromptPresets.unshift(item);if(!persistUserPromptPresets()){userPromptPresets=userPromptPresets.filter(x=>x.id!==id);throw Error('本机预设保存失败。');}
    g.renderUserPromptPresets?.();
    status('已另存为新预设；没有覆盖旧预设。');
    if(g.syncEasyPanelSharedState){const result=await g.syncEasyPanelSharedState({manual:true});status(result?.ok?'已另存到“我的提示词预设”，并同步到服务器。':'预设已保存在本机；服务器同步暂未成功，可稍后点立即同步。',!result?.ok);}
  }
  function apply(){
    if(!state.pending)return;
    const current=sections();
    if(JSON.stringify(current)!==JSON.stringify(state.pending.before)){state.pending.before=current;renderEditor();status('主面板内容已变化，已重新显示当前内容；请检查后再应用。',true);return;}
    const plan=draftPlan();if(!plan.changes.length){status('没有可写入的分区；请选追加或替换，并检查分区锁。',true);return;}
    if(plan.changes.some(x=>/[^\x00-\x7f]/.test(state.pending.draft[x.key].text)))throw Error('草稿提示词请使用英文；中文可以写在名称中。');
      g.EasyPanelHistory?.record();
      state.pending.lastApplied=plan.changes.map(x=>x.key);
    for(const change of plan.changes){const n=$(fields[change.key]);if(n)n.value=change.after;state.pending.draft[change.key].mode='keep';}
    if(typeof g.setFinalPromptMode==='function')g.setFinalPromptMode(false);
    g.promptEditorChanged?.();state.pending.before=sections();rememberDraft();renderEditor();
    status(`已${plan.changes.map(x=>(x.mode==='append'?'追加':'替换')+labels[x.key]).join('、')}；其他分区原样保留。可用面板左上角撤销。`);
  }
  function renderFree(host){
    host.append(note('自由组合你的动作、表情、场景与镜头。下方草稿可逐区编辑，并直接读取你的个人预设。职业故事和镜头卡只是可选素材。'));
      host.append(row(button('打开自由草稿',()=>{if(state.pending)renderEditor();else if(saved.draft?.draft){state.pending={name:saved.draft.name||'我的组合',draft:saved.draft.draft,before:sections()};renderEditor();}else stage('我的组合',{});}),button('从当前分区建立草稿',()=>stage('当前画面变体',sections(),{selected:[],fresh:true}))));
    if(!state.pending){if(saved.draft?.draft){state.pending={name:saved.draft.name||'我的组合',draft:saved.draft.draft,before:sections()};renderEditor();}else stage('我的组合',{});}else renderEditor();
  }
  function renderCareers(host){
    host.append(note('先选好角色和主服装。每张抓住一个小事故；应用前可预览，锁定分区会保留。'));
    const choice=el('label','play-check'),include=el('input');include.type='checkbox';choice.append(include,document.createTextNode('同时建议职业服装（服装分区需先解锁）'));host.append(choice);
    const grid=el('div','play-grid');
    D.careers.forEach(recipe=>{const card=el('article','play-card');card.append(el('h3','',recipe.name),note(recipe.moment),button('编辑这份素材',()=>{const s={...recipe.sections};if(!include.checked)delete s.clothing;stage(recipe.name,s);}));grid.append(card);});
    host.append(row(button('抽一个兼容的职业故事',()=>{const recipes=D.careers.map(x=>({...x,sections:{...x.sections}}));if(!include.checked)recipes.forEach(x=>delete x.sections.clothing);const found=C.chooseCompatible(recipes,sections(),locks());if(!found){status('在当前锁定内容下，没有通过已知规则的配方；请先检查搭配。',true);return;}stage(found.name,found.sections);})),grid);
  }
  function seedsControl(){const l=el('label','play-field','固定种子（1–4 个，逗号分隔）'),n=el('input');n.value=/^\d+$/.test($('seed')?.value||'')?$('seed').value:'20260929';l.append(n);return {node:l,input:n};}
  function showPrepared(name,jobs,extra=''){
    state.prepared={name,jobs,createdAt:new Date().toISOString()};
    const host=$('playPrepared');host.replaceChildren();host.hidden=false;
    host.append(el('h3','',`${name} · ${jobs.length} 个任务`),note(extra||'完整参数和最终正负向已冻结；每个变体使用相同的一组种子，每任务一张。'));
    jobs.forEach(job=>{const d=el('details');d.append(el('summary','',job.experiment.label));d.append(note(`${job.model} · ${job.width}×${job.height} · ${job.steps} 步 · ${job.sampler}/${job.scheduler}`),area('冻结的正向',job.promptOverride.positive,true).node,area('冻结的负向',job.promptOverride.negative,true).node);host.append(d);});
    const queue=button('加入暂存队列',()=>{queueJobs(jobs);queue.disabled=true;queue.textContent='本组已暂存';},'play-primary');
    host.append(row(queue,button('导出实验 JSON',()=>download('anima-experiment.json',state.prepared))));
    status('实验已准备好，检查后可暂存或导出。');
  }
  async function withBusy(action){if(state.busy)return;state.busy=true;state.prepared=null;$('playPrepared').hidden=true;status('正在冻结参数并编译实验…');try{await action();}finally{state.busy=false;}}
  function renderActing(host){
    host.append(note('动作与四组性格描述都可编辑。实验只替换姿势和表情；角色、服装、场景、构图、光线和其他参数全部沿用当前面板。'));
    const action=select('动作素材（可改写）',[...D.actions,{id:'custom',name:'自定义动作'}]),seeds=seedsControl();
    const common=area('共同动作（英文，可自由编辑）',D.actions[0].pose);
    action.input.onchange=()=>{common.input.value=D.actions.find(x=>x.id===action.input.value)?.pose||'';};
    host.append(action.node,common.node,seeds.node);
    const grid=el('div','play-grid'),editors=[];
    D.personalities.forEach(p=>{
      const card=el('article','play-card'),body=area(p.name+'的动作细节',p.pose),face=area(p.name+'的表情',p.expression);
      editors.push({id:p.id,name:p.name,body:body.input,face:face.input});
      card.append(el('h3','',p.name),body.node,face.node,button('放入自由草稿',()=>{
        stage(p.name+' · '+(D.actions.find(x=>x.id===action.input.value)?.name||'自定义动作'),{pose:[common.input.value,body.input.value].filter(Boolean).join(' '),expression:face.input.value},{selected:['pose','expression']});
      }));grid.append(card);
    });host.append(grid);
    host.append(button('建立四性格固定种子实验',()=>withBusy(async()=>{
      const base=currentBase(),seedList=C.parseSeeds(seeds.input.value),variants=[];let negative=null;
      if(locks().some(k=>k==='pose'||k==='expression'))throw Error('姿势或表情分区已锁定；请先在主面板解锁要比较的分区。');
      if(!common.input.value.trim())throw Error('请先填写共同动作。');
      const rows=editors.map(p=>({id:p.id,name:p.name,pose:[common.input.value,p.body.value].filter(Boolean).join(' '),expression:p.face.value}));
      if(rows.some(p=>/[^\x00-\x7f]/.test(p.pose+p.expression)))throw Error('实验提示词请使用英文。');
      for(const p of rows){const candidate=C.clone(base);candidate.promptSections={...candidate.promptSections,pose:p.pose,expression:p.expression};candidate.promptOverride={enabled:false};
        const result=await compile(candidate);if(negative!==null&&negative!==result.negative)throw Error('变体触发了不同的自动负面词，暂不能建立严格对照。');negative=result.negative;
        variants.push({id:p.id,name:p.name,positive:result.positive,sections:candidate.promptSections});
      }
      showPrepared('自定义动作 · 四种性格',C.buildJobs(base,variants,seedList,negative,'personality'));
    }),'play-primary'));
  }
  function diagram(shot){
    const wide=shot.ratio==='16:9',width=wide?240:180,height=160;
    const x=width*(shot.x||50)/100,y=height*(shot.y||50)/100,s=shot.scale||.8;
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(shot.name)}构图示意"><rect width="${width}" height="${height}" rx="8" fill="#172637"/><path d="M0 110 Q60 75 ${width} 102 V160 H0Z" fill="#28434c"/><path d="M${width/3} 0V160M${width*2/3} 0V160M0 53H${width}M0 107H${width}" stroke="#53727a" stroke-dasharray="3 5" opacity=".55"/>${shot.depth?`<path d="M0 0H22V160H0ZM${width-17} 0H${width}V160H${width-17}Z" fill="#0b1625"/>`:''}<g transform="translate(${x} ${y}) scale(${s})"><circle cy="-40" r="13" fill="#ecd3bd"/><path d="M-17 -24Q0 -30 17 -24L22 22H-22Z" fill="#af94df"/><path d="M-18 -18L-29 20M18 -18L29 20M-10 22L-13 65M10 22L13 65" stroke="#af94df" stroke-width="10" stroke-linecap="round"/></g></svg>`;
  }
  function renderShots(host){
    host.append(note('这些是原创构图示意，不是生图样张。点击卡片只写入构图；尺寸需另点按钮。你也可以把当前镜头保存成自己的卡。'));
    const grid=el('div','play-grid');
    [...D.shots,...saved.shots].forEach(shot=>{const card=el('article','play-card');const visual=el('div','play-shot');visual.innerHTML=diagram(shot);card.append(visual,el('h3','',shot.name),note(`${shot.ratio||'自定义'} · ${shot.notes||'从主面板保存的构图'}`),button('编辑此镜头',()=>stage(shot.name,shot.sections)));if(shot.size)card.append(button(`设置 ${shot.size}`,()=>{const target=$('size');if(!target)throw Error('未找到尺寸选择器。');g.EasyPanelHistory?.record();if(![...target.options].some(o=>o.value===shot.size)){const o=el('option','',shot.size+'（镜头卡）');o.value=shot.size;target.append(o);}target.value=shot.size;target.dispatchEvent(new Event('change',{bubbles:true}));status('画布已设为 '+shot.size+'。');}));grid.append(card);});host.append(grid);
    const name=el('input');name.placeholder='我的镜头卡名称';name.setAttribute('aria-label','我的镜头卡名称');
    host.append(row(name,button('保存当前构图为卡片',()=>{const content=sections().composition;if(!name.value.trim()||!content.trim())throw Error('请填写卡名，并在主面板准备构图提示词。');if(saved.shots.length>=40)throw Error('本机镜头卡已达 40 张，请先导出整理。');saved.shots.push({id:'custom_'+Date.now(),name:name.value.trim().slice(0,60),sections:{composition:content},ratio:'自定义',scale:.8,x:50,y:48});const ok=persist();render();if(ok)status('镜头卡已保存在当前浏览器。');})));
  }
  function renderCheck(host){
    host.append(note('检查帽子、鞋带、双手占用、脚部裁切、镜头、视线、姿势和光源等 12 条明确规则。未提示不等于全部兼容；修正只在你预览并应用后写入。'));
    const results=el('div','play-grid');
    function inspect(){results.replaceChildren();const issues=C.check(sections());if(!issues.length)results.append(note('当前未命中已知冲突。复杂遮挡、左右归属仍需出图检查。'));issues.forEach(issue=>{const card=el('article','play-card');card.append(note(issue.message),button('编辑建议修改',()=>stage('搭配修正',issue.fix,{mode:'replace'})));results.append(card);});status(`检查完成：发现 ${issues.length} 条提示。`);}
    host.append(row(button('检查当前分区',inspect,'play-primary'),button('载入冲突演示（只预览）',()=>stage('冲突演示：持伞与双手翻书',{pose:'Hold an umbrella in one hand while using both hands to turn the pages of a book.',composition:'Frame the head and shoulders in a close-up.'}))),results);
  }
  function renderSlim(host){
    host.append(note('建立原版、仅去通用质量修饰、仅去完全重复内容三个独立对照；相同版本自动跳过。可选第四个手工核心版本。不会自动删除角色触发词、权重或整句描述。'));
    const core=area('可选：手工核心版本（完整英文正向；留空则不建立第四组）',''),seeds=seedsControl();core.input.placeholder='保留角色 / 服装触发词、动作、构图和光线；这里只用你明确写出的版本。';host.append(core.node,seeds.node);
    host.append(button('冻结当前提示词并建立瘦身对照',()=>withBusy(async()=>{const base=currentBase(),seedList=C.parseSeeds(seeds.input.value),coreText=core.input.value;if(coreText&&/[^\x00-\x7f]/.test(coreText))throw Error('核心正向请使用英文提示词。');const compiled=await compile(base),result=C.slimVariants(compiled.positive,coreText,[...(compiled.triggers||[]),...C.splitPrompt(base.promptSections?.subject||'')]);if(result.variants.length<2)throw Error('未发现可移除的通用质量词或重复内容；请填写核心版本以建立对照。');showPrepared('提示词瘦身',C.buildJobs(base,result.variants,seedList,compiled.negative),`每组固定同样参数与负向。${result.unchanged.length?'自动跳过无变化版本：'+result.unchanged.join('、')+'。':''}只比较本次改动，不自动判定画质胜负。`);}), 'play-primary'));
  }
  function releaseBlind(){for(const x of state.blind?.items||[])if(x.url.startsWith('blob:'))URL.revokeObjectURL(x.url);state.blind=null;}
  function startBlind(items,demo=false){releaseBlind();state.blind={id:'vote_'+Date.now(),items:C.shuffle(items),demo,revealed:false,winner:null,recorded:false};render();status(demo?'当前是构图示意演示，不计入真实图片偏好。':'图片已打乱；选择后才显示文件名。');}
  function renderBlind(host){
    host.append(note('选择 2–4 张本地图片，在浏览器内打乱并隐藏文件名。先选喜欢的，再揭晓和记录原因。真实图片由你挑选；不会替你投票。'));
    const input=el('input');input.type='file';input.multiple=true;input.accept='image/png,image/jpeg,image/webp';input.setAttribute('aria-label','选择盲选图片');
    input.onchange=async()=>{try{const files=[...input.files];if(files.length<2||files.length>4)throw Error('每轮请选择 2–4 张图片。');if(files.some(f=>!/^image\/(png|jpeg|webp)$/.test(f.type)||f.size>30*1024*1024))throw Error('请选择不超过 30 MB 的 PNG、JPG 或 WebP。');const items=files.map((f,i)=>({id:String(i),name:f.name,url:URL.createObjectURL(f)}));startBlind(items);}catch(e){status(e.message,true);}};
    host.append(row(input,button('体验示意图盲选',()=>{const items=D.shots.slice(0,4).map(x=>({id:x.id,name:x.name,url:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(diagram(x))}));startBlind(items,true);})));
    if(state.blind){const roundState=state.blind,grid=el('div','play-blind-grid');
      roundState.items.forEach((item,i)=>{const card=el('article','play-card'),img=el('img');img.src=item.url;img.alt=`候选 ${String.fromCharCode(65+i)}`;img.onerror=()=>status('有图片无法解码，请重新选择有效图片。',true);card.append(img,el('h3','',roundState.revealed?item.name:`候选 ${String.fromCharCode(65+i)}`));if(!roundState.revealed)card.append(button('选这张并揭晓',()=>{roundState.winner=item.id;roundState.revealed=true;render();}));else if(roundState.winner===item.id)card.append(note('你的选择'));grid.append(card);});host.append(grid);
      if(roundState.revealed){const reason=select('你喜欢它的主要原因', [{id:'composition',name:'构图与主体占比'},{id:'lighting',name:'光影'},{id:'line',name:'线条与画风'},{id:'expression',name:'表情与动作'},{id:'detail',name:'角色与服装还原'},{id:'overall',name:'整体感觉'}]);host.append(reason.node);const save=button(roundState.recorded?'本轮已记录':'记录本轮偏好',()=>{if(roundState.recorded)return;const win=roundState.items.find(x=>x.id===roundState.winner);const record={id:roundState.id,createdAt:new Date().toISOString(),demo:roundState.demo,winner:win.name,options:roundState.items.map(x=>x.name),reason:reason.input.value};saved.votes.push(record);saved.votes=saved.votes.slice(-200);roundState.recorded=true;const ok=persist();render();if(ok)status(roundState.demo?'已记录演示结果，与真实偏好统计分开。':'偏好已保存在当前浏览器，可导出 JSON。');});save.disabled=roundState.recorded;host.append(save);}}
    const real=saved.votes.filter(x=>!x.demo);host.append(el('h3','',`真实图片记录 ${real.length} 轮 · 演示 ${saved.votes.length-real.length} 轮`));
    if(real.length){const count={};real.forEach(x=>count[x.reason]=(count[x.reason]||0)+1);host.append(note('已标记的喜欢原因：'+Object.entries(count).map(([k,v])=>`${({composition:'构图',lighting:'光影',line:'画风',expression:'表情动作',detail:'还原',overall:'整体'})[k]||k} ${v} 次`).join('、')));host.append(note('这是你主动标记的原因统计；不同图片会混入多个变量，不能据此断言某参数更好。'));}
  }
  function render(){
    const host=$('playBody');host.replaceChildren();
    document.querySelectorAll('#playTabs button').forEach(n=>{n.classList.toggle('active',n.dataset.tab===state.tab);n.setAttribute('aria-pressed',String(n.dataset.tab===state.tab));});
    ({free:renderFree,career:renderCareers,acting:renderActing,shots:renderShots,check:renderCheck,slim:renderSlim,blind:renderBlind})[state.tab](host);
  }
  function open(){if(!$('creativePlayground'))init();render();$('creativePlayground').showModal();$('creativePlayground').scrollTop=0;if(storageError)status(storageError,true);}
  function init(){
    if($('creativePlayground'))return;
    const anchor=$('userPromptPresetPanel');if(!anchor)return;
    const launch=button('🎲 创作游乐场',open);launch.id='creativePlaygroundOpen';launch.title='职业故事、性格演出、镜头卡、搭配检查、瘦身实验与审美盲选';anchor.before(launch);
    const dialog=el('dialog','creative-playground');dialog.id='creativePlayground';dialog.setAttribute('aria-label','创作游乐场');
    const head=el('header','play-head'),titles=el('div');titles.append(el('span','play-kicker','ANIMA · PLAYGROUND'),el('h2','','自由搭配你的角色画面'),note('保留原设，按分区挑选、修改，再决定如何写入。'));head.append(titles,button('关闭',()=>dialog.close()));
    const nav=el('nav','play-tabs');nav.id='playTabs';nav.setAttribute('aria-label','游乐场玩法');
    for(const [id,name] of Object.entries({free:'自由组合',career:'职业体验',acting:'性格演出',shots:'镜头卡',check:'搭配检查',slim:'提示词瘦身',blind:'审美盲选'})){const b=button(name,()=>{state.tab=id;render();dialog.scrollTop=0;});b.dataset.tab=id;nav.append(b);}
    const body=el('div','play-body');body.id='playBody';const preview=el('section','play-preview');preview.id='playPreview';preview.hidden=true;const prepared=el('section','play-preview');prepared.id='playPrepared';prepared.hidden=true;
    const footer=el('footer','play-footer'),message=el('p','play-status','配方只写入提示词；实验先暂存，再从面板发送队列。');message.id='playStatus';message.setAttribute('role','status');footer.append(message,button('导出镜头卡与偏好记录',()=>download('anima-playground-notes.json',saved)));
    dialog.append(head,nav,body,preview,prepared,footer);document.body.append(dialog);
  }
  g.EasyPanelPlayground={open,init,sections,stage,queueJobs};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})(window);
