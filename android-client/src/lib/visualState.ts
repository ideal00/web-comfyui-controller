import { readStoredState, writeStoredState } from '../platform/stateStore'

const VISUAL_STATE_KEY = 'rpgbox-easy-panel-visual-v1'

/** Address is intentionally entered by the user; never ship a workstation IP. */
export const EASY_PANEL_SUGGESTED_BASE_URL = ''

export type VisualAutoMode = 'manual' | 'scene-change' | 'every-turn'

export interface EasyPanelVisualSettings {
  enabled: boolean
  baseUrl: string
  token: string
  autoMode: VisualAutoMode
  model: string
  width: number
  height: number
  regional: boolean
  safetyLevel: string
  negative: string
  pollIntervalMs: number
  dimPercent: number
}

export interface VisualCacheRecord {
  gameId: string
  messageId: string
  requestId: string
  uri: string
  updatedAt: number
}

export interface PersistedVisualState {
  settings: EasyPanelVisualSettings
  latestCgByGame: Record<string, VisualCacheRecord>
  lastSceneSignatureByGame: Record<string, string>
}

export const DEFAULT_VISUAL_SETTINGS: EasyPanelVisualSettings = {
  enabled: false,
  baseUrl: '',
  token: '',
  autoMode: 'scene-change',
  model: '',
  width: 832,
  height: 1216,
  regional: false,
  safetyLevel: 'safe',
  negative: '',
  pollIntervalMs: 1800,
  dimPercent: 28,
}

export function defaultVisualState(): PersistedVisualState {
  return {
    settings: { ...DEFAULT_VISUAL_SETTINGS },
    latestCgByGame: {},
    lastSceneSignatureByGame: {},
  }
}

export async function loadVisualState(): Promise<PersistedVisualState> {
  const raw = await readStoredState(VISUAL_STATE_KEY)
  if (!raw) return defaultVisualState()
  try {
    const parsed = JSON.parse(raw) as Partial<PersistedVisualState>
    return {
      settings: normalizeVisualSettings(parsed.settings),
      latestCgByGame: parsed.latestCgByGame ?? {},
      lastSceneSignatureByGame: parsed.lastSceneSignatureByGame ?? {},
    }
  } catch {
    return defaultVisualState()
  }
}

export async function saveVisualState(state: PersistedVisualState): Promise<void> {
  await writeStoredState(VISUAL_STATE_KEY, JSON.stringify(state))
}

export function normalizeVisualSettings(value: Partial<EasyPanelVisualSettings> | undefined): EasyPanelVisualSettings {
  const defaults = DEFAULT_VISUAL_SETTINGS
  const width = clampInt(value?.width, 512, 2048, defaults.width)
  const height = clampInt(value?.height, 512, 2048, defaults.height)
  const pollIntervalMs = clampInt(value?.pollIntervalMs, 800, 10000, defaults.pollIntervalMs)
  const dimPercent = clampInt(value?.dimPercent, 0, 80, defaults.dimPercent)
  const autoMode: VisualAutoMode = value?.autoMode === 'manual' || value?.autoMode === 'every-turn' || value?.autoMode === 'scene-change'
    ? value.autoMode
    : defaults.autoMode
  return {
    ...defaults,
    ...value,
    width,
    height,
    pollIntervalMs,
    dimPercent,
    autoMode,
    baseUrl: value?.baseUrl?.trim() ?? '',
    token: value?.token?.trim() ?? '',
    model: value?.model?.trim() ?? '',
    safetyLevel: value?.safetyLevel?.trim() || defaults.safetyLevel,
    negative: value?.negative ?? '',
  }
}

function clampInt(value: number | undefined, min: number, max: number, fallback: number): number {
  if (!Number.isFinite(value)) return fallback
  return Math.min(max, Math.max(min, Math.round(value as number)))
}
