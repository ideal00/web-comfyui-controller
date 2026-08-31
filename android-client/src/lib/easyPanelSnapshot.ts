import {
  normalizeEasyPanelControllerSettings,
  type EasyPanelControllerSettings,
} from './easyPanelController'
import type { EasyPanelSnapshotRecord } from '../services/easyPanelSnapshots'

export type EasyPanelSnapshotRestoreMode = 'full' | 'seed-only' | 'continue-editing'

/** Continue editing is an intentional prompt-editor interaction, not a second full-restore label. */
export function shouldFocusPromptAfterSnapshotRestore(mode: EasyPanelSnapshotRestoreMode): boolean {
  return mode === 'continue-editing'
}

export interface EasyPanelSnapshotRestoreResult {
  settings: EasyPanelControllerSettings
  mode: EasyPanelSnapshotRestoreMode
  advancedFieldCount: number
}

export interface EasyPanelSnapshotPromptSource {
  key: string
  label: string
  kind: string
  enabled: boolean
  terms: string[]
}

export interface EasyPanelSnapshotLoraTriggerSource {
  name: string
  role: string
  trigger: string
  weight?: number | string
}

export interface EasyPanelSnapshotExplanation {
  sourceSections: Record<string, string>
  userInputSources: EasyPanelSnapshotPromptSource[]
  automaticSources: EasyPanelSnapshotPromptSource[]
  promptSources: EasyPanelSnapshotPromptSource[]
  loraTriggerSources: EasyPanelSnapshotLoraTriggerSource[]
  triggerTerms: string[]
  modelStrategy: Record<string, unknown>
  automation: Record<string, boolean>
  deduplication: Record<string, unknown>
  diagnostics: Array<Record<string, unknown>>
  warnings: string[]
  errors: string[]
  overridden: boolean
  finalPositive: string
  finalNegative: string
  sampling: Record<string, unknown>
}

export function restoreSnapshotToSettings(
  current: EasyPanelControllerSettings,
  snapshot: EasyPanelSnapshotRecord,
  mode: EasyPanelSnapshotRestoreMode = 'full',
): EasyPanelSnapshotRestoreResult {
  const payload = object(snapshot.payload)
  const source = object(snapshot.source)
  const compiled = object(snapshot.compiled)
  const generation = object(source.generation)
  const promptOverride = object(payload.promptOverride)
  const sections = object(payload.promptSections)
  const positive = promptOverride.enabled === true && text(promptOverride.positive)
    ? text(promptOverride.positive)
    : text(compiled.positive) || text(payload.prompt) || joinSections(sections)
  const negative = promptOverride.enabled === true && text(promptOverride.negative)
    ? text(promptOverride.negative)
    : text(compiled.negative) || text(payload.negative) || text(source.negative)
  const restoredSeed = scalarText(generation.seed ?? payload.seed)
  const nextSeed = mode === 'seed-only' ? createVariationSeed(restoredSeed) : restoredSeed
  const model = text(source.checkpoint) || text(payload.model)
  const quality = text(generation.quality ?? payload.quality)
  const advancedFieldCount = countAdvancedFields(payload, source)
  const settings = normalizeEasyPanelControllerSettings({
    ...current,
    ...(model ? { model } : {}),
    ...(quality === 'fast' || quality === 'balanced' || quality === 'detailed' ? { quality } : {}),
    width: numberValue(generation.width ?? payload.width, current.width),
    height: numberValue(generation.height ?? payload.height, current.height),
    prompt: positive,
    negative,
    seed: nextSeed,
  })
  return { settings, mode, advancedFieldCount }
}

export function snapshotPromptSourceLabels(snapshot: EasyPanelSnapshotRecord): string[] {
  return explainSnapshot(snapshot).promptSources
    .filter((item) => item.terms.length > 0)
    .map((item) => item.label)
    .filter(Boolean)
}

/**
 * Convert the server's compiler trace into a read-only explanation model.
 * This function only reads structured snapshot fields; it never alters the
 * prompt that will be submitted.
 */
export function explainSnapshot(snapshot: EasyPanelSnapshotRecord): EasyPanelSnapshotExplanation {
  const source = object(snapshot.source)
  const compiled = object(snapshot.compiled)
  const promptSources = arrayOfObjects(compiled.sources).map((item) => ({
    key: text(item.key),
    label: text(item.label),
    kind: text(item.kind),
    enabled: item.enabled !== false,
    terms: stringArray(item.terms),
  })).filter((item) => item.key || item.label)
  const loraTriggerSources = arrayOfObjects(source.loras).flatMap((item) => {
    const name = text(item.name)
    const trigger = text(item.trigger)
    if (!name || !trigger) return []
    const weight = item.weight
    return [{
      name,
      role: text(item.role),
      trigger,
      ...(typeof weight === 'number' || typeof weight === 'string' ? { weight } : {}),
    }]
  })
  const sections = object(compiled.sections)
  const sourceSections = Object.fromEntries(
    Object.entries(sections).flatMap(([key, value]) => {
      const normalized = text(value)
      return normalized ? [[key, normalized]] : []
    }),
  )
  const userInputSources = promptSources.filter((item) =>
    item.key === 'userPositive' || item.key === 'naturalLanguage' || item.key === 'manualOverride')
  const automaticSources = promptSources.filter((item) => !userInputSources.includes(item))
  const profile = object(compiled.profile)
  const sourceStrategy = object(source.modelStrategy)
  return {
    sourceSections,
    userInputSources,
    automaticSources,
    promptSources,
    loraTriggerSources,
    triggerTerms: stringArray(compiled.triggers),
    modelStrategy: Object.keys(profile).length ? profile : sourceStrategy,
    automation: booleanRecord(compiled.automation),
    deduplication: object(compiled.deduplication),
    diagnostics: arrayOfObjects(compiled.diagnostics),
    warnings: stringArray(compiled.warnings),
    errors: stringArray(compiled.errors),
    overridden: compiled.overridden === true,
    finalPositive: text(compiled.positive),
    finalNegative: text(compiled.negative),
    sampling: object(compiled.sampling),
  }
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

function countAdvancedFields(payload: Record<string, unknown>, source: Record<string, unknown>): number {
  const enhancements = object(source.enhancements)
  return [
    payload.steps, payload.cfg, payload.sampler, payload.scheduler, payload.vae,
    payload.regions, enhancements.hires, enhancements.repair, enhancements.img2img,
    enhancements.pose, enhancements.depth, enhancements.colorCorrection,
    enhancements.outputEnhancement, enhancements.modelEnhancement,
    enhancements.transparentBackground, enhancements.guidance,
  ].filter((value) => value !== undefined && value !== null && value !== '').length
}

function createVariationSeed(previous: string): string {
  const parsed = Number(previous)
  if (Number.isSafeInteger(parsed) && parsed >= 0) {
    return String((parsed + 1) % 9007199254740991)
  }
  return String(Math.floor(Math.random() * 900000000000000000) + 1)
}

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function scalarText(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function arrayOfObjects(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : []
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())).map((item) => item.trim()) : []
}

function booleanRecord(value: unknown): Record<string, boolean> {
  const record = object(value)
  return Object.fromEntries(Object.entries(record).map(([key, item]) => [key, Boolean(item)]))
}
