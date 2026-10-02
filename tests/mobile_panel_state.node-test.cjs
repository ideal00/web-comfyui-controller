const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/assets/js/panel.js'),'utf8');
const line=name=>source.split('\n').find(text=>text.startsWith(`function ${name}(`))||'';
function mobileHarness(saved,ready=true) {
  const values=new Map();if(saved)values.set('easyPanelMobilePersistV1',JSON.stringify(saved));
  const fields={batchCount:{value:'16'},model:{value:'model',options:ready?[{value:'model'}]:[]},loras:{innerHTML:'',children:[]}};
  const intervals=[];
  const context=vm.createContext({window:{},location:{search:'?mobile=1'},$:id=>fields[id],
    localStorage:{getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value)},
    payload:()=>({model:'model',promptSections:{pose:'standing'}}),allLoraState:()=>[],selectedLoraPayload:()=>[],collectPromptSections:()=>({pose:'standing'}),
    addLora(){},setAppliedOutfits(){},reconcileAppliedOutfitsAfterRestore(){},syncMemoOutfitModeControl(){},saveLoraState(){},promptEditorChanged(){},
    document:{querySelectorAll:()=>[]},setInterval:fn=>{intervals.push(fn);return 1},clearInterval(){}});
  vm.runInContext(`let jobQueue=[],appliedOutfits=[],currentLoraName='',memoOutfitOverwriteMode=true,mobilePanelReady=false,mobilePanelRestoring=false;
    const MAX_LOGICAL_JOBS=10,MOBILE_PANEL_STATE_KEY='easyPanelMobilePersistV1';
    ${line('normalizeGenerationCount')}
    ${line('generationCount')}
    ${line('mobilePanelMode')}
    ${line('mobilePanelSnapshot')}
    ${line('saveMobilePanelState')}
    ${source.slice(source.indexOf('function restoreMobilePanelState('),source.indexOf('function startMobilePanelKeep('))}
    function restorePayloadToPanel(){}`,context);
  return {fields,context,intervals,values,run:script=>vm.runInContext(script,context)};
}

test('mobile snapshots keep the selected generation count apart from queued jobs',()=>{
  const page=mobileHarness();page.fields.batchCount.value='3';
  page.run('jobQueue=[{batchCount:16}];mobilePanelReady=true;saveMobilePanelState()');
  const saved=JSON.parse(page.values.get('easyPanelMobilePersistV1'));
  assert.equal(saved.generationCount,3);assert.equal(saved.jobQueue[0].batchCount,16);
  page.fields.batchCount.value='16';page.run('restoreMobilePanelState()');
  assert.equal(page.fields.batchCount.value,'3');
});

test('old mobile snapshots without a generation count restore one image before models finish loading',()=>{
  const page=mobileHarness({payload:{model:'model'}},false);
  page.run('restoreMobilePanelState()');
  assert.equal(page.fields.batchCount.value,'1');
});

test('a deliberately selected sixteen is preserved, while corrupt counts never become the maximum',()=>{
  for(const value of [16,2,0,17,999999,'bad',3.5]){
    const page=mobileHarness({payload:{model:'model'},generationCount:value});page.run('restoreMobilePanelState()');
    assert.equal(page.fields.batchCount.value,Number.isInteger(value)&&value>=1&&value<=16?String(value):'1');
  }
});

test('partial mobile forms still save the count without rewriting an input being edited',()=>{
  const page=mobileHarness();page.context.payload=()=>{throw Error('catalog loading')};
  page.fields.batchCount.value='4';
  assert.equal(JSON.parse(page.run('mobilePanelSnapshot()')).generationCount,4);
  page.fields.batchCount.value='';
  assert.equal(JSON.parse(page.run('mobilePanelSnapshot()')).generationCount,1);
  assert.equal(page.fields.batchCount.value,'');
});
