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
const panelSource = fs.readFileSync(path.join(__dirname, '..', 'web', 'assets', 'js', 'panel.js'), 'utf8')

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

function createPage(fetchImpl, overrides = {}) {
  const ids = [
    'creativeLibraryDialog', 'creativeLibraryOpen', 'creativeLibraryClose', 'creativeLibraryRefresh',
    'creativeLibraryAuth', 'creativeLibraryToken', 'creativeLibraryNotice', 'creativeLibraryListView',
    'creativeLibraryFilters', 'creativeLibraryOperation', 'creativeLibraryStatus', 'creativeLibraryModel', 'creativeLibrarySort',
    'creativeLibraryOrder', 'creativeLibraryApplyFilters', 'creativeLibraryList',
    'creativeLibraryPagination', 'creativeLibraryPrevious', 'creativeLibraryPageInfo', 'creativeLibraryNext',
    'creativeLibraryJump', 'creativeLibraryPageNumber', 'creativeLibraryJumpButton',
    'creativeLibraryDetailView', 'creativeLibraryBack', 'creativeLibraryDetailStatus', 'creativeLibraryDetail',
    'panelImageViewer',
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
    AbortController,
    setTimeout,
    openLinkedImageViewer: undefined,
    ...overrides,
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

test('library reads reuse the browser session without a second login form', () => {
  assert.doesNotMatch(html, /id="creativeLibraryAuth"|id="creativeLibraryToken"|使用 Token 读取/)
})

test('thumbnail URLs stay authenticated and use the small preview endpoint', () => {
  assert.equal(library.thumbnailPath('/api/rpg/image?name=a.png&preview=0', 'http://localhost'), '/api/rpg/image?name=a.png&preview=1')
  assert.equal(library.thumbnailPath('https://outside.invalid/api/rpg/image?name=a.png', 'http://localhost'), '')
  assert.equal(library.pageOffset('3', 49), 48)
  for (const input of ['', '0', '-1', '1.5', '1e1', '4', 'Infinity']) assert.equal(library.pageOffset(input, 49), null)
})

test('jump submits a single target page while preserving active filters', async () => {
  const requests = []
  const page = createPage(async (url) => {
    if (!url.startsWith('/api/rpg/library/generations?')) return response({})
    requests.push(url)
    const offset = Number(new URLSearchParams(url.split('?')[1]).get('offset'))
    return response({items:[{generation_id:offset.toString(16).padStart(32,'0'),model:'sample'}],total:73,has_more:offset<72})
  })
  page.elements.creativeLibraryModel.value = 'selected model'
  page.elements.creativeLibraryOpen.click()
  await flush()
  page.elements.creativeLibraryPageNumber.value = '4'
  page.elements.creativeLibraryJump.dispatch('submit')
  await flush()
  const query = new URLSearchParams(requests.at(-1).split('?')[1])
  assert.equal(query.get('offset'), '72')
  assert.equal(query.get('model'), 'selected model')
  assert.match(page.elements.creativeLibraryPageInfo.textContent, /第 4 \/ 4 页/)
  for (const invalid of ['0','5','1.5','']) {
    page.elements.creativeLibraryPageNumber.value = invalid
    page.elements.creativeLibraryJump.dispatch('submit')
  }
  assert.equal(requests.length, 2)
  assert.match(page.elements.creativeLibraryNotice.textContent, /整数页码/)
  page.elements.creativeLibraryClose.click()
})

test('thumbnails appear independently, stay bounded, and abort when the library closes', async () => {
  const items = Array.from({length:8},(_,i)=>({generation_id:i.toString(16).padStart(32,'0'),thumbnail_url:'/api/rpg/image?name='+i+'.png'}))
  const pending = []
  const page = createPage((url, options) => {
    if (url.startsWith('/api/rpg/image')) {
      assert.equal(new URLSearchParams(url.split('?')[1]).get('preview'),'1')
      return new Promise((resolve) => pending.push({resolve,signal:options.signal}))
    }
    return Promise.resolve(response({items,total:8,has_more:false}))
  })
  page.elements.creativeLibraryOpen.click()
  await flush()
  assert.equal(pending.length,4)
  const firstThumb = page.elements.creativeLibraryList.children[0].children[0].children[0]
  const secondThumb = page.elements.creativeLibraryList.children[1].children[0].children[0]
  pending[0].resolve(response({}))
  await flush()
  assert.equal(firstThumb.children[0].tagName,'IMG')
  assert.equal(secondThumb.children[0].tagName,'SPAN')
  assert.equal(pending.length,5)
  page.elements.creativeLibraryClose.click()
  assert.ok(pending.slice(1).every((job)=>job.signal.aborted))
  pending.slice(1).forEach((job)=>job.resolve(response({})))
  await flush()
  assert.equal(pending.length,5, 'closed pages must not drain the old queue')
})

test('offscreen cards wait for intersection and returning pages reuse thumbnails', async () => {
  const items=Array.from({length:25},(_,i)=>({generation_id:i.toString(16).padStart(32,'0'),thumbnail_url:'/api/rpg/image?name='+i+'.png'}))
  let observer,images=0
  class Observer {
    constructor(callback){this.callback=callback;this.targets=[];observer=this}
    observe(target){this.targets.push(target)}
    unobserve(){}
    disconnect(){}
  }
  const page=createPage(async(url)=>{
    if(url.startsWith('/api/rpg/image')){images++;return response({})}
    if(url.startsWith('/api/rpg/library/generations?')){
      const offset=Number(new URLSearchParams(url.split('?')[1]).get('offset'))
      return response({items:items.slice(offset,offset+24),total:25,has_more:offset===0})
    }
    return response({})
  },{IntersectionObserver:Observer})
  page.elements.creativeLibraryOpen.click();await flush()
  assert.equal(images,0)
  observer.callback([{target:observer.targets[0],isIntersecting:true}]);await flush()
  assert.equal(images,1)
  page.elements.creativeLibraryNext.click();await flush()
  observer.callback([{target:observer.targets[0],isIntersecting:true}]);await flush()
  assert.equal(images,2)
  page.elements.creativeLibraryPrevious.click();await flush()
  observer.callback([{target:observer.targets[0],isIntersecting:true}]);await flush()
  assert.equal(images,2)
  assert.equal(page.elements.creativeLibraryList.children[0].children[0].children[0].children[0].tagName,'IMG')
  page.elements.creativeLibraryClose.click()
})

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
  assert.match(html, /snapshot-flow\.js\?v=3[\s\S]*creative-library\.js\?v=13/)
  assert.match(html, /panel\.css\?v=\d+/)
  assert.match(html, /id="pendingDerivation"/)
})

test('desktop generation routes consume and clear one-shot lineage context', () => {
  assert.match(panelSource, /function applyPendingDerivation\(/)
  assert.match(panelSource, /const body=payload\(\),count=(?:freshSeed\?1:)?generationCount\(\),outputSize=effectiveOutputSize\(\),submissionContext=beginGenerationProgress\(count\)/)
  assert.match(panelSource, /body:JSON\.stringify\(batchPayload\(body,index,submissionContext\)\)/)
  assert.match(panelSource, /const body=applyPendingDerivation\(payload\(\),pendingDerivationContext\)/)
  assert.match(panelSource, /function markPendingGenerationAccepted\(/)
  assert.match(panelSource, /clearPendingDerivationContext\(true\)/)
})

test('multi-image generate keeps one local lineage context after the first accepted child', () => {
  const match = panelSource.match(/function batchPayload\(base,index,context\)\{.*?\}(?=\r?\nfunction imageSource)/s)
  assert.ok(match, 'batchPayload must remain available for the generation route')
  const apply = (body, context) => context
    ? { ...body, parentGenerationId: context.parentGenerationId, operation: context.operation }
    : { ...body }
  const batchPayload = vm.runInNewContext(`(${match[0]})`, {
    BigInt,
    applyPendingDerivation: apply,
  })
  const submissionContext = Object.freeze({
    parentGenerationId: 'a'.repeat(32),
    operation: 'txt2img',
  })
  let globalContext = submissionContext
  const submitted = []
  for (let index = 0; index < 3; index += 1) {
    submitted.push(batchPayload({ prompt: 'same', seed: '41' }, index, submissionContext))
    if (index === 0) globalContext = null // markPendingGenerationAccepted clears only global UI state
  }
  assert.equal(globalContext, null)
  assert.deepEqual(submitted.map((item) => item.parentGenerationId), [
    'a'.repeat(32), 'a'.repeat(32), 'a'.repeat(32),
  ])
  assert.deepEqual(submitted.map((item) => item.seed), ['41', '42', '43'])
  const nextClick = batchPayload({ prompt: 'new', seed: '99' }, 0, globalContext)
  assert.equal(nextClick.parentGenerationId, undefined)
  assert.equal(nextClick.operation, undefined)
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

test('library restore creates a safe one-shot lineage context without an implicit artifact', () => {
  const detail = {
    generation_id: 'a'.repeat(32),
    operation: 'txt2img',
    artifacts: [{
      artifact_id: 'b'.repeat(32),
      filename: 'output.png',
      subfolder: '2026/08',
      exists: true,
    }],
  }
  assert.deepEqual(library.pendingDerivationContextForDetail(detail, 'continue-edit'), {
    parentGenerationId: 'a'.repeat(32),
    operation: 'txt2img',
  })
  assert.deepEqual(library.pendingDerivationContextForDetail({ ...detail, operation: 'img2img' }, 'continue-edit'), {
    parentGenerationId: 'a'.repeat(32),
    operation: 'img2img',
  })
  assert.equal(library.pendingDerivationContextForDetail(detail, 'seed-variant').operation, 'seed_variant')
  assert.deepEqual(library.attachPendingDerivationToPayload({ prompt: 'same' }, {
    parentGenerationId: 'a'.repeat(32),
    parentArtifactId: 'b'.repeat(32),
    operation: 'seed_variant',
  }), {
    prompt: 'same',
    parentGenerationId: 'a'.repeat(32),
    parentArtifactId: 'b'.repeat(32),
    operation: 'seed_variant',
  })
})

test('missing artifacts never become a concrete parent output', () => {
  const context = library.pendingDerivationContextForDetail({
    generation_id: 'c'.repeat(32),
    operation: 'txt2img',
    artifacts: [{ artifact_id: 'd'.repeat(32), filename: 'missing.png', exists: false }],
  }, 'continue-edit')
  assert.deepEqual(context, { parentGenerationId: 'c'.repeat(32), operation: 'txt2img' })
})

test('safe paths reject traversal, external origins, and HTML-shaped ids', () => {
  assert.throws(() => library.safeGenerationId('<img src=x onerror=alert(1)>'))
  assert.equal(library.safeLibraryImagePath('javascript:alert(1)', 'http://localhost:8190'), '')
  assert.equal(library.safeLibraryImagePath('http://evil.test/api/rpg/image?name=x.png', 'http://localhost:8190'), '')
  assert.equal(library.artifactPath({ filename: '../private.png' }, 'http://localhost:8190'), '')
  assert.equal(library.artifactPath({ filename: 'ok.png', subfolder: '../private' }, 'http://localhost:8190'), '/api/rpg/image?name=ok.png&type=output')
  assert.doesNotMatch(source, /innerHTML/)
  assert.match(source, /const response = await fetcher\(path, \{ method: 'GET'/)
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
  let pending
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
  page.root.setPendingDerivationContext = (context) => { pending = context }
  page.elements.creativeLibraryOpen.click()
  await flush()
  page.elements.creativeLibraryList.children[0].children[0].click()
  await flush()
  await flush()
  const actions = page.elements.creativeLibraryDetail.children.find((child) => child.className === 'creative-library-actions')
  assert.ok(actions)
  actions.children[0].click()
  assert.deepEqual(restored, { model: 'model.safetensors', quality: 'fast', prompt: 'safe prompt', seed: '7' })
  assert.equal(JSON.stringify(pending), JSON.stringify({ parentGenerationId: id, operation: 'txt2img' }))
  assert.match(page.elements.status.textContent, /手动点击“生成图片”/)
  assert.ok(calls.every(([, options]) => options.method === 'GET'))
  assert.equal(calls.some(([, options]) => options.method !== 'GET'), false)
})

test('closing a paged image gallery shows the viewed work and returns to its list page', async () => {
  const ids = Array.from({length: 49}, (_, index) => index.toString(16).padStart(32, '0'))
  const page = createPage(async (url) => {
    if (url.startsWith('/api/rpg/library/generations?')) {
      const offset = Number(new URLSearchParams(url.split('?')[1]).get('offset'))
      return response({items:ids.slice(offset, offset + 24).map((id) => ({
        generation_id:id, model:id, operation:'txt2img', status:'completed',
        thumbnail_url:'/api/rpg/image?name='+id+'.png',
      })), total:49, has_more:offset + 24 < 49})
    }
    if (url.endsWith('/lineage')) return response({lineage:{ancestors:[],descendants:[],edges:[]}})
    if (url.startsWith('/api/rpg/library/generations/')) {
      const id = url.split('/').pop()
      const artifact = {artifact_id:id, generation_id:id, filename:id+'.png', exists:true,
        url:'/api/rpg/image?name='+id+'.png'}
      return response({generation:{generation_id:id,model:id,operation:'txt2img',status:'completed',
        artifacts:[artifact],preview:{artifact_id:id},thumbnail_url:artifact.url,loras:[]}})
    }
    return response({})
  })
  let gallery
  page.root.openPanelImageGallery = (_event, images, index, onChange) => {
    gallery = {images,index,onChange}
    page.elements.panelImageViewer.open = true
    return false
  }
  page.elements.creativeLibraryOpen.click()
  await flush()
  page.elements.creativeLibraryNext.click()
  await flush()
  assert.equal(page.elements.creativeLibraryPageInfo.textContent, '第 2 / 3 页 · 25–48 / 49')
  page.elements.creativeLibraryListView.scrollTop = 180
  page.elements.creativeLibraryList.children[0].children[0].click()
  await flush()
  await flush()
  const preview = page.elements.creativeLibraryDetail.children[0].children[0]
  preview.children[0].click()
  assert.equal(gallery.index, 0)
  gallery.onChange(1)
  page.elements.panelImageViewer.close()
  await flush()
  await flush()
  const heading = page.elements.creativeLibraryDetail.children[0].children[1].children[0]
  assert.equal(heading.textContent, ids[25])
  page.elements.creativeLibraryBack.click()
  assert.equal(page.elements.creativeLibraryPageInfo.textContent, '第 2 / 3 页 · 25–48 / 49')
  assert.equal(page.elements.creativeLibraryListView.scrollTop, 180)
})
