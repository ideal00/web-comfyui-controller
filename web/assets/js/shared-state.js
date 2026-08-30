(function (root) {
  'use strict'

  const ENDPOINT = '/api/shared-state'
  const META_KEY = 'easyPanelSharedStateMetaV1'
  let activeSync = null

  function clone(value) {
    return JSON.parse(JSON.stringify(value))
  }

  function updatedAt(item) {
    const value = Number(item && item.updatedAt)
    return Number.isFinite(value) && value >= 0 ? value : 0
  }

  function fingerprint(item) {
    const rawSections = item && item.sections && typeof item.sections === 'object' ? item.sections : {}
    const sections = {}
    Object.keys(rawSections).sort().forEach((key) => { sections[key] = String(rawSections[key] || '') })
    return JSON.stringify([
      String(item && item.name || '').trim(),
      String(item && item.category || '').trim(),
      String(item && item.content || '').trim(),
      sections,
    ])
  }

  function mergePromptPresets(left, right) {
    const result = []
    const add = (item, allowReplacement) => {
      if (!item || typeof item !== 'object') return
      const id = typeof item.id === 'string' ? item.id : ''
      let index = id ? result.findIndex((entry) => entry.id === id) : -1
      if (index < 0) index = result.findIndex((entry) => fingerprint(entry) === fingerprint(item))
      if (index < 0) {
        result.push(clone(item))
      } else if (allowReplacement && updatedAt(item) > updatedAt(result[index])) {
        result[index] = clone(item)
      }
    }
    ;(Array.isArray(left) ? left : []).forEach((item) => add(item, false))
    ;(Array.isArray(right) ? right : []).forEach((item) => add(item, true))
    return result.sort((a, b) => updatedAt(b) - updatedAt(a) || String(a.id || '').localeCompare(String(b.id || '')))
  }

  function mergeStates(left, right) {
    const a = left && typeof left === 'object' ? left : {}
    const b = right && typeof right === 'object' ? right : {}
    const favorites = []
    ;(Array.isArray(a.characterFavorites) ? a.characterFavorites : [])
      .concat(Array.isArray(b.characterFavorites) ? b.characterFavorites : [])
      .forEach((value) => {
        if (typeof value !== 'string') return
        const normalized = value.trim().replace(/\\/g, '/')
        if (normalized && !favorites.includes(normalized)) favorites.push(normalized)
      })
    favorites.sort((x, y) => x.localeCompare(y))
    return {
      schema: Number.isInteger(b.schema) ? b.schema : (Number.isInteger(a.schema) ? a.schema : 1),
      revision: Number.isInteger(b.revision) ? b.revision : (Number.isInteger(a.revision) ? a.revision : 0),
      updatedAt: Math.max(Number(a.updatedAt) || 0, Number(b.updatedAt) || 0),
      promptPresets: mergePromptPresets(a.promptPresets, b.promptPresets),
      characterFavorites: favorites,
    }
  }

  function hasData(state) {
    return Boolean(
      state && (
        (Array.isArray(state.promptPresets) && state.promptPresets.length) ||
        (Array.isArray(state.characterFavorites) && state.characterFavorites.length)
      ),
    )
  }

  function bridge() {
    return root.EasyPanelSharedStateBridge
  }

  function setStatus(kind, message) {
    const status = root.document && root.document.getElementById('sharedStateSyncStatus')
    const button = root.document && root.document.getElementById('sharedStateSyncButton')
    if (status) {
      status.textContent = message
      status.dataset.state = kind
    }
    if (button) button.disabled = kind === 'busy'
  }

  function ensureUi() {
    const document = root.document
    if (!document || document.getElementById('sharedStateSyncPanel')) return
    const anchor = document.getElementById('userPresetStatus')
    if (!anchor || !anchor.parentElement) return
    const panel = document.createElement('div')
    panel.id = 'sharedStateSyncPanel'
    panel.className = 'shared-state-sync'
    const copy = document.createElement('div')
    copy.className = 'shared-state-sync-copy'
    const title = document.createElement('b')
    title.textContent = '跨设备同步'
    const status = document.createElement('span')
    status.id = 'sharedStateSyncStatus'
    status.className = 'small'
    status.textContent = '首次打开会自动合并本机预设与角色收藏；不会删除本机数据。'
    copy.append(title, status)
    const button = document.createElement('button')
    button.id = 'sharedStateSyncButton'
    button.type = 'button'
    button.className = 'secondary'
    button.textContent = '立即同步'
    button.addEventListener('click', () => { void syncEasyPanelSharedState({ manual: true }) })
    panel.append(copy, button)
    anchor.parentElement.appendChild(panel)
  }

  function saveRevision(revision) {
    try {
      root.localStorage.setItem(META_KEY, JSON.stringify({ revision, syncedAt: Date.now() }))
    } catch (_) {
      // Shared data remains in the server/local collection when metadata storage is unavailable.
    }
  }

  async function request(url, options) {
    const response = await root.fetch(url, options)
    let data = {}
    try { data = await response.json() } catch (_) { data = {} }
    if (!response.ok) throw new Error(data.error || `服务器返回 HTTP ${response.status}`)
    return data
  }

  async function syncEasyPanelSharedState() {
    if (activeSync) return activeSync
    ensureUi()
    const currentBridge = bridge()
    if (!currentBridge || typeof currentBridge.read !== 'function' || typeof currentBridge.write !== 'function') {
      setStatus('error', '同步适配器未加载；本机数据未改变，请刷新页面后重试。')
      return { ok: false, reason: 'bridge_unavailable' }
    }
    const localSnapshot = clone(currentBridge.read())
    setStatus('busy', '正在读取服务器共享状态…')
    activeSync = (async () => {
      try {
        const remoteResponse = await request(ENDPOINT, { cache: 'no-store' })
        const serverState = remoteResponse.state || remoteResponse
        if (!serverState || typeof serverState !== 'object') throw new Error('服务器共享状态格式无效。')
        if (!hasData(localSnapshot)) {
          if (hasData(serverState)) {
            currentBridge.write(serverState)
            saveRevision(Number(serverState.revision) || 0)
            setStatus('success', `已从服务器读取 ${serverState.promptPresets?.length || 0} 个预设、${serverState.characterFavorites?.length || 0} 个角色收藏。`)
          } else {
            saveRevision(Number(serverState.revision) || 0)
            setStatus('success', '已连接服务器，当前还没有共享预设或角色收藏。')
          }
          return { ok: true, state: serverState, pulled: hasData(serverState) }
        }

        setStatus('busy', '正在安全合并本机与服务器数据…')
        const result = await request(ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            baseRevision: Number.isInteger(serverState.revision) ? serverState.revision : 0,
            state: localSnapshot,
          }),
        })
        let merged = result.state || serverState
        const currentAfterRequest = clone(currentBridge.read())
        if (JSON.stringify(currentAfterRequest) !== JSON.stringify(localSnapshot)) {
          merged = mergeStates(merged, currentAfterRequest)
        }
        currentBridge.write(merged)
        saveRevision(Number(merged.revision) || 0)
        if (result.conflict) {
          setStatus('conflict', `检测到其他设备有更新，已合并 ${merged.promptPresets?.length || 0} 个预设、${merged.characterFavorites?.length || 0} 个角色收藏；未覆盖服务器较新的记录。`)
        } else if (result.recovered) {
          setStatus('success', '服务器已从备份恢复，并完成本机数据同步。')
        } else {
          setStatus('success', `同步完成：${merged.promptPresets?.length || 0} 个预设、${merged.characterFavorites?.length || 0} 个角色收藏。`)
        }
        return result
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        setStatus('offline', `同步失败：${message}；本机数据仍保留，联网后可再次点击“立即同步”。`)
        return { ok: false, reason: 'request_failed', error: message }
      } finally {
        activeSync = null
      }
    })()
    return activeSync
  }

  root.syncEasyPanelSharedState = syncEasyPanelSharedState
  root.EasyPanelSharedState = {
    endpoint: ENDPOINT,
    metadataKey: META_KEY,
    fingerprint,
    mergeStates,
    hasData,
    sync: syncEasyPanelSharedState,
  }

  function initialize() {
    if (root.__easyPanelSharedStateInitialized) return
    root.__easyPanelSharedStateInitialized = true
    ensureUi()
    if (typeof root.addEventListener === 'function') {
      root.addEventListener('online', () => { void syncEasyPanelSharedState({ reconnect: true }) })
    }
    void syncEasyPanelSharedState({ initial: true })
  }

  if (root.document) {
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', initialize)
    else initialize()
  }
})(window)
