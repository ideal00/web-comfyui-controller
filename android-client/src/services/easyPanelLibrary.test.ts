import { afterEach, describe, expect, it, vi } from 'vitest'
import { getEasyPanelGeneration, getEasyPanelLibrary, getEasyPanelLineage } from './easyPanelLibrary'

afterEach(() => vi.restoreAllMocks())

describe('Easy Panel creative Library API', () => {
  it('reads a paginated list with filters and sends the token in a header', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      api_version: 2,
      index_schema_version: 1,
      schema_version: 1,
      items: [],
      total: 0,
      limit: 10,
      offset: 20,
      has_more: false,
    }), { status: 200 }))

    await expect(getEasyPanelLibrary({ baseUrl: 'http://192.168.1.10:8190', token: 'local-token' }, {
      limit: 10,
      offset: 20,
      operation: 'img2img',
      status: 'completed',
      model: 'wai model',
      sort: 'updated_at',
      order: 'asc',
    })).resolves.toMatchObject({ total: 0 })

    expect(fetchMock.mock.calls[0][0]).toBe(
      'http://192.168.1.10:8190/api/rpg/library/generations?limit=10&offset=20&operation=img2img&status=completed&model=wai+model&sort=updated_at&order=asc',
    )
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ headers: { 'X-RPG-Token': 'local-token' } })
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('local-token')
  })

  it('loads detail and lineage only for a strict generation id', async () => {
    const id = 'a'.repeat(32)
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ generation: { generation_id: id } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ lineage: { generation_id: id } }), { status: 200 }))
    await getEasyPanelGeneration({ baseUrl: 'http://desktop:8190', token: 't' }, id)
    await getEasyPanelLineage({ baseUrl: 'http://desktop:8190', token: 't' }, id)
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `http://desktop:8190/api/rpg/library/generations/${id}`,
      `http://desktop:8190/api/rpg/library/generations/${id}/lineage`,
    ])
    await expect(getEasyPanelGeneration({ baseUrl: 'http://desktop:8190', token: 't' }, 'not-valid'))
      .rejects.toThrow('作品编号无效')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
