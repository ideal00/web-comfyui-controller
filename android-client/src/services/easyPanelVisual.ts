/** RPGBox -> ComfyUI Easy Panel mobile visual client (API v2). */

export interface EasyPanelVisualConfig {
  baseUrl: string
  token: string
  pollIntervalMs?: number
  requestTimeoutMs?: number
}

export interface VisualCharacter {
  id: string
  name?: string
  gender?: string
  outfit?: string
  expression?: string
  pose?: string
  action?: string
  prompt?: string
  appearance?: string
  outfitPrompt?: string
  loras?: Array<{ name: string; weight?: number }>
}

export interface VisualScene {
  characters: VisualCharacter[]
  location?: string
  time?: string
  scene?: string
  weather?: string
  lighting?: string
  shot?: string
  cameraAngle?: string
  composition?: string
  mood?: string
  relation?: string
  groupAction?: string
  style?: string
  extraPrompt?: string
}

export interface VisualGenerationSettings {
  model?: string
  quality?: 'fast' | 'balanced' | 'detailed'
  width?: number
  height?: number
  seed?: number | string
  regional?: boolean
  safetyLevel?: string
  negative?: string
  steps?: number
  cfg?: number
  sampler?: string
  scheduler?: string
  hiresScale?: number
  hiresDenoise?: number
  hiresSteps?: number
  hiresCfg?: number
  hiresSampler?: string
  hiresScheduler?: string
  loras?: Array<{ name: string; weight?: number | string }>
  characterLoras?: Array<{ name: string; weight?: number | string }>
  styleLoras?: Array<{ name: string; weight?: number | string }>
  styleFamily?: string
  illustriousMode?: string
  guidance?: Record<string, unknown>
  vae?: Record<string, unknown>
  modelEnhancement?: Record<string, unknown>
  transparentBackground?: Record<string, unknown>
  colorCorrection?: Record<string, unknown>
  outputEnhancement?: Record<string, unknown>
  repair?: Record<string, unknown>
  img2img?: Record<string, unknown>
  pose?: Record<string, unknown>
  depth?: Record<string, unknown>
}

export interface VisualGenerateRequest {
  client: {
    gameId: string
    sceneId: string
    /** Stable id. Reusing it will not submit a duplicate ComfyUI job. */
    requestId: string
  }
  visual: VisualScene
  generation?: VisualGenerationSettings
}

export interface VisualImageRef {
  filename: string
  subfolder?: string
  type?: string
  url: string
}

export interface VisualJobStatus {
  api_version: number
  job_id: string
  prompt_id?: string
  status: 'queued' | 'running' | 'completed' | 'error'
  images: VisualImageRef[]
  error?: unknown
  deduplicated?: boolean
  status_url?: string
}

export interface EasyPanelPing {
  ok: boolean
  api_version: number
  service?: string
  token_required: boolean
}

export class EasyPanelHttpError extends Error {
  status: number
  payload: unknown

  constructor(status: number, message: string, payload: unknown) {
    super(message)
    this.name = 'EasyPanelHttpError'
    this.status = status
    this.payload = payload
  }
}

function extractErrorMessage(payload: unknown): string {
  if (!payload || typeof payload !== 'object') return ''
  const record = payload as Record<string, unknown>
  const candidates = [record.message, record.detail, record.error]
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) return candidate.trim()
    if (!candidate || typeof candidate !== 'object') continue
    const nested = candidate as Record<string, unknown>
    for (const key of ['message', 'detail', 'status']) {
      if (typeof nested[key] === 'string' && String(nested[key]).trim()) return String(nested[key]).trim()
    }
  }
  return ''
}

function redactToken(text: string, token: string): string {
  const cleanToken = token.trim()
  return cleanToken ? text.split(cleanToken).join('[已隐藏]') : text
}

export function normalizeEasyPanelBaseUrl(value: string): string {
  const raw = value.trim()
  if (!raw) throw new Error('Easy Panel 地址不能为空')
  const candidate = /^[a-z][a-z\d+.-]*:\/\//i.test(raw) ? raw : `http://${raw}`
  let parsed: URL
  try {
    parsed = new URL(candidate)
  } catch {
    throw new Error('Easy Panel 地址格式不正确，请填写电脑 IP、Tailscale IP 或 MagicDNS 主机名和端口。')
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('Easy Panel 地址只支持 http:// 或 https://。')
  }
  if (!parsed.hostname) throw new Error('Easy Panel 地址缺少主机名或 IP。')
  if (parsed.username || parsed.password) throw new Error('Easy Panel 地址不能包含用户名或密码。')
  if ((parsed.pathname !== '' && parsed.pathname !== '/') || parsed.search || parsed.hash) {
    throw new Error('Easy Panel 地址只能包含协议、主机名/IP 和端口，不能包含路径、查询参数或锚点。')
  }
  return `${parsed.protocol}//${parsed.host}`
}

function requestHeaders(token: string, json = false): Record<string, string> {
  const result: Record<string, string> = {}
  if (json) result['Content-Type'] = 'application/json'
  if (token.trim()) result['X-RPG-Token'] = token.trim()
  return result
}

export async function jsonRequest<T>(config: EasyPanelVisualConfig, path: string, init: RequestInit = {}): Promise<T> {
  const baseUrl = normalizeEasyPanelBaseUrl(config.baseUrl)
  const response = await fetchWithTimeout(baseUrl + path, {
      ...init,
      headers: { ...requestHeaders(config.token, Boolean(init.body)), ...(init.headers ?? {}) },
    }, config.requestTimeoutMs ?? 15000)
  const text = await response.text()
  let payload: unknown = {}
  try { payload = text ? JSON.parse(text) : {} } catch { payload = { error: text } }
  if (!response.ok) {
    const detail = extractErrorMessage(payload)
    const message = redactToken(detail || `HTTP ${response.status}`, config.token)
    throw new EasyPanelHttpError(response.status, message, payload)
  }
  return payload as T
}

export async function pingEasyPanel(config: EasyPanelVisualConfig) {
  return jsonRequest<EasyPanelPing>(config, '/api/rpg/ping')
}

export async function getEasyPanelCapabilities(config: EasyPanelVisualConfig) {
  return jsonRequest<Record<string, unknown>>(config, '/api/rpg/capabilities')
}

export async function getEasyPanelModels(config: EasyPanelVisualConfig) {
  return jsonRequest<Record<string, unknown>>(config, '/api/rpg/models')
}

export async function submitVisualJob(config: EasyPanelVisualConfig, request: VisualGenerateRequest) {
  return jsonRequest<VisualJobStatus>(config, '/api/rpg/generate', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export async function getVisualJob(config: EasyPanelVisualConfig, jobId: string) {
  return jsonRequest<VisualJobStatus>(config, `/api/rpg/jobs/${encodeURIComponent(jobId)}`)
}

export async function recoverVisualJob(config: EasyPanelVisualConfig, requestId: string) {
  return jsonRequest<VisualJobStatus>(config, `/api/rpg/jobs/by-request/${encodeURIComponent(requestId)}`)
}

export async function waitForVisualJob(
  config: EasyPanelVisualConfig,
  initial: VisualJobStatus,
  signal?: AbortSignal,
  onUpdate?: (job: VisualJobStatus) => void,
): Promise<VisualJobStatus> {
  let job = initial
  const interval = Math.max(800, config.pollIntervalMs ?? 1800)
  let transientFailures = 0
  while (job.status !== 'completed' && job.status !== 'error') {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    await waitWithAbort(interval, signal)
    try {
      job = await getVisualJob(config, job.job_id)
      transientFailures = 0
    } catch (error) {
      if (signal?.aborted || (error instanceof DOMException && error.name === 'AbortError')) throw error
      transientFailures += 1
      if (transientFailures > 3) throw error
      await waitWithAbort(Math.min(8000, 750 * 2 ** (transientFailures - 1)), signal)
      continue
    }
    onUpdate?.(job)
  }
  return job
}

export async function downloadVisualImage(config: EasyPanelVisualConfig, image: VisualImageRef): Promise<Blob> {
  const baseUrl = normalizeEasyPanelBaseUrl(config.baseUrl)
  const response = await fetchWithTimeout(baseUrl + image.url, { headers: requestHeaders(config.token) }, config.requestTimeoutMs ?? 30000)
  if (!response.ok) throw new EasyPanelHttpError(response.status, `下载剧情 CG 失败 (${response.status})`, null)
  return response.blob()
}

export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result !== 'string') return reject(new Error('无法读取剧情 CG'))
      resolve(reader.result.slice(reader.result.indexOf(',') + 1))
    }
    reader.onerror = () => reject(reader.error ?? new Error('无法读取剧情 CG'))
    reader.readAsDataURL(blob)
  })
}

export function createVisualRequestId(gameId: string, sceneId: string, suffix = ''): string {
  const clean = (value: string) => value.replace(/[^0-9A-Za-z_-]+/g, '_').replace(/^_+|_+$/g, '')
  const full = clean(`${gameId}_${sceneId}${suffix ? `_${suffix}` : ''}`)
  return (full || `scene_${Date.now()}`).slice(0, 48)
}

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController()
  let timedOut = false
  const callerSignal = init.signal
  const relayAbort = () => controller.abort()
  if (callerSignal?.aborted) controller.abort()
  else callerSignal?.addEventListener('abort', relayAbort, { once: true })
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, Math.max(1000, timeoutMs))
  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } catch (error) {
    if (timedOut) throw new Error('Easy Panel 请求超时，请检查电脑服务、网络和地址。')
    throw error
  } finally {
    clearTimeout(timer)
    callerSignal?.removeEventListener('abort', relayAbort)
  }
}

function waitWithAbort(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', abort)
      resolve()
    }, delayMs)
    const abort = () => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abort)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    if (signal?.aborted) abort()
    else signal?.addEventListener('abort', abort, { once: true })
  })
}
