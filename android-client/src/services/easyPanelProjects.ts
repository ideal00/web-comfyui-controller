/** 作品项目（角色图集 / 场景项目）：分区 + 项目内作品 + 关联资源。 */

import { jsonRequest, type EasyPanelVisualConfig } from './easyPanelVisual'
import type { EasyPanelGenerationSummary } from './easyPanelLibrary'

export type EasyPanelProjectLinkKind = 'lora' | 'preset' | 'experiment' | 'favorite_group'

export interface EasyPanelProject {
  project_id: string
  name: string
  note: string
  sections: string[]
  favorites_group_id: string | null
  cover_artifact_id: string | null
  cover_url: string | null
  item_count: number
  created_at: number
  updated_at: number
}

export interface EasyPanelProjectEntry {
  item_id: string
  section: string
  position: number
  note: string
  created_at: number
  generation: EasyPanelGenerationSummary | Record<string, never>
}

export interface EasyPanelProjectSection {
  name: string
  items: EasyPanelProjectEntry[]
}

export interface EasyPanelProjectLink {
  link_id: string
  kind: EasyPanelProjectLinkKind
  ref: string
  label: string
  created_at: number
}

export interface EasyPanelProjectDetail {
  project: EasyPanelProject
  sections: EasyPanelProjectSection[]
  links: Record<string, EasyPanelProjectLink[]>
  total: number
  truncated?: boolean
}

export interface EasyPanelProjectList {
  items: EasyPanelProject[]
  total: number
  defaultSections: string[]
}

export const EASY_PANEL_DEFAULT_PROJECT_SECTIONS = [
  '基准角色', '日常服装', '战斗服装', '废墟场景', '夜景', '最终精选',
]

const LINK_KINDS: EasyPanelProjectLinkKind[] = ['lora', 'preset', 'experiment', 'favorite_group']

export function safeProjectId(value: unknown): string {
  const text = String(value ?? '').trim().toLowerCase()
  return /^[0-9a-f]{32}$/.test(text) ? text : ''
}

export function isEasyPanelProjectLinkKind(value: unknown): value is EasyPanelProjectLinkKind {
  return LINK_KINDS.includes(String(value ?? '').trim() as EasyPanelProjectLinkKind)
}

/** 把「基准角色, 夜景」这类文本整理成去重后的分区列表。 */
export function normalizeProjectSections(value: unknown): string[] {
  const source = Array.isArray(value) ? value : String(value ?? '').split(/[,，]/)
  const sections: string[] = []
  for (const entry of source) {
    // 折叠空白（含换行），和后端 _safe_project_sections 保持一致。
    const name = String(entry ?? '').replace(/\s+/g, ' ').trim().slice(0, 24)
    if (name && !sections.includes(name)) sections.push(name)
    if (sections.length >= 16) break
  }
  return sections.length ? sections : [...EASY_PANEL_DEFAULT_PROJECT_SECTIONS]
}

async function projectRequest(
  config: EasyPanelVisualConfig,
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return jsonRequest<Record<string, unknown>>(config, '/api/rpg/library/projects', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function getEasyPanelProjects(config: EasyPanelVisualConfig): Promise<EasyPanelProjectList> {
  return jsonRequest<EasyPanelProjectList>(config, '/api/rpg/library/projects')
}

export async function getEasyPanelProject(
  config: EasyPanelVisualConfig,
  projectId: string,
): Promise<EasyPanelProjectDetail> {
  const wanted = safeProjectId(projectId)
  if (!wanted) throw new Error('项目编号无效。')
  return jsonRequest<EasyPanelProjectDetail>(config, `/api/rpg/library/projects/${wanted}`)
}

export async function createEasyPanelProject(
  config: EasyPanelVisualConfig,
  name: string,
  options: { note?: string; sections?: unknown } = {},
) {
  const clean = String(name ?? '').trim()
  if (!clean) throw new Error('项目名称不能为空。')
  return projectRequest(config, {
    action: 'create', name: clean, note: options.note ?? '',
    sections: options.sections === undefined ? undefined : normalizeProjectSections(options.sections),
  })
}

export async function updateEasyPanelProject(
  config: EasyPanelVisualConfig,
  projectId: string,
  patch: { name?: string; note?: string; sections?: unknown },
) {
  const wanted = safeProjectId(projectId)
  if (!wanted) throw new Error('项目编号无效。')
  const body: Record<string, unknown> = { action: 'update', project_id: wanted }
  if (patch.name !== undefined) body.name = String(patch.name).trim()
  if (patch.note !== undefined) body.note = patch.note
  if (patch.sections !== undefined) body.sections = normalizeProjectSections(patch.sections)
  return projectRequest(config, body)
}

export async function deleteEasyPanelProject(config: EasyPanelVisualConfig, projectId: string) {
  const wanted = safeProjectId(projectId)
  if (!wanted) throw new Error('项目编号无效。')
  return projectRequest(config, { action: 'delete', project_id: wanted })
}

export async function addEasyPanelProjectItems(
  config: EasyPanelVisualConfig,
  projectId: string,
  generationIds: string[],
  section = '',
) {
  const wanted = safeProjectId(projectId)
  if (!wanted) throw new Error('项目编号无效。')
  const ids = (Array.isArray(generationIds) ? generationIds : [generationIds]).filter(Boolean)
  if (!ids.length) throw new Error('没有可加入项目的作品。')
  return projectRequest(config, {
    action: 'add-items', project_id: wanted, generation_ids: ids, section: String(section ?? '').trim(),
  })
}

export async function removeEasyPanelProjectItems(
  config: EasyPanelVisualConfig,
  projectId: string,
  ids: { itemIds?: string[]; generationIds?: string[] },
) {
  const wanted = safeProjectId(projectId)
  if (!wanted) throw new Error('项目编号无效。')
  const body: Record<string, unknown> = { action: 'remove-items', project_id: wanted }
  if (ids.itemIds?.length) body.item_ids = ids.itemIds
  if (ids.generationIds?.length) body.generation_ids = ids.generationIds
  if (!body.item_ids && !body.generation_ids) throw new Error('没有要移除的项目内容。')
  return projectRequest(config, body)
}

export async function updateEasyPanelProjectItem(
  config: EasyPanelVisualConfig,
  projectId: string,
  itemId: string,
  patch: { section?: string; note?: string; position?: number },
) {
  const wanted = safeProjectId(projectId)
  if (!wanted) throw new Error('项目编号无效。')
  const body: Record<string, unknown> = { action: 'update-item', project_id: wanted, item_id: String(itemId ?? '').trim() }
  if (patch.section !== undefined) body.section = String(patch.section ?? '').trim()
  if (patch.note !== undefined) body.note = patch.note
  if (patch.position !== undefined) body.position = patch.position
  return projectRequest(config, body)
}

export async function setEasyPanelProjectCover(
  config: EasyPanelVisualConfig,
  projectId: string,
  generationId: string,
) {
  const wanted = safeProjectId(projectId)
  if (!wanted) throw new Error('项目编号无效。')
  const generation = String(generationId ?? '').trim()
  if (!generation) throw new Error('请选择要作为封面的作品。')
  return projectRequest(config, { action: 'set-cover', project_id: wanted, generation_id: generation })
}

export async function addEasyPanelProjectLink(
  config: EasyPanelVisualConfig,
  projectId: string,
  kind: string,
  ref: string,
  label = '',
) {
  const wanted = safeProjectId(projectId)
  if (!wanted) throw new Error('项目编号无效。')
  if (!isEasyPanelProjectLinkKind(kind)) throw new Error('项目关联类型无效。')
  const target = String(ref ?? '').trim()
  if (!target) throw new Error('关联内容不能为空。')
  return projectRequest(config, {
    action: 'add-link', project_id: wanted, kind, ref: target, label: String(label ?? '').trim(),
  })
}

export async function removeEasyPanelProjectLink(
  config: EasyPanelVisualConfig,
  projectId: string,
  linkId: string,
) {
  const wanted = safeProjectId(projectId)
  if (!wanted) throw new Error('项目编号无效。')
  const link = String(linkId ?? '').trim()
  if (!link) throw new Error('关联编号无效。')
  return projectRequest(config, { action: 'remove-link', project_id: wanted, link_id: link })
}

/** 项目关联类型的中文标签。 */
export function projectLinkLabel(kind: string): string {
  switch (kind) {
    case 'lora': return 'LoRA'
    case 'preset': return 'Prompt 预设'
    case 'experiment': return '单变量实验'
    case 'favorite_group': return '收藏组'
    default: return String(kind || '关联')
  }
}
