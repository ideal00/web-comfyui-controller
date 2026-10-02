const test = require('node:test');
const assert = require('node:assert/strict');
const editor = require('../web/assets/js/visual-tag-editor.js');

test('work prompt candidates exclude Chinese, LoRA calls and narrative blocks', () => {
  assert.equal(editor.tagsFromText("white_shirt, vest, 中文名称, <lora:test:1>, vest, (blue eyes:1.2), This is a very long description of two people in a room."), 'white_shirt, vest');
});

test('work link offers separate prompt sections without mixing negative tags', () => {
  assert.deepEqual(editor.promptSources({snapshot:{payload:{promptSections:{clothing:'white_shirt, vest',pose:'standing',negative:'bad hands'}},compiled:{positive:'1girl, solo',negative:'bad hands'}}}),
    {clothing:'white_shirt, vest',pose:'standing',positive:'1girl, solo'});
});
