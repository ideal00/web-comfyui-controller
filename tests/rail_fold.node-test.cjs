/* 左侧抽屉折叠层的纯函数测试（状态读写 + 默认值 + 污染输入清理）。
 *
 * 与 tests/test_rail_fold.py 分工：Python 侧查接线（markup / 样式 / payload 同步），
 * 这里跑 localStorage 状态的读写与合并规则。
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

const fold = require(path.join(__dirname, '..', 'web', 'assets', 'js', 'rail-fold.js'))
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8')

test('默认没有任何记忆时返回空状态（页面按默认折叠处理）', () => {
  storage.clear()
  assert.deepEqual(fold.readFoldState(), {})
})

test('写入只保留布尔值，垃圾数据被清理', () => {
  storage.clear()
  assert.deepEqual(fold.writeFoldState({ translationCard: true, customFeatureCard: 'yes', '': true }), {
    translationCard: true,
    customFeatureCard: false,
  })
  assert.deepEqual(fold.readFoldState(), { translationCard: true, customFeatureCard: false })
})

test('坏 JSON 不会抛错，直接退回空状态', () => {
  storage.set(fold.FOLD_STORAGE_KEY, '{不是 json')
  assert.deepEqual(fold.readFoldState(), {})
  storage.set(fold.FOLD_STORAGE_KEY, '"字符串"')
  assert.deepEqual(fold.readFoldState(), {})
})

test('rememberFold 按 id 合并，不影响其它面板', () => {
  storage.clear()
  fold.rememberFold({ id: 'translationCard', dataset: {} }, true)
  fold.rememberFold({ id: 'imageReadCard', dataset: {} }, true)
  fold.rememberFold({ id: 'translationCard', dataset: {} }, false)
  assert.deepEqual(fold.readFoldState(), { translationCard: false, imageReadCard: true })
  // 无 id 且无 data-fold-key 的节点直接忽略，不写脏数据
  fold.rememberFold({ dataset: {} }, true)
  assert.deepEqual(fold.readFoldState(), { translationCard: false, imageReadCard: true })
})

test('applyFoldState：记住 true 才展开，其它一律默认折叠', () => {
  const node = { id: 'translationCard', open: true, dataset: {} }
  fold.applyFoldState(node, { translationCard: true })
  assert.equal(node.open, true)
  fold.applyFoldState(node, {})
  assert.equal(node.open, false)
  fold.applyFoldState(node, { translationCard: false })
  assert.equal(node.open, false)
})

test('折叠栏中点击已展开摘要会展开整列但保留 details 内容', () => {
  const classes = new Set(['left-rail-collapsed'])
  const layout = {
    classList: {
      contains: (name) => classes.has(name),
      remove: (name) => classes.delete(name),
    },
  }
  const previousDocument = global.document
  const previousToggle = global.toggleLeftRail
  global.document = { getElementById: (id) => (id === 'studioLayout' ? layout : null) }
  global.toggleLeftRail = (force) => {
    assert.equal(force, false)
    classes.delete('left-rail-collapsed')
  }
  try {
    const node = {
      open: true,
      closest: (selector) => (selector === '.studio-left' ? {} : null),
    }
    let prevented = false
    fold.handleRailSummaryClick({ preventDefault: () => { prevented = true } }, node)
    assert.equal(prevented, true)
    assert.equal(node.open, true)
    assert.equal(classes.has('left-rail-collapsed'), false)
  } finally {
    global.document = previousDocument
    global.toggleLeftRail = previousToggle
  }
})

test('index.html 里每一块抽屉面板都带 data-rail-fold 与 summary', () => {
  const blocks = html.match(/<details[^>]*data-rail-fold[^>]*>/g) || []
  assert.equal(blocks.length, 4)
  blocks.forEach((block) => {
    assert.ok(/id="(customFeatureCard|taskQueueFold|translationCard|imageReadCard)"/.test(block), block)
    assert.ok(!/\sopen(\s|>)/.test(block), `默认必须折叠：${block}`)
  })
  assert.ok(html.includes('id="railTransparentMount"'))
  // 任务批处理控制已从生成列搬进抽屉
  const generation = html.slice(html.indexOf('id="generationSection"'), html.indexOf('id="studioToolDrawer"'))
  assert.ok(!generation.includes('id="taskQueueToolbar"'))
})

test('队列计数 → 折叠摘要短标签', () => {
  assert.equal(
    fold.summarizeTaskCounts('排队中 2 · 执行中 1 · 已完成 12 · 失败 3 · 已取消 0 · 已跳过 0'),
    '执行中 1 · 排队 2 · 失败 3',
  )
  assert.equal(fold.summarizeTaskCounts('排队中 0 · 执行中 0 · 已完成 4 · 失败 0 · 已取消 0 · 已跳过 0'), '空闲')
  assert.equal(fold.summarizeTaskCounts('读取中…'), '读取中…')
  assert.equal(fold.summarizeTaskCounts(''), '读取中…')
  assert.equal(fold.summarizeTaskCounts(undefined), '读取中…')
  assert.equal(fold.summarizeTaskCounts('排队中 5'), '排队 5')
})
