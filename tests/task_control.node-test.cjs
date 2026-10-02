const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/assets/js/task-control.js'),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const snapshot=(paused=false)=>({paused,counts:{pending:1,running:0,error:0,cancelled:0,skipped:0},items:[{id:'a',label:'test',status:'pending'}],message:'',runner:{alive:true}});
const response=data=>({ok:true,json:async()=>data});
async function harness(fetch) {
  const ids=['taskQueueServerList','taskQueueServerCounts','taskQueueNotice','taskAutoSkip','taskSelectOnly','taskPauseBtn','taskRunBtn','taskCancelCurrentBtn','taskCancelPendingBtn','taskCleanFailedBtn','taskCleanFinishedBtn','status'];
  const elements=Object.fromEntries(ids.map(id=>[id,{id,textContent:'',value:'',checked:false,disabled:false,writes:0,_html:'',
    get innerHTML(){return this._html},set innerHTML(value){this._html=value;this.writes++},classList:{toggle(){}},addEventListener(){}}]));
  const timers=new Map();let nextTimer=0;
  const context={window:{},document:{readyState:'complete',hidden:false,getElementById:id=>elements[id]},fetch,AbortController,
    setTimeout:(fn,delay)=>{const id=++nextTimer;timers.set(id,{fn,delay});return id},clearTimeout:id=>timers.delete(id),setInterval:()=>1};
  vm.runInNewContext(source,context);await flush();
  return {api:context.window.__taskControl,elements,timers,context};
}

test('identical queue refreshes preserve row elements while the user is touching them',async()=>{
  const page=await harness(async()=>response(snapshot()));
  const writes=page.elements.taskQueueServerList.writes;await page.api.refresh();
  assert.equal(page.elements.taskQueueServerList.writes,writes);
});

test('a late poll cannot overwrite the result of a newer pause action',async()=>{
  let release;let hold=false;
  const page=await harness(async(path,options)=>{
    if(options?.method==='POST')return response(snapshot(true));
    if(hold)await new Promise(resolve=>{release=resolve});
    return response(snapshot());
  });
  hold=true;const poll=page.api.refresh();await page.api.control('pause');release();await poll;
  assert.equal(page.api.state.snapshot.paused,true);assert.equal(page.elements.taskRunBtn.disabled,false);
});

test('duplicate checking cannot silently block a queue pause action',async()=>{
  let posts=0;
  const page=await harness(async(path,options)=>{if(options?.method==='POST')posts++;return response(snapshot(true))});
  page.api.state.busy=true;await page.api.control('pause');assert.equal(posts,1);
});

test('control errors appear inside the expanded task panel',async()=>{
  const page=await harness(async(path,options)=>{if(options?.method==='POST')throw Error('连接断开');return response(snapshot())});
  await page.api.control('pause');assert.match(page.elements.taskQueueNotice.textContent,/连接断开/);
});

test('a timed-out control releases its lock so the next operation can succeed',async()=>{
  let online=false;
  const page=await harness(async(path,options)=>{
    if(options?.method==='POST'&&!online)return new Promise((resolve,reject)=>options.signal?.addEventListener('abort',()=>reject(Object.assign(Error('abort'),{name:'AbortError'})),{once:true}));
    return response(snapshot(true));
  });
  const pending=page.api.control('pause');
  const timer=[...page.timers.values()].find(timer=>timer.delay===10000);assert.ok(timer,'queue controls require a request timeout');
  timer.fn();await pending;assert.equal(page.api.state.controlBusy,false);
  assert.match(page.elements.taskQueueNotice.textContent,/超时/);
  online=true;await page.api.control('pause');assert.equal(page.api.state.snapshot.paused,true);
});

test('a pending control disables its buttons and repeated taps submit only once',async()=>{
  let release;let posts=0;
  const page=await harness(async(path,options)=>{
    if(options?.method==='POST'){posts++;await new Promise(resolve=>{release=resolve});return response(snapshot(true))}
    return response(snapshot());
  });
  const pending=page.api.control('pause');await page.api.control('pause');
  assert.equal(posts,1);assert.equal(page.elements.taskPauseBtn.disabled,true);
  release();await pending;assert.equal(page.elements.taskRunBtn.disabled,false);
});
