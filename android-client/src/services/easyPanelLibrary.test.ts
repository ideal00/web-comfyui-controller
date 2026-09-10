import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createEasyPanelFavoriteGroup,
  deleteEasyPanelFavoriteGroup,
  getEasyPanelFavoriteGroups,
  getEasyPanelGeneration,
  getEasyPanelLibrary,
  getEasyPanelLineage,
  libraryFlagsPayload,
  normalizeGroupName,
  renameEasyPanelFavoriteGroup,
  setEasyPanelGenerationFlags,
} from './easyPanelLibrary'

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

  it('marks a work as 入选 without touching the recipe', async () => {
    const id = 'b'.repeat(32)
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      api_version: 2,
      index_schema_version: 1,
      generation: { generation_id: id, favorite: true, rating: 4, note: '构图最好' },
    }), { status: 200 }))

    const response = await setEasyPanelGenerationFlags(
      { baseUrl: 'http://desktop:8190', token: 't' },
      id,
      { favorite: true, rating: 4.4, note: '构图最好' },
    )

    expect(response.generation.favorite).toBe(true)
    expect(fetchMock.mock.calls[0][0]).toBe('http://desktop:8190/api/rpg/library/favorite')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST' })
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      generation_id: id,
      favorite: true,
      rating: 4,
      note: '构图最好',
    })
    await expect(setEasyPanelGenerationFlags({ baseUrl: 'http://desktop:8190', token: 't' }, id, {}))
      .rejects.toThrow('没有需要保存的收藏字段')
  })

  it('filters the list by 入选 and keeps unknown fields out of the payload', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      items: [], total: 0, limit: 20, offset: 0, has_more: false,
    }), { status: 200 }))
    await getEasyPanelLibrary({ baseUrl: 'http://desktop:8190', token: 't' }, { favorite: 'favorite' })
    expect(String(fetchMock.mock.calls[0][0])).toContain('favorite=favorite')
    expect(libraryFlagsPayload({ rating: 9 })).toEqual({ rating: 5 })
    expect(libraryFlagsPayload({ favorite: false })).toEqual({ favorite: false })
  })

  it('manages named 收藏组 and assigns works to them', async () => {
    const groupId = 'c'.repeat(32)
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({
        api_version: 2, index_schema_version: 1,
        groups: [{ group_id: groupId, name: '成图候选', item_count: 2, created_at: 1, updated_at: 1 }],
        total: 1,
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        api_version: 2, index_schema_version: 1,
        result: { created: true, group: { group_id: groupId, name: '成图候选' } },
        groups: [], total: 0,
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ groups: [], total: 0 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        result: { deleted: true, name: '最终成图', removed_links: 2 }, groups: [], total: 0,
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        generation: { generation_id: 'd'.repeat(32), groups: [{ group_id: groupId, name: '成图候选' }] },
      }), { status: 200 }))

    const list = await getEasyPanelFavoriteGroups({ baseUrl: 'http://desktop:8190', token: 't' })
    expect(list.groups[0]).toMatchObject({ name: '成图候选', item_count: 2 })
    await createEasyPanelFavoriteGroup({ baseUrl: 'http://desktop:8190', token: 't' }, '  成图   候选  ')
    await renameEasyPanelFavoriteGroup({ baseUrl: 'http://desktop:8190', token: 't' }, groupId, '最终成图')
    await deleteEasyPanelFavoriteGroup({ baseUrl: 'http://desktop:8190', token: 't' }, groupId)
    await setEasyPanelGenerationFlags({ baseUrl: 'http://desktop:8190', token: 't' }, 'd'.repeat(32), { groups: [groupId] })

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://desktop:8190/api/rpg/library/groups',
      'http://desktop:8190/api/rpg/library/groups',
      'http://desktop:8190/api/rpg/library/groups',
      'http://desktop:8190/api/rpg/library/groups',
      'http://desktop:8190/api/rpg/library/favorite',
    ])
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ action: 'create', name: '成图 候选' })
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ action: 'rename', group_id: groupId, name: '最终成图' })
    expect(JSON.parse(String(fetchMock.mock.calls[3][1]?.body))).toEqual({ action: 'delete', group_id: groupId })
    expect(JSON.parse(String(fetchMock.mock.calls[4][1]?.body))).toEqual({
      generation_id: 'd'.repeat(32), groups: [groupId],
    })
    expect(normalizeGroupName('  成图   候选  ')).toBe('成图 候选')
    expect(() => normalizeGroupName('   ')).toThrow('收藏组名称不能为空')
    expect(libraryFlagsPayload({ groupAdd: [groupId, 'bad', groupId] })).toEqual({ group_add: [groupId] })
    expect(libraryFlagsPayload({ groupRemove: [] })).toEqual({ group_remove: [] })
    await expect(setEasyPanelGenerationFlags({ baseUrl: 'http://desktop:8190', token: 't' }, 'd'.repeat(32), {}))
      .rejects.toThrow('没有需要保存的收藏字段')
  })
})
