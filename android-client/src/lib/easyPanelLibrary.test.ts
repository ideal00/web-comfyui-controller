import { describe, expect, it } from 'vitest'
import { pendingDerivationContextForLibraryGeneration, restoreLibraryGenerationToSettings } from './easyPanelLibrary'
import type { EasyPanelControllerSettings } from './easyPanelController'
import type { EasyPanelGenerationDetail } from '../services/easyPanelLibrary'

const current: EasyPanelControllerSettings = {
  baseUrl: 'http://desktop:8190',
  token: 'secret',
  model: 'old.safetensors',
  quality: 'fast',
  width: 832,
  height: 1216,
  prompt: 'old prompt',
  negative: 'old negative',
  seed: '10',
  pollIntervalMs: 1800,
}

function detail(overrides: Partial<EasyPanelGenerationDetail> = {}): EasyPanelGenerationDetail {
  return {
    generation_id: 'a'.repeat(32),
    operation: 'txt2img',
    status: 'completed',
    created_at: 1,
    updated_at: 1,
    schema_version: 1,
    model: 'new.safetensors',
    lora_count: 0,
    artifact_count: 0,
    parent_count: 0,
    child_count: 0,
    input: {},
    compiled: {},
    inference: {},
    workflow: {},
    snapshot: {},
    error: {},
    loras: [],
    artifacts: [],
    replay: { can_submit: false, action: 'restore_to_form', payload: {}, operation: 'txt2img', note: '' },
    variation: { can_submit: false, action: 'restore_to_form', payload: {}, operation: 'txt2img', note: '' },
    ...overrides,
  }
}

describe('creative Library restore', () => {
  it('restores payload-only details into the current form without a submit action', () => {
    const result = restoreLibraryGenerationToSettings(current, detail({
      input: {
        model: 'library.safetensors',
        quality: 'detailed',
        width: 1024,
        height: 1024,
        promptSections: { subject: '1girl', scene: 'quiet cafe' },
        negative: 'bad anatomy',
        seed: 123,
      },
    }))
    expect(result.settings).toMatchObject({
      model: 'library.safetensors',
      quality: 'detailed',
      width: 1024,
      height: 1024,
      prompt: '1girl, quiet cafe',
      negative: 'bad anatomy',
      seed: '123',
    })
    expect(result.snapshot).toBeUndefined()
  })

  it('changes only the restored seed in the variation path', () => {
    const result = restoreLibraryGenerationToSettings(current, detail({
      seed: '41',
      input: { prompt: 'same prompt', width: 900, height: 1000 },
    }), 'seed-variant')
    expect(result.settings.prompt).toBe('same prompt')
    expect(result.settings.width).toBe(900)
    expect(result.settings.height).toBe(1000)
    expect(result.settings.seed).toBe('42')
  })

  it('accepts a full snapshot and leaves submit responsibility outside the helper', () => {
    const snapshot = {
      id: 'b'.repeat(32),
      createdAt: 1,
      schemaVersion: 2,
      payload: { prompt: 'snapshot prompt', model: 'snapshot.safetensors', seed: '77' },
      source: { checkpoint: 'snapshot.safetensors', generation: { seed: '77', width: 832, height: 1216 } },
      compiled: { positive: 'snapshot prompt', negative: '' },
      outputs: [],
    }
    const result = restoreLibraryGenerationToSettings(current, detail({ snapshot: snapshot as never }))
    expect(result.snapshot?.id).toBe(snapshot.id)
    expect(result.settings.prompt).toBe('snapshot prompt')
    expect(result.settings.seed).toBe('77')
  })

  it('creates a safe one-shot lineage context without an implicit artifact', () => {
    const result = pendingDerivationContextForLibraryGeneration(detail({
      operation: 'txt2img',
      artifacts: [{
        artifact_id: 'c'.repeat(32),
        generation_id: 'a'.repeat(32),
        filename: 'output.png',
        subfolder: '2026/08',
        type: 'output',
        kind: 'output',
        exists: true,
        metadata: {},
        created_at: 1,
      }],
    }), 'continue-edit')
    expect(result).toEqual({
      parentGenerationId: 'a'.repeat(32),
      operation: 'txt2img',
    })
    expect(pendingDerivationContextForLibraryGeneration(detail({ operation: 'img2img' }), 'continue-edit'))
      .toEqual({ parentGenerationId: 'a'.repeat(32), operation: 'img2img' })
    expect(pendingDerivationContextForLibraryGeneration(detail({ operation: 'txt2img' }), 'seed-variant').operation)
      .toBe('seed_variant')
  })

  it('does not attach a missing or unsafe artifact to the lineage context', () => {
    const result = pendingDerivationContextForLibraryGeneration(detail({
      artifacts: [{
        artifact_id: 'd'.repeat(32),
        generation_id: 'a'.repeat(32),
        filename: 'missing.png',
        subfolder: '',
        type: 'output',
        kind: 'output',
        exists: false,
        metadata: {},
        created_at: 1,
      }],
    }))
    expect(result).toEqual({ parentGenerationId: 'a'.repeat(32), operation: 'txt2img' })
  })
})
