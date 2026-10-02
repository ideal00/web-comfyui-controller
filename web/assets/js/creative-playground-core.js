(function (root) {
  'use strict';
  const clone = x => JSON.parse(JSON.stringify(x));
  function splitPrompt(text) {
    const parts = []; let buffer = '', round = 0, square = 0, angle = 0;
    for (const c of String(text || '')) {
      if (c === '(') round++; if (c === ')') round = Math.max(0,round-1);
      if (c === '[') square++; if (c === ']') square = Math.max(0,square-1);
      if (c === '<') angle++; if (c === '>') angle = Math.max(0,angle-1);
      if ((c === ',' || c === '\n') && !round && !square && !angle) {
        if (buffer.trim()) parts.push(buffer.trim()); buffer = '';
      } else buffer += c;
    }
    if (buffer.trim()) parts.push(buffer.trim());
    return parts;
  }
  const quality = new Set(['masterpiece','best quality','very aesthetic','highres','absurdres','amazing quality','great quality']);
  function withoutQuality(text, protectedTerms = []) {
    const protectedKeys=new Set(protectedTerms.map(x=>String(x).trim().toLowerCase()));
    return splitPrompt(text).filter(x=>protectedKeys.has(x.toLowerCase())||!quality.has(x.toLowerCase())).join(', ');
  }
  function deduplicate(text) {
    const seen = new Set();
    return splitPrompt(text).filter(x=>{
      // LoRA calls and structural separators may be intentionally repeated.
      if (/^(?:<|embedding:|BREAK$|AND$)/i.test(x)) return true;
      const key = x.toLowerCase().replace(/\s+/g,' ');
      if (seen.has(key)) return false; seen.add(key); return true;
    }).join(', ');
  }
  function slimVariants(positive, core, protectedTerms = []) {
    if (!String(positive||'').trim()) throw Error('最终正向为空，请先填写提示词。');
    const candidates = [
      {id:'baseline',name:'原版',positive},
      {id:'quality',name:'仅去通用质量修饰',positive:withoutQuality(positive,protectedTerms)},
      {id:'duplicates',name:'仅去完全重复内容',positive:deduplicate(positive)},
      ...(String(core||'').trim() ? [{id:'core',name:'手工核心版本',positive:core.trim()}] : [])
    ];
    const normalize = s=>splitPrompt(s).join(', ');
    const seen = new Set(); const variants = [], unchanged = [];
    for (const item of candidates) {
      const key = normalize(item.positive);
      if (seen.has(key)) unchanged.push(item.name);
      else {seen.add(key); variants.push(item);}
    }
    return {variants,unchanged};
  }
  function parseSeeds(raw) {
    const values = String(raw||'').trim().split(/[\s,，]+/).filter(Boolean);
    if (!values.length || values.length > 4) throw Error('请输入 1–4 个固定种子。');
    if (values.some(x=>!/^\d+$/.test(x) || !Number.isSafeInteger(Number(x)) || Number(x)>4294967295)) throw Error('种子必须是 0–4294967295 的整数。');
    return [...new Set(values.map(Number))];
  }
  function buildJobs(base, variants, seeds, negative, mode = 'prompt-ablation', runId = String(Date.now())) {
    if (!base?.model) throw Error('请先选择模型。');
    if (!variants.length || !seeds.length || variants.length * seeds.length > 32) throw Error('实验数量无效或超过 32 个任务。');
    return seeds.flatMap(seed=>variants.map(variant=>{
      if (!Number.isInteger(seed) || seed < 0 || seed > 4294967295) throw Error('实验必须使用固定整数种子。');
      if (!variant.positive?.trim()) throw Error('实验提示词不能为空。');
      const job = clone(base);
      job.seed = String(seed); job.batchCount = 1;
      if (variant.sections) job.promptSections = clone(variant.sections);
      job.promptOverride = {enabled:true,positive:variant.positive,negative};
      job.experiment = {strict:true,mode,label:`游乐场 ${variant.name} · seed ${seed}`,variable:'positive',value:variant.id,runId};
      return job;
    }));
  }
  function check(s) {
    const t = key=>String(s[key]||'').toLowerCase().replace(/_/g,' ');
    const pose = t('pose'), comp = t('composition'), clothes=t('clothing'), scene=t('scene'), light=t('lighting');
    const action = pose+' '+t('manual')+' '+t('naturalLanguage');
    const face = t('expression')+' '+pose;
    const issues = [];
    const add = (id,message,fix)=>issues.push({id,message,fix});
    const full = {composition:'Frame the entire subject with both hands and feet visible and a clear margin around the body.'};
    if (/hat brim|brim of a hat|press.*brim/.test(action) && !/\b(hat|cap|beret|bonnet)\b/.test(clothes)) add('hat','按帽檐需要帽子；服装分区尚未发现帽子。',{clothing:(s.clothing||'')+' Wear a simple brimmed hat.'});
    if (/shoelace|shoe lace|tie.*shoes/.test(action) && !/lace-up|sneakers|running shoes|shoelaces/.test(clothes)) add('laces','系鞋带需要带鞋带的鞋；请检查当前鞋款。',{clothing:(s.clothing||'')+' Wear lace-up walking shoes.'});
    if (/umbrella/.test(action) && /both hands|one hand[\s\S]*other hand|one forearm[\s\S]*opposite hand/.test(action) && /book|cup|bouquet/.test(action)) add('hands','持伞与双手操作道具可能争用手；可换成单手抱书。',{pose:'Hold an umbrella handle with one hand. Cradle one closed book against the torso with the opposite forearm.'});
    const tight = /close.up|portrait|head and shoulders|head to the hips|head to.*waist|waist.up/.test(comp);
    if (tight && /shoelace|shoes|leading foot|trailing heel|feet|ankles|legs/.test(pose)) add('feet-crop','当前近景看不到脚部动作；建议改全身构图。',full);
    if (/close.up|head and shoulders/.test(comp) && /full body|entire subject|whole figure/.test(comp)) add('framing','构图同时要求近景和全身。',full);
    if (/from above|top.down|elevated/.test(comp) && /from below|low.angle|upward/.test(comp)) add('camera','构图同时要求俯视和仰视；请选择一种。',{composition:'Use an eye-level three-quarter camera angle with the whole figure visible.'});
    if (/closed eyes|eyes closed/.test(face) && /looking at viewer|meet.*gaze|eyes.*viewer/.test(face)) add('eyes','闭眼与看向观众冲突。',{expression:'Keep the eyes open and direct the gaze toward the viewer with a small relaxed smile.'});
    if (/\brunning\b/.test(pose) && /\bsitting\b|\bkneeling\b|\bcrouching\b/.test(pose)) add('body','跑动与坐、跪或蹲姿同时出现。',{pose:'Run with a short forward stride and bent elbows while the trailing heel lifts.'});
    if (/window light|through.*window|nearby window/.test(light) && !/window|classroom|cafe|room|train|house|studio|library/.test(scene)) add('window','光线要求窗户，但场景分区未提供窗户；可改天光。',{lighting:'Use diffuse open-sky daylight with faint ground bounce on the shaded cheek.'});
    if (/aquarium/.test(light) && !/aquarium/.test(scene)) add('aquarium','水族箱光缺少对应场景。',{scene:'Use an aquarium gallery with a large viewing window beside the subject.'});
    if (/lantern/.test(light) && !/lantern/.test(scene+' '+action)) add('lantern','提灯光线缺少灯；可改为一般柔光。',{lighting:'Use a broad warm light from the front left with faint neutral fill.'});
    if (/wide|distant|one third/.test(comp) && /pores|individual eyelashes|iris details/.test(t('manual')+' '+t('appearance'))) add('detail','远景中的面部微细节可能无法辨认；可另拍特写。',{composition:'Frame the head and shoulders at eye level with the face in sharp focus.'});
    return issues;
  }
  function shuffle(items, random = Math.random) {
    const result = [...items];
    for (let i=result.length-1;i>0;i--) {const j=Math.floor(random()*(i+1)); [result[i],result[j]]=[result[j],result[i]];}
    return result;
  }
  function chooseCompatible(recipes, base, locked = [], random = Math.random) {
    const options = recipes.filter(recipe=>!check({...base,...Object.fromEntries(Object.entries(recipe.sections).filter(([key])=>!locked.includes(key)))}).length);
    return options.length ? options[Math.floor(random()*options.length)] : null;
  }
  function planChanges(before, proposed, locked = []) {
    const changes = [], skipped = [];
    for (const [key,value] of Object.entries(proposed)) {
      if (locked.includes(key)) {if ((before[key]||'')!==value) skipped.push(key); continue;}
      if ((before[key]||'')!==value) changes.push({key,before:before[key]||'',after:value});
    }
    return {changes,skipped};
  }
  function composeDraft(before, draft, locked = []) {
    const changes=[],skipped=[];
    for(const [key,item] of Object.entries(draft)) {
      if(!item || item.mode==='keep') continue;
      if(!['append','replace'].includes(item.mode)) throw Error('未知的分区应用方式。');
      if(locked.includes(key)){skipped.push(key);continue;}
      const old=String(before[key]||''),value=String(item.text||'').trim();
      const after=item.mode==='replace'?value:(!value?old:!old.trim()?value:old.trim()+', '+value);
      if(after!==old)changes.push({key,before:old,after,mode:item.mode});
    }
    return {changes,skipped};
  }
  function queueCapacity(queue, jobs) {
    if (queue.length + jobs.length > 50) throw Error('暂存队列最多 50 个任务，请先处理现有队列。');
    const images = [...queue,...jobs].reduce((n,j)=>n+Math.max(1,Math.min(16,parseInt(j.batchCount,10)||1)),0);
    if (images > 200) throw Error('暂存队列最多 200 张图片。');
    return true;
  }
  const core = {clone,splitPrompt,withoutQuality,deduplicate,slimVariants,parseSeeds,buildJobs,check,shuffle,chooseCompatible,planChanges,composeDraft,queueCapacity};
  if (typeof module !== 'undefined' && module.exports) module.exports = core;
  else root.EasyPanelPlaygroundCore = core;
})(typeof window !== 'undefined' ? window : globalThis);
