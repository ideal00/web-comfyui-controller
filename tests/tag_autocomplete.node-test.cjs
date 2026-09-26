const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
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
