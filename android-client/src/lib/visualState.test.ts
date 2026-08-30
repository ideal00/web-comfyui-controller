import { describe, expect, it } from 'vitest'
import { DEFAULT_VISUAL_SETTINGS, EASY_PANEL_SUGGESTED_BASE_URL, normalizeVisualSettings } from './visualState'

describe('Easy Panel visual settings', () => {
  it('keeps the workstation suggestion separate from the persisted default', () => {
    expect(DEFAULT_VISUAL_SETTINGS.baseUrl).toBe('')
    expect(DEFAULT_VISUAL_SETTINGS.token).toBe('')
    expect(EASY_PANEL_SUGGESTED_BASE_URL).toBe('')
  })

  it('trims the address and token before saving or testing', () => {
    expect(normalizeVisualSettings({
      baseUrl: '  http://192.168.1.10:8190/  ',
      token: '  token-content\n',
    })).toMatchObject({
      baseUrl: 'http://192.168.1.10:8190/',
      token: 'token-content',
    })
  })
})
