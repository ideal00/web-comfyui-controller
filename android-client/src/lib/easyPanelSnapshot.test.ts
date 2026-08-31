import { describe, expect, it } from 'vitest'
import { buildEasyPanelControllerRequest, normalizeEasyPanelControllerSettings } from './easyPanelController'
import { explainSnapshot, restoreSnapshotToSettings, shouldFocusPromptAfterSnapshotRestore, snapshotPromptSourceLabels } from './easyPanelSnapshot'
import type { EasyPanelSnapshotRecord } from '../services/easyPanelSnapshots'

const snapshot: EasyPanelSnapshotRecord = {
  id: 'a'.repeat(32),
  createdAt: 100,
  schemaVersion: 2,
  payload: {
    model: 'checkpoint.safetensors',
    quality: 'detailed',
    width: 1024,
    height: 1024,
    seed: '42',
    loras: [{ name: 'characters/luna.safetensors', weight: 0.8 }],
    promptSections: { scene: 'a quiet cafe' },
    prompt: '',
    negative: 'blurry',
    steps: 28,
    cfg: 6.5,
    sampler: 'euler_ancestral',
    scheduler: 'normal',
  },
  source: {
    checkpoint: 'checkpoint.safetensors',
    characters: [{ id: 'luna', appearance: 'blue eyes', outfit: 'blue dress', loras: [{ name: 'characters/luna.safetensors', weight: 0.8 }] }],
    scene: 'a quiet cafe',
    styleColoring: 'soft anime illustration',
    generation: { quality: 'detailed', width: 1024, height: 1024, seed: '42' },
    loras: [{ name: 'characters/luna.safetensors', role: 'character', weight: 0.8, trigger: 'luna' }],
    enhancements: { hires: {}, repair: {}, guidance: {} },
  },
  compiled: {
    positive: 'luna, blue eyes, blue dress, a quiet cafe',
    negative: 'blurry',
    sources: [{ key: 'loraTriggers', label: 'LoRA 自动触发词', kind: 'positive', enabled: true, terms: ['luna'] }],
    sections: { scene: 'a quiet cafe', pose: 'standing' },
    profile: { family: 'illustrious', quality: ['masterpiece', 'best quality'] },
    automation: { quality: true, loraTriggers: true, dynamicNegative: true },
    deduplication: { positiveCandidates: 5, positiveFinal: 4, positiveRemoved: 1, positiveRemovedTerms: ['luna'] },
    diagnostics: [{ code: 'positive-negative', severity: 'warning', message: 'standing conflicts' }],
    warnings: ['standing conflicts'],
    errors: [],
    overridden: false,
    sampling: {
      settings: { steps: 28, cfg: 6.5, sampler: 'euler_ancestral', scheduler: 'normal' },
      reasons: [{ code: 'quality-profile', message: '来自质量策略' }],
    },
  },
  outputs: [],
}

describe('mobile snapshot restore', () => {
  it('restores editable fields while leaving the connection credentials untouched', () => {
    const current = normalizeEasyPanelControllerSettings({
      baseUrl: 'http://192.168.1.10:8190',
      token: 'local-token',
      prompt: 'old prompt',
      seed: '9',
    })
    const result = restoreSnapshotToSettings(current, snapshot, 'full')
    expect(result.settings).toMatchObject({
      baseUrl: current.baseUrl,
      token: current.token,
      model: 'checkpoint.safetensors',
      quality: 'detailed',
      width: 1024,
      height: 1024,
      prompt: 'luna, blue eyes, blue dress, a quiet cafe',
      negative: 'blurry',
      seed: '42',
    })
    expect(result.advancedFieldCount).toBeGreaterThan(0)
  })

  it('changes only the restored seed for the variation action', () => {
    const current = normalizeEasyPanelControllerSettings({ baseUrl: 'http://192.168.1.10:8190', token: 'local-token' })
    const result = restoreSnapshotToSettings(current, snapshot, 'seed-only')
    expect(result.settings.seed).toBe('43')
    expect(result.settings.prompt).toBe('luna, blue eyes, blue dress, a quiet cafe')
  })

  it('keeps the attachment semantics explicit for continue editing', () => {
    const current = normalizeEasyPanelControllerSettings({
      baseUrl: 'http://192.168.1.10:8190', token: 'local-token', prompt: 'old prompt', seed: '9',
    })
    const result = restoreSnapshotToSettings(current, snapshot, 'continue-editing')
    expect(result.mode).toBe('continue-editing')
    expect(result.settings.prompt).toBe('luna, blue eyes, blue dress, a quiet cafe')
    expect(result.advancedFieldCount).toBeGreaterThan(0)
  })

  it('distinguishes continue editing with a prompt-editor focus interaction', () => {
    expect(shouldFocusPromptAfterSnapshotRestore('full')).toBe(false)
    expect(shouldFocusPromptAfterSnapshotRestore('seed-only')).toBe(false)
    expect(shouldFocusPromptAfterSnapshotRestore('continue-editing')).toBe(true)
  })

  it('keeps the server snapshot source in the next structured request', () => {
    const settings = normalizeEasyPanelControllerSettings({
      prompt: 'edited prompt',
      negative: 'edited negative',
      seed: '44',
      model: 'checkpoint.safetensors',
    })
    const request = buildEasyPanelControllerRequest(settings, 'request-1', snapshot)
    expect(request.visual.characters[0]).toMatchObject({ id: 'luna', appearance: 'blue eyes', outfit: 'blue dress', loras: [{ name: 'characters/luna.safetensors', weight: 0.8 }] })
    expect(request.visual.scene).toBe('edited prompt')
    expect(request.generation).toMatchObject({
      model: 'checkpoint.safetensors',
      seed: '44',
      steps: 28,
      cfg: 6.5,
      sampler: 'euler_ancestral',
      scheduler: 'normal',
      loras: [{ name: 'characters/luna.safetensors', weight: 0.8 }],
    })
  })

  it('does not duplicate the compiled prompt when generating immediately after restore', () => {
    const current = normalizeEasyPanelControllerSettings({
      prompt: snapshot.compiled.positive as string,
      model: 'checkpoint.safetensors',
      seed: '42',
    })
    const request = buildEasyPanelControllerRequest(current, 'request-restore', snapshot)
    expect(request.visual.scene).toBe('a quiet cafe')
    expect(request.visual.location).toBeUndefined()
  })

  it('exposes read-only prompt provenance labels', () => {
    expect(snapshotPromptSourceLabels(snapshot)).toEqual(['LoRA 自动触发词'])
  })

  it('exposes the actual layered compiler explanation fields', () => {
    const explanation = explainSnapshot(snapshot)
    expect(explanation.sourceSections).toMatchObject({ scene: 'a quiet cafe', pose: 'standing' })
    expect(explanation.promptSources[0]).toMatchObject({ key: 'loraTriggers', label: 'LoRA 自动触发词', terms: ['luna'] })
    expect(explanation.loraTriggerSources[0]).toMatchObject({ name: 'characters/luna.safetensors', role: 'character', trigger: 'luna' })
    expect(explanation.modelStrategy).toMatchObject({ family: 'illustrious' })
    expect(explanation.automation).toMatchObject({ quality: true, loraTriggers: true })
    expect(explanation.deduplication).toMatchObject({ positiveRemoved: 1 })
    expect(explanation.diagnostics[0]).toMatchObject({ code: 'positive-negative', severity: 'warning' })
    expect(explanation.finalPositive).toContain('blue dress')
    expect(explanation.finalNegative).toBe('blurry')
    expect(explanation.sampling.settings).toMatchObject({ sampler: 'euler_ancestral', cfg: 6.5 })
    expect(explanation.sampling.reasons).toEqual([{ code: 'quality-profile', message: '来自质量策略' }])
  })

  it('omits all snapshot advanced parameters for an ordinary generation request', () => {
    const settings = normalizeEasyPanelControllerSettings({
      prompt: 'ordinary prompt', negative: 'ordinary negative', seed: '45', model: 'checkpoint.safetensors',
    })
    const request = buildEasyPanelControllerRequest(settings, 'request-ordinary')
    expect(request.generation).not.toHaveProperty('loras')
    expect(request.generation).not.toHaveProperty('repair')
    expect(request.generation).not.toHaveProperty('img2img')
    expect(request.generation).not.toHaveProperty('pose')
    expect(request.generation).not.toHaveProperty('guidance')
    expect(request.generation).toMatchObject({ seed: '45', model: 'checkpoint.safetensors' })
  })
})
