import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadBlob } from './browserDownload'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('downloadBlob', () => {
  it('keeps the browser fallback as a normal blob download', async () => {
    const click = vi.fn()
    const remove = vi.fn()
    const append = vi.fn()
    const anchor = { href: '', download: '', style: { display: '' }, click, remove }
    vi.stubGlobal('document', {
      createElement: vi.fn(() => anchor),
      body: { append },
    })
    vi.stubGlobal('window', { setTimeout: (callback: () => void) => { callback(); return 1 } })
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:test'),
      revokeObjectURL: vi.fn(),
    })

    await expect(downloadBlob(new Blob(['image'], { type: 'image/png' }), 'output.png')).resolves.toEqual({
      saved: true,
      filename: 'output.png',
      location: '浏览器下载目录',
    })
    expect(append).toHaveBeenCalledWith(anchor)
    expect(anchor.download).toBe('output.png')
    expect(click).toHaveBeenCalledTimes(1)
    expect(remove).toHaveBeenCalledTimes(1)
  })
})
