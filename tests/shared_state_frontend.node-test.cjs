const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'assets', 'js', 'shared-state.js'),
  'utf8',
)

function storage() {
  const values = new Map()
  return {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
}

function response(data, ok = true, status = 200) {
  return { ok, status, json: async () => data }
}

function loadContext(fetch) {
  const root = {
    document: { readyState: 'loading', addEventListener() {}, getElementById() { return null } },
    localStorage: storage(),
    fetch,
    addEventListener() {},
  }
  vm.runInNewContext(source, { window: root, Date, JSON, Number, String, Error })
  return root
}

function preset(id, content, updatedAt = 100) {
  return { id, name: 'fixture', category: 'pose', content, sections: {}, updatedAt }
}

test('desktop localStorage data migrates to the server without putting a token in the URL', async () => {
  let state = { promptPresets: [preset('desktop', 'standing')], characterFavorites: ['characters/alice.safetensors'] }
  const calls = []
  const root = loadContext(async (url, options = {}) => {
    calls.push([url, options])
    if (!options.method) return response({ state: { schema: 1, revision: 0, updatedAt: 0, promptPresets: [], characterFavorites: [] } })
    const submitted = JSON.parse(options.body)
    return response({ ok: true, changed: true, conflict: false, state: { schema: 1, revision: 1, updatedAt: 1, ...submitted.state } })
  })
  root.EasyPanelSharedStateBridge = { read: () => JSON.parse(JSON.stringify(state)), write: (next) => { state = JSON.parse(JSON.stringify(next)) } }

  const result = await root.EasyPanelSharedState.sync()
  assert.equal(result.ok, true)
  assert.equal(calls[0][0], '/api/shared-state')
  assert.equal(calls[1][0], '/api/shared-state')
  assert.equal(calls[1][1].method, 'POST')
  assert.match(calls[1][1].body, /baseRevision/)
  assert.doesNotMatch(calls[1][0], /token|secret|authorization/i)
  assert.deepEqual(state.characterFavorites, ['characters/alice.safetensors'])
})

test('an empty mobile collection pulls server state and never posts an empty overwrite', async () => {
  let state = { promptPresets: [], characterFavorites: [] }
  const calls = []
  const server = { schema: 1, revision: 4, updatedAt: 4, promptPresets: [preset('computer', 'computer')], characterFavorites: ['characters/kept.safetensors'] }
  const root = loadContext(async (url, options = {}) => {
    calls.push([url, options])
    return response({ state: server })
  })
  root.EasyPanelSharedStateBridge = { read: () => JSON.parse(JSON.stringify(state)), write: (next) => { state = JSON.parse(JSON.stringify(next)) } }

  const result = await root.EasyPanelSharedState.sync()
  assert.equal(result.pulled, true)
  assert.equal(calls.length, 1)
  assert.deepEqual(state.characterFavorites, server.characterFavorites)
  assert.equal(root.EasyPanelSharedState.hasData(state), true)
})

test('offline sync keeps local state intact and the merge helper deduplicates by id/fingerprint', async () => {
  const local = { promptPresets: [preset('local', 'local')], characterFavorites: ['characters/local.safetensors'] }
  let state = JSON.parse(JSON.stringify(local))
  const root = loadContext(async () => { throw new Error('offline') })
  root.EasyPanelSharedStateBridge = { read: () => JSON.parse(JSON.stringify(state)), write: (next) => { state = JSON.parse(JSON.stringify(next)) } }

  const result = await root.EasyPanelSharedState.sync()
  assert.equal(result.ok, false)
  assert.deepEqual(state, local)

  const merged = root.EasyPanelSharedState.mergeStates(
    { promptPresets: [preset('same', 'old', 10)], characterFavorites: ['characters/a.safetensors'] },
    { promptPresets: [preset('same', 'new', 20), preset('duplicate', 'new', 30)], characterFavorites: ['characters/a.safetensors', 'characters/b.safetensors'] },
  )
  assert.equal(merged.promptPresets.length, 1)
  assert.equal(merged.promptPresets[0].content, 'new')
  assert.deepEqual(JSON.parse(JSON.stringify(merged.characterFavorites)), ['characters/a.safetensors', 'characters/b.safetensors'])
})
