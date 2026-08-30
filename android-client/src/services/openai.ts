import { Capacitor, CapacitorHttp } from '@capacitor/core'
import type { HttpOptions } from '@capacitor/core'
import type { ProviderProfile } from '../types'

export interface CompletionRequest {
  provider: ProviderProfile
  messages: Array<{ role: string; content: string }>
  /** Optional ordered models used only after the primary model exhausts temporary-error retries. */
  fallbackModels?: string[]
  signal?: AbortSignal
  onToken?: (fullText: string) => void
  onFinishReason?: (reason: string) => void
  onUsage?: (usage: CompletionUsage) => void
  onRetry?: (info: CompletionRetryInfo) => void
  onModelFallback?: (info: CompletionModelFallbackInfo) => void
}

export interface CompletionUsage {
  inputTokens: number
  outputTokens: number
}

export interface CompletionRetryInfo {
  attempt: number
  maxAttempts: number
  delayMs: number
  status: number
  message: string
  model: string
}

export interface CompletionModelFallbackInfo {
  fromModel: string
  toModel: string
  fallbackIndex: number
}

export type ProviderErrorKind = 'address' | 'api-key' | 'network' | 'model' | 'region' | 'temporary' | 'response'

export class ProviderRequestError extends Error {
  readonly kind: ProviderErrorKind
  readonly status?: number
  readonly detail?: string

  constructor(kind: ProviderErrorKind, message: string, status?: number, detail?: string) {
    super(message)
    this.name = 'ProviderRequestError'
    this.kind = kind
    this.status = status
    this.detail = detail
  }
}

export const GEMINI_OPENAI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/openai'
export const GEMINI_NATIVE_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'
export const GEMINI_NATIVE_MODELS_URL = `${GEMINI_NATIVE_BASE_URL}/models`

const GOOGLE_API_HOSTS = new Set([
  'googleapis.com',
  'generativelanguage.googleapis.com',
])

interface ProviderResponse {
  status: number
  ok: boolean
  headers: Headers
  body: ReadableStream<Uint8Array> | null
  text: () => Promise<string>
  json: () => Promise<unknown>
}

interface ProviderRequestOptions {
  method: 'GET' | 'POST'
  headers: Record<string, string>
  body?: unknown
  signal?: AbortSignal
  nativeHttp?: boolean
}

function addressError(): ProviderRequestError {
  return new ProviderRequestError('address', '接口地址格式错误，请填写完整的 HTTP(S) Base URL。')
}

function parseBaseUrl(baseUrl: string): URL {
  const raw = baseUrl.trim()
  if (!raw) throw addressError()
  const withProtocol = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`

  try {
    const url = new URL(withProtocol)
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname) throw new Error('unsupported URL')
    return url
  } catch {
    throw addressError()
  }
}

function isGoogleApiHostname(hostname: string): boolean {
  return GOOGLE_API_HOSTS.has(hostname.toLowerCase().replace(/\.$/u, ''))
}

function isGeminiUrl(url: URL): boolean {
  return isGoogleApiHostname(url.hostname)
}

/**
 * Normalize both ordinary OpenAI-compatible roots and the input variants users
 * commonly paste for Google's Gemini OpenAI-compatible endpoint.
 */
export function normalizeBaseUrl(baseUrl: string): string {
  if (!baseUrl.trim()) return ''
  const url = parseBaseUrl(baseUrl)

  // A query string is deliberately discarded. Gemini OpenAI compatibility uses
  // Authorization: Bearer, so an accidental ?key=... must never be retained.
  url.username = ''
  url.password = ''
  url.search = ''
  url.hash = ''

  if (isGeminiUrl(url)) return GEMINI_OPENAI_BASE_URL

  const path = url.pathname.replace(/\/{2,}/gu, '/').replace(/\/+$/u, '')
  url.pathname = path || '/v1'
  return url.toString().replace(/\/+$/u, '')
}

export function isGeminiOpenAiBaseUrl(baseUrl: string): boolean {
  try {
    const normalized = normalizeBaseUrl(baseUrl)
    return normalized ? isGeminiUrl(new URL(normalized)) : false
  } catch {
    return false
  }
}

/**
 * Gemini's native API calls models `models/gemini-*`, while its OpenAI
 * compatibility layer expects only `gemini-*`. Keep ordinary providers
 * untouched and apply this conversion at every provider boundary.
 */
export function normalizeProviderModelId(model: string, baseUrl: string): string {
  const trimmed = model.trim()
  return isGeminiOpenAiBaseUrl(baseUrl) ? trimmed.replace(/^models\//iu, '') : trimmed
}

export function completionUrl(baseUrl: string): string {
  const normalized = normalizeBaseUrl(baseUrl)
  if (!normalized) return ''
  if (/\/chat\/completions$/iu.test(normalized)) return normalized
  if (/\/models$/iu.test(normalized)) return `${normalized.replace(/\/models$/iu, '')}/chat/completions`
  return `${normalized}/chat/completions`
}

export function modelsUrl(baseUrl: string): string {
  const normalized = normalizeBaseUrl(baseUrl)
  if (!normalized) return ''
  if (/\/models$/iu.test(normalized)) return normalized
  if (/\/chat\/completions$/iu.test(normalized)) {
    return `${normalized.replace(/\/chat\/completions$/iu, '')}/models`
  }
  return `${normalized}/models`
}

export function usesNativeHttpTransport(baseUrl?: string): boolean {
  try {
    // CapacitorHttp is bundled into @capacitor/core and registered by the
    // Android bridge, so native platform detection is the reliable switch.
    // Checking isPluginAvailable here can be false before plugin headers are
    // initialized and would incorrectly send Android requests through CORS.
    return Capacitor.isNativePlatform() && (baseUrl === undefined || isGeminiOpenAiBaseUrl(baseUrl))
  } catch {
    return false
  }
}

function createAbortError(): DOMException {
  return new DOMException('The operation was aborted', 'AbortError')
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function networkError(): ProviderRequestError {
  return new ProviderRequestError(
    'network',
    '网络/CORS 连接失败，请检查网络和 Base URL；Android 端已启用原生 HTTP 通道。',
  )
}

function nativeDataToText(data: unknown): string {
  if (typeof data === 'string') return data
  if (data === undefined || data === null) return ''
  try {
    return JSON.stringify(data)
  } catch {
    return String(data)
  }
}

function nativeResponse(response: { status: number; headers?: Record<string, string>; data?: unknown; url?: string }): ProviderResponse {
  const data = response.data
  let cachedText: string | undefined
  let cachedJson: unknown
  let hasCachedJson = false
  const text = async () => {
    if (cachedText === undefined) cachedText = nativeDataToText(data)
    return cachedText
  }
  const json = async () => {
    if (hasCachedJson) return cachedJson
    cachedJson = typeof data === 'string' ? JSON.parse(data) : data
    hasCachedJson = true
    return cachedJson
  }
  return {
    status: response.status,
    ok: response.status >= 200 && response.status < 300,
    headers: new Headers(response.headers ?? {}),
    body: null,
    text,
    json,
  }
}

async function requestProvider(url: string, options: ProviderRequestOptions): Promise<ProviderResponse> {
  if (options.signal?.aborted) throw createAbortError()

  if (options.nativeHttp && usesNativeHttpTransport()) {
    try {
      // Capacitor's Android bridge treats `data` as a request body. Do not
      // include it at all for GET: Google rejects a GET with an empty/encoded
      // body even when the JavaScript value is merely undefined.
      const request: HttpOptions = {
        url,
        method: options.method,
        headers: options.headers,
        responseType: 'text',
        connectTimeout: 30_000,
        readTimeout: 120_000,
      }
      if (options.method !== 'GET' && options.body !== undefined) request.data = options.body
      const response = await CapacitorHttp.request(request)
      if (options.signal?.aborted) throw createAbortError()
      return nativeResponse(response)
    } catch (error) {
      if (isAbortError(error) || options.signal?.aborted) throw createAbortError()
      throw networkError()
    }
  }

  try {
    const response = await fetch(url, {
      method: options.method,
      headers: options.headers,
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      signal: options.signal,
    })
    return response
  } catch (error) {
    if (isAbortError(error) || options.signal?.aborted) throw createAbortError()
    throw networkError()
  }
}

function redactSensitiveText(value: string): string {
  return value
    .replace(/Bearer\s+[^\s,;"'}]+/giu, 'Bearer [已隐藏]')
    .replace(/((?:authorization|x-goog-api-key|api[_ -]?key)\s*[:=]\s*)[^\s,;"'}]+/giu, '$1[已隐藏]')
    .replace(/([?&](?:key|api[_-]?key|apikey|token)=)[^&\s]+/giu, '$1[已隐藏]')
    .replace(/AIza[0-9A-Za-z_-]{20,}/gu, '[已隐藏]')
}

function safeErrorDetail(value: string, secret?: string): string {
  const secretValue = secret?.trim()
  const compact = redactSensitiveText(value.replace(/\s+/gu, ' ').trim())
  const withoutSecret = secretValue ? compact.split(secretValue).join('[已隐藏]') : compact
  return withoutSecret.length > 360 ? `${withoutSecret.slice(0, 360)}…` : withoutSecret
}

function errorText(payload: string): string {
  try {
    const parsed = JSON.parse(payload) as unknown
    if (parsed && typeof parsed === 'object') {
      const record = parsed as Record<string, unknown>
      const nested = record.error
      if (nested && typeof nested === 'object') {
        const errorRecord = nested as Record<string, unknown>
        const labels = [errorRecord.status, errorRecord.code, errorRecord.message]
          .filter((value): value is string | number => typeof value === 'string' || typeof value === 'number')
          .map(String)
        if (labels.length) return safeErrorDetail(labels.join(': '))
      }
      const labels = [record.status, record.code, record.message]
        .filter((value): value is string | number => typeof value === 'string' || typeof value === 'number')
        .map(String)
      if (labels.length) return safeErrorDetail(labels.join(': '))
    }
  } catch {
    // Plain-text error responses are handled below.
  }
  return safeErrorDetail(payload)
}

function isModelNotFound(detail: string): boolean {
  return /(?:model|models\/)[\s\S]{0,160}(?:not found|does not exist|unsupported|not available|unknown)|(?:not found|does not exist|unsupported|not available|unknown)[\s\S]{0,160}(?:model|models\/)/iu.test(detail)
}

function isRegionRestriction(detail: string): boolean {
  if (/(?:region|location|country|countries|geographic|geo[- ]?restriction|territory)/iu.test(detail)) return true
  return /(?:failed[_ -]?precondition|not supported|unsupported)/iu.test(detail) && !/\bmodels?\b|models\//iu.test(detail)
}

const GEMINI_REGION_ERROR = '当前网络出口地区不受 Gemini API 支持，请切换到 Google 官方支持的地区网络后重试。'

export const MAX_TEMPORARY_RETRIES = 3
const TEMPORARY_RETRY_BACKOFF_MS = [1000, 2000, 4000]
const MAX_SERVER_RETRY_DELAY_MS = 120_000

type CompletionBody = Record<string, unknown> & {
  model: string
  messages: CompletionRequest['messages']
  stream: boolean
}

function withErrorDetail(message: string, detail: string): string {
  const safeDetail = safeErrorDetail(detail)
  return safeDetail ? `${message} 返回：${safeDetail}` : message
}

function httpError(status: number, detail: string, operation: 'models' | 'chat', model?: string, secret?: string): ProviderRequestError {
  const safeDetail = safeErrorDetail(detail, secret)
  if (status === 401 || status === 403 || /(?:unauthenticated|invalid (?:api )?key|authentication credentials|permission denied|forbidden)/iu.test(detail)) {
    return new ProviderRequestError('api-key', withErrorDetail(`API Key 无效或未授权（HTTP ${status}），请检查密钥与接口权限。`, safeDetail), status, safeDetail)
  }
  if (isRegionRestriction(detail)) {
    return new ProviderRequestError('region', withErrorDetail(GEMINI_REGION_ERROR, safeDetail), status, safeDetail)
  }
  if (isTemporaryStatus(status) || isTemporaryServiceDetail(detail)) {
    return new ProviderRequestError('temporary', withErrorDetail(temporaryErrorMessage(status, detail, false), safeDetail), status, safeDetail)
  }
  if (isModelNotFound(detail)) {
    return new ProviderRequestError('model', withErrorDetail(`模型不存在或当前接口不支持该模型：${model?.trim() || '当前模型'}。`, safeDetail), status, safeDetail)
  }
  if (status === 404) {
    return new ProviderRequestError('address', withErrorDetail(`接口地址错误（HTTP ${status}），请确认 Base URL 使用的是 OpenAI 兼容接口地址。`, safeDetail), status, safeDetail)
  }
  if (status === 400) {
    const action = operation === 'models' ? '模型列表请求' : '对话请求'
    return new ProviderRequestError('response', withErrorDetail(`${action}被接口拒绝（HTTP 400），请查看返回详情。`, safeDetail), status, safeDetail)
  }
  return new ProviderRequestError('response', withErrorDetail(`API 请求失败（HTTP ${status}），请检查接口配置或稍后重试。`, safeDetail), status, safeDetail)
}

export function isTemporaryStatus(status: number): boolean {
  return [408, 429, 500, 502, 503, 504].includes(status)
}

function isTemporaryServiceDetail(detail: string): boolean {
  return /\b(?:UNAVAILABLE|OVERLOADED)\b|high demand|temporar(?:y|ily) (?:unavailable|busy)|service unavailable/iu.test(detail)
}

function temporaryErrorMessage(status: number, detail: string, retrying: boolean): string {
  if (status === 503 || isTemporaryServiceDetail(detail)) {
    return retrying ? '模型当前请求量过高，正在重试' : '模型当前请求量过高，请稍后重试或切换到稳定的 Flash-Lite/Flash 模型。'
  }
  if (status === 429) return retrying ? '请求过于频繁，正在重试' : '请求过于频繁，请稍后重试或切换模型。'
  return retrying ? `服务暂时不可用（HTTP ${status}），正在重试` : `服务暂时不可用（HTTP ${status}），请稍后重试或切换模型。`
}

function buildCompletionBody(provider: ProviderProfile, messages: CompletionRequest['messages'], model: string, nativeTransport: boolean): CompletionBody {
  const core: CompletionBody = {
    model,
    messages,
    max_tokens: provider.maxTokens,
    stream: !nativeTransport,
  }

  // Gemini 3.6/3.7 reject the deprecated sampling fields. Do this before the
  // request leaves the app so a stale UI value can never trigger INVALID_ARGUMENT.
  if (!isGeminiSamplingRestrictedModel(model, provider.baseUrl)) {
    core.temperature = provider.temperature
    core.top_p = provider.topP
  }

  // Gemini's OpenAI compatibility layer accepts a smaller request schema than
  // ordinary OpenAI-compatible services. In particular, penalty fields and
  // stream_options are not part of the compatibility request we send.
  if (isGeminiOpenAiBaseUrl(provider.baseUrl)) return core

  return {
    ...core,
    presence_penalty: provider.presencePenalty,
    frequency_penalty: provider.frequencyPenalty,
    ...(nativeTransport ? {} : { stream_options: { include_usage: true } }),
  }
}

function parseRetryAfter(headers: Headers): number | undefined {
  const value = headers.get('retry-after')?.trim()
  if (!value) return undefined
  if (/^\d+(?:\.\d+)?$/u.test(value)) return Number(value) * 1000
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? Math.max(0, timestamp - Date.now()) : undefined
}

function parseDurationMs(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, value * 1000)
  if (typeof value === 'string') {
    const match = value.trim().match(/^(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)$/iu)
    if (match) return Number(match[1]) * 1000
    if (/^\d+(?:\.\d+)?\s*ms$/iu.test(value.trim())) return Number.parseFloat(value)
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const record = value as Record<string, unknown>
  const seconds = Number(record.seconds ?? 0)
  const nanos = Number(record.nanos ?? 0)
  if (!Number.isFinite(seconds) || !Number.isFinite(nanos)) return undefined
  return Math.max(0, seconds * 1000 + nanos / 1_000_000)
}

function parseRetryInfoDelay(payload: string): number | undefined {
  try {
    const parsed = JSON.parse(payload) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return undefined
    const root = parsed as Record<string, unknown>
    const error = root.error && typeof root.error === 'object' && !Array.isArray(root.error)
      ? root.error as Record<string, unknown>
      : root
    const details = error.details
    if (Array.isArray(details)) {
      for (const detail of details) {
        if (!detail || typeof detail !== 'object' || Array.isArray(detail)) continue
        const retryDelay = parseDurationMs((detail as Record<string, unknown>).retryDelay)
        if (retryDelay !== undefined) return retryDelay
      }
    }
    return parseDurationMs(error.retryDelay)
  } catch {
    return undefined
  }
}

function retryDelayMs(response: ProviderResponse, payload: string, attempt: number): number {
  const serverDelay = parseRetryAfter(response.headers) ?? parseRetryInfoDelay(payload)
  if (serverDelay !== undefined) return Math.min(MAX_SERVER_RETRY_DELAY_MS, Math.max(0, Math.ceil(serverDelay)))
  const baseDelay = TEMPORARY_RETRY_BACKOFF_MS[Math.min(attempt - 1, TEMPORARY_RETRY_BACKOFF_MS.length - 1)]
  const jitter = Math.floor(Math.random() * 250)
  return baseDelay + jitter
}

function waitForRetry(delay: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(createAbortError())
  if (delay <= 0) return Promise.resolve()
  return new Promise((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const cleanup = () => {
      if (timer !== undefined) clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
    }
    const onAbort = () => {
      cleanup()
      reject(createAbortError())
    }
    timer = setTimeout(() => {
      cleanup()
      resolve()
    }, delay)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

export function extractModelIds(payload: unknown): string[] {
  let candidates: unknown = payload
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    const record = payload as Record<string, unknown>
    candidates = record.data ?? record.models ?? []
  }
  if (!Array.isArray(candidates)) return []

  const ids = candidates.flatMap((candidate) => {
    if (typeof candidate === 'string') return [candidate]
    if (!candidate || typeof candidate !== 'object') return []
    const record = candidate as Record<string, unknown>
    const id = record.id ?? record.name ?? record.model
    return typeof id === 'string' ? [id] : []
  })

  return Array.from(new Set(ids.map((id) => id.trim()).filter(Boolean))).sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }),
  )
}

function sortModelIds(ids: string[]): string[] {
  return Array.from(new Set(ids.map((id) => id.trim()).filter(Boolean))).sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }),
  )
}

export function normalizeProviderModelIds(models: string[], baseUrl: string): string[] {
  return Array.from(new Set(models.map((model) => normalizeProviderModelId(model, baseUrl)).filter(Boolean)))
}

/**
 * Models ordered for ordinary RPG text chat. Keep this list deliberately
 * explicit: it makes the picker useful when Google returns a large catalogue
 * containing audio, image, live and embedding models.
 */
export const GEMINI_RECOMMENDED_TEXT_MODELS = [
  'gemini-3.5-flash-lite',
  'gemini-3.1-flash-lite',
  'gemini-3.5-flash',
  'gemini-3.6-flash',
  'gemini-3.7-flash',
] as const

const GEMINI_SPECIALIZED_MODEL_PATTERN = /(?:image|live|tts|transcrib|embedding|embed|veo|robotics|robot|audio|speech)/iu

export function isGeminiSpecializedModelId(model: string): boolean {
  const normalized = normalizeProviderModelId(model, GEMINI_OPENAI_BASE_URL).toLocaleLowerCase()
  return GEMINI_SPECIALIZED_MODEL_PATTERN.test(normalized)
}

export function isGeminiSamplingRestrictedModel(model: string, baseUrl: string): boolean {
  if (!isGeminiOpenAiBaseUrl(baseUrl)) return false
  const normalized = normalizeProviderModelId(model, baseUrl)
  return /^gemini-3\.[67](?:-|$)/iu.test(normalized)
}

export function geminiModelRecommendationRank(model: string): number {
  const normalized = normalizeProviderModelId(model, GEMINI_OPENAI_BASE_URL).toLocaleLowerCase()
  const preferredIndex = GEMINI_RECOMMENDED_TEXT_MODELS.findIndex((preferred) =>
    normalized === preferred || normalized.startsWith(`${preferred}-`),
  )
  if (preferredIndex >= 0) return preferredIndex
  if (isGeminiSpecializedModelId(normalized)) return 10_000
  if (normalized.includes('flash-lite')) return 100
  if (normalized.includes('flash')) return 200
  if (normalized.startsWith('gemini-')) return 300
  return 1_000
}

export function sortGeminiTextModelIds(models: string[]): string[] {
  return Array.from(new Set(models.map((model) => normalizeProviderModelId(model, GEMINI_OPENAI_BASE_URL)).filter(Boolean)))
    .filter((model) => !isGeminiSpecializedModelId(model))
    .sort((left, right) =>
    geminiModelRecommendationRank(left) - geminiModelRecommendationRank(right)
      || left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' }),
  )
}

export interface GeminiModelPartition {
  textModels: string[]
  specializedModels: string[]
}

export function partitionGeminiModels(models: string[]): GeminiModelPartition {
  const normalized = normalizeProviderModelIds(models, GEMINI_OPENAI_BASE_URL)
  return {
    textModels: sortGeminiTextModelIds(normalized.filter((model) => !isGeminiSpecializedModelId(model))),
    specializedModels: sortModelIds(normalized.filter(isGeminiSpecializedModelId)),
  }
}

/** Parse Gemini's native GET /v1beta/models response into selectable model IDs. */
export function extractGeminiNativeModelIds(payload: unknown): string[] {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return []
  const candidates = (payload as Record<string, unknown>).models
  if (!Array.isArray(candidates)) return []

  const models = candidates.flatMap((candidate) => {
    if (!candidate || typeof candidate !== 'object') return []
    const record = candidate as Record<string, unknown>
    const name = record.name ?? record.id
    if (typeof name !== 'string' || !name.trim()) return []
    const methods = Array.isArray(record.supportedGenerationMethods)
      ? record.supportedGenerationMethods.filter((method): method is string => typeof method === 'string')
      : undefined
    return [{ name: normalizeProviderModelId(name, GEMINI_NATIVE_BASE_URL), supportsGenerateContent: methods?.some((method) => method === 'generateContent') ?? false, hasMethods: methods !== undefined }]
  })
  if (!models.length) return []

  // If the API supplies capability metadata, prefer models that can actually
  // generate content. Some compatible proxies omit the metadata, so retain all
  // named models in that case instead of returning an empty list.
  const generationModels = models.filter((model) => model.supportsGenerateContent)
  const selected = generationModels.length
    ? generationModels
    : models.every((model) => !model.hasMethods)
      ? models
      : generationModels
  return sortModelIds(selected.map((model) => model.name))
}

export interface AvailableModelsResult {
  models: string[]
  source: 'openai' | 'gemini-native'
  /** Gemini models kept available for manual selection but folded away from the text-chat list. */
  specializedModels?: string[]
  warning?: string
}

function organizeAvailableModels(models: string[], gemini: boolean): Pick<AvailableModelsResult, 'models' | 'specializedModels'> {
  if (!gemini) return { models }
  const partition = partitionGeminiModels(models)
  return {
    models: partition.textModels,
    specializedModels: partition.specializedModels,
  }
}

function describeProviderError(error: unknown): string {
  if (error instanceof ProviderRequestError) {
    const status = error.status === undefined ? '' : `HTTP ${error.status}`
    const detail = safeErrorDetail(error.detail ?? '')
    return [status, error.kind === 'region' ? error.message : detail || error.message].filter(Boolean).join('：')
  }
  return '未知请求错误'
}

function shouldTryGeminiNativeFallback(error: unknown): error is ProviderRequestError {
  if (!(error instanceof ProviderRequestError) || error.kind === 'api-key') return false
  return error.kind === 'network' || error.status === undefined || error.status >= 400
}

function combinedGeminiModelError(openAiError: unknown, nativeError: unknown): ProviderRequestError {
  const hasRegionError = nativeError instanceof ProviderRequestError && nativeError.kind === 'region' || openAiError instanceof ProviderRequestError && openAiError.kind === 'region'
  const hasTemporaryError = nativeError instanceof ProviderRequestError && nativeError.kind === 'temporary' || openAiError instanceof ProviderRequestError && openAiError.kind === 'temporary'
  const kind: ProviderErrorKind = hasRegionError
    ? 'region'
    : nativeError instanceof ProviderRequestError && nativeError.kind === 'api-key'
    ? 'api-key'
    : hasTemporaryError
      ? 'temporary'
    : openAiError instanceof ProviderRequestError && openAiError.kind === 'network' && nativeError instanceof ProviderRequestError && nativeError.kind === 'network'
      ? 'network'
      : 'response'
  const status = nativeError instanceof ProviderRequestError ? nativeError.status : openAiError instanceof ProviderRequestError ? openAiError.status : undefined
  const prefix = hasRegionError ? `${GEMINI_REGION_ERROR} ` : ''
  const message = `${prefix}Gemini 模型列表获取失败。兼容接口：${describeProviderError(openAiError)}；原生接口回退：${describeProviderError(nativeError)}。`
  return new ProviderRequestError(kind, redactSensitiveText(message), status, redactSensitiveText(message))
}

async function fetchOpenAiModels(
  provider: Pick<ProviderProfile, 'baseUrl' | 'apiKey'>,
  signal?: AbortSignal,
): Promise<string[]> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (provider.apiKey.trim()) headers.Authorization = `Bearer ${provider.apiKey.trim()}`
  const response = await requestProvider(modelsUrl(provider.baseUrl), {
    method: 'GET',
    headers,
    signal,
    nativeHttp: usesNativeHttpTransport(provider.baseUrl),
  })
  if (!response.ok) {
    const detail = await response.text()
    throw httpError(response.status, errorText(detail), 'models', undefined, provider.apiKey)
  }

  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new ProviderRequestError('response', '接口返回格式错误，无法读取模型列表。', response.status)
  }
  const models = normalizeProviderModelIds(extractModelIds(payload), provider.baseUrl)
  if (!models.length) throw new ProviderRequestError('response', '接口返回成功，但没有找到可用模型。', response.status)
  return models
}

async function fetchGeminiNativeModels(apiKey: string, signal?: AbortSignal): Promise<string[]> {
  const response = await requestProvider(GEMINI_NATIVE_MODELS_URL, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      'x-goog-api-key': apiKey.trim(),
    },
    signal,
    nativeHttp: usesNativeHttpTransport(GEMINI_NATIVE_BASE_URL),
  })
  if (!response.ok) {
    const detail = await response.text()
    throw httpError(response.status, errorText(detail), 'models', undefined, apiKey)
  }

  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new ProviderRequestError('response', 'Gemini 原生模型接口返回格式错误。', response.status)
  }
  const models = extractGeminiNativeModelIds(payload)
  if (!models.length) throw new ProviderRequestError('response', 'Gemini 原生模型接口没有返回可生成内容的模型。', response.status)
  return models
}

export async function fetchAvailableModelsWithSource(
  provider: Pick<ProviderProfile, 'baseUrl' | 'apiKey'>,
  signal?: AbortSignal,
): Promise<AvailableModelsResult> {
  if (!provider.baseUrl.trim()) throw addressError()
  if (!provider.apiKey.trim()) throw new ProviderRequestError('api-key', '请先在 API 设置中填写密钥。')
  const normalizedBaseUrl = normalizeBaseUrl(provider.baseUrl)
  const isGemini = isGeminiOpenAiBaseUrl(normalizedBaseUrl)

  try {
    return {
      ...organizeAvailableModels(await fetchOpenAiModels({ ...provider, baseUrl: normalizedBaseUrl }, signal), isGemini),
      source: 'openai',
    }
  } catch (openAiError) {
    if (!isGemini || !shouldTryGeminiNativeFallback(openAiError)) throw openAiError
    try {
      const models = await fetchGeminiNativeModels(provider.apiKey, signal)
      return {
        ...organizeAvailableModels(models, true),
        source: 'gemini-native',
        warning: `Gemini OpenAI 兼容模型接口异常（${describeProviderError(openAiError)}），已回退到原生模型列表。`,
      }
    } catch (nativeError) {
      throw combinedGeminiModelError(openAiError, nativeError)
    }
  }
}

export async function fetchAvailableModels(
  provider: Pick<ProviderProfile, 'baseUrl' | 'apiKey'>,
  signal?: AbortSignal,
): Promise<string[]> {
  return (await fetchAvailableModelsWithSource(provider, signal)).models
}

function contentText(value: unknown): string {
  if (typeof value === 'string') return value
  if (!Array.isArray(value)) return ''
  return value.map((part) => {
    if (typeof part === 'string') return part
    if (!part || typeof part !== 'object') return ''
    const record = part as Record<string, unknown>
    return typeof record.text === 'string' ? record.text : typeof record.content === 'string' ? record.content : ''
  }).join('')
}

function extractDelta(payload: unknown): string {
  if (!payload || typeof payload !== 'object') return ''
  const choices = (payload as { choices?: unknown }).choices
  if (!Array.isArray(choices) || !choices[0] || typeof choices[0] !== 'object') return ''
  const choice = choices[0] as { delta?: { content?: unknown }; message?: { content?: unknown } }
  return contentText(choice.delta?.content) || contentText(choice.message?.content)
}

function extractFinishReason(payload: unknown): string | undefined {
  if (!payload || typeof payload !== 'object') return undefined
  const record = payload as Record<string, unknown>
  const choices = record.choices
  if (Array.isArray(choices)) {
    for (const candidate of choices) {
      if (!candidate || typeof candidate !== 'object') continue
      const choice = candidate as Record<string, unknown>
      const reason = choice.finish_reason ?? choice.finishReason
      if (typeof reason === 'string' && reason.trim()) return reason.trim()
    }
  }
  const reason = record.stop_reason ?? record.stopReason
  return typeof reason === 'string' && reason.trim() ? reason.trim() : undefined
}

function extractUsage(payload: unknown): CompletionUsage | undefined {
  if (!payload || typeof payload !== 'object') return undefined
  const usage = (payload as Record<string, unknown>).usage
  if (!usage || typeof usage !== 'object') return undefined
  const record = usage as Record<string, unknown>
  const inputTokens = Number(record.prompt_tokens ?? record.input_tokens ?? record.promptTokens ?? record.inputTokens)
  const outputTokens = Number(record.completion_tokens ?? record.output_tokens ?? record.completionTokens ?? record.outputTokens)
  if (!Number.isFinite(inputTokens) || !Number.isFinite(outputTokens)) return undefined
  return { inputTokens, outputTokens }
}

function publishPayload(
  payload: unknown,
  onToken?: (fullText: string) => void,
  onFinishReason?: (reason: string) => void,
  onUsage?: (usage: CompletionUsage) => void,
): string {
  const text = extractDelta(payload)
  const finishReason = extractFinishReason(payload)
  const usage = extractUsage(payload)
  if (finishReason) onFinishReason?.(finishReason)
  if (usage) onUsage?.(usage)
  onToken?.(text)
  return text
}

interface CompletionNetworkRequest {
  provider: ProviderProfile
  messages: CompletionRequest['messages']
  model: string
  nativeTransport: boolean
  signal?: AbortSignal
  onRetry?: (info: CompletionRetryInfo) => void
}

async function requestCompletionWithRetries({ provider, messages, model, nativeTransport, signal, onRetry }: CompletionNetworkRequest): Promise<ProviderResponse> {
  const endpoint = completionUrl(provider.baseUrl)
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
    Authorization: `Bearer ${provider.apiKey.trim()}`,
  }
  const body = buildCompletionBody(provider, messages, model, nativeTransport)
  const postCompletion = () => requestProvider(endpoint, {
    method: 'POST',
    headers,
    body,
    signal,
    nativeHttp: nativeTransport,
  })

  let response = await postCompletion()
  let temporaryRetries = 0
  while (!response.ok) {
    const rawDetail = await response.text()
    const detail = errorText(rawDetail)
    const classified = httpError(response.status, detail, 'chat', model, provider.apiKey)
    if (classified.kind !== 'temporary' || !isTemporaryStatus(response.status) || temporaryRetries >= MAX_TEMPORARY_RETRIES) {
      throw classified
    }

    temporaryRetries += 1
    const delay = retryDelayMs(response, rawDetail, temporaryRetries)
    onRetry?.({
      attempt: temporaryRetries,
      maxAttempts: MAX_TEMPORARY_RETRIES,
      delayMs: delay,
      status: response.status,
      message: temporaryErrorMessage(response.status, detail, true),
      model,
    })
    await waitForRetry(delay, signal)
    response = await postCompletion()
  }
  return response
}

function canTryBusyModelFallback(error: unknown): error is ProviderRequestError {
  if (!(error instanceof ProviderRequestError) || error.kind !== 'temporary') return false
  const status = error.status
  return status === 429 || status === 503 || status === 500 || status === 502 || status === 504
}

export async function streamCompletion({
  provider,
  messages,
  fallbackModels,
  signal,
  onToken,
  onFinishReason,
  onUsage,
  onRetry,
  onModelFallback,
}: CompletionRequest): Promise<string> {
  if (!provider.apiKey.trim()) throw new ProviderRequestError('api-key', '请先在 API 设置中填写密钥。')
  if (!provider.baseUrl.trim()) throw addressError()
  const normalizedModel = normalizeProviderModelId(provider.model, provider.baseUrl)
  if (!normalizedModel) throw new ProviderRequestError('model', '请先填写模型名。')

  const nativeTransport = usesNativeHttpTransport(provider.baseUrl)
  const models = Array.from(new Set([
    normalizedModel,
    ...(fallbackModels ?? []).map((model) => normalizeProviderModelId(model, provider.baseUrl)),
  ].map((model) => model.trim()).filter(Boolean)))
  let response: ProviderResponse | undefined
  for (let modelIndex = 0; modelIndex < models.length; modelIndex += 1) {
    const model = models[modelIndex]
    try {
      response = await requestCompletionWithRetries({
        provider,
        messages,
        model,
        nativeTransport,
        signal,
        onRetry,
      })
      break
    } catch (requestError) {
      const nextModel = models[modelIndex + 1]
      if (!nextModel || !canTryBusyModelFallback(requestError)) throw requestError
      onModelFallback?.({ fromModel: model, toModel: nextModel, fallbackIndex: modelIndex + 1 })
    }
  }

  if (!response) throw new ProviderRequestError('response', '接口没有返回对话响应。')

  if (!response.body) {
    let payload: unknown
    try {
      payload = await response.json()
    } catch {
      throw new ProviderRequestError('response', '接口返回格式错误，无法读取对话内容。', response.status)
    }
    return publishPayload(payload, onToken, onFinishReason, onUsage)
  }

  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    let payload: unknown
    try {
      payload = await response.json()
    } catch {
      throw new ProviderRequestError('response', '接口返回格式错误，无法读取对话内容。', response.status)
    }
    return publishPayload(payload, onToken, onFinishReason, onUsage)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let fullText = ''
  let finishSeen = false

  while (true) {
    const readResult = finishSeen ? await readAfterFinish(reader) : await reader.read()
    if ('timedOut' in readResult) {
      await reader.cancel()
      return fullText
    }
    const { done, value } = readResult
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      const event = consumeEventLine(line, fullText, onToken)
      fullText = event.text
      if (event.finishReason) onFinishReason?.(event.finishReason)
      if (event.usage) onUsage?.(event.usage)
      if (event.finishReason) finishSeen = true
      if (event.done) {
        await reader.cancel()
        return fullText
      }
    }
  }

  if (buffer.trim()) {
    const event = consumeEventLine(buffer, fullText, onToken)
    fullText = event.text
    if (event.finishReason) onFinishReason?.(event.finishReason)
    if (event.usage) onUsage?.(event.usage)
  }

  return fullText
}

async function readAfterFinish(reader: ReadableStreamDefaultReader<Uint8Array>) {
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<{ timedOut: true }>((resolve) => {
    timer = setTimeout(() => resolve({ timedOut: true }), 500)
  })
  const result = await Promise.race([reader.read(), timeout])
  if (timer) clearTimeout(timer)
  return result
}

function consumeEventLine(line: string, current: string, onToken?: (fullText: string) => void) {
  const data = line.trim().replace(/^data:\s*/u, '')
  if (!data) return { text: current, done: false, finishReason: undefined, usage: undefined }
  if (data === '[DONE]') return { text: current, done: true, finishReason: undefined, usage: undefined }
  try {
    const payload = JSON.parse(data)
    const next = current + extractDelta(payload)
    onToken?.(next)
    const finishReason = extractFinishReason(payload)
    return { text: next, done: false, finishReason, usage: extractUsage(payload) }
  } catch {
    // Providers may insert keepalive comments between SSE events.
    return { text: current, done: false, finishReason: undefined, usage: undefined }
  }
}
