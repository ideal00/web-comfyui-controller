import { describe, expect, it, vi } from 'vitest'
import {
  attachEasyPanelPendingDerivation,
  buildEasyPanelControllerRequest,
  createEasyPanelControllerRequestId,
  extractEasyPanelModels,
  normalizeEasyPanelControllerSettings,
  normalizeEasyPanelControllerState,
  reduceEasyPanelControllerInteraction,
} from './easyPanelController'

describe('standalone Easy Panel controller', () => {
  it('normalizes mobile settings to the server limits', () => {
    const settings = normalizeEasyPanelControllerSettings({
      width: 1,
      height: 99999,
      pollIntervalMs: 1,
      prompt: '  a prompt  ',
      negative: '  bad anatomy  ',
      quality: 'fast',
    })
    expect(settings).toMatchObject({
      width: 512,
      height: 1920,
      pollIntervalMs: 800,
      prompt: 'a prompt',
      negative: 'bad anatomy',
      quality: 'fast',
    })
  })

  it('builds a generic structured request without exposing workflow details', () => {
    const settings = normalizeEasyPanelControllerSettings({
      prompt: 'anime illustration, a lighthouse at sunset',
      negative: 'blurry',
      quality: 'detailed',
      model: 'checkpoint.safetensors',
      width: 1024,
      height: 1024,
    })
    const request = buildEasyPanelControllerRequest(settings, 'easy_panel_mobile_123')
    expect(request.client).toEqual({
      gameId: 'easy-panel-mobile',
      sceneId: 'easy_panel_mobile_123',
      requestId: 'easy_panel_mobile_123',
    })
    expect(request.visual).toEqual({ characters: [], scene: 'anime illustration, a lighthouse at sunset' })
    expect(request.generation).toMatchObject({
      model: 'checkpoint.safetensors',
      quality: 'detailed',
      width: 1024,
      height: 1024,
      negative: 'blurry',
    })
  })

  it('creates a recoverable request id and preserves a pending request in state', () => {
    const requestId = createEasyPanelControllerRequestId()
    expect(requestId).toMatch(/^[0-9A-Za-z_-]+$/u)
    expect(requestId.length).toBeLessThanOrEqual(48)
    const request = buildEasyPanelControllerRequest(
      normalizeEasyPanelControllerSettings({ prompt: 'a quiet room' }),
      requestId,
    )
    const state = normalizeEasyPanelControllerState({
      pendingJob: { requestId, jobId: '', submittedAt: 123, request },
    })
    expect(state.pendingJob?.requestId).toBe(requestId)
    expect(state.pendingJob?.request.visual.scene).toBe('a quiet room')
  })

  it('deduplicates model names across server model families', () => {
    expect(extractEasyPanelModels({
      api_version: 2,
      checkpoints: ['a.safetensors', 'shared.safetensors'],
      anima_models: ['shared.safetensors', 'anima.gguf'],
      krea2_models: ['krea2.gguf'],
      qualityProfiles: { fast: { steps: 8 } },
    })).toEqual(['a.safetensors', 'shared.safetensors', 'anima.gguf', 'krea2.gguf'])
  })

  it('attaches only a validated one-shot lineage relation to explicit requests', () => {
    const request = buildEasyPanelControllerRequest(
      normalizeEasyPanelControllerSettings({ prompt: 'a quiet room' }),
      'request-lineage',
    )
    const linked = attachEasyPanelPendingDerivation(request, {
      parentGenerationId: 'a'.repeat(32),
      parentArtifactId: 'b'.repeat(32),
      operation: 'seed_variant',
    })
    expect(linked).toMatchObject({
      parentGenerationId: 'a'.repeat(32),
      parentArtifactId: 'b'.repeat(32),
      operation: 'seed_variant',
    })
    expect(attachEasyPanelPendingDerivation(request, {
      parentGenerationId: 'unsafe', operation: 'txt2img',
    })).toEqual(request)
  })

  it('keeps model/quality/size/prompt edits away from the mocked generate API', () => {
    const generateApi = vi.fn()
    let settings = normalizeEasyPanelControllerSettings({
      baseUrl: 'http://192.168.1.10:8190',
      token: 'local-token',
      prompt: 'initial prompt',
    })
    const edits = [
      { model: 'checkpoint.safetensors' },
      { quality: 'detailed' as const },
      { width: 1024 },
      { height: 1024 },
      { prompt: 'a new prompt' },
      { negative: 'blurry' },
    ]

    for (const patch of edits) {
      const result = reduceEasyPanelControllerInteraction(settings, { type: 'settings-changed', patch })
      settings = result.settings
      if (result.shouldSubmit) generateApi()
    }
    expect(generateApi).toHaveBeenCalledTimes(0)

    const explicitGenerate = reduceEasyPanelControllerInteraction(settings, { type: 'generate-requested' })
    if (explicitGenerate.shouldSubmit) generateApi()
    expect(generateApi).toHaveBeenCalledTimes(1)
  })
})
