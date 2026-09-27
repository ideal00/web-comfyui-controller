const assert = require('node:assert/strict')
const test = require('node:test')
const { vramAssessment, vramChecklistLevel } = require('../web/assets/js/preflight-check.js')

const base = {
  width: 1344,
  height: 1792,
  loras: [{ name: 'style' }, { name: 'character' }],
  pose: { enabled: false },
  depth: { enabled: false },
}

test('Anima 精细首采只按当前配置估算，不把假设 1.5× 算进峰值', () => {
  const result = vramAssessment(base, 'anima')
  assert.equal(result.baseMb, 6068)
  assert.equal(result.peakMb, 6068)
  assert.equal(result.level, 'ok')
  assert.equal(result.hires, false)
  assert.ok(result.notes.some((note) => note.includes('精细首采')))
  assert.ok(result.notes.every((note) => !note.includes('1.25 MP 以内')))
})

test('启用 Anima 二采后才把二采计入当前峰值', () => {
  const result = vramAssessment({ ...base, animaHighres: { enabled: true, scale: 1.5 } }, 'anima')
  assert.equal(result.hires, true)
  assert.ok(result.hiresMegapixels > result.megapixels)
  assert.equal(result.peakMb, Math.max(result.baseMb, result.hiresMb))
  assert.ok(result.notes.some((note) => note.includes('已启用二采')))
})

test('显存估算为提醒，不作为禁止生成的硬错误', () => {
  assert.equal(vramChecklistLevel('error'), 'warn')
  assert.equal(vramChecklistLevel('warn'), 'warn')
  assert.equal(vramChecklistLevel('ok'), 'ok')
})
