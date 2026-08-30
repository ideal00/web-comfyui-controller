import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { buildVisualScene, visualSceneSignature } from '../lib/visualScene'
import {
  DEFAULT_VISUAL_SETTINGS,
  loadVisualState,
  normalizeVisualSettings,
  saveVisualState,
  type EasyPanelVisualSettings,
  type PersistedVisualState,
} from '../lib/visualState'
import { deletePortraitFile, portraitSource, savePortraitBase64 } from '../lib/portraits'
import {
  blobToBase64,
  createVisualRequestId,
  downloadVisualImage,
  submitVisualJob,
  waitForVisualJob,
  type EasyPanelVisualConfig,
  type VisualJobStatus,
} from '../services/easyPanelVisual'
import type { ChatMessage, GameSession, StorySegment } from '../types'

export type VisualRuntimeStatus = 'idle' | 'queued' | 'running' | 'saving' | 'completed' | 'error'

interface UseEasyPanelVisualArgs {
  game: GameSession
  assistant?: ChatMessage
  segments: StorySegment[]
  busy: boolean
}

export interface EasyPanelVisualController {
  hydrated: boolean
  settings: EasyPanelVisualSettings
  setSettings: (settings: EasyPanelVisualSettings) => void
  status: VisualRuntimeStatus
  job?: VisualJobStatus
  error: string
  cgUri: string
  cgSource: string
  generateNow: () => Promise<void>
  clearCg: () => Promise<void>
}

function extensionForBlob(blob: Blob): string {
  if (blob.type.includes('jpeg')) return 'jpg'
  if (blob.type.includes('webp')) return 'webp'
  return 'png'
}

function messageHasStory(game: GameSession): boolean {
  return game.messages.some((message) => message.role === 'user')
}

export function useEasyPanelVisual({ game, assistant, segments, busy }: UseEasyPanelVisualArgs): EasyPanelVisualController {
  const [hydrated, setHydrated] = useState(false)
  const [settings, setSettingsState] = useState<EasyPanelVisualSettings>({ ...DEFAULT_VISUAL_SETTINGS })
  const [status, setStatus] = useState<VisualRuntimeStatus>('idle')
  const [job, setJob] = useState<VisualJobStatus>()
  const [error, setError] = useState('')
  const [cgUri, setCgUri] = useState('')
  const persistedRef = useRef<PersistedVisualState | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const generatingRef = useRef<string>('')

  const config = useMemo<EasyPanelVisualConfig>(() => ({
    baseUrl: settings.baseUrl,
    token: settings.token,
    pollIntervalMs: settings.pollIntervalMs,
  }), [settings.baseUrl, settings.pollIntervalMs, settings.token])

  const persist = useCallback((next: PersistedVisualState) => {
    persistedRef.current = next
    void saveVisualState(next)
  }, [])

  useEffect(() => {
    let cancelled = false
    void loadVisualState().then((saved) => {
      if (cancelled) return
      persistedRef.current = saved
      setSettingsState(saved.settings)
      setCgUri(saved.latestCgByGame[game.id]?.uri ?? '')
      setHydrated(true)
    })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!hydrated) return
    setCgUri(persistedRef.current?.latestCgByGame[game.id]?.uri ?? '')
    setStatus('idle')
    setJob(undefined)
    setError('')
  }, [game.id, hydrated])

  useEffect(() => () => abortRef.current?.abort(), [])

  const setSettings = useCallback((nextSettings: EasyPanelVisualSettings) => {
    const normalized = normalizeVisualSettings(nextSettings)
    setSettingsState(normalized)
    const current = persistedRef.current
    if (!current) return
    persist({ ...current, settings: normalized })
  }, [persist])

  const runGeneration = useCallback(async (manual: boolean) => {
    if (!hydrated || busy || !assistant || !messageHasStory(game)) return
    if (!settings.enabled && !manual) return
    if (!settings.baseUrl.trim()) {
      setError('请先在视觉设置中填写 Easy Panel 地址')
      setStatus('error')
      return
    }

    const sceneId = assistant.id || `scene-${Date.now()}`
    const requestId = createVisualRequestId(game.id, sceneId, manual ? `manual_${Date.now()}` : '')
    if (generatingRef.current === requestId) return
    generatingRef.current = requestId
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setError('')
    setStatus('queued')
    setJob(undefined)

    try {
      const visual = buildVisualScene(game, segments)
      const initial = await submitVisualJob(config, {
        client: { gameId: game.id, sceneId, requestId },
        visual,
        generation: {
          ...(settings.model.trim() ? { model: settings.model.trim() } : {}),
          width: settings.width,
          height: settings.height,
          seed: -1,
          regional: settings.regional && visual.characters.length > 1,
          safetyLevel: settings.safetyLevel,
          ...(settings.negative.trim() ? { negative: settings.negative.trim() } : {}),
        },
      })
      setJob(initial)
      setStatus(initial.status === 'running' ? 'running' : initial.status === 'completed' ? 'saving' : 'queued')
      const completed = initial.status === 'completed'
        ? initial
        : await waitForVisualJob(config, initial, controller.signal, (next) => {
          setJob(next)
          setStatus(next.status === 'running' ? 'running' : next.status === 'queued' ? 'queued' : next.status === 'error' ? 'error' : 'saving')
        })
      if (completed.status === 'error') throw new Error(typeof completed.error === 'string' ? completed.error : 'Easy Panel 生图失败')
      const image = completed.images[0]
      if (!image) throw new Error('Easy Panel 已完成任务，但没有返回图片')

      setStatus('saving')
      const blob = await downloadVisualImage(config, image)
      const uri = await savePortraitBase64(game.id, '_generated_cg', await blobToBase64(blob), extensionForBlob(blob))
      const current = persistedRef.current
      const oldUri = current?.latestCgByGame[game.id]?.uri
      if (oldUri && oldUri !== uri) void deletePortraitFile(oldUri)
      if (current) {
        persist({
          ...current,
          latestCgByGame: {
            ...current.latestCgByGame,
            [game.id]: { gameId: game.id, messageId: assistant.id, requestId, uri, updatedAt: Date.now() },
          },
          lastSceneSignatureByGame: manual
            ? current.lastSceneSignatureByGame
            : { ...current.lastSceneSignatureByGame, [game.id]: visualSceneSignature(game, segments) },
        })
      }
      setCgUri(uri)
      setJob(completed)
      setStatus('completed')
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return
      setError(caught instanceof Error ? caught.message : '剧情 CG 生成失败')
      setStatus('error')
    } finally {
      if (generatingRef.current === requestId) generatingRef.current = ''
    }
  }, [assistant, busy, config, game, hydrated, persist, segments, settings.enabled, settings.height, settings.model, settings.negative, settings.regional, settings.safetyLevel, settings.width])

  useEffect(() => {
    if (!hydrated || busy || !assistant || assistant.id === 'opening' || !settings.enabled || settings.autoMode === 'manual') return
    if (!messageHasStory(game)) return
    if (settings.autoMode === 'scene-change') {
      const signature = visualSceneSignature(game, segments)
      if (persistedRef.current?.lastSceneSignatureByGame[game.id] === signature) return
    }
    void runGeneration(false)
  }, [assistant?.id, busy, game.id, hydrated, runGeneration, segments, settings.autoMode, settings.enabled])

  const generateNow = useCallback(() => runGeneration(true), [runGeneration])

  const clearCg = useCallback(async () => {
    const current = persistedRef.current
    const record = current?.latestCgByGame[game.id]
    if (record?.uri) await deletePortraitFile(record.uri)
    if (current) {
      const nextCache = { ...current.latestCgByGame }
      delete nextCache[game.id]
      persist({ ...current, latestCgByGame: nextCache })
    }
    setCgUri('')
    setStatus('idle')
    setJob(undefined)
    setError('')
  }, [game.id, persist])

  return {
    hydrated,
    settings,
    setSettings,
    status,
    job,
    error,
    cgUri,
    cgSource: cgUri ? portraitSource(cgUri) : '',
    generateNow,
    clearCg,
  }
}
