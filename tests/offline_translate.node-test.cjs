/* 离线翻译前端契约测试：中文片段识别 / 原地替换 / 页面接线。 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

global.window = global
const offline = require(path.join(__dirname, '..', 'web', 'assets', 'js', 'offline-translate.js'))
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8')

test('中文判定覆盖中英文混排', () => {
  assert.equal(offline.hasChinese('蓝发'), true)
  assert.equal(offline.hasChinese('long hair'), false)
  assert.equal(offline.hasChinese('1girl, 蓝发'), true)
  assert.equal(offline.hasChinese(''), false)
  assert.equal(offline.hasChinese(undefined), false)
})

test('只挑出含中文的片段，去重保序', () => {
  assert.deepEqual(
    offline.chineseSegments('1girl, 蓝发, white shirt, 蓝发, 白裙'),
    ['蓝发', '白裙'],
  )
  assert.deepEqual(offline.chineseSegments('long hair, white shirt'), [])
  assert.deepEqual(offline.chineseSegments('蓝发；白裙\n微笑'), ['蓝发', '白裙', '微笑'])
})

test('原地替换只动中文片段，英文标签与分隔符保持', () => {
  const mapping = { '蓝发': 'blue hair', '白裙': 'white dress' }
  assert.equal(
    offline.replaceSegments('1girl, 蓝发, white shirt, 白裙', mapping),
    '1girl, blue hair, white shirt, white dress',
  )
  // 中文分号与换行保持原样
  assert.equal(offline.replaceSegments('蓝发；白裙', mapping), 'blue hair；white dress')
  assert.equal(offline.replaceSegments('蓝发\n白裙', mapping), 'blue hair\nwhite dress')
  // 没有映射的片段原样保留
  assert.equal(offline.replaceSegments('蓝发, 微笑', mapping), 'blue hair, 微笑')
  assert.equal(offline.replaceSegments('   ', mapping), '   ')
})

test('收集分区片段：跳过纯英文字段，批次去重', () => {
  const collected = offline.collectFieldSegments({
    promptSubject: '1girl, 蓝发',
    promptClothing: 'white dress',
    promptScene: '废墟, 蓝发',
  })
  assert.deepEqual(collected.batch, ['蓝发', '废墟'])
  assert.deepEqual(collected.fields.map((item) => item.id), ['promptSubject', 'promptScene'])
  assert.equal(collected.fields[0].label, '人物与角色')
})

test('状态文案区分可用与不可用', () => {
  assert.match(offline.statusText({ available: true, pairs: ['zh→en'], home: 'G:\\x' }), /离线可用/)
  assert.match(offline.statusText({ available: false, reason: '未找到离线翻译器' }), /未找到离线翻译器/)
  assert.match(offline.statusText(null), /不可用/)
})

test('变更摘要列出分区与段数', () => {
  assert.equal(
    offline.summarizeChanges([{ label: '人物与角色', count: 2 }, { label: '场景', count: 1 }]),
    '已翻译：人物与角色(2 段)、场景(1 段)',
  )
  assert.equal(offline.summarizeChanges([]), '没有需要翻译的中文片段。')
})

test('本地词表优先：命中词表且不再含中文就不走机翻', () => {
  global.chineseMap = { '蓝发': 'blue hair', '白裙': 'white dress', '丝袜': 'pantyhose' }
  const hit = offline.applyChineseMap('蓝发')
  assert.equal(hit.text, 'blue hair')
  assert.equal(hit.hits, 1)
  assert.equal(hit.hasChineseLeft, false)
  const mixed = offline.applyChineseMap('白裙')
  assert.equal(mixed.text, 'white dress')
  const split = offline.splitSegmentsByDictionary(['蓝发', '在废墟里回眸', '白裙'])
  assert.deepEqual(split.resolved, { '蓝发': 'blue hair', '白裙': 'white dress' })
  assert.deepEqual(split.pending, ['在废墟里回眸'])
  delete global.chineseMap
})

test('词表只能部分命中时仍交给机翻（不产出中英混杂结果）', () => {
  global.chineseMap = { '蓝发': 'blue hair' }
  const partial = offline.applyChineseMap('蓝发的少女在奔跑')
  assert.equal(partial.hasChineseLeft, true)
  const split = offline.splitSegmentsByDictionary(['蓝发的少女在奔跑'])
  assert.deepEqual(split.resolved, {})
  assert.deepEqual(split.pending, ['蓝发的少女在奔跑'])
  delete global.chineseMap
})

test('机翻结果做标签化清理', () => {
  assert.equal(offline.cleanTranslatedTag('Light nylon stockings.'), 'light nylon stockings')
  assert.equal(offline.cleanTranslatedTag('Blue  hair  。'), 'blue hair')
  assert.equal(offline.cleanTranslatedTag(''), '')
})

test('页面接线：12 个框各带一个「翻译」按钮（与清空/粘贴同排）', () => {
  const buttons = [...html.matchAll(/data-translate-field="([a-zA-Z]+)"/g)].map((m) => m[1])
  assert.equal(buttons.length, 12)
  for (const field of ['promptSubject', 'promptAppearance', 'promptExpression', 'promptClothing',
                       'promptPose', 'promptComposition', 'promptScene', 'promptLighting',
                       'promptStyle', 'promptNaturalLanguage', 'prompt', 'negative']) {
    assert.ok(buttons.includes(field), field)
    assert.ok(html.includes(`translateArgosField('${field}')`), field)
  }
  assert.ok(html.includes('class="prompt-section-translate"'))
  const css = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'css', 'panel.css'), 'utf8')
  assert.ok(css.includes('.prompt-section-translate{'))
  assert.ok(css.includes('.prompt-section-translate:hover'))
})

test('按框翻译：只翻该框的中文片段，再点一次撤销', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'offline-translate.js'), 'utf8')
  assert.ok(source.includes('async function translateField(fieldId)'))
  assert.ok(source.includes('global.translateArgosField = translateField'))
  assert.ok(source.includes('delete fieldUndo[fieldId]'))
  assert.ok(source.includes('已撤销${label}分区的翻译'))
  assert.ok(source.includes('data-translate-field='))
  // 按框翻译只改动该框：写回的是同一个 field 节点
  assert.ok(source.includes('const field = byId(fieldId)'))
})

test('页面接线：两个按钮 + 提示位 + 脚本', () => {
  assert.ok(html.includes('/assets/js/offline-translate.js?v='))
  assert.ok(html.includes('translateArgosOffline()'))
  assert.ok(html.includes('translateArgosSections()'))
  assert.ok(html.includes('id="argosHint"'))
  assert.ok(html.includes('id="argosSectionHint"'))
  assert.ok(html.includes('id="argosSectionTranslate"'))
})

test('模块对接面板现有流程', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'offline-translate.js'), 'utf8')
  assert.ok(source.includes('/api/argos-translate'))
  assert.ok(source.includes('easyPanelUndoOfflineTranslate'))
  assert.ok(source.includes('translated = {'))
  assert.ok(source.includes('promptEditorChanged'))
})
