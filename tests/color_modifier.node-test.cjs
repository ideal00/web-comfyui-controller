/* 颜色修饰（color-modifier.js）前端行为测试。
 *
 * 覆盖：颜色标签识别、非颜色标签原样、已有修饰词不叠加/可替换、
 * 状态持久化、以及与 Prompt 方言层的串联（dark_blue_hair → dark blue hair）。
 */
const assert = require('node:assert/strict')
const path = require('node:path')
const test = require('node:test')

global.window = global
const storage = new Map()
global.localStorage = {
  getItem: (key) => (storage.has(key) ? storage.get(key) : null),
  setItem: (key, value) => storage.set(key, String(value)),
}

const modifier = require(path.join(__dirname, '..', 'web', 'assets', 'js', 'color-modifier.js'))
const dialect = require(path.join(__dirname, '..', 'web', 'assets', 'js', 'prompt-dialect.js'))

test('未选择修饰词时原样返回', () => {
  modifier.set('')
  assert.equal(modifier.current(), '')
  assert.equal(modifier.compose('blue_hair'), 'blue_hair')
  assert.equal(modifier.compose('blue_hair', ''), 'blue_hair')
})

test('颜色标签在写入时插入修饰词', () => {
  assert.equal(modifier.compose('blue_hair', 'dark'), 'dark_blue_hair')
  assert.equal(modifier.compose('blue_eyes', 'dark'), 'dark_blue_eyes')
  assert.equal(modifier.compose('red_dress', 'vivid'), 'vivid_red_dress')
  assert.equal(modifier.compose('white_hair', 'dark'), 'dark_white_hair')
  assert.equal(modifier.compose('blue_background', 'deep'), 'deep_blue_background')
  assert.equal(modifier.compose('purple_highlights', 'soft'), 'soft_purple_highlights')
  assert.equal(modifier.compose('blue_and_pink_hair', 'dark'), 'dark_blue_and_pink_hair')
})

test('本地标签库的空格写法同样生效，且保留原分隔符', () => {
  assert.equal(modifier.compose('blue hair', 'dark'), 'dark blue hair')
  assert.equal(modifier.compose('blue eyes', 'pale'), 'pale blue eyes')
  assert.equal(modifier.compose('light blue hair', 'dark'), 'dark blue hair')
  assert.equal(modifier.compose('dark blue hair', 'dark'), 'dark blue hair')
  assert.equal(modifier.compose('blue hairband', 'dark'), 'blue hairband')
  assert.deepEqual(modifier.analyze('light blue hair'), { colorIndex: 1, modifierIndex: 0 })
})

test('非颜色标签不受影响', () => {
  const untouched = [
    'long_hair', 'hair_ribbon', 'school_uniform', 'multicolored_hair',
    'ice_cream', 'cream_pie', 'blue_archive', 'black_hairband',
    'red_(pokemon)', '@somebody_artist', 'score_7', 'dark_skin',
    'blue archive', 'ice cream', 'long hair',
  ]
  for (const tag of untouched) {
    assert.equal(modifier.compose(tag, 'dark'), tag, tag)
    assert.equal(modifier.isColorTag(tag), false, tag)
  }
})

test('已有修饰词不叠加：相同则原样，不同则替换', () => {
  assert.equal(modifier.compose('dark_blue_hair', 'dark'), 'dark_blue_hair')
  assert.equal(modifier.compose('pale_blue_eyes', 'pale'), 'pale_blue_eyes')
  assert.equal(modifier.compose('light_blue_hair', 'dark'), 'dark_blue_hair')
  assert.equal(modifier.compose('dark_blue_hair', 'pale'), 'pale_blue_hair')
})

test('分析结果给出颜色词与已有修饰词的位置', () => {
  assert.deepEqual(modifier.analyze('blue_hair'), { colorIndex: 0, modifierIndex: -1 })
  assert.deepEqual(modifier.analyze('dark_blue_hair'), { colorIndex: 1, modifierIndex: 0 })
  assert.deepEqual(modifier.analyze('long_hair'), { colorIndex: -1, modifierIndex: -1 })
  assert.deepEqual(modifier.analyze('blue_and_pink_hair'), { colorIndex: 0, modifierIndex: -1 })
  assert.deepEqual(modifier.analyze('ice_cream'), { colorIndex: -1, modifierIndex: -1 })
})

test('状态读写与文案', () => {
  assert.equal(modifier.set('dark'), 'dark')
  assert.equal(modifier.current(), 'dark')
  assert.equal(storage.get(modifier.STORAGE_KEY), 'dark')
  assert.equal(modifier.compose('blue_hair'), 'dark_blue_hair')   // 省略 modifier 时读 UI 状态
  assert.equal(modifier.describe('dark'), '深 dark')
  assert.equal(modifier.describe(''), '无')
  assert.equal(modifier.set('不存在的词'), '')                     // 非法值回落到「无」
  assert.equal(modifier.current(), '')
  assert.equal(modifier.set(''), '')
})

test('批量组合与空输入', () => {
  assert.deepEqual(
    modifier.composeTags(['blue_hair', 'long_hair', 'blue_eyes'], 'dark'),
    ['dark_blue_hair', 'long_hair', 'dark_blue_eyes'],
  )
  assert.deepEqual(modifier.composeTags([], 'dark'), [])
  assert.equal(modifier.compose(''), '')
  assert.equal(modifier.compose(null, 'dark'), '')
})

test('与 Prompt 方言层串联：原形 → 修饰 → 方言', () => {
  const composed = modifier.compose('blue_hair', 'dark')
  assert.equal(dialect.formatTag(composed, { dialect: 'canonical' }), 'dark_blue_hair')
  assert.equal(dialect.formatTag(composed, { dialect: 'space' }), 'dark blue hair')
  assert.equal(modifier.compose('score_7', 'dark'), 'score_7')
})
