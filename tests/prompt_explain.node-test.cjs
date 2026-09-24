/* 🇨🇳 解析词条的契约测试：切分 / 保护 token / 序列化 / 缓存回填 / 页面接线。 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

global.window = global
const explain = require(path.join(__dirname, '..', 'web', 'assets', 'js', 'prompt-explain.js'))
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8')

const SAMPLE = 'standing, looking at viewer, from side, bent over,\none leg raised, arms behind back, blush, open mouth'

test('切分：逗号/分号/换行都是一个词条，空项被丢掉', () => {
  assert.deepEqual(explain.splitTokens('a, b,,c;d；e\ng'), ['a', 'b', 'c', 'd', 'e', 'g'])
  assert.deepEqual(explain.splitTokens('   '), [])
})

test('保护 token：LoRA / score / 人数 / artist 结构词条不翻译', () => {
  for (const token of ['<lora:xxx:0.8>', '<lora:character:0.8>', 'score_9', 'score_8_up',
                       '1girl', '2boys', 'solo', 'artist:foo', '@artist_name', '1.5', ':q']) {
    assert.equal(explain.isProtectedToken(token), true, token)
  }
  for (const token of ['standing', 'looking at viewer', 'bent over while turning upper body',
                       'one leg raised', 'blush']) {
    assert.equal(explain.isProtectedToken(token), false, token)
  }
})

test('解析：短语整体成一个词条，不拆成单词', () => {
  const tokens = explain.parsePromptTokens(SAMPLE)
  assert.equal(tokens.length, 8)
  assert.deepEqual(tokens.map((item) => item.text), [
    'standing', 'looking at viewer', 'from side', 'bent over',
    'one leg raised', 'arms behind back', 'blush', 'open mouth',
  ])
  assert.ok(tokens.every((item) => item.enabled === true))
  assert.ok(tokens.every((item) => item.translation === ''))
  assert.ok(tokens.every((item) => item.protected === false))
})

test('解析：混合提示词里结构词条被标保护', () => {
  const tokens = explain.parsePromptTokens('score_9, 1girl, <lora:x:0.7>, standing')
  assert.deepEqual(tokens.map((item) => item.protected), [true, true, true, false])
})

test('删除 / 恢复：序列化只保留 enabled 的词条并修掉多余逗号', () => {
  const tokens = explain.parsePromptTokens(SAMPLE)
  tokens[2].enabled = false   // from side
  tokens[5].enabled = false   // arms behind back
  assert.equal(
    explain.serializeTokens(tokens),
    'standing, looking at viewer, bent over, one leg raised, blush, open mouth',
  )
  tokens[2].enabled = true
  assert.equal(explain.serializeTokens(tokens),
    'standing, looking at viewer, from side, bent over, one leg raised, blush, open mouth')
  assert.equal(explain.serializeTokens([]), '')
})

test('统计与摘要', () => {
  const tokens = explain.parsePromptTokens('score_9, standing, blush, 1girl')
  tokens[2].enabled = false
  const stats = explain.statsFor(tokens)
  assert.deepEqual(stats, { total: 4, kept: 3, removed: 1, protectedCount: 2 })
  assert.match(explain.summaryText(tokens), /已保留 3 \/ 4 个词条/)
  assert.match(explain.summaryText(tokens), /🔒 2 个结构词条/)
})

test('缓存：命中的直接回填，未命中的才进批次', () => {
  const cache = { 'standing': '站立', 'looking at viewer': '看向观众' }
  const tokens = explain.parsePromptTokens('standing, looking at viewer, blush, <lora:x:1>')
  explain.applyGlossary(tokens, cache)
  assert.equal(tokens[0].translation, '站立')
  assert.equal(tokens[1].translation, '看向观众')
  assert.equal(tokens[2].translation, '')
  const pending = explain.pendingTokens(tokens, cache).map((item) => item.text)
  // blush 未命中要翻；<lora> 是保护词条，不进批次
  assert.deepEqual(pending, ['blush'])
})

test('词表反查：常见 tag 直接用手写中文，其余才交机翻', () => {
  global.chineseMap = {
    '看向观众': 'looking at viewer',
    '站立': 'standing',
    '轻薄尼龙丝袜': 'semi-sheer nylon pantyhose, subtle skin tone visible beneath fabric',
  }
  const reversed = explain.reverseChineseMap()
  assert.equal(reversed['looking at viewer'], '看向观众')
  assert.equal(reversed.standing, '站立')

  const tokens = explain.parsePromptTokens('standing, looking at viewer, blush, <lora:x:1>')
  const seeded = explain.seedFromReverseMap(tokens, {})
  assert.equal(seeded, 2)
  assert.equal(tokens[0].translation, '站立')
  assert.equal(tokens[1].translation, '看向观众')
  // blush 词表里没有 → 仍要机翻；保护词条永远不进批次
  assert.deepEqual(explain.pendingTokens(tokens, {}).map((item) => item.text), ['blush'])
  delete global.chineseMap
})

test('词表反查：已有缓存/翻译不被覆盖', () => {
  global.chineseMap = { '站立': 'standing' }
  const tokens = explain.parsePromptTokens('standing')
  tokens[0].translation = '自己写的解释'
  assert.equal(explain.seedFromReverseMap(tokens, {}), 0)
  assert.equal(tokens[0].translation, '自己写的解释')
  delete global.chineseMap
})

test('页面接线：编译器上的解析按钮 + 脚本', () => {
  assert.ok(html.includes('/assets/js/prompt-explain.js?v='))
  assert.ok(html.includes('easyPanelOpenPromptExplainer()'))
  assert.ok(html.includes('id="promptExplainButton"'))
})

test('模块暴露文档约定的三个核心接口', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'prompt-explain.js'), 'utf8')
  assert.ok(source.includes('global.EasyPanelPromptExplainer = testApi'))
  assert.ok(source.includes('{ analyze, apply, restore, open: openForActiveField }'))
  assert.ok(source.includes('/api/argos-translate'))
  assert.ok(source.includes('from: "en", to: "zh"'))
  assert.ok(source.includes('easyPanelPromptGlossaryV1'))
  assert.ok(source.includes('promptEditorChanged'))
  // 不改写英文：序列化的永远是原词条文本
  assert.ok(source.includes('return (Array.isArray(tokens) ? tokens : [])'))
})
