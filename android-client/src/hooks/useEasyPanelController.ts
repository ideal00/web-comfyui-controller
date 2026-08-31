import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  buildEasyPanelControllerRequest,
  attachEasyPanelPendingDerivation,
  controllerStatusLabel,
  createEasyPanelControllerRequestId,
  defaultEasyPanelControllerState,
  EASY_PANEL_CONTROLLER_STATE_KEY,
  extractEasyPanelModels,
  isControllerBusy,
  normalizeEasyPanelControllerSettings,
  normalizeEasyPanelControllerState,
  reduceEasyPanelControllerInteraction,
  type EasyPanelControllerImage,
  type EasyPanelControllerSettings,
  type EasyPanelControllerState,
  type EasyPanelPendingDerivationContext,
  type PendingEasyPanelJob,
} from '../lib/easyPanelController'
import { downloadBlob } from '../platform/browserDownload'
import { readStoredState, writeStoredState } from '../platform/stateStore'
import { deletePortraitFile, portraitSource, readPortraitBase64, savePortraitBase64 } from '../lib/portraits'
import {
  blobToBase64,
  downloadVisualImage,
  EasyPanelHttpError,
  getEasyPanelCapabilities,
  getEasyPanelModels,
  normalizeEasyPanelBaseUrl,
  pingEasyPanel,
  recoverVisualJob,
  submitVisualJob,
  waitForVisualJob,
  type EasyPanelVisualConfig,
  type VisualJobStatus,
} from '../services/easyPanelVisual'
import {
  getEasyPanelGeneration,
  getEasyPanelLineage,
  getEasyPanelLibrary,
} from '../services/easyPanelLibrary'
import type {
  EasyPanelGenerationArtifact,
  EasyPanelGenerationDetail,
  EasyPanelGenerationSummary,
  EasyPanelLibraryLineage,
} from '../services/easyPanelLibrary'
import {
  getEasyPanelSnapshot,
  getEasyPanelSnapshots,
  type EasyPanelSnapshotRecord,
  type EasyPanelSnapshotSummary,
} from '../services/easyPanelSnapshots'
import {
  restoreSnapshotToSettings,
  type EasyPanelSnapshotRestoreMode,
} from '../lib/easyPanelSnapshot'
import {
  restoreLibraryGenerationToSettings,
  type EasyPanelLibraryRestoreMode,
} from '../lib/easyPanelLibrary'

export type EasyPanelControllerStatus =
  | 'idle'
  | 'checking'
  | 'recovering'
  | 'submitting'
  | 'queued'
  | 'running'
  | 'saving'
  | 'completed'
  | 'error'

export interface EasyPanelController {
  hydrated: boolean
  settings: EasyPanelControllerSettings
  status: EasyPanelControllerStatus
  statusLabel: string
  job?: VisualJobStatus
  image?: EasyPanelControllerImage
  imageSource: string
  models: string[]
  capabilities: Record<string, unknown> | null
  connectionMessage: string
  error: string
  pendingJob?: PendingEasyPanelJob
  modelsLoading: boolean
  modelsMessage: string
  modelsError: string
  downloadLoading: boolean
  downloadMessage: string
  snapshots: EasyPanelSnapshotSummary[]
  snapshotsLoading: boolean
  snapshotsMessage: string
  snapshotsError: string
  restoredSnapshot?: EasyPanelSnapshotRecord
  library: EasyPanelGenerationSummary[]
  libraryLoading: boolean
  libraryMessage: string
  libraryError: string
  libraryDetail?: EasyPanelGenerationDetail
  libraryLineage?: EasyPanelLibraryLineage
  libraryThumbnailSources: Record<string, string>
  libraryDownloadLoading: string
  libraryDownloadMessage: string
  pendingDerivation?: EasyPanelPendingDerivationContext
  setSettings: (settings: EasyPanelControllerSettings) => void
  testConnection: () => Promise<void>
  refreshModels: () => Promise<void>
  generate: () => Promise<void>
  recoverPending: () => Promise<void>
  clearPending: () => Promise<void>
  clearImage: () => Promise<void>
  downloadCurrent: () => Promise<void>
  refreshSnapshots: () => Promise<void>
  restoreSnapshot: (id: string, mode?: EasyPanelSnapshotRestoreMode) => Promise<boolean>
  clearSnapshotAdvancedConfig: () => void
  refreshLibrary: () => Promise<void>
  openLibraryGeneration: (id: string) => Promise<boolean>
  clearLibraryDetail: () => void
  restoreLibraryGeneration: (mode?: EasyPanelLibraryRestoreMode) => Promise<boolean>
  clearPendingDerivation: () => void
  downloadLibraryArtifact: (artifact: EasyPanelGenerationArtifact) => Promise<void>
}

const CONTROLLER_GAME_ID = 'easy-panel-mobile'

export function useEasyPanelController(): EasyPanelController {
  const [state, setState] = useState<EasyPanelControllerState>(() => defaultEasyPanelControllerState())
  const [hydrated, setHydrated] = useState(false)
  const [status, setStatus] = useState<EasyPanelControllerStatus>('idle')
  const [job, setJob] = useState<VisualJobStatus>()
  const [models, setModels] = useState<string[]>([])
  const [capabilities, setCapabilities] = useState<Record<string, unknown> | null>(null)
  const [connectionMessage, setConnectionMessage] = useState('尚未连接电脑')
  const [error, setError] = useState('')
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsMessage, setModelsMessage] = useState('连接后读取模型')
  const [modelsError, setModelsError] = useState('')
  const [downloadLoading, setDownloadLoading] = useState(false)
  const [downloadMessage, setDownloadMessage] = useState('')
  const [snapshots, setSnapshots] = useState<EasyPanelSnapshotSummary[]>([])
  const [snapshotsLoading, setSnapshotsLoading] = useState(false)
  const [snapshotsMessage, setSnapshotsMessage] = useState('连接后刷新电脑端历史快照')
  const [snapshotsError, setSnapshotsError] = useState('')
  const [restoredSnapshot, setRestoredSnapshot] = useState<EasyPanelSnapshotRecord>()
  const [library, setLibrary] = useState<EasyPanelGenerationSummary[]>([])
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [libraryMessage, setLibraryMessage] = useState('连接后读取作品库')
  const [libraryError, setLibraryError] = useState('')
  const [libraryDetail, setLibraryDetail] = useState<EasyPanelGenerationDetail>()
  const [libraryLineage, setLibraryLineage] = useState<EasyPanelLibraryLineage>()
  const [libraryThumbnailSources, setLibraryThumbnailSources] = useState<Record<string, string>>({})
  const [libraryDownloadLoading, setLibraryDownloadLoading] = useState('')
  const [libraryDownloadMessage, setLibraryDownloadMessage] = useState('')
  const [pendingDerivation, setPendingDerivation] = useState<EasyPanelPendingDerivationContext>()
  const stateRef = useRef(state)
  const activeRef = useRef(false)
  const hydratedRecoveryRef = useRef(false)
  const recoveryRef = useRef<(() => Promise<void>) | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const libraryRequestRef = useRef(0)
  const libraryThumbnailUrlsRef = useRef<Record<string, string>>({})

  const settings = state.settings
  const config = useMemo<EasyPanelVisualConfig>(() => ({
    baseUrl: settings.baseUrl,
    token: settings.token,
    pollIntervalMs: settings.pollIntervalMs,
    requestTimeoutMs: 15000,
  }), [settings.baseUrl, settings.pollIntervalMs, settings.token])

  const commitState = useCallback((next: EasyPanelControllerState) => {
    stateRef.current = next
    setState(next)
    void writeStoredState(EASY_PANEL_CONTROLLER_STATE_KEY, JSON.stringify(next)).catch(() => undefined)
  }, [])

  const clearLibraryThumbnailSources = useCallback(() => {
    for (const source of Object.values(libraryThumbnailUrlsRef.current)) URL.revokeObjectURL(source)
    libraryThumbnailUrlsRef.current = {}
    setLibraryThumbnailSources({})
  }, [])

  useEffect(() => {
    let cancelled = false
    void readStoredState(EASY_PANEL_CONTROLLER_STATE_KEY).then((raw) => {
      if (cancelled) return
      let parsed: Partial<EasyPanelControllerState> | undefined
      if (raw) {
        try {
          parsed = JSON.parse(raw) as Partial<EasyPanelControllerState>
        } catch {
          parsed = undefined
        }
      }
      const next = normalizeEasyPanelControllerState(parsed)
      stateRef.current = next
      setState(next)
      setHydrated(true)
    }).catch(() => {
      if (!cancelled) setHydrated(true)
    })
    return () => { cancelled = true }
  }, [])

  const setSettings = useCallback((nextSettings: EasyPanelControllerSettings) => {
    const normalized = normalizeEasyPanelControllerSettings(nextSettings)
    const previous = stateRef.current.settings
    commitState({ ...stateRef.current, settings: normalized })
    if (normalized.baseUrl !== previous.baseUrl || normalized.token !== previous.token) {
      setModels([])
      setModelsMessage('地址或 Token 已改变，请重新读取模型')
      setModelsError('')
      setSnapshots([])
      setSnapshotsMessage('地址或 Token 已改变，请重新读取历史快照')
      setSnapshotsError('')
      setRestoredSnapshot(undefined)
      setLibrary([])
      setLibraryMessage('地址或 Token 已改变，请重新读取作品库')
      setLibraryError('')
      setLibraryDetail(undefined)
      setLibraryLineage(undefined)
      setLibraryDownloadMessage('')
      setPendingDerivation(undefined)
      clearLibraryThumbnailSources()
    }
    setDownloadMessage('')
    setError('')
  }, [clearLibraryThumbnailSources, commitState])

  const loadModelCatalog = useCallback(async (nextConfig: EasyPanelVisualConfig): Promise<number | undefined> => {
    setModelsLoading(true)
    setModelsMessage('正在读取电脑端模型…')
    setModelsError('')
    try {
      const payload = await getEasyPanelModels(nextConfig)
      const nextModels = extractEasyPanelModels(payload)
      setModels(nextModels)
      if (nextModels.length === 0) {
        setModelsMessage('接口已响应，但没有可用模型')
        setModelsError('模型列表为空，请检查电脑端 ComfyUI 的模型目录和加载状态。')
      } else {
        setModelsMessage(`已加载 ${nextModels.length} 个可用模型`)
      }
      return nextModels.length
    } catch (caught) {
      setModelsMessage('模型列表读取失败')
      setModelsError(errorMessage(caught, settings.token, '读取模型'))
      return undefined
    } finally {
      setModelsLoading(false)
    }
  }, [settings.token])

  const testConnection = useCallback(async () => {
    let normalizedUrl: string
    try {
      normalizedUrl = normalizeEasyPanelBaseUrl(settings.baseUrl)
    } catch (caught) {
      setError(errorMessage(caught, settings.token, '地址'))
      setConnectionMessage('地址未通过校验')
      setStatus('error')
      return
    }
    if (!settings.token.trim()) {
      setError('请填写 RPG Token。Token 是电脑端移动 API 的访问凭据。')
      setConnectionMessage('缺少 Token')
      setStatus('error')
      return
    }
    if (normalizedUrl !== settings.baseUrl) {
      const nextSettings = { ...settings, baseUrl: normalizedUrl }
      commitState({ ...stateRef.current, settings: normalizeEasyPanelControllerSettings(nextSettings) })
    }
    setStatus('checking')
    setError('')
    setConnectionMessage('正在检查 Easy Panel 和电脑端 ComfyUI…')
    try {
      const nextConfig = { ...config, baseUrl: normalizedUrl }
      const ping = await pingEasyPanel(nextConfig)
      if (!ping.ok) throw new Error('Easy Panel 返回了不可用状态。')
      const nextCapabilities = await getEasyPanelCapabilities(nextConfig)
      setCapabilities(nextCapabilities)
      setConnectionMessage(`已连接 · API v${ping.api_version} · 电脑端 ComfyUI 就绪`)
      setStatus('idle')
      // A connection check also warms the real model picker. A model-list
      // failure is reported beside the picker without turning a healthy ping
      // into a false connection failure.
      await loadModelCatalog(nextConfig)
    } catch (caught) {
      setConnectionMessage('连接失败')
      setError(errorMessage(caught, settings.token, '连接'))
      setStatus('error')
    }
  }, [commitState, config, loadModelCatalog, settings])

  const refreshModels = useCallback(async () => {
    try {
      normalizeEasyPanelBaseUrl(settings.baseUrl)
    } catch (caught) {
      setError(errorMessage(caught, settings.token, '地址'))
      return
    }
    if (!settings.token.trim()) {
      setError('请先填写 RPG Token，再读取电脑端模型。')
      return
    }
    setError('')
    const count = await loadModelCatalog(config)
    if (count === undefined) {
      setError('读取模型失败：请查看“Checkpoint”选择框下方的具体提示。')
    } else if (count === 0) {
      setConnectionMessage('已连接，但电脑端没有返回可用模型')
    } else {
      setConnectionMessage(`已读取 ${count} 个可用模型`)
    }
  }, [config, loadModelCatalog, settings.baseUrl, settings.token])

  const refreshSnapshots = useCallback(async () => {
    try {
      normalizeEasyPanelBaseUrl(settings.baseUrl)
    } catch (caught) {
      setSnapshotsError(errorMessage(caught, settings.token, '读取历史'))
      return
    }
    if (!settings.token.trim()) {
      setSnapshotsError('请先填写 RPG Token，再读取电脑端历史快照。')
      return
    }
    setSnapshotsLoading(true)
    setSnapshotsError('')
    setSnapshotsMessage('正在读取电脑端历史快照…')
    try {
      const response = await getEasyPanelSnapshots(config, 20)
      setSnapshots(response.snapshots)
      setSnapshotsMessage(response.snapshots.length ? `已读取 ${response.snapshots.length} 条服务器快照` : '电脑端暂无历史快照')
    } catch (caught) {
      setSnapshotsMessage('历史快照读取失败')
      setSnapshotsError(errorMessage(caught, settings.token, '读取历史'))
    } finally {
      setSnapshotsLoading(false)
    }
  }, [config, settings.baseUrl, settings.token])

  const loadLibraryThumbnails = useCallback(async (
    items: EasyPanelGenerationSummary[],
    nextConfig: EasyPanelVisualConfig,
    requestNumber: number,
  ) => {
    if (typeof URL.createObjectURL !== 'function') return
    const loaded = await Promise.all(items.map(async (item) => {
      if (!item.thumbnail_url) return undefined
      try {
        const blob = await downloadVisualImage(nextConfig, {
          filename: `${item.generation_id}.png`,
          type: 'output',
          url: item.thumbnail_url,
        })
        return { id: item.generation_id, source: URL.createObjectURL(blob) }
      } catch {
        return undefined
      }
    }))
    if (libraryRequestRef.current !== requestNumber) {
      for (const item of loaded) if (item) URL.revokeObjectURL(item.source)
      return
    }
    const nextSources: Record<string, string> = {}
    for (const item of loaded) if (item) nextSources[item.id] = item.source
    for (const source of Object.values(libraryThumbnailUrlsRef.current)) {
      if (!Object.values(nextSources).includes(source)) URL.revokeObjectURL(source)
    }
    libraryThumbnailUrlsRef.current = nextSources
    setLibraryThumbnailSources(nextSources)
  }, [])

  const refreshLibrary = useCallback(async () => {
    try {
      normalizeEasyPanelBaseUrl(settings.baseUrl)
    } catch (caught) {
      setLibraryError(errorMessage(caught, settings.token, '读取作品库'))
      return
    }
    if (!settings.token.trim()) {
      setLibraryError('请先填写 RPG Token，再读取电脑端作品库。')
      return
    }
    const requestNumber = libraryRequestRef.current + 1
    libraryRequestRef.current = requestNumber
    clearLibraryThumbnailSources()
    setLibraryDetail(undefined)
    setLibraryLineage(undefined)
    setLibraryLoading(true)
    setLibraryError('')
    setLibraryMessage('正在读取电脑端作品库…')
    try {
      const response = await getEasyPanelLibrary(config, { limit: 30, offset: 0, sort: 'created_at', order: 'desc' })
      if (libraryRequestRef.current !== requestNumber) return
      setLibrary(response.items)
      setLibraryMessage(response.items.length ? `已读取 ${response.items.length} 条作品${response.has_more ? '，下拉刷新可继续查看最新页' : ''}` : '电脑端暂无可用作品')
      void loadLibraryThumbnails(response.items, config, requestNumber)
    } catch (caught) {
      setLibraryMessage('作品库读取失败')
      setLibraryError(errorMessage(caught, settings.token, '读取作品库'))
    } finally {
      if (libraryRequestRef.current === requestNumber) setLibraryLoading(false)
    }
  }, [clearLibraryThumbnailSources, config, loadLibraryThumbnails, settings.baseUrl, settings.token])

  const openLibraryGeneration = useCallback(async (id: string) => {
    try {
      normalizeEasyPanelBaseUrl(settings.baseUrl)
    } catch (caught) {
      setLibraryError(errorMessage(caught, settings.token, '读取作品详情'))
      return false
    }
    if (!settings.token.trim()) {
      setLibraryError('请先填写 RPG Token，再查看作品详情。')
      return false
    }
    setLibraryLoading(true)
    setLibraryError('')
    setLibraryMessage('正在读取作品详情…')
    try {
      const response = await getEasyPanelGeneration(config, id)
      setLibraryDetail(response.generation)
      let lineageAvailable = false
      try {
        const lineage = await getEasyPanelLineage(config, id)
        setLibraryLineage(lineage.lineage)
        lineageAvailable = true
      } catch {
        setLibraryLineage(undefined)
        setLibraryMessage('详情已加载；当前电脑端未提供谱系信息。')
      }
      if (lineageAvailable) setLibraryMessage('详情已加载；可恢复到当前表单后再显式点击生成。')
      return true
    } catch (caught) {
      setLibraryDetail(undefined)
      setLibraryLineage(undefined)
      setLibraryMessage('作品详情读取失败')
      setLibraryError(errorMessage(caught, settings.token, '读取作品详情'))
      return false
    } finally {
      setLibraryLoading(false)
    }
  }, [config, settings.baseUrl, settings.token])

  const restoreLibraryGeneration = useCallback(async (
    mode: EasyPanelLibraryRestoreMode = 'reproduce',
  ) => {
    const generation = libraryDetail
    if (!generation) {
      setLibraryError('请先打开一条作品详情。')
      return false
    }
    try {
      const restored = restoreLibraryGenerationToSettings(settings, generation, mode)
      setRestoredSnapshot(restored.snapshot)
      setPendingDerivation(restored.derivation)
      commitState({ ...stateRef.current, settings: restored.settings })
      const modeLabel = mode === 'seed-variant' ? '已载入作品并更换 Seed' : mode === 'continue-edit' ? '已载入作品，可继续编辑' : '已载入作品参数'
      setLibraryMessage(`${modeLabel}；将从该作品派生（不会自动选择输出图作为编辑输入），可取消关联；请回到当前表单，确认后点击“生成图片”。`)
      setLibraryError('')
      setError('')
      return true
    } catch (caught) {
      setLibraryError(errorMessage(caught, settings.token, '恢复作品'))
      return false
    }
  }, [commitState, libraryDetail, settings])

  const clearPendingDerivation = useCallback(() => {
    setPendingDerivation(undefined)
    setLibraryMessage('已取消派生关联；后续按当前表单的普通生图参数提交。')
    setError('')
  }, [])

  const clearLibraryDetail = useCallback(() => {
    setLibraryDetail(undefined)
    setLibraryLineage(undefined)
    setLibraryError('')
    setLibraryDownloadMessage('')
  }, [])

  const downloadLibraryArtifact = useCallback(async (artifact: EasyPanelGenerationArtifact) => {
    if (!artifact.url || artifact.exists === false || libraryDownloadLoading) return
    setLibraryDownloadLoading(artifact.artifact_id)
    setLibraryDownloadMessage('正在下载作品…')
    try {
      const blob = await downloadVisualImage(config, {
        filename: artifact.filename,
        subfolder: artifact.subfolder,
        type: artifact.type,
        url: artifact.url,
      })
      const filename = (artifact.filename || 'easy-panel-library.png').replace(/[\\/:*?"<>|]/gu, '_')
      const result = await downloadBlob(blob, filename || 'easy-panel-library.png')
      setLibraryDownloadMessage(result.location ? `已保存：${result.location}` : '已交给浏览器下载，请检查下载通知。')
      setError('')
    } catch (caught) {
      setLibraryDownloadMessage('作品下载失败')
      setLibraryError(errorMessage(caught, settings.token, '下载作品'))
    } finally {
      setLibraryDownloadLoading('')
    }
  }, [config, libraryDownloadLoading, settings.token])

  const restoreSnapshot = useCallback(async (
    snapshotId: string,
    mode: EasyPanelSnapshotRestoreMode = 'full',
  ) => {
    try {
      normalizeEasyPanelBaseUrl(settings.baseUrl)
    } catch (caught) {
      setSnapshotsError(errorMessage(caught, settings.token, '恢复快照'))
      return false
    }
    if (!settings.token.trim()) {
      setSnapshotsError('请先填写 RPG Token，再恢复电脑端快照。')
      return false
    }
    setSnapshotsLoading(true)
    setSnapshotsError('')
    try {
      const response = await getEasyPanelSnapshot(config, snapshotId)
      const detail = response.snapshot
      const restored = restoreSnapshotToSettings(settings, detail, mode)
      setRestoredSnapshot(detail)
      commitState({ ...stateRef.current, settings: restored.settings })
      const modeLabel = mode === 'seed-only' ? '已恢复快照并只更换 Seed' : mode === 'continue-editing' ? '已恢复快照，可继续编辑' : '已完整载入快照'
      setSnapshotsMessage(`${modeLabel}；服务器记录的高级参数共 ${restored.advancedFieldCount} 项，当前页面可继续编辑基础字段。`)
      setError('')
      return true
    } catch (caught) {
      setSnapshotsError(errorMessage(caught, settings.token, '恢复快照'))
      return false
    } finally {
      setSnapshotsLoading(false)
    }
  }, [commitState, config, settings])

  const clearSnapshotAdvancedConfig = useCallback(() => {
    setRestoredSnapshot(undefined)
    setSnapshotsError('')
    setSnapshotsMessage('已解除快照高级配置；后续按当前页面的普通生图参数提交。')
    setError('')
  }, [])

  const saveCompleted = useCallback(async (completed: VisualJobStatus) => {
    if (completed.status === 'error') throw new Error(formatJobError(completed.error))
    const image = completed.images[0]
    if (!image) throw new Error('任务已完成，但 Easy Panel 没有返回图片。')
    setStatus('saving')
    const blob = await downloadVisualImage(config, image)
    const uri = await savePortraitBase64(CONTROLLER_GAME_ID, 'latest', await blobToBase64(blob), extensionForBlob(blob))
    const previous = stateRef.current.image
    if (previous && previous.uri !== uri) void deletePortraitFile(previous.uri)
    const savedImage: EasyPanelControllerImage = {
      uri,
      filename: image.filename || 'easy-panel-output.png',
      type: blob.type || image.type || 'image/png',
      savedAt: Date.now(),
    }
    commitState({ ...stateRef.current, image: savedImage, pendingJob: undefined })
    setJob(completed)
    setStatus('completed')
  }, [commitState, config])

  const followJob = useCallback(async (initial: VisualJobStatus, pending: PendingEasyPanelJob) => {
    setJob(initial)
    if (initial.status === 'completed') {
      await saveCompleted(initial)
      return
    }
    if (initial.status === 'error') throw new Error(formatJobError(initial.error))
    setStatus(initial.status === 'running' ? 'running' : 'queued')
    const completed = await waitForVisualJob(config, initial, abortRef.current?.signal, (next) => {
      setJob(next)
      setStatus(next.status === 'running' ? 'running' : next.status === 'queued' ? 'queued' : next.status === 'error' ? 'error' : 'saving')
    })
    if (completed.status === 'error') throw new Error(formatJobError(completed.error))
    await saveCompleted(completed)
    if (stateRef.current.pendingJob?.requestId === pending.requestId) {
      commitState({ ...stateRef.current, pendingJob: undefined })
    }
  }, [commitState, config, saveCompleted])

  const recoverPending = useCallback(async () => {
    const pending = stateRef.current.pendingJob
    if (!pending || activeRef.current) return
    activeRef.current = true
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    setStatus('recovering')
    setError('')
    try {
      let initial: VisualJobStatus
      try {
        initial = await recoverVisualJob(config, pending.requestId)
      } catch (caught) {
        // A missing server record must never silently create a second job.
        // The user can explicitly press the generate button if a new job is
        // desired; recovery itself only resumes an existing requestId.
        if (caught instanceof EasyPanelHttpError && caught.status === 404) {
          throw new Error('电脑端没有找到这条未完成任务，未重新提交；如需重新生成，请点击“生成图片”。')
        }
        throw caught
      }
      const nextPending = { ...pending, jobId: initial.job_id || pending.jobId }
      commitState({ ...stateRef.current, pendingJob: nextPending })
      await followJob(initial, nextPending)
    } catch (caught) {
      setStatus('error')
      setError(`任务仍保存在本机，可稍后恢复。${errorMessage(caught, settings.token, '恢复')}`)
    } finally {
      activeRef.current = false
    }
  }, [commitState, config, followJob, settings.token])

  recoveryRef.current = recoverPending

  const generate = useCallback(async () => {
    if (activeRef.current || isControllerBusy(status)) return
    let normalizedUrl: string
    try {
      normalizedUrl = normalizeEasyPanelBaseUrl(settings.baseUrl)
    } catch (caught) {
      setStatus('error')
      setError(errorMessage(caught, settings.token, '地址'))
      return
    }
    if (!settings.token.trim()) {
      setStatus('error')
      setError('请填写 RPG Token，再提交生图任务。')
      return
    }
    if (!settings.prompt.trim()) {
      setStatus('error')
      setError('请先填写正向提示词。')
      return
    }
    if (normalizedUrl !== settings.baseUrl) {
      const nextSettings = normalizeEasyPanelControllerSettings({ ...settings, baseUrl: normalizedUrl })
      commitState({ ...stateRef.current, settings: nextSettings })
    }
    const requestId = createEasyPanelControllerRequestId()
    const request = attachEasyPanelPendingDerivation(
      buildEasyPanelControllerRequest(settings, requestId, restoredSnapshot),
      pendingDerivation,
    )
    const pending: PendingEasyPanelJob = {
      requestId,
      jobId: '',
      submittedAt: Date.now(),
      request,
    }
    commitState({ ...stateRef.current, pendingJob: pending })
    activeRef.current = true
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    setStatus('submitting')
    setJob(undefined)
    setError('')
    try {
      const initial = await submitVisualJob({ ...config, baseUrl: normalizedUrl }, request)
      // The server has accepted this explicit submission.  Keep the relation
      // on the persisted pending request, but do not reuse it for a later
      // ordinary Generate action.
      setPendingDerivation(undefined)
      const nextPending = { ...pending, jobId: initial.job_id || '' }
      commitState({ ...stateRef.current, pendingJob: nextPending })
      await followJob(initial, nextPending)
    } catch (caught) {
      setStatus('error')
      setError(`提交结果可能仍在电脑端处理，任务已保留。${errorMessage(caught, settings.token, '生成')}`)
    } finally {
      activeRef.current = false
    }
  }, [commitState, config, followJob, pendingDerivation, restoredSnapshot, settings, status])

  const clearPending = useCallback(async () => {
    abortRef.current?.abort()
    commitState({ ...stateRef.current, pendingJob: undefined })
    setJob(undefined)
    setStatus('idle')
    setError('')
  }, [commitState])

  const clearImage = useCallback(async () => {
    const image = stateRef.current.image
    if (image) await deletePortraitFile(image.uri)
    commitState({ ...stateRef.current, image: undefined })
    setJob(undefined)
    setStatus('idle')
    setError('')
  }, [commitState])

  const downloadCurrent = useCallback(async () => {
    const image = stateRef.current.image
    if (!image || downloadLoading) return
    setDownloadLoading(true)
    setDownloadMessage('正在保存图片…')
    try {
      const base64 = await readPortraitBase64(image.uri)
      const result = await downloadBlob(base64ToBlob(base64, image.type), image.filename)
      setDownloadMessage(result.location ? `已保存：${result.location}` : '已交给浏览器下载，请检查下载通知。')
      setError('')
    } catch (caught) {
      setDownloadMessage('图片保存失败')
      setError(errorMessage(caught, settings.token, '下载'))
    } finally {
      setDownloadLoading(false)
    }
  }, [downloadLoading, settings.token])

  useEffect(() => {
    if (!hydrated || hydratedRecoveryRef.current) return
    hydratedRecoveryRef.current = true
    if (stateRef.current.pendingJob) void recoverPending()
  }, [hydrated, recoverPending])

  useEffect(() => {
    const onResume = () => {
      if (document.visibilityState !== 'visible' || activeRef.current || !stateRef.current.pendingJob) return
      void recoveryRef.current?.()
    }
    document.addEventListener('visibilitychange', onResume)
    window.addEventListener('online', onResume)
    return () => {
      document.removeEventListener('visibilitychange', onResume)
      window.removeEventListener('online', onResume)
    }
  }, [])

  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => () => {
    for (const source of Object.values(libraryThumbnailUrlsRef.current)) URL.revokeObjectURL(source)
  }, [])

  return {
    hydrated,
    settings,
    status,
    statusLabel: controllerStatusLabel(status),
    job,
    image: state.image,
    imageSource: state.image ? portraitSource(state.image.uri) : '',
    models,
    capabilities,
    connectionMessage,
    error,
    pendingJob: state.pendingJob,
    modelsLoading,
    modelsMessage,
    modelsError,
    downloadLoading,
    downloadMessage,
    snapshots,
    snapshotsLoading,
    snapshotsMessage,
    snapshotsError,
    restoredSnapshot,
    library,
    libraryLoading,
    libraryMessage,
    libraryError,
    libraryDetail,
    libraryLineage,
    libraryThumbnailSources,
    libraryDownloadLoading,
    libraryDownloadMessage,
    pendingDerivation,
    setSettings,
    testConnection,
    refreshModels,
    generate,
    recoverPending,
    clearPending,
    clearImage,
    downloadCurrent,
    refreshSnapshots,
    restoreSnapshot,
    clearSnapshotAdvancedConfig,
    refreshLibrary,
    openLibraryGeneration,
    clearLibraryDetail,
    restoreLibraryGeneration,
    clearPendingDerivation,
    downloadLibraryArtifact,
  }
}

function extensionForBlob(blob: Blob): string {
  if (blob.type.includes('jpeg')) return 'jpg'
  if (blob.type.includes('webp')) return 'webp'
  return 'png'
}

function base64ToBlob(base64: string, mime: string): Blob {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return new Blob([bytes], { type: mime || 'image/png' })
}

function errorMessage(error: unknown, token: string, action: string): string {
  if (error instanceof EasyPanelHttpError) {
    if (error.status === 401 || error.status === 403) return `${action}失败：Token 无效或电脑端未接受该 Token。`
    if (error.status === 404) return `${action}失败：没有找到 Easy Panel API，请检查电脑地址和 8190 端口。`
    if (error.status === 413) return `${action}失败：请求或图片超过电脑端限制。`
    return `${action}失败（HTTP ${error.status}）：${redact(String(error.message || ''), token)}`
  }
  if (error instanceof DOMException && error.name === 'AbortError') return `${action}已取消。`
  if (error instanceof TypeError) return `${action}失败：无法连接电脑，请检查局域网/Tailscale、IP、MagicDNS 和防火墙。`
  if (error instanceof Error) return `${action}失败：${redact(error.message, token)}`
  return `${action}失败，请检查电脑端服务和网络。`
}

function formatJobError(error: unknown): string {
  if (typeof error === 'string' && error.trim()) return error.trim()
  if (Array.isArray(error)) return error.map((item) => typeof item === 'string' ? item : JSON.stringify(item)).join('；')
  if (error && typeof error === 'object') return JSON.stringify(error)
  return 'Easy Panel 生图失败。'
}

function redact(value: string, token: string): string {
  const clean = token.trim()
  return clean ? value.split(clean).join('[已隐藏]') : value
}
