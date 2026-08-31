import { describe, expect, it } from 'vitest'
import { appendPromptText, parsePromptTranslation } from './promptTranslation'

describe('mobile prompt translation helpers', () => {
  it('parses the shared POSITIVE / NEGATIVE response format', () => {
    expect(parsePromptTranslation('```text\nPOSITIVE: 1girl, warm window light\nNEGATIVE: blurry, text\n```')).toEqual({
      positive: '1girl, warm window light',
      negative: 'blurry, text',
    })
  })

  it('keeps an unlabelled AI answer usable as a positive prompt', () => {
    expect(parsePromptTranslation('a quiet bookstore at sunset')).toEqual({
      positive: 'a quiet bookstore at sunset',
      negative: '',
    })
  })

  it('does not duplicate an existing prompt fragment', () => {
    expect(appendPromptText('1girl, warm light', 'warm light')).toBe('1girl, warm light')
    expect(appendPromptText('1girl', 'warm light')).toBe('1girl, warm light')
  })
})
