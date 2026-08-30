import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createVisualRequestId,
  EasyPanelHttpError,
  getEasyPanelCapabilities,
  normalizeEasyPanelBaseUrl,
  pingEasyPanel,
  recoverVisualJob,
} from './easyPanelVisual'

afterEach(() => vi.restoreAllMocks())

describe('Easy Panel connection checks', () => {
  it('uses the trimmed token for ping and authenticated capabilities checks', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, api_version: 2, token_required: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ api_version: 2, endpoints: ['/api/rpg/generate'] }), { status: 200 }))
    const config = { baseUrl: ' http://192.168.1.10:8190/ ', token: '  token-content\n ' }

    await expect(pingEasyPanel(config)).resolves.toMatchObject({ ok: true, api_version: 2 })
    await expect(getEasyPanelCapabilities(config)).resolves.toMatchObject({ api_version: 2 })

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://192.168.1.10:8190/api/rpg/ping',
      'http://192.168.1.10:8190/api/rpg/capabilities',
    ])
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ headers: { 'X-RPG-Token': 'token-content' } })
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ headers: { 'X-RPG-Token': 'token-content' } })
  })

  it('keeps server error details useful without exposing the token', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { message: 'invalid token-content' } }), { status: 401 }))

    const error = await pingEasyPanel({ baseUrl: 'http://192.168.1.10:8190', token: 'token-content' }).catch((value: unknown) => value)
    expect(error).toBeInstanceOf(EasyPanelHttpError)
    expect((error as EasyPanelHttpError).status).toBe(401)
    expect((error as EasyPanelHttpError).message).toContain('invalid [已隐藏]')
    expect((error as EasyPanelHttpError).message).not.toContain('token-content')
  })

  it.each([
    ['http://192.168.1.10:8190/', 'http://192.168.1.10:8190'],
    ['http://100.86.12.4:8190', 'http://100.86.12.4:8190'],
    ['http://desktop.tailnet-name.ts.net:8190/', 'http://desktop.tailnet-name.ts.net:8190'],
    ['desktop.tailnet-name.ts.net:8190', 'http://desktop.tailnet-name.ts.net:8190'],
  ])('normalizes LAN, Tailscale and MagicDNS addresses: %s', (value, expected) => {
    expect(normalizeEasyPanelBaseUrl(value)).toBe(expected)
  })

  it.each([
    '',
    'ftp://192.168.1.10:8190',
    'http://user:password@192.168.1.10:8190',
    'http://192.168.1.10:8190/api',
    'http://192.168.1.10:8190?debug=1',
  ])('rejects unsafe or incomplete Easy Panel addresses: %s', (value) => {
    expect(() => normalizeEasyPanelBaseUrl(value)).toThrow()
  })

  it('keeps request IDs safe for the server recovery route', () => {
    const requestId = createVisualRequestId('easy-panel-mobile', 'a scene with spaces and a very long identifier', 'manual_123456789')
    expect(requestId).toMatch(/^[0-9A-Za-z_-]+$/u)
    expect(requestId.length).toBeLessThanOrEqual(48)
  })

  it('recovers a job by requestId with the RPG token', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ api_version: 2, job_id: 'job-1', status: 'running', images: [] }), { status: 200 }),
    )
    await expect(recoverVisualJob({ baseUrl: 'http://desktop.tailnet-name.ts.net:8190/', token: 'token-content' }, 'easy_panel_mobile_abc'))
      .resolves.toMatchObject({ job_id: 'job-1', status: 'running' })
    expect(fetchMock.mock.calls[0][0]).toBe('http://desktop.tailnet-name.ts.net:8190/api/rpg/jobs/by-request/easy_panel_mobile_abc')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ headers: { 'X-RPG-Token': 'token-content' } })
  })

  it('turns a stalled network request into a clear timeout error', async () => {
    vi.useFakeTimers()
    try {
      vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
      }))
      const pending = pingEasyPanel({ baseUrl: 'http://100.86.12.4:8190', token: 'token-content', requestTimeoutMs: 1000 })
      const assertion = expect(pending).rejects.toThrow('请求超时')
      await vi.advanceTimersByTimeAsync(1000)
      await assertion
    } finally {
      vi.useRealTimers()
    }
  })
})
