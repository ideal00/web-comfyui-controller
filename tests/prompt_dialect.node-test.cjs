/* Prompt 方言前端实现的一致性测试。
 *
 * 与 tests/test_prompt_dialect.py 共用 tests/prompt_dialect_cases.json：
 * 同一份用例表，Python 与 JS 必须得出相同结果。
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

global.window = global
const storage = new Map()
global.localStorage = {
  getItem: (key) => (storage.has(key) ? storage.get(key) : null),
  setItem: (key, value) => storage.set(key, String(value)),
}

const dialect = require(path.join(__dirname, '..', 'web', 'assets', 'js', 'prompt-dialect.js'))
const cases = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'prompt_dialect_cases.json'), 'utf8'),
).cases

function withFamily(family, run) {
  const previous = global.modelFamilyClient
  global.modelFamilyClient = () => family
  try {
    return run()
  } finally {
    if (previous === undefined) delete global.modelFamilyClient
    else global.modelFamilyClient = previous
  }
}

test('共享用例表：JS 得到与 Python 相同结果', () => {
  for (const item of cases) {
    const actual = withFamily(item.family, () => {
      dialect.setDialect(item.dialect)
      return dialect.formatTag(item.tag, {
        kind: item.kind,
        protect: Boolean(item.protect),
        dialect: item.dialect,
      })
    })
    assert.equal(actual, item.expect, `${item.tag} / ${item.kind} / ${item.family} / ${item.dialect} — ${item.note || ''}`)
  }
})

test('方言解析跟随模型族，手动指定优先', () => {
  assert.equal(withFamily('anima', () => dialect.resolve('auto')), 'space')
  assert.equal(withFamily('krea2', () => dialect.resolve('auto')), 'space')
  assert.equal(withFamily('illustrious', () => dialect.resolve('auto')), 'canonical')
  assert.equal(withFamily('sdxl', () => dialect.resolve('auto')), 'canonical')
  assert.equal(withFamily('illustrious', () => dialect.resolve('space')), 'space')
  assert.equal(withFamily('anima', () => dialect.resolve('canonical')), 'canonical')
})

test('类别判断：score / 画师 / 其他', () => {
  assert.equal(dialect.classify('score_7'), 'score')
  assert.equal(dialect.classify('SCORE_9_UP'), 'score')
  assert.equal(dialect.classify('@somebody'), 'artist')
  assert.equal(dialect.classify('high_heels'), 'general')
  assert.equal(dialect.classify('high_heels', 'character'), 'character')
  assert.equal(dialect.classify(''), 'unknown')
})

test('LoRA 触发词永不转换', () => {
  const trigger = 'some_custom_trigger_v2'
  assert.equal(dialect.formatTag(trigger, { kind: 'trigger', dialect: 'space' }), trigger)
  assert.equal(dialect.formatTag(trigger, { protect: true, dialect: 'space' }), trigger)
})

test('批量与空输入', () => {
  assert.deepEqual(
    dialect.formatTags(['high_heels', 'score_7'], { dialect: 'space' }),
    ['high heels', 'score_7'],
  )
  assert.equal(dialect.formatTag('', { dialect: 'space' }), '')
  assert.deepEqual(dialect.formatTags([], {}), [])
})

test('描述文案区分手动与自动', () => {
  assert.match(dialect.describe('space'), /手动指定/)
  assert.match(dialect.describe('auto'), /按当前模型/)
})
