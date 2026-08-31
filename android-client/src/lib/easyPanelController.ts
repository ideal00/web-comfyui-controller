import { createVisualRequestId, type VisualGenerateRequest } from '../services/easyPanelVisual'
import type { EasyPanelSnapshotRecord } from '../services/easyPanelSnapshots'

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
  seed: string
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
  seed: '',
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
    seed: text(source.seed).slice(0, 40),
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
  snapshot?: EasyPanelSnapshotRecord,
): VisualGenerateRequest {
  const prompt = settings.prompt.trim()
  if (!prompt) throw new Error('请先填写正向提示词。')
  const source = snapshot ? snapshotObject(snapshot.source) : {}
  const payload = snapshot ? snapshotObject(snapshot.payload) : {}
  const compiled = snapshot ? snapshotObject(snapshot.compiled) : {}
  const request: VisualGenerateRequest = {
    client: {
      gameId: 'easy-panel-mobile',
      sceneId: requestId,
      requestId,
    },
    visual: snapshot ? snapshotVisual(source, prompt, compiled) : { characters: [], scene: prompt },
    generation: {
      quality: settings.quality,
      width: settings.width,
      height: settings.height,
      seed: settings.seed.trim() || -1,
      safetyLevel: 'safe',
      ...(settings.model.trim() ? { model: settings.model.trim() } : {}),
      ...(settings.negative.trim() ? { negative: settings.negative.trim() } : {}),
      ...(snapshot ? snapshotGeneration(source, payload) : {}),
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

function snapshotObject(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function snapshotText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function snapshotVisual(
  source: Record<string, unknown>,
  prompt: string,
  compiled: Record<string, unknown>,
): VisualGenerateRequest['visual'] {
  const characters = Array.isArray(source.characters)
    ? source.characters.flatMap((value) => {
      const item = snapshotObject(value)
      const id = snapshotText(item.id) || snapshotText(item.name)
      if (!id) return []
      return [{
        id,
        ...(snapshotText(item.name) ? { name: snapshotText(item.name) } : {}),
        ...(snapshotText(item.gender) ? { gender: snapshotText(item.gender) } : {}),
        ...(snapshotText(item.appearance) ? { appearance: snapshotText(item.appearance) } : {}),
        ...(snapshotText(item.outfit) ? { outfit: snapshotText(item.outfit) } : {}),
        ...(snapshotText(item.outfitPrompt) ? { outfitPrompt: snapshotText(item.outfitPrompt) } : {}),
        ...(snapshotText(item.expression) ? { expression: snapshotText(item.expression) } : {}),
        ...(snapshotText(item.pose) ? { pose: snapshotText(item.pose) } : {}),
        ...(snapshotText(item.action) ? { action: snapshotText(item.action) } : {}),
        ...(snapshotText(item.prompt) ? { prompt: snapshotText(item.prompt) } : {}),
        ...(snapshotText(item.style) ? { style: snapshotText(item.style) } : {}),
        ...(Array.isArray(item.loras) ? {
          loras: item.loras.flatMap((value) => {
            const lora = snapshotObject(value)
            const name = snapshotText(lora.name)
            if (!name) return []
            const weight = lora.weight
            const numericWeight = typeof weight === 'number' && Number.isFinite(weight)
              ? weight
              : typeof weight === 'string' && Number.isFinite(Number(weight)) ? Number(weight) : undefined
            return [{ name, ...(numericWeight === undefined ? {} : { weight: numericWeight }) }]
          }),
        } : {}),
      }]
    })
    : []
  const sourceScene = snapshotText(source.scene)
  const restoredPositive = snapshotText(compiled.positive)
  const useRestoredStructuredScene = Boolean(sourceScene && restoredPositive && prompt === restoredPositive)
  return {
    characters,
    scene: useRestoredStructuredScene ? sourceScene : prompt,
    ...(!useRestoredStructuredScene && sourceScene ? { location: sourceScene } : {}),
    ...(snapshotText(source.lighting) ? { lighting: snapshotText(source.lighting) } : {}),
    ...(snapshotText(source.composition) ? { composition: snapshotText(source.composition), shot: snapshotText(source.composition) } : {}),
    ...(snapshotText(source.styleColoring) ? { style: snapshotText(source.styleColoring) } : {}),
    ...(snapshotText(source.naturalLanguage) ? { relation: snapshotText(source.naturalLanguage) } : {}),
    ...(snapshotText(source.regionGlobalPrompt) ? { groupAction: snapshotText(source.regionGlobalPrompt) } : {}),
    ...(snapshotText(source.manual) ? { extraPrompt: snapshotText(source.manual) } : {}),
  }
}

function snapshotGeneration(
  source: Record<string, unknown>,
  payload: Record<string, unknown>,
): VisualGenerateRequest['generation'] {
  const sourceGeneration = snapshotObject(source.generation)
  const enhancements = snapshotObject(source.enhancements)
  const result: NonNullable<VisualGenerateRequest['generation']> = {}
  const scalarKeys = [
    'steps', 'cfg', 'sampler', 'scheduler', 'hiresScale', 'hiresDenoise', 'hiresSteps',
    'hiresCfg', 'hiresSampler', 'hiresScheduler', 'styleFamily', 'illustriousMode',
  ] as const
  for (const key of scalarKeys) {
    const value = payload[key] ?? sourceGeneration[key] ?? enhancements[key]
    if (typeof value === 'string' || typeof value === 'number') result[key] = value as never
  }
  const sourceLoras = Array.isArray(source.loras) ? source.loras : []
  const payloadLoras = Array.isArray(payload.loras) ? payload.loras : sourceLoras
  const loras = payloadLoras.flatMap((value) => {
    const item = snapshotObject(value)
    const name = snapshotText(item.name)
    if (!name) return []
    const weight = item.weight
    return [{ name, ...(typeof weight === 'number' || typeof weight === 'string' ? { weight } : {}) }]
  })
  if (loras.length) result.loras = loras
  for (const key of [
    'characterLoras', 'styleLoras', 'guidance', 'vae', 'modelEnhancement', 'transparentBackground',
    'colorCorrection', 'outputEnhancement', 'repair', 'img2img', 'pose', 'depth',
  ] as const) {
    const value = payload[key] ?? enhancements[key] ?? (key === 'vae' ? source.vae : undefined)
    if (value && typeof value === 'object' && !Array.isArray(value)) result[key] = value as never
  }
  return result
}
