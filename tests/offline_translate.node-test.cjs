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
  assert.ok(css.includes('.prompt-section-translate-status{'))
})

test('按框翻译：每个框都有独立状态位（不再写全局 tokenHint）', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'offline-translate.js'), 'utf8')
  for (const field of ['promptSubject', 'promptAppearance', 'promptExpression', 'promptClothing',
                       'promptPose', 'promptComposition', 'promptScene', 'promptLighting',
                       'promptStyle', 'promptNaturalLanguage', 'prompt', 'negative']) {
    assert.ok(html.includes(`data-translate-status="${field}"`), field)
  }
  assert.ok(source.includes('function setFieldHint(fieldId, message, error)'))
  assert.ok(source.includes('data-translate-status="${fieldId}"'))
})

test('按框翻译：只翻该框的中文片段，再点一次撤销', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'offline-translate.js'), 'utf8')
  assert.ok(source.includes('async function translateField(fieldId)'))
  assert.ok(source.includes('global.translateArgosField = translateField'))
  assert.ok(source.includes('delete fieldUndo[fieldId]'))
  assert.ok(source.includes('再点可撤销上一次翻译'))
  assert.ok(source.includes('中文框 → 翻成英文；纯英文框 → 展开中文对照（点词条行可删除）'))
  assert.ok(source.includes('data-translate-field='))
  // 按框翻译只改动该框：写回的是同一个 field 节点
  assert.ok(source.includes('const field = byId(fieldId)'))
})

test('纯英文框：走「英文→中文对照」而不是写回中文', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'offline-translate.js'), 'utf8')
  assert.ok(source.includes('function explainEnglishField(fieldId)'))
  assert.ok(source.includes('global.easyPanelAnalyzePromptField'))
  assert.ok(source.includes('return explainEnglishField(fieldId)'))
  assert.ok(source.includes('英文词条 → 中文对照已打开（点整行可删除）'))
  // 纯英文框不许把中文写进框里：explain 分支直接 return，不碰 field.value
  const branch = source.slice(source.indexOf('const segments = chineseSegments(current)'),
                              source.indexOf('const { resolved, pending } = splitSegmentsByDictionary(segments)'))
  assert.ok(!branch.includes('.value ='))
  // 解析面板写回的是同一个分区，它也得把逐框翻译快照作废
  const explain = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'prompt-explain.js'), 'utf8')
  assert.ok(explain.includes('global.easyPanelInvalidateFieldUndo(state.fieldId)'))
})

test('过期快照失效：手动改 / 清空 / 粘贴 / 换预设后不再“撤销”', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'offline-translate.js'), 'utf8')
  assert.ok(source.includes('function invalidateFieldUndo(fieldId)'))
  assert.ok(source.includes('global.easyPanelInvalidateFieldUndo = invalidateFieldUndo'))
  assert.ok(source.includes('if (writingField === target.id) return;'))
  assert.ok(source.includes('wrap("clearPromptSection", clearField)'))
  assert.ok(source.includes('wrap("pastePromptSection", clearField)'))
  assert.ok(source.includes('wrap("applyPromptPreset", () => { markUserTouched(); invalidateFieldUndo(); })'))
  // 用户主动动过提示词 → 告诉面板，别在启动时拿旧的家庭状态覆盖
  assert.ok(source.includes('typeof global.markPromptTouched === "function"'))
})

test('面板：模型目录加载完的“家庭状态恢复”不再顶掉用户刚写的内容', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'panel.js'), 'utf8')
  assert.ok(source.includes('let promptTouchedSinceLoad=false;'))
  assert.ok(source.includes('function markPromptTouched(){promptTouchedSinceLoad=true}'))
  assert.ok(source.includes("document.addEventListener('input',(event)=>{const id=event.target&&event.target.id;"))
  assert.ok(source.includes('if(firstLoad&&promptTouchedSinceLoad)'))
  assert.ok(source.includes('else restorePromptFamilyState(nextFamily)'))
})

test('长提示词自动分批：32 段一批顺序请求，结果按原序合并', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'offline-translate.js'), 'utf8')
  assert.ok(source.includes('const BATCH_LIMIT = 32'))
  assert.ok(source.includes('async function requestTranslations(items, options)'))
  assert.ok(source.includes('start += BATCH_LIMIT'))
  assert.ok(source.includes('离线翻译返回的段数与请求不一致'))
  assert.ok(source.includes('global.easyPanelArgosBatch = (texts, options) => requestTranslations(texts, options)'))
  // 不再有“只发一次请求”的旧路径
  assert.ok(!source.includes('await postArgos({ texts: pending })'))
  assert.ok(!source.includes('await postArgos({ texts })\n'))
})

test('分批请求实测：33 段 → 2 次请求，结果顺序与输入一一对应', async () => {
  const calls = []
  offline.setArgosPoster(async (body) => {
    calls.push({ count: (body.texts || []).length, first: (body.texts || [])[0] })
    return { texts: (body.texts || []).map((value) => `en:${value}`) }
  })
  try {
    const items = Array.from({ length: 33 }, (_, index) => `段${index + 1}`)
    const progress = []
    const out = await offline.requestTranslations(items, {
      onProgress: (done, total) => progress.push(`${done}/${total}`),
    })
    assert.equal(calls.length, 2)
    assert.deepEqual(calls.map((call) => call.count), [32, 1])
    assert.equal(calls[0].first, '段1')
    assert.equal(calls[1].first, '段33')
    assert.deepEqual(progress, ['1/2', '2/2'])
    assert.equal(out.length, 33)
    assert.equal(out[0], 'en:段1')
    assert.equal(out[32], 'en:段33')
  } finally {
    offline.setArgosPoster(null)
  }
})

test('分批请求：32 段以内只发一次，空输入不发请求', async () => {
  const calls = []
  offline.setArgosPoster(async (body) => {
    calls.push((body.texts || []).length)
    return { texts: (body.texts || []).map((value) => value) }
  })
  try {
    assert.deepEqual(await offline.requestTranslations([], {}), [])
    assert.equal(calls.length, 0)
    await offline.requestTranslations(Array.from({ length: 32 }, (_, i) => `t${i}`))
    assert.deepEqual(calls, [32])
  } finally {
    offline.setArgosPoster(null)
  }
})

test('分批请求：段数对不上直接报错，不会静默串位', async () => {
  offline.setArgosPoster(async () => ({ texts: ['只有一个'] }))
  try {
    await assert.rejects(
      () => offline.requestTranslations(['a', 'b']),
      /段数与请求不一致/,
    )
  } finally {
    offline.setArgosPoster(null)
  }
})

test('页面接线：一个入口按钮 + 每框状态位 + 脚本', () => {
  assert.ok(html.includes('/assets/js/offline-translate.js?v='))
  assert.ok(html.includes('translateArgosOffline()'))
  assert.ok(html.includes('id="argosHint"'))
  // 逐框「翻译」已覆盖分区翻译，保留整段按钮、去掉重复的分区按钮与它的提示位
  assert.ok(!html.includes('id="argosSectionTranslate"'))
  assert.ok(!html.includes('id="argosSectionHint"'))
  assert.ok(!html.includes('translateArgosSections()'))
})

test('模块对接面板现有流程', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'offline-translate.js'), 'utf8')
  assert.ok(source.includes('/api/argos-translate'))
  assert.ok(source.includes('easyPanelUndoOfflineTranslate'))
  assert.ok(source.includes('translated = {'))
  assert.ok(source.includes('promptEditorChanged'))
})
