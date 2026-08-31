import { describe, expect, it } from 'vitest'
import { restoreLibraryGenerationToSettings } from './easyPanelLibrary'
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
})
