const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const C=require('../web/assets/js/creative-playground-core.js');
const D=require('../web/assets/js/creative-playground-data.js');

test('all new recipes have separate ASCII prompt sections and unique IDs',()=>{
  const recipes=[...D.careers,...D.shots,...D.actions.flatMap(a=>D.personalities.map(p=>D.acting(a.id,p.id)))];
  assert.equal(recipes.length,28);assert.equal(new Set(recipes.map(r=>r.id)).size,28);
  for(const r of recipes){for(const value of Object.values(r.sections))assert.match(value,/^[\x00-\x7f]+$/);assert.equal(r.sections.subject,undefined);assert.equal(r.sections.appearance,undefined);}
});
test('all authored recipes pass their own compatibility conditions',()=>{
  for(const r of D.careers)assert.deepEqual(C.check(r.sections),[],r.id);
  for(const a of D.actions)for(const p of D.personalities)assert.deepEqual(C.check(D.acting(a.id,p.id).sections),[]);
});
test('acting recipes hold scene, camera and light constant',()=>{
  for(const a of D.actions){const s=D.personalities.map(p=>D.acting(a.id,p.id).sections);for(const key of ['scene','composition','lighting'])assert.equal(new Set(s.map(x=>x[key])).size,1);assert.equal(new Set(s.map(x=>x.pose)).size,4);assert.equal(new Set(s.map(x=>x.expression)).size,4);}
});
test('tokenizer preserves weights, LoRA calls and bracketed schedules',()=>{
  assert.deepEqual(C.splitPrompt('1girl, (red hair, blue eyes:1.2), <lora:a,b:1>, [a,b:c:0.5]\nhello'),['1girl','(red hair, blue eyes:1.2)','<lora:a,b:1>','[a,b:c:0.5]','hello']);
});
test('quality ablation preserves scores, names, weights and descriptive sentences',()=>{
  assert.equal(C.withoutQuality('masterpiece, score_9, ArtistTrigger, (best quality:1.1), Paint a masterpiece on the wall.'),'score_9, ArtistTrigger, (best quality:1.1), Paint a masterpiece on the wall.');
});
test('quality-looking identity and known LoRA triggers remain protected',()=>{
  assert.equal(C.withoutQuality('masterpiece, best quality, smile',['masterpiece']),'masterpiece, smile');
  assert.equal(C.slimVariants('masterpiece, smile','',['masterpiece']).variants.length,1);
});
test('dedupe preserves intentional BREAK and repeated LoRA references',()=>{
  assert.equal(C.deduplicate('smile, Smile, BREAK, BREAK, <lora:x:1>, <lora:x:1>'),'smile, BREAK, BREAK, <lora:x:1>, <lora:x:1>');
});
test('independent ablations do not accidentally combine two variables',()=>{
  const r=C.slimVariants('masterpiece, smile, smile');
  assert.equal(r.variants[1].positive,'smile, smile');assert.equal(r.variants[2].positive,'masterpiece, smile');
});
test('no-op variants and duplicate seeds are skipped',()=>{
  assert.equal(C.slimVariants('solo, smile').variants.length,1);
  assert.deepEqual(C.parseSeeds('0,42,42'),[0,42]);
});
test('seed input rejects random negative floats huge values and excessive runs',()=>{
  for(const s of ['','-1','random','2.5','4294967296','1,2,3,4,5','Infinity'])assert.throws(()=>C.parseSeeds(s));
});
test('build jobs freezes all settings and negative while varying only positive and paired seeds',()=>{
  const b={model:'anima.safetensors',seed:'-1',loras:[{name:'a',weight:.7}],width:1152,height:1536,hiresDenoise:.25,promptSections:{subject:'A'},sampler:'er_sde',cfg:4.5};
  const original=C.clone(b),jobs=C.buildJobs(b,[{id:'a',name:'A',positive:'one'},{id:'b',name:'B',positive:'two'}],[11,12],'bad');
  assert.deepEqual(b,original);assert.equal(jobs.length,4);assert.deepEqual(jobs.map(x=>x.seed),['11','11','12','12']);
  for(const j of jobs){assert.deepEqual(j.loras,b.loras);assert.equal(j.cfg,b.cfg);assert.equal(j.hiresDenoise,b.hiresDenoise);assert.equal(j.promptOverride.negative,'bad');assert.equal(j.batchCount,1);assert.equal(j.promptOverride.enabled,true);}
  jobs[0].loras[0].weight=9;assert.equal(jobs[1].loras[0].weight,.7);assert.equal(b.loras[0].weight,.7);
});
test('job creation fails with missing model or invalid seed',()=>{
  assert.throws(()=>C.buildJobs({},[{positive:'x'}],[1],''));assert.throws(()=>C.buildJobs({model:'a'},[{positive:'x'}],[-1],''));
});
test('queue capacity check is all-or-nothing and respects image limits',()=>{
  assert.throws(()=>C.queueCapacity(Array(49).fill({}),[{},{}]));
  assert.throws(()=>C.queueCapacity(Array(13).fill({batchCount:16}),[{}]));
  assert.equal(C.queueCapacity(Array(49).fill({}),[{}]),true);
});
test('lock-aware preview only modifies requested unlocked fields',()=>{
  const b={subject:'my character',clothing:'uniform',pose:'standing'},r=C.planChanges(b,{clothing:'apron',pose:'sitting'},['clothing']);
  assert.deepEqual(r.skipped,['clothing']);assert.deepEqual(r.changes,[{key:'pose',before:'standing',after:'sitting'}]);assert.equal(b.pose,'standing');
});
test('free drafts preserve scene clothing lighting and identity unless individually selected',()=>{
  const before={subject:'original',clothing:'coat',scene:'street',lighting:'sunlight',pose:'standing'};
  const draft={subject:{mode:'keep',text:'other'},clothing:{mode:'keep',text:'apron'},scene:{mode:'keep',text:'cafe'},lighting:{mode:'keep',text:'window'},pose:{mode:'append',text:'waving'}};
  const result=C.composeDraft(before,draft);
  assert.deepEqual(result.changes,[{key:'pose',before:'standing',after:'standing, waving',mode:'append'}]);
  assert.deepEqual(before,{subject:'original',clothing:'coat',scene:'street',lighting:'sunlight',pose:'standing'});
});
test('free drafts support mixed append replace keep and an explicit empty replacement',()=>{
  const plan=C.composeDraft({pose:'running',expression:'smile',scene:'forest',manual:'old'},
    {pose:{mode:'replace',text:'sitting'},expression:{mode:'append',text:'blush'},scene:{mode:'keep',text:'cafe'},manual:{mode:'replace',text:''}});
  assert.deepEqual(plan.changes.map(x=>[x.key,x.after]),[['pose','sitting'],['expression','smile, blush'],['manual','']]);
});
test('free draft append to empty fields and lock protection',()=>{
  const plan=C.composeDraft({}, {pose:{mode:'append',text:'walking'},clothing:{mode:'replace',text:'apron'}},['clothing']);
  assert.equal(plan.changes[0].after,'walking');assert.deepEqual(plan.skipped,['clothing']);
  assert.throws(()=>C.composeDraft({}, {pose:{mode:'oops',text:'x'}}));
});
test('personal preset append action passes false even if its saved mode is replace',()=>{
  const root=path.join(__dirname,'..');
  for(const dir of [root,path.join(root,'installers/payload')]){
    const src=fs.readFileSync(path.join(dir,'web/assets/js/panel.js'),'utf8');
    assert.ok(src.includes('onclick="applyUserPromptPreset(\'${item.id}\',false)">追加</button>'));
    assert.ok(!src.includes('onclick="applyUserPromptPreset(\'${item.id}\')">追加</button>'));
  }
});
const cases=[
  ['hat',{pose:'Press one hand against the brim of a hat.',clothing:'shirt'}],
  ['laces',{pose:'Tie the shoelaces.',clothing:'loafers'}],
  ['hands',{pose:'Hold an umbrella while using both hands to turn a book page.'}],
  ['feet-crop',{pose:'Tie the shoelaces.',composition:'head and shoulders'}],
  ['framing',{composition:'close-up, full body'}],
  ['camera',{composition:'from above, from below'}],
  ['eyes',{expression:'closed eyes, looking at viewer'}],
  ['body',{pose:'running, sitting'}],
  ['window',{lighting:'Use window light.',scene:'mountain summit'}],
  ['aquarium',{lighting:'Blue aquarium light.',scene:'forest'}],
  ['lantern',{lighting:'Warm lantern light.',scene:'field'}],
  ['detail',{composition:'wide view',manual:'individual eyelashes'}],
];
for(const [id,s] of cases)test('compatibility rule: '+id,()=>assert.ok(C.check(s).some(x=>x.id===id)));
test('compatible hat, shoes and window scenes do not warn',()=>{
  assert.deepEqual(C.check({pose:'Press a hat brim.',clothing:'Wear a brimmed hat.'}),[]);
  assert.deepEqual(C.check({pose:'Tie shoelaces.',clothing:'lace-up boots'}),[]);
  assert.deepEqual(C.check({lighting:'window light',scene:'cafe window'}),[]);
});
test('compatible random respects locks and returns no option if all conflict',()=>{
  const candidates=[{id:'bad',sections:{pose:'running, sitting'}},{id:'ok',sections:{pose:'standing'}}];
  assert.equal(C.chooseCompatible(candidates,{},[],()=>0).id,'ok');
  assert.equal(C.chooseCompatible(candidates,{pose:'running, sitting'},['pose'],()=>0),null);
});
test('shuffle does not mutate input or drop images',()=>{
  const input=['a','b','c','d'],out=C.shuffle(input,()=>0);assert.deepEqual(input,['a','b','c','d']);assert.deepEqual([...out].sort(),input);assert.notDeepEqual(out,input);
});
test('runtime and installer new assets and entry references are synchronized',()=>{
  const root=path.join(__dirname,'..');for(const file of ['js/creative-playground-data.js','js/creative-playground-core.js','js/creative-playground.js','css/creative-playground.css'])assert.equal(fs.readFileSync(path.join(root,'web/assets',file),'utf8'),fs.readFileSync(path.join(root,'installers/payload/web/assets',file),'utf8'));
  for(const dir of [root,path.join(root,'installers/payload')]){const html=fs.readFileSync(path.join(dir,'index.html'),'utf8');for(const file of ['creative-playground.js','creative-playground-data.js','creative-playground-core.js','creative-playground.css'])assert.equal(html.split(file).length-1,1);}
});
