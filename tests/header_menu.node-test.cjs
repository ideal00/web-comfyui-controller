/* 顶部「⋯ 更多」菜单的宽窄屏切换测试。
 *
 * 与 tests/test_header_menu.py 分工：Python 侧查接线（markup / 样式 / payload 同步），
 * 这里跑 open 状态的切换规则（宽屏平铺、窄屏下拉）。
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

global.window = global

const menu = require(path.join(__dirname, '..', 'web', 'assets', 'js', 'header-menu.js'))
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8')
const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'header-menu.js'), 'utf8')

test('宽屏平铺：open=true（summary 由 CSS 隐藏）', () => {
  const fake = { open: false }
  assert.equal(menu.sync(fake, true), true)
  assert.equal(fake.open, true)
})

test('窄屏下拉：open=false', () => {
  const fake = { open: true }
  assert.equal(menu.sync(fake, false), false)
  assert.equal(fake.open, false)
})

test('未传 wide / 空菜单都不报错', () => {
  const fake = { open: true }
  menu.sync(fake)
  assert.equal(fake.open, false)
  assert.equal(menu.sync(null, true), null)
})

test('断点常量与页面结构一致', () => {
  assert.equal(menu.WIDE_QUERY, '(min-width:1341px)')
  assert.ok(html.includes('id="studioMoreMenu"'))
  assert.ok(html.includes('class="studio-more-body"'))
  assert.ok(source.includes('matchMedia'))
})
