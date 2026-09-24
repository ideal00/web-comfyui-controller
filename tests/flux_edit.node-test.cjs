/* FLUX 智能修图前端契约测试：纯函数（表单 → fluxEdit）+ 页面接线。
 *
 * 与 tests/test_flux_klein_edit.py 分工：Python 侧查节点链与后端端点，
 * 这里查对话框读出来的字段、校验提示和提交 payload。
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

global.window = global
const flux = require(path.join(__dirname, '..', 'web', 'assets', 'js', 'flux-edit.js'))
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8')

test('缺省模式是整图细化 + 标准策略 + 全勾保留', () => {
  const edit = flux.normalizeEdit({ source: 'a.png', instruction: 'refine' })
  assert.equal(edit.mode, 'full')
  assert.equal(edit.strategy, 'standard')
  assert.deepEqual(edit.preserve, ['identity', 'face', 'pose', 'clothing', 'composition', 'background'])
  assert.equal(edit.enabled, true)
  assert.equal(edit.megapixels, 1)
})

test('未知模式/策略回退，保留项去重且过滤非法值', () => {
  const edit = flux.normalizeEdit({
    mode: '局部修复', strategy: '???', preserve: ['face', 'FACE', 'nope', 'composition'],
  })
  assert.equal(edit.mode, 'full')
  assert.equal(edit.strategy, 'standard')
  assert.deepEqual(edit.preserve, ['face', 'composition'])
})

test('参考图最多两张、空值被剔除', () => {
  const edit = flux.normalizeEdit({ source: 'a.png', instruction: 'x', references: ['r1', '', 'r2', 'r3'] })
  assert.deepEqual(edit.references, ['r1', 'r2'])
})

test('客户端校验与后端同一套规则', () => {
  const empty = flux.normalizeEdit({ mode: 'regional' })
  const errors = flux.validateEdit(empty)
  assert.equal(errors.length, 3)
  assert.ok(errors.some((item) => item.includes('原图')))
  assert.ok(errors.some((item) => item.includes('修改描述')))
  assert.ok(errors.some((item) => item.includes('蒙版')))
  const ok = flux.normalizeEdit({ source: 'a.png', instruction: 'refine' })
  assert.deepEqual(flux.validateEdit(ok), [])
})

test('局部修复没有蒙版时报错，整图细化不需要蒙版', () => {
  const full = flux.normalizeEdit({ mode: 'full', source: 'a.png', instruction: 'refine' })
  assert.deepEqual(flux.validateEdit(full), [])
  const regional = flux.normalizeEdit({ mode: 'regional', source: 'a.png', instruction: 'refine' })
  assert.equal(flux.validateEdit(regional).length, 1)
})

test('提交 payload 带上 fluxEdit 与 operation=flux_edit', () => {
  const edit = flux.normalizeEdit({ mode: 'regional', source: 'a.png', mask: 'easy_panel/m.png', instruction: 'fix' })
  const payload = flux.buildRequestPayload(edit, { model: 'wai-v17.safetensors', width: 832 })
  assert.equal(payload.operation, 'flux_edit')
  assert.equal(payload.model, 'wai-v17.safetensors')
  assert.equal(payload.fluxEdit.mode, 'regional')
  assert.equal(payload.fluxEdit.mask, 'easy_panel/m.png')
  assert.equal(payload.fluxEdit.enabled, true)
})

test('摘要文案覆盖模式、策略与蒙版/参考图', () => {
  const regional = flux.normalizeEdit({ mode: 'regional', source: 'a.png', instruction: 'x' })
  assert.equal(flux.describeEdit(regional), '局部修复 · 标准 · 带蒙版')
  const withRefs = flux.normalizeEdit({ source: 'a.png', instruction: 'x', strategy: 'conservative', references: ['r1'] })
  assert.equal(flux.describeEdit(withRefs), '整图细化 · 保守 · 1 张参考图')
})

test('index.html 接线：脚本、手部工作台按钮、作品库筛选项', () => {
  assert.ok(html.includes('/assets/js/flux-edit.js?v='))
  assert.ok(html.includes('handSendToFlux()'))
  assert.ok(html.includes('<option value="flux_edit">FLUX 修图</option>'))
  assert.ok(html.indexOf('result-workbench.js?v=') < html.indexOf('flux-edit.js?v='))
})

test('手部工作台导出的是黑底白区蒙版', () => {
  const hand = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'hand-workbench.js'), 'utf8')
  assert.ok(hand.includes('window.handExportMask'))
  assert.ok(hand.includes("ctx.fillStyle='#000'"))
  assert.ok(hand.includes('window.handSendToFlux'))
  assert.ok(hand.includes('easyPanelFluxUseHandMask'))
})

test('对话框会从结果卡当前图片取原图，并上传蒙版到专用端点', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'flux-edit.js'), 'utf8')
  assert.ok(source.includes("#result a[href^='/output']"))
  assert.ok(source.includes('/api/upload-flux-mask'))
  assert.ok(source.includes('/api/generate'))
  assert.ok(source.includes("operation: \"flux_edit\""))
  assert.ok(source.includes('手部工作台圈选'))
  assert.ok(source.includes('最近一次蒙版'))
})

test('ComfyUI 的校验错误被翻成“缺哪个文件、放哪个目录”', () => {
  const payload = JSON.stringify({
    error: { type: 'prompt_outputs_failed_validation' },
    node_errors: {
      11: { errors: [{ type: 'value_not_in_list', details: "clip_name: 'qwen_3_4b.safetensors' not in ['a']" }] },
      12: { errors: [{ type: 'value_not_in_list', details: "vae_name: 'flux2-vae.safetensors' not in ['b']" }] },
    },
  })
  const text = flux.readableError(payload)
  assert.ok(text.includes('qwen_3_4b.safetensors'))
  assert.ok(text.includes('models/text_encoders/'))
  assert.ok(text.includes('flux2-vae.safetensors'))
  assert.ok(text.includes('models/vae/'))
  assert.equal(flux.readableError('普通的错误文本'), '普通的错误文本')
  assert.equal(flux.readableError(''), '未知错误')
  assert.equal(flux.readableError('{"error": "模型未选择。"}'), '模型未选择。')
})
