import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_PROVIDER } from './config'
import { createBlankGame } from './game'
import { loadState } from './storage'

const preferenceMocks = vi.hoisted(() => ({
  get: vi.fn(),
  set: vi.fn(),
}))

vi.mock('@capacitor/preferences', () => ({
  Preferences: preferenceMocks,
}))

describe('RPG storage migration', () => {
  beforeEach(() => {
    preferenceMocks.get.mockReset()
    preferenceMocks.set.mockReset()
  })

  it('keeps an empty library empty instead of restoring the sample RPG', async () => {
    preferenceMocks.get.mockResolvedValue({
      value: JSON.stringify({ games: [], activeGameId: '' }),
    })

    const loaded = await loadState()
    expect(loaded.games).toEqual([])
    expect(loaded.activeGameId).toBe('')
  })

  it('fills defaults for older saved RPGs', async () => {
    const legacy = createBlankGame(1)
    preferenceMocks.get.mockResolvedValue({
      value: JSON.stringify({ games: [legacy], activeGameId: legacy.id }),
    })

    const loaded = await loadState()
    expect(loaded.games?.[0].newStoryChoiceCount).toBe(4)
    expect(loaded.games?.[0].chapterTransitionRules).toBe('')
    expect(loaded.games?.[0].recommendedChapterTurnsEnabled).toBe(false)
    expect(loaded.games?.[0].recommendedChapterTurns).toBe(20)
    expect(loaded.games?.[0].aiSettings.useCompatiblePromptFormat).toBe(true)
    expect(loaded.games?.[0].aiSettings.warnOnProtocolAnomaly).toBe(false)
  })

  it('defaults the format warning to disabled for older saved RPGs', async () => {
    const game = createBlankGame(1)
    delete (game.aiSettings as Partial<typeof game.aiSettings>).warnOnProtocolAnomaly
    preferenceMocks.get.mockResolvedValue({
      value: JSON.stringify({ games: [game], activeGameId: game.id }),
    })

    const loaded = await loadState()
    expect(loaded.games?.[0].aiSettings.warnOnProtocolAnomaly).toBe(false)
  })

  it('defaults the compatible prompt format to disabled for older saved RPGs', async () => {
    const game = createBlankGame(1)
    delete (game.aiSettings as Partial<typeof game.aiSettings>).useCompatiblePromptFormat
    preferenceMocks.get.mockResolvedValue({
      value: JSON.stringify({ games: [game], activeGameId: game.id }),
    })

    const loaded = await loadState()
    expect(loaded.games?.[0].aiSettings.useCompatiblePromptFormat).toBe(true)
  })

  it('normalizes invalid and out-of-range new-story choice counts', async () => {
    const invalid = { ...createBlankGame(1), id: 'invalid', newStoryChoiceCount: Number.NaN }
    const tooLarge = { ...createBlankGame(2), id: 'large', newStoryChoiceCount: 99 }
    preferenceMocks.get.mockResolvedValue({
      value: JSON.stringify({ games: [invalid, tooLarge], activeGameId: invalid.id }),
    })

    const loaded = await loadState()
    expect(loaded.games?.map((game) => game.newStoryChoiceCount)).toEqual([4, 10])
  })

  it('migrates Gemini models/gemini IDs in providers and RPG AI settings', async () => {
    const provider = {
      ...DEFAULT_PROVIDER,
      id: 'gemini-provider',
      baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
      model: 'models/gemini-3.7-flash',
      models: ['models/gemini-3.7-flash', 'models/gemini-2.0-flash'],
    }
    const game = createBlankGame(1, provider)
    game.aiSettings.providerId = provider.id
    game.aiSettings.model = 'models/gemini-3.7-flash'
    game.aiSettings.fallbackModels = ['models/gemini-3.6-flash', 'gemini-3.5-flash-lite']
    game.aiSettings.enableFallbackModels = true
    preferenceMocks.get.mockResolvedValue({
      value: JSON.stringify({
        providers: [provider],
        activeProviderId: provider.id,
        games: [game],
        activeGameId: game.id,
      }),
    })

    const loaded = await loadState()
    expect(loaded.providers?.[0].model).toBe('gemini-3.7-flash')
    expect(loaded.providers?.[0].models).toEqual(['gemini-3.7-flash', 'gemini-2.0-flash'])
    expect(loaded.games?.[0].aiSettings.model).toBe('gemini-3.7-flash')
    expect(loaded.games?.[0].aiSettings.fallbackModels).toEqual(['gemini-3.6-flash', 'gemini-3.5-flash-lite'])
    expect(loaded.games?.[0].aiSettings.enableFallbackModels).toBe(true)
  })
})
