import { describe, expect, it } from 'vitest'
import { buildAdvancedPanelUrl } from './easyPanelAdvanced'

describe('Easy Panel advanced viewer URL', () => {
  it.each([
    ['192.168.1.10:8190', 'http://192.168.1.10:8190/?mobile=1'],
    ['http://100.86.12.4:8190/', 'http://100.86.12.4:8190/?mobile=1'],
    ['https://desktop.tailnet-name.ts.net:8190', 'https://desktop.tailnet-name.ts.net:8190/?mobile=1'],
  ])('normalizes %s and adds the mobile host flag', (value, expected) => {
    expect(buildAdvancedPanelUrl(value)).toBe(expected)
  })

  it('does not put a token or an arbitrary path/query into the viewer URL', () => {
    const url = buildAdvancedPanelUrl('http://desktop.tailnet-name.ts.net:8190')
    expect(url).toBe('http://desktop.tailnet-name.ts.net:8190/?mobile=1')
    expect(url).not.toContain('token')
    expect(() => buildAdvancedPanelUrl('http://desktop.tailnet-name.ts.net:8190/api')).toThrow()
    expect(() => buildAdvancedPanelUrl('http://desktop.tailnet-name.ts.net:8190/?token=secret')).toThrow()
  })
})
