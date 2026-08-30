import { createVisualRequestId, type VisualGenerateRequest } from '../services/easyPanelVisual'

export const EASY_PANEL_CONTROLLER_STATE_KEY = 'easy-panel-mobile-controller-v1'

export type EasyPanelQuality = 'fast' | 'balanced' | 'detailed'

export interface EasyPanelControllerSettings {
  baseUrl: string
  token: string
  model: string
  quality: EasyPanelQuality
  width: number
  height: number
  prompt: string
  negative: string
  pollIntervalMs: number
}

export interface EasyPanelControllerImage {
  uri: string
  filename: string
  type: string
  savedAt: number
}

export interface PendingEasyPanelJob {
  requestId: string
  jobId: string
  submittedAt: number
  request: VisualGenerateRequest
}

export interface EasyPanelControllerState {
  settings: EasyPanelControllerSettings
  image?: EasyPanelControllerImage
  pendingJob?: PendingEasyPanelJob
}

export type EasyPanelControllerInteraction =
  | { type: 'settings-changed'; patch: Partial<EasyPanelControllerSettings> }
  | { type: 'generate-requested' }

export interface EasyPanelControllerInteractionResult {
  settings: EasyPanelControllerSettings
  shouldSubmit: boolean
}

export const DEFAULT_EASY_PANEL_CONTROLLER_SETTINGS: EasyPanelControllerSettings = {
  baseUrl: '',
  token: '',
  model: '',
  quality: 'balanced',
  width: 832,
  height: 1216,
  prompt: '',
  negative: '',
  pollIntervalMs: 1800,
}

export function defaultEasyPanelControllerState(): EasyPanelControllerState {
  return { settings: { ...DEFAULT_EASY_PANEL_CONTROLLER_SETTINGS } }
}

export function normalizeEasyPanelControllerSettings(
  value: Partial<EasyPanelControllerSettings> | undefined,
): EasyPanelControllerSettings {
  const source = value ?? {}
  const quality: EasyPanelQuality = source.quality === 'fast' || source.quality === 'detailed'
    ? source.quality
    : 'balanced'
  return {
    ...DEFAULT_EASY_PANEL_CONTROLLER_SETTINGS,
    ...source,
    baseUrl: text(source.baseUrl),
    token: text(source.token),
    model: text(source.model),
    quality,
    width: clampInt(source.width, 512, 1920, DEFAULT_EASY_PANEL_CONTROLLER_SETTINGS.width),
    height: clampInt(source.height, 512, 1920, DEFAULT_EASY_PANEL_CONTROLLER_SETTINGS.height),
    prompt: text(source.prompt).slice(0, 1200),
    negative: text(source.negative).slice(0, 1600),
    pollIntervalMs: clampInt(source.pollIntervalMs, 800, 10000, DEFAULT_EASY_PANEL_CONTROLLER_SETTINGS.pollIntervalMs),
  }
}

export function normalizeEasyPanelControllerState(
  value: Partial<EasyPanelControllerState> | undefined,
): EasyPanelControllerState {
  const source = value ?? {}
  const image = normalizeImage(source.image)
  const pendingJob = normalizePendingJob(source.pendingJob)
  return {
    settings: normalizeEasyPanelControllerSettings(source.settings),
    ...(image ? { image } : {}),
    ...(pendingJob ? { pendingJob } : {}),
  }
}

/**
 * Keep the mobile form's mutation boundary explicit. Editing a field only
 * returns the next persisted settings; submission is a separate, explicit
 * user action. This makes it impossible for a field change to accidentally
 * become a generate request when the view is refactored.
 */
export function reduceEasyPanelControllerInteraction(
  settings: EasyPanelControllerSettings,
  interaction: EasyPanelControllerInteraction,
): EasyPanelControllerInteractionResult {
  if (interaction.type === 'generate-requested') {
    return { settings, shouldSubmit: true }
  }
  return {
    settings: normalizeEasyPanelControllerSettings({ ...settings, ...interaction.patch }),
    shouldSubmit: false,
  }
}

export function buildEasyPanelControllerRequest(
  settings: EasyPanelControllerSettings,
  requestId: string,
): VisualGenerateRequest {
  const prompt = settings.prompt.trim()
  if (!prompt) throw new Error('请先填写正向提示词。')
  const request: VisualGenerateRequest = {
    client: {
      gameId: 'easy-panel-mobile',
      sceneId: requestId,
      requestId,
    },
    visual: {
      characters: [],
      scene: prompt,
    },
    generation: {
      quality: settings.quality,
      width: settings.width,
      height: settings.height,
      seed: -1,
      safetyLevel: 'safe',
      ...(settings.model.trim() ? { model: settings.model.trim() } : {}),
      ...(settings.negative.trim() ? { negative: settings.negative.trim() } : {}),
    },
  }
  return request
}

export function createEasyPanelControllerRequestId(): string {
  const entropy = Math.random().toString(36).slice(2, 10)
  return createVisualRequestId('easy-panel-mobile', `prompt_${Date.now()}_${entropy}`)
}

export function extractEasyPanelModels(payload: unknown): string[] {
  if (!payload || typeof payload !== 'object') return []
  const record = payload as Record<string, unknown>
  const names: string[] = []
  for (const key of ['checkpoints', 'anima_models', 'krea2_models']) {
    const values = record[key]
    if (!Array.isArray(values)) continue
    for (const value of values) {
      if (typeof value === 'string' && value.trim() && !names.includes(value)) names.push(value)
    }
  }
  return names
}

export function controllerStatusLabel(status: string): string {
  if (status === 'checking') return '正在连接'
  if (status === 'recovering') return '正在恢复任务'
  if (status === 'submitting') return '正在提交'
  if (status === 'queued') return '排队中'
  if (status === 'running') return '生成中'
  if (status === 'saving') return '保存图片'
  if (status === 'completed') return '生成完成'
  if (status === 'error') return '需要处理'
  return '待机'
}

export function isControllerBusy(status: string): boolean {
  return status === 'checking' || status === 'recovering' || status === 'submitting'
    || status === 'queued' || status === 'running' || status === 'saving'
}

function normalizeImage(value: unknown): EasyPanelControllerImage | undefined {
  if (!value || typeof value !== 'object') return undefined
  const record = value as Record<string, unknown>
  const uri = text(record.uri)
  if (!uri) return undefined
  return {
    uri,
    filename: text(record.filename) || 'easy-panel-output.png',
    type: text(record.type) || 'image/png',
    savedAt: finiteNumber(record.savedAt, Date.now()),
  }
}

function normalizePendingJob(value: unknown): PendingEasyPanelJob | undefined {
  if (!value || typeof value !== 'object') return undefined
  const record = value as Record<string, unknown>
  const requestId = text(record.requestId)
  const request = record.request
  if (!requestId || !request || typeof request !== 'object') return undefined
  const requestRecord = request as Record<string, unknown>
  const client = requestRecord.client
  if (!client || typeof client !== 'object') return undefined
  return {
    requestId,
    jobId: text(record.jobId),
    submittedAt: finiteNumber(record.submittedAt, Date.now()),
    request: request as PendingEasyPanelJob['request'],
  }
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function clampInt(value: unknown, min: number, max: number, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback
  return Math.min(max, Math.max(min, Math.round(value)))
}
