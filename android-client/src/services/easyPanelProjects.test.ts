import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  addEasyPanelProjectItems,
  addEasyPanelProjectLink,
  createEasyPanelProject,
  deleteEasyPanelProject,
  getEasyPanelProject,
  getEasyPanelProjects,
  isEasyPanelProjectLinkKind,
  normalizeProjectSections,
  projectLinkLabel,
  removeEasyPanelProjectLink,
  safeProjectId,
  setEasyPanelProjectCover,
  updateEasyPanelProject,
  updateEasyPanelProjectItem,
} from './easyPanelProjects'

afterEach(() => vi.restoreAllMocks())

const config = { baseUrl: 'http://desktop:8190', token: 't' }
const projectId = 'b'.repeat(32)

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), { status: 200 })
}

describe('Easy Panel mobile project API', () => {
  it('lists projects and reads one detail', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ items: [{ project_id: projectId, name: 'Luna' }], total: 1, defaultSections: [] }))
      .mockResolvedValueOnce(jsonResponse({ project: { project_id: projectId }, sections: [], links: {}, total: 0 }))

    await getEasyPanelProjects(config)
    await getEasyPanelProject(config, projectId.toUpperCase())

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://desktop:8190/api/rpg/library/projects',
      `http://desktop:8190/api/rpg/library/projects/${projectId}`,
    ])
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ headers: { 'X-RPG-Token': 't' } })
    await expect(getEasyPanelProject(config, 'nope')).rejects.toThrow('项目编号无效')
  })

  it('creates, renames and deletes projects', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => jsonResponse({ project: { project_id: projectId } }))

    await createEasyPanelProject(config, '  Luna 角色图集  ', { sections: '基准角色，夜景\n' })
    await updateEasyPanelProject(config, projectId, { name: 'Luna 2026' })
    await deleteEasyPanelProject(config, projectId)

    const bodies = fetchMock.mock.calls.map(([, init]) => JSON.parse(String(init?.body)))
    expect(bodies[0]).toEqual({
      action: 'create', name: 'Luna 角色图集', note: '', sections: ['基准角色', '夜景'],
    })
    expect(bodies[1]).toEqual({ action: 'update', project_id: projectId, name: 'Luna 2026' })
    expect(bodies[2]).toEqual({ action: 'delete', project_id: projectId })
    await expect(createEasyPanelProject(config, '   ')).rejects.toThrow('项目名称不能为空')
  })

  it('adds and removes project items, and sets the cover', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => jsonResponse({ added: 1 }))
    const generationId = 'c'.repeat(32)

    await addEasyPanelProjectItems(config, projectId, [generationId], '基准角色')
    await updateEasyPanelProjectItem(config, projectId, 'item-1', { section: '最终精选', note: '最佳版本' })
    await setEasyPanelProjectCover(config, projectId, generationId)

    const bodies = fetchMock.mock.calls.map(([, init]) => JSON.parse(String(init?.body)))
    expect(bodies[0]).toEqual({
      action: 'add-items', project_id: projectId, generation_ids: [generationId], section: '基准角色',
    })
    expect(bodies[1]).toEqual({
      action: 'update-item', project_id: projectId, item_id: 'item-1', section: '最终精选', note: '最佳版本',
    })
    expect(bodies[2]).toEqual({ action: 'set-cover', project_id: projectId, generation_id: generationId })
    await expect(addEasyPanelProjectItems(config, projectId, [])).rejects.toThrow('没有可加入项目的作品')
    await expect(setEasyPanelProjectCover(config, projectId, '')).rejects.toThrow('请选择要作为封面的作品')
  })

  it('links and unlinks project resources', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => jsonResponse({ project: {} }))

    await addEasyPanelProjectLink(config, projectId, 'lora', 'Illustrious/luna.safetensors', 'Luna')
    await addEasyPanelProjectLink(config, projectId, 'experiment', 'cfg 5/7/9')
    await removeEasyPanelProjectLink(config, projectId, 'link-1')

    const bodies = fetchMock.mock.calls.map(([, init]) => JSON.parse(String(init?.body)))
    expect(bodies[0]).toEqual({
      action: 'add-link', project_id: projectId, kind: 'lora', ref: 'Illustrious/luna.safetensors', label: 'Luna',
    })
    expect(bodies[1]).toEqual({
      action: 'add-link', project_id: projectId, kind: 'experiment', ref: 'cfg 5/7/9', label: '',
    })
    expect(bodies[2]).toEqual({ action: 'remove-link', project_id: projectId, link_id: 'link-1' })
    await expect(addEasyPanelProjectLink(config, projectId, 'unknown', 'x')).rejects.toThrow('关联类型无效')
    await expect(addEasyPanelProjectLink(config, projectId, 'lora', '   ')).rejects.toThrow('关联内容不能为空')
  })
})

describe('Easy Panel mobile project helpers', () => {
  it('normalizes sections and validates ids/kinds', () => {
    expect(normalizeProjectSections('基准角色, 夜景')).toEqual(['基准角色', '夜景'])
    expect(normalizeProjectSections(' 夜景 , 夜景 ')).toEqual(['夜景'])
    expect(normalizeProjectSections(['  ', '夜景', '夜景'])).toEqual(['夜景'])
    expect(normalizeProjectSections('')).toEqual(['基准角色', '日常服装', '战斗服装', '废墟场景', '夜景', '最终精选'])
    expect(safeProjectId(projectId.toUpperCase())).toBe(projectId)
    expect(safeProjectId('bad')).toBe('')
    expect(isEasyPanelProjectLinkKind('favorite_group')).toBe(true)
    expect(isEasyPanelProjectLinkKind('nope')).toBe(false)
    expect(projectLinkLabel('preset')).toBe('Prompt 预设')
    expect(projectLinkLabel('weird')).toBe('weird')
  })
})
