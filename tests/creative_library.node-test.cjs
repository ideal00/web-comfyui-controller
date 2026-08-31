const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const library = require(path.join(__dirname, '..', 'web', 'assets', 'js', 'creative-library.js'))
const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'assets', 'js', 'creative-library.js'),
  'utf8',
)
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8')

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    blob: async () => new Blob(['image'], { type: 'image/png' }),
  }
}

class Element {
  constructor(id = '') {
    this.id = id
    this.children = []
    this.listeners = new Map()
    this.dataset = {}
    this.style = {}
    this.hidden = false
    this.disabled = false
    this.open = false
    this.value = ''
    this.textContent = ''
    this.className = ''
  }

  append(...nodes) {
    this.children.push(...nodes.filter((node) => node != null))
  }

  replaceChildren(...nodes) {
    this.children = nodes.filter((node) => node != null)
  }

  addEventListener(type, handler) {
    const handlers = this.listeners.get(type) || []
    handlers.push(handler)
    this.listeners.set(type, handlers)
  }

  dispatch(type, event = {}) {
    const payload = {
      preventDefault() { payload.defaultPrevented = true },
      defaultPrevented: false,
      target: this,
      currentTarget: this,
      ...event,
    }
    for (const handler of this.listeners.get(type) || []) handler(payload)
    return payload
  }

  click() {
    if (this.type === 'submit' && this.form) return this.form.dispatch('submit')
    return this.dispatch('click')
  }

  focus() {}

  setAttribute(name, value) {
    this[name] = String(value)
  }

  removeAttribute(name) {
    if (name === 'open') this.open = false
    else delete this[name]
  }

  showModal() {
    this.open = true
  }

  close() {
    this.open = false
    this.dispatch('close')
  }

  remove() {}
}

function createPage(fetchImpl) {
  const ids = [
    'creativeLibraryDialog', 'creativeLibraryOpen', 'creativeLibraryClose', 'creativeLibraryRefresh',
    'creativeLibraryAuth', 'creativeLibraryToken', 'creativeLibraryNotice', 'creativeLibraryListView',
    'creativeLibraryFilters', 'creativeLibraryOperation', 'creativeLibraryStatus', 'creativeLibraryModel', 'creativeLibrarySort',
    'creativeLibraryOrder', 'creativeLibraryApplyFilters', 'creativeLibraryList',
    'creativeLibraryPagination', 'creativeLibraryPrevious', 'creativeLibraryPageInfo', 'creativeLibraryNext',
    'creativeLibraryDetailView', 'creativeLibraryBack', 'creativeLibraryDetailStatus', 'creativeLibraryDetail',
    'status', 'quality',
  ]
  const elements = Object.fromEntries(ids.map((id) => [id, new Element(id)]))
  elements.creativeLibraryDialog.open = false
  elements.creativeLibraryApplyFilters.type = 'submit'
  elements.creativeLibraryApplyFilters.form = elements.creativeLibraryFilters
  const document = {
    readyState: 'complete',
    activeElement: elements.creativeLibraryOpen,
    body: new Element('body'),
    getElementById(id) { return elements[id] || null },
    createElement(tag) {
      const node = new Element()
      node.tagName = tag.toUpperCase()
      return node
    },
    addEventListener() {},
  }
  const root = {
    document,
    fetch: fetchImpl,
    location: { origin: 'http://localhost:8190' },
    URL,
    setTimeout,
    openLinkedImageViewer: undefined,
  }
  vm.runInNewContext(source, {
    window: root,
    document,
    URL,
    URLSearchParams,
    BigInt,
    Blob,
    Date,
    JSON,
    Math,
    Number,
    String,
    Error,
    Promise,
    setTimeout,
  })
  return { root, elements }
}

async function flush() {
  await new Promise((resolve) => setImmediate(resolve))
  await new Promise((resolve) => setImmediate(resolve))
}

test('list query bounds and URL-encodes filters without exposing credentials', () => {
  const query = library.buildListQuery({
    limit: 999,
    offset: -20,
    operation: 'IMG2IMG',
    status: 'COMPLETED',
    model: 'model & /测试',
    sort: 'updated_at',
    order: 'asc',
  })
  const params = new URLSearchParams(query)
  assert.equal(params.get('limit'), '100')
  assert.equal(params.get('offset'), '0')
  assert.equal(params.get('operation'), 'img2img')
  assert.equal(params.get('status'), 'completed')
  assert.equal(params.get('model'), 'model & /测试')
  assert.equal(params.get('sort'), 'updated_at')
  assert.equal(params.get('order'), 'asc')
  assert.doesNotMatch(query, /token|secret|authorization/i)
  assert.equal(library.buildListQuery({ operation: 'DROP TABLE', sort: 'injection' }), 'limit=24&offset=0')
})

test('desktop HTML contains the isolated Library entry, dialog, and script after snapshot restore', () => {
  assert.match(html, /id="creativeLibraryOpen"/)
  assert.match(html, /id="creativeLibraryDialog"/)
  assert.match(html, /id="creativeLibraryFilters"/)
  assert.match(html, /id="creativeLibraryDetail"/)
  assert.match(html, /snapshot-flow\.js\?v=1[\s\S]*creative-library\.js\?v=1/)
  assert.match(html, /panel\.css\?v=38/)
})

test('restore and seed variant clone form payloads without mutating the source', () => {
  const detail = {
    generation_id: 'a'.repeat(32),
    seed: '41',
    input: { model: 'fallback.safetensors' },
    snapshot: { payload: { model: 'model.safetensors', seed: '41', promptSections: { subject: '1girl' }, nested: { keep: true } } },
    replay: { payload: { model: 'replay.safetensors' } },
  }
  const original = JSON.stringify(detail)
  const restored = library.restorePayloadForForm(detail, 'reproduce')
  const variant = library.restorePayloadForForm(detail, 'seed-variant')
  assert.deepEqual(restored, detail.snapshot.payload)
  assert.equal(variant.seed, '42')
  assert.equal(variant.model, 'model.safetensors')
  assert.equal(variant.nested.keep, true)
  assert.equal(JSON.stringify(detail), original)
  restored.nested.keep = false
  assert.equal(detail.snapshot.payload.nested.keep, true)
})

test('safe paths reject traversal, external origins, and HTML-shaped ids', () => {
  assert.throws(() => library.safeGenerationId('<img src=x onerror=alert(1)>'))
  assert.equal(library.safeLibraryImagePath('javascript:alert(1)', 'http://localhost:8190'), '')
  assert.equal(library.safeLibraryImagePath('http://evil.test/api/rpg/image?name=x.png', 'http://localhost:8190'), '')
  assert.equal(library.artifactPath({ filename: '../private.png' }, 'http://localhost:8190'), '')
  assert.equal(library.artifactPath({ filename: 'ok.png', subfolder: '../private' }, 'http://localhost:8190'), '/api/rpg/image?name=ok.png&type=output')
  assert.doesNotMatch(source, /innerHTML/)
  assert.doesNotMatch(source, /method:\s*['"]POST['"]/)
  assert.doesNotMatch(source, /\/api\/generate(?:-batch|['"?])/)
})

test('GET-only API wrapper and old-server 404 are handled without breaking the panel', async () => {
  const calls = []
  const page = createPage(async (url, options) => {
    calls.push([url, options])
    return response({ error: 'missing' }, 404)
  })
  page.elements.creativeLibraryOpen.click()
  await flush()
  assert.match(page.elements.creativeLibraryNotice.textContent, /不支持作品库/)
  assert.equal(page.elements.status.textContent, '')
  page.elements.creativeLibraryOperation.value = 'img2img'
  page.elements.creativeLibraryApplyFilters.click()
  await flush()
  assert.ok(calls.length >= 2)
  assert.ok(calls.every(([, options]) => options.method === 'GET'))
  assert.equal(page.elements.quality.click().defaultPrevented, false)
  assert.equal(page.elements.status.textContent, '')
  const error = Object.assign(new Error('old server'), { status: 404 })
  assert.match(library.libraryErrorMessage(error, '读取作品库'), /不支持作品库/)
})

test('filter and restore clicks stay read-only and only restore to the existing form', async () => {
  const id = 'b'.repeat(32)
  const calls = []
  let restored
  const page = createPage(async (url, options) => {
    calls.push([url, options])
    if (url.startsWith('/api/rpg/library/generations?')) {
      return response({ items: [{ generation_id: id, model: 'model.safetensors', operation: 'txt2img', status: 'completed', created_at: 1, updated_at: 1, seed: '7', width: 832, height: 1216, parent_count: 0, child_count: 0 }], total: 1, has_more: false })
    }
    if (url.endsWith(`/${id}/lineage`)) return response({ lineage: { ancestors: [], descendants: [], edges: [] } })
    if (url.endsWith(`/${id}`)) {
      return response({ generation: {
        generation_id: id, model: 'model.safetensors', operation: 'txt2img', status: 'completed', created_at: 1, updated_at: 1,
        seed: '7', width: 832, height: 1216, quality: 'fast', parent_count: 0, child_count: 0, lora_count: 0,
        input: {}, snapshot: { payload: { model: 'model.safetensors', quality: 'fast', prompt: 'safe prompt', seed: '7' } },
        replay: { payload: {} }, artifacts: [], loras: [],
      } })
    }
    throw new Error(`unexpected URL ${url}`)
  })
  page.root.restorePayloadToPanel = (payload) => { restored = payload }
  page.elements.creativeLibraryOpen.click()
  await flush()
  page.elements.creativeLibraryList.children[0].click()
  await flush()
  await flush()
  const actions = page.elements.creativeLibraryDetail.children.find((child) => child.className === 'creative-library-actions')
  assert.ok(actions)
  actions.children[0].click()
  assert.deepEqual(restored, { model: 'model.safetensors', quality: 'fast', prompt: 'safe prompt', seed: '7' })
  assert.match(page.elements.status.textContent, /手动点击“生成图片”/)
  assert.ok(calls.every(([, options]) => options.method === 'GET'))
  assert.equal(calls.some(([, options]) => options.method !== 'GET'), false)
})
