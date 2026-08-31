import { afterEach, describe, expect, it, vi } from 'vitest'
import { getEasyPanelSnapshot, getEasyPanelSnapshots } from './easyPanelSnapshots'

afterEach(() => vi.restoreAllMocks())

describe('Easy Panel shared snapshot API', () => {
  it('reads summaries with the existing RPG token and no token in the URL', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      api_version: 2,
      schema_version: 2,
      snapshots: [{ id: 'a'.repeat(32), schemaVersion: 2, model: 'checkpoint.safetensors', loraCount: 1, outputCount: 0, characterCount: 1, sourceSections: [], promptSources: [] }],
    }), { status: 200 }))
    const config = { baseUrl: 'http://192.168.1.10:8190', token: 'local-token' }
    await expect(getEasyPanelSnapshots(config, 20)).resolves.toMatchObject({ schema_version: 2 })
    expect(fetchMock.mock.calls[0][0]).toBe('http://192.168.1.10:8190/api/rpg/snapshots?limit=20')
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('local-token')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ headers: { 'X-RPG-Token': 'local-token' } })
  })

  it('loads a full detail only after an explicit id request', async () => {
    const id = 'b'.repeat(32)
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      api_version: 2,
      schema_version: 2,
      snapshot: { id, schemaVersion: 2, payload: {}, source: {}, compiled: {}, outputs: [] },
    }), { status: 200 }))
    await expect(getEasyPanelSnapshot({ baseUrl: 'http://desktop:8190', token: 'local-token' }, id))
      .resolves.toMatchObject({ snapshot: { id, schemaVersion: 2 } })
    expect(fetchMock.mock.calls[0][0]).toBe(`http://desktop:8190/api/rpg/snapshots/${id}`)
  })

  it('rejects a non-hex snapshot id before making a request', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    await expect(getEasyPanelSnapshot({ baseUrl: 'http://desktop:8190', token: 'local-token' }, 'not-a-snapshot'))
      .rejects.toThrow('快照编号无效')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
