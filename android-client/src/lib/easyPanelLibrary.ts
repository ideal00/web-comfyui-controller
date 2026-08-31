import {
  normalizeEasyPanelControllerSettings,
  type EasyPanelControllerSettings,
} from './easyPanelController'
import {
  restoreSnapshotToSettings,
} from './easyPanelSnapshot'
import type { EasyPanelSnapshotRecord } from '../services/easyPanelSnapshots'
import type { EasyPanelGenerationDetail } from '../services/easyPanelLibrary'

export type EasyPanelLibraryRestoreMode = 'reproduce' | 'seed-variant'

export interface EasyPanelLibraryRestoreResult {
  settings: EasyPanelControllerSettings
  snapshot?: EasyPanelSnapshotRecord
  operation: string
  advancedFieldCount: number
}

/**
 * Turn a read-only Library detail into the existing form state.  This helper
 * deliberately has no network or submit side effects; Generate remains a
 * separate explicit controller action.
 */
export function restoreLibraryGenerationToSettings(
  current: EasyPanelControllerSettings,
  generation: EasyPanelGenerationDetail,
  mode: EasyPanelLibraryRestoreMode = 'reproduce',
): EasyPanelLibraryRestoreResult {
  const snapshot = asSnapshotRecord(generation.snapshot)
  if (snapshot) {
    const restored = restoreSnapshotToSettings(
      current,
      snapshot,
      mode === 'seed-variant' ? 'seed-only' : 'full',
    )
    return {
      settings: restored.settings,
      snapshot,
      operation: generation.operation,
      advancedFieldCount: restored.advancedFieldCount,
    }
  }

  const replayPayload = object(generation.replay?.payload)
  const payload = Object.keys(replayPayload).length > 0 ? replayPayload : object(generation.input)
  const seed = text(payload.seed) || text(generation.seed)
  const nextSeed = mode === 'seed-variant' ? createVariationSeed(seed) : seed
  const promptSections = object(payload.promptSections)
  const prompt = text(payload.prompt)
    || text(payload.positive)
    || joinSections(promptSections)
    || `恢复作品 ${generation.generation_id.slice(0, 8)}`
  const quality = text(payload.quality) || text(generation.quality)
  const settings = normalizeEasyPanelControllerSettings({
    ...current,
    ...(text(payload.model) || generation.model ? { model: text(payload.model) || generation.model } : {}),
    ...(quality === 'fast' || quality === 'balanced' || quality === 'detailed' ? { quality } : {}),
    width: numberValue(payload.width, generation.width ?? current.width),
    height: numberValue(payload.height, generation.height ?? current.height),
    prompt,
    negative: text(payload.negative) || current.negative,
    seed: nextSeed,
  })
  return {
    settings,
    operation: generation.operation,
    advancedFieldCount: 0,
  }
}

function asSnapshotRecord(value: unknown): EasyPanelSnapshotRecord | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const record = value as Record<string, unknown>
  if (!text(record.id) || !isObject(record.payload) || !isObject(record.source) || !isObject(record.compiled)) return undefined
  return record as unknown as EasyPanelSnapshotRecord
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value).trim() : ''
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function joinSections(sections: Record<string, unknown>): string {
  return [
    sections.subject,
    sections.appearance,
    sections.clothing,
    sections.pose,
    sections.composition,
    sections.scene,
    sections.lighting,
    sections.style,
    sections.naturalLanguage,
    sections.manual,
  ].map(text).filter(Boolean).join(', ')
}

function createVariationSeed(previous: string): string {
  const parsed = Number(previous)
  if (Number.isSafeInteger(parsed) && parsed >= 0) return String((parsed + 1) % 9007199254740991)
  return String(Math.floor(Math.random() * 900000000000000000) + 1)
}
