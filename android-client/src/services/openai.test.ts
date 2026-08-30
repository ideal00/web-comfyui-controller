import { afterEach, describe, expect, it, vi } from 'vitest'
vi.mock('@capacitor/core', () => ({
  Capacitor: {
    isNativePlatform: vi.fn(() => false),
    isPluginAvailable: vi.fn(() => false),
  },
  CapacitorHttp: { request: vi.fn() },
}))
import { Capacitor, CapacitorHttp } from '@capacitor/core'
import { completionUrl, extractGeminiNativeModelIds, extractModelIds, fetchAvailableModels, fetchAvailableModelsWithSource, GEMINI_NATIVE_MODELS_URL, GEMINI_OPENAI_BASE_URL, geminiModelRecommendationRank, isGeminiOpenAiBaseUrl, isGeminiSamplingRestrictedModel, isGeminiSpecializedModelId, isTemporaryStatus, MAX_TEMPORARY_RETRIES, modelsUrl, normalizeBaseUrl, normalizeProviderModelId, normalizeProviderModelIds, partitionGeminiModels, ProviderRequestError, sortGeminiTextModelIds, streamCompletion } from './openai'

afterEach(() => vi.restoreAllMocks())

describe('OpenAI-compatible URLs', () => {
  it('builds endpoints from a v1 base URL', () => {
    expect(completionUrl('https://example.com/v1/')).toBe('https://example.com/v1/chat/completions')
    expect(modelsUrl('https://example.com/v1/')).toBe('https://example.com/v1/models')
  })

  it('replaces a full completion URL when listing models', () => {
    expect(modelsUrl('https://example.com/v1/chat/completions')).toBe('https://example.com/v1/models')
  })

  it('keeps Gemini model URLs exact without duplicate path segments', () => {
    expect(modelsUrl('https://generativelanguage.googleapis.com/v1beta/openai')).toBe('https://generativelanguage.googleapis.com/v1beta/openai/models')
    expect(modelsUrl('https://generativelanguage.googleapis.com/v1beta/openai/')).toBe('https://generativelanguage.googleapis.com/v1beta/openai/models')
    expect(modelsUrl('https://generativelanguage.googleapis.com/v1beta/openai/models')).toBe('https://generativelanguage.googleapis.com/v1beta/openai/models')
    expect(modelsUrl('https://generativelanguage.googleapis.com/v1beta/openai/v1/models')).toBe('https://generativelanguage.googleapis.com/v1beta/openai/models')
  })

  it('normalizes a bare proxy domain to an OpenAI v1 base URL', () => {
    expect(normalizeBaseUrl('example.com')).toBe('https://example.com/v1')
    expect(modelsUrl('example.com')).toBe('https://example.com/v1/models')
  })

  it.each([
    'googleapis.com',
    'https://googleapis.com',
    'generativelanguage.googleapis.com',
    'https://generativelanguage.googleapis.com/v1beta/',
    'https://generativelanguage.googleapis.com/v1beta/openai/',
    'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
  ])('normalizes Gemini input %s to its OpenAI-compatible root', (input) => {
    expect(normalizeBaseUrl(input)).toBe(GEMINI_OPENAI_BASE_URL)
    expect(isGeminiOpenAiBaseUrl(input)).toBe(true)
    expect(modelsUrl(input)).toBe(`${GEMINI_OPENAI_BASE_URL}/models`)
    expect(completionUrl(input)).toBe(`${GEMINI_OPENAI_BASE_URL}/chat/completions`)
  })

  it('does not duplicate OpenAI endpoint suffixes for other providers', () => {
    expect(completionUrl('https://example.com/v1/openai/')).toBe('https://example.com/v1/openai/chat/completions')
    expect(modelsUrl('https://example.com/v1/openai/chat/completions')).toBe('https://example.com/v1/openai/models')
  })

  it('rejects malformed addresses with a Chinese address error', () => {
    expect(() => normalizeBaseUrl('not a valid url')).toThrow('接口地址格式错误')
  })
})

describe('extractModelIds', () => {
  it('reads and deduplicates the standard OpenAI response', () => {
    expect(extractModelIds({ data: [{ id: 'gpt-4o' }, { id: 'gpt-4o' }, { id: 'claude-3.5' }] })).toEqual([
      'claude-3.5',
      'gpt-4o',
    ])
  })

  it('accepts common proxy response variants', () => {
    expect(extractModelIds({ models: ['model-10', { name: 'model-2' }] })).toEqual(['model-2', 'model-10'])
  })
})

describe('provider model IDs', () => {
  it('removes only Gemini native resource prefixes', () => {
    expect(normalizeProviderModelId('models/gemini-3.7-flash', GEMINI_OPENAI_BASE_URL)).toBe('gemini-3.7-flash')
    expect(normalizeProviderModelId('models/gpt-4o', 'https://api.openai.com/v1')).toBe('models/gpt-4o')
    expect(normalizeProviderModelIds(['models/gemini-3.7-flash', 'gemini-3.7-flash'], GEMINI_OPENAI_BASE_URL)).toEqual(['gemini-3.7-flash'])
  })

  it('sorts Gemini text models by RPG stability recommendation and folds specialized models', () => {
    const partition = partitionGeminiModels([
      'models/gemini-3.7-flash',
      'gemini-2.0-flash-live',
      'gemini-3.5-flash',
      'models/gemini-3.1-flash-lite',
      'gemini-2.5-flash-image-preview',
      'gemini-3.5-flash-lite',
      'gemini-3.6-flash',
      'gemini-embedding-001',
    ])
    expect(partition.textModels).toEqual([
      'gemini-3.5-flash-lite',
      'gemini-3.1-flash-lite',
      'gemini-3.5-flash',
      'gemini-3.6-flash',
      'gemini-3.7-flash',
    ])
    expect(partition.specializedModels).toEqual(['gemini-2.0-flash-live', 'gemini-2.5-flash-image-preview', 'gemini-embedding-001'])
    expect(sortGeminiTextModelIds(['models/gemini-3.7-flash', 'gemini-3.5-flash-lite'])).toEqual(['gemini-3.5-flash-lite', 'gemini-3.7-flash'])
    expect(isGeminiSpecializedModelId('gemini-2.5-flash-image-preview')).toBe(true)
    expect(isGeminiSpecializedModelId('gemini-3.5-flash')).toBe(false)
    expect(geminiModelRecommendationRank('gemini-3.5-flash-lite')).toBeLessThan(geminiModelRecommendationRank('gemini-3.7-flash'))
  })

  it('marks Gemini 3.6/3.7 as sampling-restricted without affecting ordinary providers', () => {
    expect(isGeminiSamplingRestrictedModel('models/gemini-3.7-flash', GEMINI_OPENAI_BASE_URL)).toBe(true)
    expect(isGeminiSamplingRestrictedModel('gemini-3.6-flash', 'generativelanguage.googleapis.com/v1beta')).toBe(true)
    expect(isGeminiSamplingRestrictedModel('gemini-3.5-flash', GEMINI_OPENAI_BASE_URL)).toBe(false)
    expect(isGeminiSamplingRestrictedModel('models/gemini-3.7-flash', 'https://api.openai.com/v1')).toBe(false)
  })
})

describe('extractGeminiNativeModelIds', () => {
  it('strips the models prefix and prefers models supporting generateContent', () => {
    expect(extractGeminiNativeModelIds({
      models: [
        { name: 'models/gemini-2.0-flash', supportedGenerationMethods: ['generateContent', 'countTokens'] },
        { name: 'models/gemini-embedding-001', supportedGenerationMethods: ['embedContent'] },
        { name: 'models/gemini-1.5-pro', supportedGenerationMethods: ['generateContent'] },
      ],
    })).toEqual(['gemini-1.5-pro', 'gemini-2.0-flash'])
  })

  it('retains named models when a proxy omits capability metadata', () => {
    expect(extractGeminiNativeModelIds({ models: [{ name: 'models/custom-gemini' }, { name: 'gemini-2' }] })).toEqual(['custom-gemini', 'gemini-2'])
  })
})

describe('provider requests', () => {
  it('uses Gemini OpenAI paths and Bearer authentication for model discovery', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ data: [{ id: 'gemini-3.7-flash' }] }), { status: 200, headers: { 'content-type': 'application/json' } }))

    await expect(fetchAvailableModels({ baseUrl: 'generativelanguage.googleapis.com/v1beta', apiKey: 'test-key' })).resolves.toEqual(['gemini-3.7-flash'])
    expect(fetchMock.mock.calls[0][0]).toBe(`${GEMINI_OPENAI_BASE_URL}/models`)
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ headers: { Authorization: 'Bearer test-key' } })
  })

  it('falls back from a Gemini OpenAI models 400 to the exact native models URL', async () => {
    vi.spyOn(Capacitor, 'isNativePlatform').mockReturnValue(true)
    const nativeRequest = vi.spyOn(CapacitorHttp, 'request').mockImplementation(async (options) => {
      if (options.url === `${GEMINI_OPENAI_BASE_URL}/models`) {
        return {
          status: 400,
          headers: { 'content-type': 'application/json' },
          data: JSON.stringify({ error: { code: 400, status: 'INVALID_ARGUMENT', message: '模型列表兼容端点参数不被接受' } }),
          url: options.url,
        }
      }
      return {
        status: 200,
        headers: { 'content-type': 'application/json' },
        data: JSON.stringify({ models: [
          { name: 'models/gemini-2.0-flash', supportedGenerationMethods: ['generateContent'] },
          { name: 'models/gemini-2.5-flash-image-preview', supportedGenerationMethods: ['generateContent'] },
          { name: 'models/gemini-embedding-001', supportedGenerationMethods: ['embedContent'] },
        ] }),
        url: options.url,
      }
    })

    const result = await fetchAvailableModelsWithSource({
      baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai/',
      apiKey: 'test-key',
    })

    expect(result).toMatchObject({ source: 'gemini-native', models: ['gemini-2.0-flash'], specializedModels: ['gemini-2.5-flash-image-preview'] })
    expect(result.warning).toContain('INVALID_ARGUMENT')
    expect(result.warning).toContain('模型列表兼容端点参数不被接受')
    expect(result.warning).not.toContain('test-key')
    expect(nativeRequest).toHaveBeenCalledTimes(2)

    const compatOptions = nativeRequest.mock.calls[0][0]
    expect(compatOptions).toMatchObject({
      url: `${GEMINI_OPENAI_BASE_URL}/models`,
      method: 'GET',
      headers: { Accept: 'application/json', Authorization: 'Bearer test-key' },
    })
    expect(compatOptions).not.toHaveProperty('data')
    expect(compatOptions).not.toHaveProperty('params')
    expect(compatOptions.headers).not.toHaveProperty('Content-Type')

    const nativeOptions = nativeRequest.mock.calls[1][0]
    expect(nativeOptions).toMatchObject({
      url: GEMINI_NATIVE_MODELS_URL,
      method: 'GET',
      headers: { Accept: 'application/json', 'x-goog-api-key': 'test-key' },
    })
    expect(nativeOptions).not.toHaveProperty('data')
    expect(nativeOptions).not.toHaveProperty('params')
    expect(nativeOptions.headers).not.toHaveProperty('Content-Type')
    expect(nativeOptions.headers).not.toHaveProperty('Authorization')
  })

  it('keeps HTTP 400 details and does not mislabel them as an address error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { code: 400, status: 'INVALID_ARGUMENT', message: '请求体中存在不支持的字段' } }), { status: 400 }))

    const error = await fetchAvailableModels({ baseUrl: 'https://example.com/v1', apiKey: 'test-key' }).catch((value: unknown) => value)
    expect(error).toMatchObject({ kind: 'response', status: 400 })
    expect((error as Error).message).toContain('请求体中存在不支持的字段')
    expect((error as Error).message).toContain('INVALID_ARGUMENT')
    expect((error as Error).message).not.toContain('接口地址错误')
    expect((error as Error).message).not.toContain('test-key')
  })

  it('recognizes Gemini region restrictions in Google error details', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { code: 400, status: 'FAILED_PRECONDITION', message: 'Gemini API is not available in your location' } }), { status: 400 }))

    const error = await fetchAvailableModels({ baseUrl: 'https://example.com/v1', apiKey: 'test-key' }).catch((value: unknown) => value)
    expect(error).toMatchObject({ kind: 'region', status: 400 })
    expect((error as Error).message).toContain('当前网络出口地区不受 Gemini API 支持')
    expect((error as Error).message).toContain('FAILED_PRECONDITION')
    expect((error as Error).message).toContain('your location')
    expect((error as Error).message).not.toContain('接口地址错误')
    expect((error as Error).message).not.toContain('test-key')
  })

  it('classifies invalid keys without exposing response details', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { status: 'UNAUTHENTICATED', message: 'invalid authentication credentials' } }), { status: 401 }))

    const error = await fetchAvailableModels({ baseUrl: 'https://generativelanguage.googleapis.com/v1beta/', apiKey: 'test-key' }).catch((value: unknown) => value)
    expect(error).toBeInstanceOf(ProviderRequestError)
    expect(error).toMatchObject({ kind: 'api-key', status: 401 })
    expect((error as Error).message).toContain('API Key 无效或未授权')
    expect((error as Error).message).not.toContain('test-key')
  })

  it('classifies browser fetch failures as network/CORS errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))

    const error = await fetchAvailableModels({ baseUrl: 'https://generativelanguage.googleapis.com/v1beta', apiKey: 'test-key' }).catch((value: unknown) => value)
    expect(error).toMatchObject({ kind: 'network' })
    expect((error as Error).message).toContain('网络/CORS')
  })

  it('classifies a missing model separately from an address error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { message: 'models/gemini-missing is not found for API version v1beta' } }), { status: 404 }))

    const error = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'https://generativelanguage.googleapis.com/v1beta', apiKey: 'test-key', model: 'gemini-missing', models: ['gemini-missing'], temperature: 1, topP: 1, presencePenalty: 0, frequencyPenalty: 0, maxTokens: 100 },
      messages: [],
    }).catch((value: unknown) => value)
    expect(error).toMatchObject({ kind: 'model', status: 404 })
    expect((error as Error).message).toContain('模型不存在')
  })

  it('classifies a missing model endpoint as an address error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('Not Found', { status: 404 }))

    const error = await fetchAvailableModels({ baseUrl: 'https://example.com/v1', apiKey: 'test-key' }).catch((value: unknown) => value)
    expect(error).toMatchObject({ kind: 'address', status: 404 })
    expect((error as Error).message).toContain('接口地址错误')
  })

  it('uses Capacitor native HTTP on Android and falls back to a complete response', async () => {
    vi.spyOn(Capacitor, 'isNativePlatform').mockReturnValue(true)
    vi.spyOn(Capacitor, 'isPluginAvailable').mockReturnValue(true)
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    const nativeRequest = vi.spyOn(CapacitorHttp, 'request').mockResolvedValue({
      status: 200,
      headers: { 'content-type': 'application/json' },
      data: JSON.stringify({ choices: [{ message: { content: 'Gemini 原生通道回复' }, finish_reason: 'stop' }] }),
      url: `${GEMINI_OPENAI_BASE_URL}/chat/completions`,
    })

    const result = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'googleapis.com/v1beta/openai/', apiKey: 'test-key', model: 'models/gemini-3.7-flash', models: ['models/gemini-3.7-flash'], temperature: 1, topP: 1, presencePenalty: 0.4, frequencyPenalty: -0.2, maxTokens: 100 },
      messages: [{ role: 'user', content: '你好' }],
    })

    expect(result).toBe('Gemini 原生通道回复')
    expect(fetchMock).not.toHaveBeenCalled()
    expect(nativeRequest).toHaveBeenCalledOnce()
    expect(nativeRequest.mock.calls[0][0]).toMatchObject({
      url: `${GEMINI_OPENAI_BASE_URL}/chat/completions`,
      method: 'POST',
      headers: { Authorization: 'Bearer test-key', 'Content-Type': 'application/json' },
      data: { model: 'gemini-3.7-flash', stream: false },
    })
    expect(nativeRequest.mock.calls[0][0].data).not.toHaveProperty('stream_options')
    expect(nativeRequest.mock.calls[0][0].data).not.toHaveProperty('presence_penalty')
    expect(nativeRequest.mock.calls[0][0].data).not.toHaveProperty('frequency_penalty')
    expect(nativeRequest.mock.calls[0][0].data).not.toHaveProperty('temperature')
    expect(nativeRequest.mock.calls[0][0].data).not.toHaveProperty('top_p')
  })

  it('keeps sampling fields for a supported Gemini text model', async () => {
    vi.spyOn(Capacitor, 'isNativePlatform').mockReturnValue(true)
    const nativeRequest = vi.spyOn(CapacitorHttp, 'request').mockResolvedValue({
      status: 200,
      headers: { 'content-type': 'application/json' },
      data: JSON.stringify({ choices: [{ message: { content: '文本模型回复' } }] }),
      url: `${GEMINI_OPENAI_BASE_URL}/chat/completions`,
    })

    await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: GEMINI_OPENAI_BASE_URL, apiKey: 'test-key', model: 'gemini-3.5-flash', models: ['gemini-3.5-flash'], temperature: 0.7, topP: 0.8, presencePenalty: 0, frequencyPenalty: 0, maxTokens: 100 },
      messages: [],
    })

    expect(nativeRequest.mock.calls[0][0].data).toMatchObject({ model: 'gemini-3.5-flash', temperature: 0.7, top_p: 0.8, max_tokens: 100, stream: false })
  })

  it('does not retry a Gemini HTTP 400, including an unknown-field response', async () => {
    vi.spyOn(Capacitor, 'isNativePlatform').mockReturnValue(true)
    const nativeRequest = vi.spyOn(CapacitorHttp, 'request').mockResolvedValue({
      status: 400,
      headers: { 'content-type': 'application/json' },
      data: JSON.stringify({ error: { code: 400, status: 'INVALID_ARGUMENT', message: 'Invalid JSON payload received. Unknown name "frequency_penalty": Cannot find field.' } }),
      url: `${GEMINI_OPENAI_BASE_URL}/chat/completions`,
    })
    const retries: unknown[] = []

    const error = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'https://generativelanguage.googleapis.com/v1beta', apiKey: 'test-key', model: 'models/gemini-3.7-flash', models: ['models/gemini-3.7-flash'], temperature: 0.7, topP: 0.8, presencePenalty: 0.4, frequencyPenalty: -0.2, maxTokens: 100 },
      messages: [{ role: 'user', content: '你好' }],
      onRetry: (info) => retries.push(info),
    }).catch((value: unknown) => value)

    expect(error).toMatchObject({ kind: 'response', status: 400 })
    expect((error as Error).message).toContain('Unknown name')
    expect((error as Error).message).toContain('frequency_penalty')
    expect(nativeRequest).toHaveBeenCalledOnce()
    expect(retries).toEqual([])
  })

  it('retries a temporary Gemini 503 and preserves one logical response callback', async () => {
    vi.spyOn(Capacitor, 'isNativePlatform').mockReturnValue(true)
    let callCount = 0
    const retryEvents: Array<{ attempt: number; status: number; delayMs: number; message: string }> = []
    const tokens: string[] = []
    const nativeRequest = vi.spyOn(CapacitorHttp, 'request').mockImplementation(async (options) => {
      callCount += 1
      if (callCount === 1) {
        return {
          status: 503,
          headers: { 'content-type': 'application/json', 'retry-after': '0' },
          data: JSON.stringify({ error: { code: 503, status: 'UNAVAILABLE', message: 'This model is currently experiencing high demand.' } }),
          url: options.url,
        }
      }
      return {
        status: 200,
        headers: { 'content-type': 'application/json', 'retry-after': '0' },
        data: JSON.stringify({ choices: [{ message: { content: '临时恢复后的回复' }, finish_reason: 'stop' }] }),
        url: options.url,
      }
    })

    const result = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'https://generativelanguage.googleapis.com/v1beta', apiKey: 'test-key', model: 'models/gemini-3.7-flash', models: ['models/gemini-3.7-flash'], temperature: 0.7, topP: 0.8, presencePenalty: 0.4, frequencyPenalty: -0.2, maxTokens: 100 },
      messages: [{ role: 'user', content: '你好' }],
      onRetry: (info) => retryEvents.push(info),
      onToken: (content) => tokens.push(content),
    })

    expect(result).toBe('临时恢复后的回复')
    expect(nativeRequest).toHaveBeenCalledTimes(2)
    expect(retryEvents).toHaveLength(1)
    expect(retryEvents[0]).toMatchObject({ attempt: 1, maxAttempts: MAX_TEMPORARY_RETRIES, status: 503, delayMs: 0 })
    expect(retryEvents[0].message).toContain('模型当前请求量过高，正在重试')
    expect(tokens).toEqual(['临时恢复后的回复'])
    expect(nativeRequest.mock.calls[0][0]).toMatchObject({ url: `${GEMINI_OPENAI_BASE_URL}/chat/completions`, method: 'POST', data: { model: 'gemini-3.7-flash', stream: false } })
    expect(nativeRequest.mock.calls[1][0]).toMatchObject({ url: `${GEMINI_OPENAI_BASE_URL}/chat/completions`, method: 'POST', data: { model: 'gemini-3.7-flash', stream: false } })
  })

  it('stops after three temporary retries and reports a Chinese congestion error', async () => {
    vi.spyOn(Capacitor, 'isNativePlatform').mockReturnValue(true)
    const nativeRequest = vi.spyOn(CapacitorHttp, 'request').mockResolvedValue({
      status: 503,
      headers: { 'content-type': 'application/json', 'retry-after': '0' },
      data: JSON.stringify({ error: { code: 503, status: 'UNAVAILABLE', message: 'This model is currently experiencing high demand.' } }),
      url: `${GEMINI_OPENAI_BASE_URL}/chat/completions`,
    })
    const retryEvents: Array<{ attempt: number; status: number }> = []
    const error = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'https://generativelanguage.googleapis.com/v1beta', apiKey: 'test-key', model: 'models/gemini-3.7-flash', models: ['models/gemini-3.7-flash'], temperature: 0.7, topP: 0.8, presencePenalty: 0, frequencyPenalty: 0, maxTokens: 100 },
      messages: [],
      onRetry: (info) => retryEvents.push({ attempt: info.attempt, status: info.status }),
    }).catch((value: unknown) => value)

    expect(nativeRequest).toHaveBeenCalledTimes(MAX_TEMPORARY_RETRIES + 1)
    expect(retryEvents).toEqual([{ attempt: 1, status: 503 }, { attempt: 2, status: 503 }, { attempt: 3, status: 503 }])
    expect(error).toMatchObject({ kind: 'temporary', status: 503 })
    expect((error as Error).message).toContain('模型当前请求量过高，请稍后重试或切换到稳定的 Flash-Lite/Flash 模型')
    expect((error as Error).message).toContain('UNAVAILABLE')
    expect((error as Error).message).not.toContain('test-key')
  })

  it('tries an ordered busy-model fallback only after the primary retries are exhausted', async () => {
    vi.spyOn(Capacitor, 'isNativePlatform').mockReturnValue(true)
    let callCount = 0
    const tokens: string[] = []
    const fallbackEvents: Array<{ fromModel: string; toModel: string; fallbackIndex: number }> = []
    const nativeRequest = vi.spyOn(CapacitorHttp, 'request').mockImplementation(async (options) => {
      callCount += 1
      if (callCount <= MAX_TEMPORARY_RETRIES + 1) {
        return {
          status: 503,
          headers: { 'content-type': 'application/json', 'retry-after': '0' },
          data: JSON.stringify({ error: { code: 503, status: 'UNAVAILABLE', message: 'high demand' } }),
          url: options.url,
        }
      }
      return {
        status: 200,
        headers: { 'content-type': 'application/json', 'retry-after': '0' },
        data: JSON.stringify({ choices: [{ message: { content: '备用模型回复' }, finish_reason: 'stop' }] }),
        url: options.url,
      }
    })

    const result = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: GEMINI_OPENAI_BASE_URL, apiKey: 'test-key', model: 'models/gemini-3.7-flash', models: ['models/gemini-3.7-flash'], temperature: 0.7, topP: 0.8, presencePenalty: 0, frequencyPenalty: 0, maxTokens: 100 },
      fallbackModels: ['models/gemini-3.5-flash-lite', 'gemini-3.5-flash'],
      messages: [{ role: 'user', content: '你好' }],
      onModelFallback: (info) => fallbackEvents.push(info),
      onToken: (content) => tokens.push(content),
    })

    expect(result).toBe('备用模型回复')
    expect(nativeRequest).toHaveBeenCalledTimes(MAX_TEMPORARY_RETRIES + 2)
    expect(fallbackEvents).toEqual([{ fromModel: 'gemini-3.7-flash', toModel: 'gemini-3.5-flash-lite', fallbackIndex: 1 }])
    expect(tokens).toEqual(['备用模型回复'])
    expect(nativeRequest.mock.calls.slice(0, MAX_TEMPORARY_RETRIES + 1).every(([options]) => options.data?.model === 'gemini-3.7-flash')).toBe(true)
    expect(nativeRequest.mock.calls.at(-1)?.[0].data).toMatchObject({ model: 'gemini-3.5-flash-lite', temperature: 0.7, top_p: 0.8 })
  })

  it('never switches to a fallback model for a non-temporary 400', async () => {
    vi.spyOn(Capacitor, 'isNativePlatform').mockReturnValue(true)
    const nativeRequest = vi.spyOn(CapacitorHttp, 'request').mockResolvedValue({
      status: 400,
      headers: { 'content-type': 'application/json' },
      data: JSON.stringify({ error: { code: 400, status: 'INVALID_ARGUMENT', message: 'bad request' } }),
      url: `${GEMINI_OPENAI_BASE_URL}/chat/completions`,
    })
    const fallbackEvents: unknown[] = []
    const error = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: GEMINI_OPENAI_BASE_URL, apiKey: 'test-key', model: 'gemini-3.7-flash', models: ['gemini-3.7-flash'], temperature: 0.7, topP: 0.8, presencePenalty: 0, frequencyPenalty: 0, maxTokens: 100 },
      fallbackModels: ['gemini-3.5-flash-lite'],
      messages: [],
      onModelFallback: (info) => fallbackEvents.push(info),
    }).catch((value: unknown) => value)

    expect(error).toMatchObject({ kind: 'response', status: 400 })
    expect(nativeRequest).toHaveBeenCalledOnce()
    expect(fallbackEvents).toEqual([])
  })

  it.each([408, 429, 500, 502, 503, 504])('recognizes HTTP %s as a temporary status', (status) => {
    expect(isTemporaryStatus(status)).toBe(true)
  })

  it('aborts during temporary retry backoff without issuing another request', async () => {
    vi.spyOn(Capacitor, 'isNativePlatform').mockReturnValue(true)
    const nativeRequest = vi.spyOn(CapacitorHttp, 'request').mockResolvedValue({
      status: 503,
      headers: { 'content-type': 'application/json', 'retry-after': '60' },
      data: JSON.stringify({ error: { code: 503, status: 'UNAVAILABLE', message: 'temporary overload' } }),
      url: `${GEMINI_OPENAI_BASE_URL}/chat/completions`,
    })
    const controller = new AbortController()
    const completion = streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'https://generativelanguage.googleapis.com/v1beta', apiKey: 'test-key', model: 'models/gemini-3.7-flash', models: ['models/gemini-3.7-flash'], temperature: 1, topP: 1, presencePenalty: 0, frequencyPenalty: 0, maxTokens: 100 },
      messages: [],
      signal: controller.signal,
    })

    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(nativeRequest).toHaveBeenCalledOnce()
    controller.abort()
    await expect(completion).rejects.toMatchObject({ name: 'AbortError' })
    expect(nativeRequest).toHaveBeenCalledOnce()
  })

  it('keeps penalty fields for ordinary OpenAI-compatible providers', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ choices: [{ message: { content: '普通接口回复' } }] }), { status: 200, headers: { 'content-type': 'application/json' } }))

    await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'https://example.com/v1', apiKey: 'test-key', model: 'model', models: ['model'], temperature: 0.7, topP: 0.8, presencePenalty: 0.4, frequencyPenalty: -0.2, maxTokens: 100 },
      messages: [],
    })

    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body)) as Record<string, unknown>
    expect(body).toMatchObject({ presence_penalty: 0.4, frequency_penalty: -0.2, stream: true, stream_options: { include_usage: true } })
  })

  it('keeps other OpenAI-compatible providers on the existing browser transport', async () => {
    vi.spyOn(Capacitor, 'isNativePlatform').mockReturnValue(true)
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ choices: [{ message: { content: '普通兼容接口回复' } }] }), { status: 200, headers: { 'content-type': 'application/json' } }))
    const nativeRequest = vi.spyOn(CapacitorHttp, 'request')

    const result = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'https://example.com/v1', apiKey: 'test-key', model: 'model', models: ['model'], temperature: 1, topP: 1, presencePenalty: 0, frequencyPenalty: 0, maxTokens: 100 },
      messages: [],
    })

    expect(result).toBe('普通兼容接口回复')
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(nativeRequest).not.toHaveBeenCalled()
  })
})

describe('streamCompletion', () => {
  it('publishes progressively accumulated SSE content', async () => {
    const encoder = new TextEncoder()
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"第一"}}]}\n\n'))
        controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"段"}}]}\n\n'))
        controller.enqueue(encoder.encode('data: [DONE]\n\n'))
        controller.close()
      },
    })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body, { headers: { 'content-type': 'text/event-stream' } }))
    const updates: string[] = []

    const result = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'https://example.com/v1', apiKey: 'key', model: 'model', models: ['model'], temperature: 1, topP: 1, presencePenalty: 0, frequencyPenalty: 0, maxTokens: 100 },
      messages: [],
      onToken: (text) => updates.push(text),
    })

    expect(updates).toEqual(['第一', '第一段'])
    expect(result).toBe('第一段')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      temperature: 1,
      top_p: 1,
      presence_penalty: 0,
      frequency_penalty: 0,
      max_tokens: 100,
      stream: true,
      stream_options: { include_usage: true },
    })
  })

  it('finishes when the provider sends finish_reason without closing the stream', async () => {
    const encoder = new TextEncoder()
    let cancelled = false
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"完整回复"}}]}\n\n'))
        controller.enqueue(encoder.encode('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'))
      },
      cancel() {
        cancelled = true
      },
    })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body, { headers: { 'content-type': 'text/event-stream' } }))

    const result = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'https://example.com/v1', apiKey: 'key', model: 'model', models: ['model'], temperature: 1, topP: 1, presencePenalty: 0, frequencyPenalty: 0, maxTokens: 100 },
      messages: [],
    })

    expect(result).toBe('完整回复')
    expect(cancelled).toBe(true)
  })

  it('reports when an SSE completion reaches the token limit', async () => {
    const encoder = new TextEncoder()
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"未完成"}}]}\n\n'))
        controller.enqueue(encoder.encode('data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'))
      },
    })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body, { headers: { 'content-type': 'text/event-stream' } }))
    const finishReasons: string[] = []

    const result = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'https://example.com/v1', apiKey: 'key', model: 'model', models: ['model'], temperature: 1, topP: 1, presencePenalty: 0, frequencyPenalty: 0, maxTokens: 100 },
      messages: [],
      onFinishReason: (reason) => finishReasons.push(reason),
    })

    expect(result).toBe('未完成')
    expect(finishReasons).toEqual(['length'])
  })

  it('reports token usage sent after the finish reason', async () => {
    const encoder = new TextEncoder()
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"完成"},"finish_reason":"stop"}]}\n\n'))
        controller.enqueue(encoder.encode('data: {"choices":[],"usage":{"prompt_tokens":123,"completion_tokens":45}}\n\n'))
        controller.enqueue(encoder.encode('data: [DONE]\n\n'))
        controller.close()
      },
    })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body, { headers: { 'content-type': 'text/event-stream' } }))
    const usages: Array<{ inputTokens: number; outputTokens: number }> = []

    const result = await streamCompletion({
      provider: { id: 'test', name: 'test', baseUrl: 'https://example.com/v1', apiKey: 'key', model: 'model', models: ['model'], temperature: 1, topP: 1, presencePenalty: 0, frequencyPenalty: 0, maxTokens: 100 },
      messages: [],
      onUsage: (usage) => usages.push(usage),
    })

    expect(result).toBe('完成')
    expect(usages).toEqual([{ inputTokens: 123, outputTokens: 45 }])
  })
})
