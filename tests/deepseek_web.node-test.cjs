const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'assets', 'js', 'panel.js'),
  'utf8',
)

function lineStartingWith(prefix) {
  const line = source.split('\n').find((value) => value.trimStart().startsWith(prefix))
  assert.ok(line, `missing ${prefix}`)
  return line.trim()
}

function loadContext({ nativeResult = true, navigatorClipboard = null, execResult = true } = {}) {
  const events = []
  const elements = {
    zhPrompt: { value: '蓝发角色站在窗边' },
    translationResult: { textContent: '' },
    deepSeekManualCopy: {
      style: {
        display: 'none',
        setProperty(key, value) { this[key] = value },
      },
    },
    deepSeekManualHelp: { style: { display: 'none' } },
    deepSeekManualInstruction: {
      value: '',
      style: { display: 'none' },
    },
  }
  const root = {
    EasyPanelClipboard: {
      copyText(value) {
        events.push(['native-copy', value])
        return nativeResult
      },
    },
    open() { events.push(['open']) },
  }
  const document = {
    body: { appendChild() {} },
    getElementById(id) { return elements[id] },
    createElement() {
      return {
        value: '', style: {}, focus() {}, select() {}, remove() {},
      }
    },
    execCommand(command) {
      events.push([command])
      return execResult
    },
  }
  const navigator = navigatorClipboard === null ? {} : {
    clipboard: {
      writeText: async (value) => { events.push(['navigator-copy', value]) },
    },
  }
  const context = {
    window: root,
    document,
    navigator,
    Error,
    String,
    Boolean,
    Object,
    Promise,
  }
  vm.runInNewContext([
    'function $(id){return document.getElementById(id)}',
    "function promptFamilyClient(){return 'illustrious'}",
    "function translationFamilyLabel(){return 'Illustrious 标签为主'}",
    "function deepSeekWebInstruction(value){return 'instruction:' + value}",
    lineStartingWith('async function copyDeepSeekInstruction'),
    lineStartingWith('function hideDeepSeekManualInstruction'),
    lineStartingWith('function showDeepSeekManualInstruction'),
    lineStartingWith('async function copyDeepSeekInstructionManually'),
    lineStartingWith('async function openDeepSeekWeb'),
  ].join('\n'), context)
  return { context, elements, events }
}

test('DeepSeek copies through the Android bridge before opening the external app', async () => {
  const fixture = loadContext({ nativeResult: true, navigatorClipboard: null })
  await fixture.context.openDeepSeekWeb()
  assert.deepEqual(fixture.events.map(([name]) => name), ['native-copy', 'open'])
  assert.match(fixture.elements.translationResult.textContent, /正在打开 DeepSeek/)
  assert.equal(fixture.elements.deepSeekManualInstruction.value, '')
  assert.equal(fixture.elements.deepSeekManualInstruction.style.display, 'none')
})

test('copy failure leaves the page open and exposes manual copy guidance', async () => {
  const fixture = loadContext({ nativeResult: false, navigatorClipboard: null, execResult: false })
  await fixture.context.openDeepSeekWeb()
  assert.deepEqual(fixture.events.map(([name]) => name), ['native-copy', 'copy'])
  assert.equal(fixture.elements.deepSeekManualCopy.style.display, 'inline-block')
  assert.equal(fixture.elements.deepSeekManualHelp.style.display, 'block')
  assert.equal(fixture.elements.deepSeekManualInstruction.style.display, 'block')
  assert.equal(fixture.elements.deepSeekManualInstruction.value, 'instruction:蓝发角色站在窗边')
  assert.match(fixture.elements.translationResult.textContent, /尚未打开/)
})

test('manual retry also exposes the complete instruction when every copy path fails', async () => {
  const fixture = loadContext({ nativeResult: false, navigatorClipboard: null, execResult: false })
  await fixture.context.copyDeepSeekInstructionManually()
  assert.equal(fixture.elements.deepSeekManualInstruction.value, 'instruction:蓝发角色站在窗边')
  assert.match(fixture.elements.translationResult.textContent, /完整转换指令/)
  assert.deepEqual(fixture.events.map(([name]) => name), ['native-copy', 'copy'])
})

test('a successful retry clears the previously displayed manual instruction', async () => {
  const fixture = loadContext({ nativeResult: true, navigatorClipboard: null })
  fixture.elements.deepSeekManualInstruction.value = 'stale instruction'
  fixture.elements.deepSeekManualInstruction.style.display = 'block'
  fixture.elements.deepSeekManualHelp.style.display = 'block'
  await fixture.context.copyDeepSeekInstructionManually()
  assert.equal(fixture.elements.deepSeekManualInstruction.value, '')
  assert.equal(fixture.elements.deepSeekManualInstruction.style.display, 'none')
  assert.equal(fixture.elements.deepSeekManualHelp.style.display, 'none')
})
