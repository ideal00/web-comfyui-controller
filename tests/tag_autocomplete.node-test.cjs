const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const vm = require('node:vm');
const autocomplete = require(path.join(__dirname, '../web/assets/js/tag-autocomplete.js'));

test('query uses the tag beside the caret and avoids replacing a partial suffix', () => {
  assert.equal(autocomplete.queryAtCursor({value:'white shirt, bla',selectionStart:16,selectionEnd:16}), 'bla');
  assert.equal(autocomplete.queryAtCursor({value:'white shirt, bla, smile',selectionStart:16,selectionEnd:16}), 'bla');
  assert.equal(autocomplete.queryAtCursor({value:'white shirt, blaCK',selectionStart:16,selectionEnd:16}), '');
  assert.equal(autocomplete.queryAtCursor({value:'standing, 腿',selectionStart:11,selectionEnd:11}), '腿');
  assert.equal(autocomplete.searchable('腿'), true);
  assert.equal(autocomplete.searchable('a'), false);
  assert.equal(autocomplete.tagAtCursor({value:'standing, (blue hair:1.2), smile',selectionStart:19}), 'blue hair');
});

test('single Chinese character searches both indexes, features local images, and caches the result', async () => {
  let calls = 0;
  global.fetch = async url => {
    calls++;
    if (url.startsWith('/api/visual-tags?')) return {ok:true,json:async () => ({results:[{tag:'crossed_legs',name_zh:'交叉双腿',category:'姿势',id:'local-1',image_status:'ready'}]})};
    assert.match(url, /\/api\/tags\?q=%E8%85%BF/);
    return {ok:true,json:async () => ({tags:[{tag:'crossed legs',translation:'交叉腿',count:10,category:'通用'},{tag:'thighs',translation:'大腿',count:20,category:'通用'}]})};
  };
  const first = await autocomplete.search('腿');
  const second = await autocomplete.search('腿');
  assert.equal(first[0].tag, 'crossed_legs');
  assert.equal(first[0].imageId, 'local-1');
  assert.equal(first[0].count, 10);
  assert.equal(first[1].tag, 'thighs');
  assert.strictEqual(first, second);
  assert.equal(calls, 2);
});

test('selected tags pass through color modifier and current prompt dialect', () => {
  global.EasyPanelColorModifier = {compose: tag => 'dark_' + tag};
  global.EasyPanelDialect = {formatTag: tag => tag.replace(/_/g,' ')};
  assert.equal(autocomplete.formatTag({tag:'blue hair',category:'通用'}), 'dark blue hair');
  delete global.EasyPanelColorModifier;
  delete global.EasyPanelDialect;
});

test('candidate toolbar exposes the current color modifier choice', () => {
  global.EasyPanelColorModifier = {MODIFIERS:[{key:'dark',label:'深 dark'}],current:() => 'dark'};
  const markup = autocomplete.colorChoiceMarkup();
  assert.match(markup, /data-autocomplete-color/);
  assert.match(markup, /value="dark" selected/);
  delete global.EasyPanelColorModifier;
});

test('weighted and dialect variants count as the same existing tag', () => {
  const terms = autocomplete.currentTerms({value:'(blue hair:1.2), (blue_hair:0.8), @artist name, red_eyes'});
  assert.equal(terms.has(autocomplete.baseTag('blue_hair')), true);
  assert.equal(terms.has(autocomplete.baseTag('blue hair')), true);
  assert.equal(terms.has(autocomplete.baseTag('artist_name')), true);
  assert.equal(terms.has(autocomplete.baseTag('red eyes')), true);
  assert.equal(terms.has(autocomplete.baseTag('green eyes')), false);
});

test('broad query retains dozens of local and dictionary candidates for scrolling', async () => {
  global.fetch = async url => url.startsWith('/api/visual-tags?')
    ? {ok:true,json:async () => ({matched:246,results:Array.from({length:80},(_,i) => ({tag:`local_${i}`,name_zh:`本地${i}`,id:`id-${i}`,image_status:'ready'}))})}
    : {ok:true,json:async () => ({tags:Array.from({length:120},(_,i) => ({tag:`global ${i}`,translation:`通用${i}`,count:120-i}))})};
  const items = await autocomplete.search('手');
  assert.equal(items.length, 180);
  assert.equal(items[0].source, 'local');
  assert.equal(items[0].localMatched, 246);
  assert.equal(items[59].source, 'local');
  assert.equal(items[60].source, 'index');
  assert.equal(items[179].tag, 'global 119');
});

test('dictionary candidates retain local images beyond the first sixty featured tags', () => {
  const local = Array.from({length:70},(_,i) => ({tag:`local_${i}`,id:`image-${i}`,image_status:'ready'}));
  const items = autocomplete.mergeResults(local,[{tag:'local_65',count:10},{tag:'remote_tag',count:5}],70);
  assert.equal(items[60].tag, 'local_65');
  assert.equal(items[60].imageId, 'image-65');
  assert.equal(items[60].source, 'local');
  assert.equal(items[61].source, 'index');
});

test('weak local keyword hits leave room for exact dictionary tags', () => {
  const local = Array.from({length:80},(_,i) => ({tag:`local_${i}`,score:11,id:`image-${i}`,image_status:'ready'}));
  const items = autocomplete.mergeResults(local,[{tag:'blue_hair',count:100}],80);
  assert.equal(items[8].tag, 'blue_hair');
});

test('mouse activation leaves scroll position alone; arrow navigation reveals hidden rows', () => {
  const viewport = {top:100,bottom:300};
  const dropdown = {
    activeItem:null, scrollTop:0,
    getActiveItem() { return this.activeItem; },
    el:{getBoundingClientRect:() => viewport,querySelector:() => null,get scrollTop(){return dropdown.scrollTop;},set scrollTop(value){dropdown.scrollTop=value;}}
  };
  const item = {dropdown,active:false,activeClassName:'active',el:{className:'',getBoundingClientRect:() => ({top:330,bottom:360})}};
  assert.equal(autocomplete.activateWithoutScroll(item), item);
  assert.equal(dropdown.scrollTop, 0);
  assert.equal(dropdown.activeItem, item);
  autocomplete.keepActiveVisible(dropdown, item);
  assert.equal(dropdown.scrollTop, 60);
});

function completionHarness(fetch, options={}) {
  const listeners = new Map(), instances = [],positionHandlers=new Map(),windowListeners=new Map(),dropdownListeners=new Map(),completionHandlers=new Map(),nodes=new Map();
  const field = {id:'promptPose',value:'',selectionStart:0,selectionEnd:0,dataset:{},
    addEventListener(type,listener) { listeners.set(type,listener); },
    removeEventListener(type,listener) { if(listeners.get(type)===listener)listeners.delete(type); },
    getBoundingClientRect(){return options.fieldRect || {top:100,bottom:134,left:10};},
    closest(selector) { return selector==='.easy-chip-picker' ? options.picker || null : null; }};
  class Textcomplete {
    static editors = {Textarea:class {constructor(el){this.el=el;} getCursorOffset(){return {top:120,left:10};}}};
    constructor(editor) {
      this.editor=editor; this.isQueryInFlight=false; this.nextPendingQuery=null; this.hits=[];
      const handlers=new Map();
      this.dropdown={shown:false,items:[],selected:[],on(type,fn){const list=handlers.get(type)||[];list.push(fn);handlers.set(type,list);positionHandlers.set(type,(...args)=>list.forEach(handler=>handler(...args)));},getActiveItem(){return null;},
        select:item=>{this.dropdown.selected.push(item);let prevented=false;completionHandlers.get('select')?.({detail:{searchResult:item.searchResult},preventDefault(){prevented=true;}});if(!prevented)field.value=item.searchResult.data.tag+', ';},
        el:{scrollTop:0,scrollHeight:220,style:{},addEventListener(type,fn,options){const list=dropdownListeners.get(type)||[];list.push({fn,capture:options===true});dropdownListeners.set(type,list);},querySelector(){return null;},getBoundingClientRect(){return {width:300,left:10,right:310,top:140};}}};
      instances.push(this);
    }
    register(strategies) { this.strategy=strategies[0]; }
    on(type,fn) { completionHandlers.set(type,fn); }
    hide() { this.dropdown.shown=false; }
    // Textcomplete 0.18.2 drains its latest pending query only when search calls back.
    trigger(text) {
      if(this.isQueryInFlight) { this.nextPendingQuery=text; return; }
      this.isQueryInFlight=true;this.nextPendingQuery=null;
      const hit = items => {
        this.hits.push(items);this.dropdown.items=items;this.dropdown.shown=items.length>0;
        this.isQueryInFlight=false;
        if(this.nextPendingQuery!==null)this.trigger(this.nextPendingQuery);
      };
      const match=text.match(this.strategy.match);
      if(match)this.strategy.search(match[2],hit);else hit([]);
    }
  }
  const context={window:{Textcomplete,visualViewport:options.visualViewport},fetch,setTimeout,clearTimeout,URLSearchParams,AbortController,
    innerWidth:390,innerHeight:844,scrollX:0,scrollY:0,
    matchMedia:()=>({matches:false}),
    document:{readyState:'loading',getElementById:id=>id===field.id?field:nodes.get(id)||null,
      createElement(){return {style:{},dataset:{},isConnected:true,append(){},replaceChildren(){},remove(){nodes.delete(this.id);this.isConnected=false;}};},
      body:{append(node){if(node.id)nodes.set(node.id,node);}},documentElement:{classList:{contains(){return false;}}},
      querySelector(){return null;},addEventListener(){}},addEventListener(){}};
  context.window.addEventListener=(type,fn)=>windowListeners.set(type,fn);
  context.window.removeEventListener=(type,fn)=>{if(windowListeners.get(type)===fn)windowListeners.delete(type);};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/assets/js/tag-autocomplete.js'),'utf8'),context);
  context.window.EasyPanelTagAutocomplete.init();
  return {field,completion:instances[0],listeners,positionHandlers,windowListeners,dropdownListeners,completionHandlers,nodes,api:context.window.EasyPanelTagAutocomplete,context,
    input(text){field.value=text;field.selectionStart=field.selectionEnd=text.length;instances[0].trigger(text);}};
}
const flush = () => new Promise(resolve=>setImmediate(resolve));

test('changing text during a request releases the pending search instead of freezing all later input',async()=>{
  let release;
  const gate=new Promise(resolve=>{release=resolve;});
  const queried=[];
  const {input,completion}=completionHarness(async url=>{
    const term=new URL(url,'http://local').searchParams.get('q');queried.push(term);
    if(term==='ha')await gate;
    return {ok:true,json:async()=>url.startsWith('/api/tags?')?{tags:[{tag:term}]}:{results:[]}};
  });
  input('ha');input('hair');release();
  for(let i=0;i<6;i++)await flush();
  assert.equal(completion.isQueryInFlight,false);
  assert.equal(completion.dropdown.items[0].tag,'hair');
  assert.equal(completion.hits.filter(items=>items.length).length,1,'stale results must never render');
  assert.ok(queried.includes('hair'));
  input('瘦');for(let i=0;i<6;i++)await flush();
  assert.equal(completion.dropdown.items[0].tag,'瘦');
});

function touchHarness(data) {
  const harness=completionHarness(async()=>({ok:true,json:async()=>({})}));
  const timers=new Map();let timerId=0;
  harness.context.setTimeout=(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;};
  harness.context.clearTimeout=id=>timers.delete(id);
  harness.context.window.EasyPanelPresetExamples={url:image=>image?'local-example.png':null};
  const row={className:'',removeEventListener(){}};
  const target={closest:selector=>selector==='.textcomplete-item'?row:null};
  const item={el:row,searchResult:{data},activate(){return this;}};
  harness.completion.dropdown.items=[item];harness.completion.dropdown.shown=true;
  harness.context.document.elementFromPoint=()=>target;
  return {...harness,item,target,timers,
    event(type,{x=30,y=180,target:eventTarget=target,multi=false}={}){
      const event={target:eventTarget,touches:multi?[{clientX:x,clientY:y},{clientX:x+1,clientY:y}]:[{clientX:x,clientY:y}],changedTouches:[{clientX:x,clientY:y}],prevented:false,stopped:false,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};
      for(const {fn} of (harness.dropdownListeners.get(type)||[]).slice().sort((a,b)=>Number(b.capture)-Number(a.capture))){fn(event);if(event.stopped)break;}
      return event;
    }};
}

for(const exampleImage of ['example-1',''])test(`one touch fills a preset ${exampleImage?'with':'without'} an example image`,()=>{
  const data={source:'preset',id:'preset-1',tag:'测试坐姿',name:'测试坐姿',text:'sitting',exampleImage,range:{before:'坐',start:0,end:1}};
  const harness=touchHarness(data);const applied=[];
  harness.context.window.EasyPanelPresetSearch={apply(...args){applied.push(args);return true;}};
  harness.event('touchstart');harness.event('touchend');
  assert.equal(harness.completion.dropdown.selected.length,1,'a first tap must insert, without waiting for a preview');
  assert.equal(applied.length,1);assert.equal(applied[0][0],data);assert.equal(applied[0][1],'promptPose');
  assert.equal(harness.nodes.has('easyTagPreview'),false);
  const mouse=harness.event('mousedown');assert.equal(mouse.prevented,true,'synthetic mouse must not insert a second time');
});

test('one touch inserts a dictionary tag even when no preview image exists',()=>{
  const harness=touchHarness({source:'index',tag:'sitting'});
  harness.event('touchstart');harness.event('touchend');
  assert.equal(harness.field.value,'sitting, ');
  assert.equal(harness.completion.dropdown.selected.length,1);
});

test('scrolling, cancelled and multiple touches never insert candidates or open a preview',()=>{
  const harness=touchHarness({source:'preset',id:'preset-1',tag:'测试坐姿'});
  harness.event('touchstart');harness.event('touchmove',{y:240});harness.event('touchend',{y:240});
  harness.event('touchstart');harness.event('touchcancel');harness.event('touchend');
  harness.event('touchstart',{multi:true});harness.event('touchend');
  harness.event('touchstart');harness.event('touchmove',{multi:true});harness.event('touchend');
  assert.equal(harness.completion.dropdown.selected.length,0);
  assert.equal(harness.nodes.size,0);assert.equal(harness.timers.size,0);
});

test('long press previews once without insertion, and a following tap still inserts',()=>{
  const harness=touchHarness({source:'preset',id:'preset-1',tag:'测试坐姿',exampleImage:'example-1'});
  harness.event('touchstart');
  assert.equal(harness.timers.size,1);
  [...harness.timers.values()][0].fn();harness.event('touchend');
  assert.equal(harness.nodes.has('easyTagPreview'),true);
  assert.equal(harness.completion.dropdown.selected.length,0);
  harness.event('touchstart');harness.event('touchend');
  assert.equal(harness.completion.dropdown.selected.length,1);
});

test('a rerendered list cancels the old gesture instead of selecting a different row',()=>{
  const harness=touchHarness({source:'index',tag:'sitting'});
  harness.event('touchstart');harness.completion.dropdown.items=[];
  harness.positionHandlers.get('rendered')();harness.event('touchend');
  assert.equal(harness.completion.dropdown.selected.length,0);assert.equal(harness.timers.size,0);
});

test('keyboard reflow cannot redirect a tap to the row now under its old coordinates',()=>{
  const harness=touchHarness({source:'index',tag:'sitting'});
  harness.context.document.elementFromPoint=()=>null;
  harness.event('touchstart');harness.event('touchend');
  assert.equal(harness.completion.dropdown.selected[0],harness.item);
  harness.event('mousemove');
  assert.equal(harness.nodes.has('easyTagPreview'),false,'synthetic mousemove cannot open a ghost preview');
});

test('the touch close button works once without inserting a candidate',()=>{
  const harness=touchHarness({source:'index',tag:'sitting'});
  const target={closest:selector=>selector==='[data-autocomplete-close]'?{}:null};
  harness.event('touchstart',{target});harness.event('touchend',{target});
  assert.equal(harness.completion.dropdown.shown,false);
  assert.equal(harness.completion.dropdown.selected.length,0);assert.equal(harness.timers.size,0);
});

test('IME composition cancelling an outstanding request still allows the committed Chinese query',async()=>{
  let release;
  const gate=new Promise(resolve=>{release=resolve;});
  const {input,field,completion,listeners}=completionHarness(async url=>{
    const term=new URL(url,'http://local').searchParams.get('q');
    if(term==='sh')await gate;
    return {ok:true,json:async()=>url.startsWith('/api/tags?')?{tags:[{tag:term}]}:{results:[]}};
  });
  input('sh');listeners.get('compositionstart')();
  input('瘦');listeners.get('compositionend')();release();
  for(let i=0;i<6;i++)await flush();
  assert.equal(field.dataset.composing,'0');
  assert.equal(completion.isQueryInFlight,false);
  assert.equal(completion.dropdown.items[0].tag,'瘦');
});

test('personal preset lookup completes once so an old response cannot clear a newer search',async()=>{
  const harness=completionHarness(async url=>({ok:true,json:async()=>url.startsWith('/api/tags?')?{tags:[{tag:'sitting'}]}:{results:[]}}));
  harness.context.window.EasyPanelPresetSearch={queryRange(){return {};},candidates(){return [{source:'preset',tag:'坐姿'}];},ready:async()=>{}};
  harness.input('坐');for(let i=0;i<6;i++)await flush();
  assert.equal(harness.completion.hits.length,1);
  assert.equal(harness.completion.dropdown.items[0].source,'preset');
});

test('a stalled source times out, retains the other source, and permits a later retry',async()=>{
  const timers=[];let online=false,aborted=false;
  const harness=completionHarness(async (url,{signal})=>{
    if(url.startsWith('/api/visual-tags?')&&!online) return new Promise((_,reject)=>{
      signal.addEventListener('abort',()=>{aborted=true;reject(new Error('timeout'));},{once:true});
    });
    return {ok:true,json:async()=>url.startsWith('/api/tags?')?{tags:[{tag:'smile'}]}:{results:[{tag:'local_smile'}]}};
  });
  harness.context.setTimeout=fn=>{timers.push(fn);return fn;};
  harness.context.clearTimeout=()=>{};
  const first=harness.api.search('smile');
  timers[0]();
  assert.equal((await first)[0].tag,'smile');
  assert.equal(aborted,true);
  online=true;
  assert.equal((await harness.api.search('smile'))[0].tag,'local_smile');
});

test('candidate placement respects the keyboard viewport and leaves the entire picker clear',()=>{
  const viewportListeners=new Map();
  const viewport={offsetTop:0,height:400,addEventListener(type,fn){viewportListeners.set(type,fn);},removeEventListener(type,fn){if(viewportListeners.get(type)===fn)viewportListeners.delete(type);}};
  const picker={querySelector(){return null;},getBoundingClientRect(){return {top:300,bottom:369};}};
  const {completion,positionHandlers,windowListeners}=completionHarness(async()=>({ok:true,json:async()=>({})}),{visualViewport:viewport,picker,fieldRect:{top:307,bottom:341,left:42}});
  completion.dropdown.shown=true;
  positionHandlers.get('rendered')();
  const style=completion.dropdown.el.style;
  assert.equal(style.position,'fixed');
  assert.ok(parseFloat(style.top)>=8);
  assert.ok(parseFloat(style.top)+parseFloat(style.maxHeight)<=300,'list must be above the picker, clear of the keyboard');
  completion.disposePositioning();
  assert.equal(viewportListeners.size,0);
  assert.equal(windowListeners.size,0,'closing a picker must not leave global positioning listeners');
});
