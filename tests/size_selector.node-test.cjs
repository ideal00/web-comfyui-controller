/* 尺寸选择器前端纯函数测试（比例 / 长边 / 档位分组 / 显存口径）。
 *
 * 与 tests/test_size_selector.py 分工：Python 侧查接线（脚本引用、payload 同步、
 * 原生 select 仍是真相源），这里用真实 index.html 的档位表跑算法，保证
 * 「比例是用户意图、档位是模型推荐尺寸」这条契约不会被改坏。
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

const sizes = require(path.join(__dirname, '..', 'web', 'assets', 'js', 'size-selector.js'))
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8')

/** 从 index.html 抽出 #size 的档位（WxH 形式的 option）。 */
function optionList() {
  const options = []
  const pattern = /<option value="(\d{2,5})x(\d{2,5})"[^>]*>([^<]*)<\/option>/g
  let match = pattern.exec(html)
  while (match) {
    options.push({ value: `${match[1]}x${match[2]}`, label: match[3] })
    match = pattern.exec(html)
  }
  return options
}

const OPTIONS = optionList()

test('比例表与按钮顺序就是约定的 11 个比例', () => {
  assert.deepEqual(sizes.RATIO_ORDER, [
    '1:1', '2:3', '3:4', '9:16', '1:2', '9:21', '3:2', '4:3', '16:9', '2:1', '21:9',
  ])
  assert.equal(Object.keys(sizes.SIZE_RATIOS).length, sizes.RATIO_ORDER.length)
  assert.deepEqual(sizes.SIZE_RATIOS['9:21'], { w: 9, h: 21 })
})

test('index.html 里的每个档位都能归到某个主比例', () => {
  assert.ok(OPTIONS.length >= 24, `档位数量异常：${OPTIONS.length}`)
  const groups = sizes.groupPresets(OPTIONS)
  const grouped = new Map(groups.map((group) => [group.key, group.presets.map((item) => item.value)]))
  assert.equal(grouped.size, 11)
  OPTIONS.forEach((option) => {
    const [width, height] = option.value.split('x').map(Number)
    const key = sizes.ratioKeyFromLabel(option.label) || sizes.nearestRatioKey(width, height)
    assert.ok(key, `${option.value} 没有归入任何比例`)
    assert.ok(grouped.get(key).includes(option.value), `${option.value} 应在 ${key} 分组里`)
    const target = sizes.SIZE_RATIOS[key]
    const drift = Math.abs(width / height - target.w / target.h) / (target.w / target.h)
    assert.ok(drift < 0.05, `${option.value} 与 ${key} 相差 ${(drift * 100).toFixed(1)}%，疑似分组错误`)
  })
})

test('常见档位的比例归属（含近似比例的档位）', () => {
  assert.equal(sizes.ratioKeyFromLabel('标准竖图 832 × 1216（2:3）'), '2:3')
  assert.equal(sizes.ratioKeyFromLabel('全高清横图 1920 × 1080(16:9)'), '16:9')
  assert.equal(sizes.ratioKeyFromLabel('手机长竖 768 × 1344（4:7）'), '') // 非主比例 → 交给像素判定
  assert.equal(sizes.nearestRatioKey(768, 1344), '9:16')
  assert.equal(sizes.nearestRatioKey(1344, 768), '16:9')
  assert.equal(sizes.nearestRatioKey(832, 1216), '2:3')
  assert.equal(sizes.nearestRatioKey(1216, 832), '3:2')
  assert.equal(sizes.nearestRatioKey(1024, 1024), '1:1')
  assert.equal(sizes.nearestRatioKey(0, 0), '')
})

test('长边 → 短边按比例向下对齐 8 的倍数', () => {
  assert.deepEqual(sizes.computeSize('3:2', 1536), { width: 1536, height: 1024 })
  assert.deepEqual(sizes.computeSize('3:2', 1664), { width: 1664, height: 1104 }) // 理论 1109.3 → 1104
  assert.deepEqual(sizes.computeSize('3:2', 1408), { width: 1408, height: 936 })  // 理论 938.7 → 936
  assert.deepEqual(sizes.computeSize('9:16', 1472), { width: 824, height: 1472 }) // 理论 828 → 824
  assert.deepEqual(sizes.computeSize('21:9', 1344), { width: 1344, height: 576 })
  assert.deepEqual(sizes.computeSize('1:1', 1216), { width: 1216, height: 1216 })
  sizes.RATIO_ORDER.forEach((key) => {
    const size = sizes.computeSize(key, 1600)
    assert.equal(size.width % 8, 0, `${key} 宽度未对齐 8`)
    assert.equal(size.height % 8, 0, `${key} 高度未对齐 8`)
    assert.equal(Math.max(size.width, size.height), 1600, `${key} 长边应等于滑块值`)
    assert.equal(sizes.alignTo(size.width, 8), size.width)
  })
})

test('最小长边保证短边不小于 512（避免被后端静默钳制）', () => {
  sizes.RATIO_ORDER.forEach((key) => {
    const min = sizes.minLongEdge(key)
    const size = sizes.computeSize(key, min)
    assert.ok(Math.min(size.width, size.height) >= 512, `${key} 在最小长边时短边偏小：${size.width}×${size.height}`)
    assert.equal(min % 8, 0)
  })
  assert.equal(sizes.minLongEdge('1:2'), 1024)
})

test('档位分组：按长边升序、近似档位有标记', () => {
  const groups = sizes.groupPresets(OPTIONS)
  const byKey = new Map(groups.map((group) => [group.key, group.presets]))
  const landscape32 = byKey.get('3:2').map((item) => item.value)
  assert.deepEqual(landscape32, ['1216x832', '1536x1024'])
  assert.equal(byKey.get('3:2')[0].exact, false) // 1216×832 实际 1.46:1
  assert.equal(byKey.get('3:2')[1].exact, true)
  assert.equal(byKey.get('9:16').find((item) => item.value === '832x1472').exact, true)
  assert.equal(byKey.get('9:16').find((item) => item.value === '768x1344').exact, false)
  groups.forEach((group) => {
    const longs = group.presets.map((item) => Math.max(item.width, item.height))
    assert.deepEqual(longs, longs.slice().sort((a, b) => a - b), `${group.key} 档位未按长边升序`)
  })
  // 自定义 option 不参与分组
  const withCustom = sizes.groupPresets(OPTIONS.concat([{ value: '1664x1104', label: '自定义 1664 × 1104', custom: true }]))
  const threeTwo = withCustom.find((group) => group.key === '3:2').presets.map((item) => item.value)
  assert.ok(!threeTwo.includes('1664x1104'))
})

test('显存负载口径：Illustrious 1.57MP 中、2.14MP 较高；Anima 同尺寸更紧', () => {
  assert.equal(sizes.vramEstimate(1536, 1024, 'illustrious').level, '中')
  assert.equal(sizes.vramEstimate(1792, 1192, 'illustrious').level, '较高')
  assert.equal(sizes.vramEstimate(768, 768, 'illustrious').level, '低')
  assert.equal(sizes.vramEstimate(864, 1152, 'sdxl').level, '低')
  assert.equal(sizes.vramEstimate(1152, 1152, 'sdxl').level, '中')
  assert.equal(sizes.vramEstimate(1536, 1024, 'anima').level, '高')
  assert.ok(sizes.vramEstimate(1536, 1024, 'anima').note.includes('1024px'))
})

test('比例记忆只接受主比例与合法尺寸', () => {
  const saved = sizes.writeMemory({ '3:2': '1664x1104', '4:7': '768x1344', '1:1': 'abc' })
  assert.deepEqual(saved, { '3:2': '1664x1104' })
  assert.deepEqual(sizes.readMemory(), { '3:2': '1664x1104' })
  sizes.writeMemory({})
  assert.deepEqual(sizes.readMemory(), {})
})

test('对齐工具与边界', () => {
  assert.equal(sizes.alignTo(1109.3, 8), 1112)
  assert.equal(sizes.alignTo(0, 8), 8)
  assert.equal(sizes.alignTo('1408', 8), 1408)
  assert.equal(sizes.computeSize('不存在', 1024), null)
  assert.equal(sizes.ratioInfo('3:4').portrait, true)
  assert.equal(sizes.ratioInfo('4:3').portrait, false)
})
