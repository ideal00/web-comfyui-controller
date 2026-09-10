import { jsonRequest, type EasyPanelVisualConfig } from './easyPanelVisual'
import type { EasyPanelSnapshotRecord } from './easyPanelSnapshots'

export type EasyPanelLibraryOperation =
  | 'txt2img'
  | 'seed_variant'
  | 'img2img'
  | 'inpaint'
  | 'face_fix'
  | 'hand_fix'
  | 'upscale'
  | 'outfit_change'
  | 'scene_change'
  | 'style_change'
  | 'unknown'

export type EasyPanelLibraryStatus = 'queued' | 'running' | 'completed' | 'error' | 'cancelled' | 'unknown'

export interface EasyPanelGenerationSummary {
  generation_id: string
  snapshot_id?: string | null
  prompt_id?: string | null
  request_id?: string | null
  operation: EasyPanelLibraryOperation
  status: EasyPanelLibraryStatus
  created_at: number
  updated_at: number
  schema_version: number
  panel_version?: string
  workflow_version?: string
  inference_version?: string
  model: string
  seed?: string | number | null
  width?: number | null
  height?: number | null
  quality?: string
  lora_count: number
  artifact_count: number
  parent_count: number
  child_count: number
  thumbnail_url?: string | null
  /** 入选（最佳版本）标记；只是作品标记，不影响任何生成参数。 */
  favorite?: boolean
  /** 0–5 星人工评分。 */
  rating?: number
  /** 人工备注，最多 2000 字。 */
  note?: string
}

export interface EasyPanelGenerationArtifact {
  artifact_id: string
  generation_id: string
  filename: string
  subfolder: string
  type: string
  kind: string
  exists?: boolean | null
  metadata: Record<string, unknown>
  url?: string | null
  created_at: number
}

export interface EasyPanelGenerationLora {
  position: number
  name: string
  weight?: string | number | null
  trigger: string
  role: string
  source: string
  metadata: Record<string, unknown>
}

export interface EasyPanelReplayPreview {
  can_submit: false
  action: 'restore_to_form'
  payload: Record<string, unknown>
  operation: EasyPanelLibraryOperation
  seed?: string | number | null
  note: string
}

export interface EasyPanelGenerationDetail extends EasyPanelGenerationSummary {
  input: Record<string, unknown>
  compiled: Record<string, unknown>
  inference: Record<string, unknown>
  workflow: Record<string, unknown>
  snapshot: EasyPanelSnapshotRecord | Record<string, unknown>
  error: Record<string, unknown>
  loras: EasyPanelGenerationLora[]
  artifacts: EasyPanelGenerationArtifact[]
  replay: EasyPanelReplayPreview
  variation: EasyPanelReplayPreview
}

export interface EasyPanelLibraryListResponse {
  api_version: number
  index_schema_version: number
  schema_version: number
  items: EasyPanelGenerationSummary[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface EasyPanelLibraryDetailResponse {
  api_version: number
  index_schema_version: number
  generation: EasyPanelGenerationDetail
}

export interface EasyPanelLibraryLineageNode extends EasyPanelGenerationSummary {
  depth: number
}

export interface EasyPanelLibraryLineageEdge {
  derivation_id: string
  parent_generation_id?: string | null
  child_generation_id?: string | null
  parent_artifact_id?: string | null
  child_artifact_id?: string | null
  operation: EasyPanelLibraryOperation
  created_at: number
  metadata: Record<string, unknown>
}

export interface EasyPanelLibraryLineage {
  generation_id: string
  ancestors: EasyPanelLibraryLineageNode[]
  descendants: EasyPanelLibraryLineageNode[]
  edges: EasyPanelLibraryLineageEdge[]
  schema_version: number
}

export interface EasyPanelLibraryLineageResponse {
  api_version: number
  index_schema_version: number
  lineage: EasyPanelLibraryLineage
}

export interface EasyPanelLibraryQuery {
  limit?: number
  offset?: number
  operation?: EasyPanelLibraryOperation | ''
  status?: EasyPanelLibraryStatus | ''
  model?: string
  favorite?: 'favorite' | 'unfavorite' | ''
  sort?: 'created_at' | 'updated_at' | 'status' | 'operation' | 'model'
  order?: 'asc' | 'desc'
}

export async function getEasyPanelLibrary(
  config: EasyPanelVisualConfig,
  query: EasyPanelLibraryQuery = {},
): Promise<EasyPanelLibraryListResponse> {
  const params = new URLSearchParams()
  params.set('limit', String(clampInteger(query.limit, 20, 1, 100)))
  params.set('offset', String(clampInteger(query.offset, 0, 0, 1_000_000)))
  if (query.operation) params.set('operation', query.operation)
  if (query.status) params.set('status', query.status)
  if (query.model?.trim()) params.set('model', query.model.trim().slice(0, 200))
  if (query.favorite === 'favorite' || query.favorite === 'unfavorite') params.set('favorite', query.favorite)
  if (query.sort) params.set('sort', query.sort)
  if (query.order) params.set('order', query.order)
  return jsonRequest<EasyPanelLibraryListResponse>(config, `/api/rpg/library/generations?${params.toString()}`)
}

export async function getEasyPanelGeneration(
  config: EasyPanelVisualConfig,
  generationId: string,
): Promise<EasyPanelLibraryDetailResponse> {
  const id = safeGenerationId(generationId)
  return jsonRequest<EasyPanelLibraryDetailResponse>(config, `/api/rpg/library/generations/${id}`)
}

export async function getEasyPanelLineage(
  config: EasyPanelVisualConfig,
  generationId: string,
): Promise<EasyPanelLibraryLineageResponse> {
  const id = safeGenerationId(generationId)
  return jsonRequest<EasyPanelLibraryLineageResponse>(config, `/api/rpg/library/generations/${id}/lineage`)
}

export interface EasyPanelLibraryDeleteResponse {
  api_version: number
  index_schema_version: number
  deleted_generation: string
  deleted: boolean
  removed_files: string[]
  missing_files: string[]
  artifact_count: number
}

/** Delete a generation record and its local output images on the computer side. */
export async function deleteEasyPanelGeneration(
  config: EasyPanelVisualConfig,
  generationId: string,
): Promise<EasyPanelLibraryDeleteResponse> {
  const id = safeGenerationId(generationId)
  return jsonRequest<EasyPanelLibraryDeleteResponse>(config, '/api/rpg/library/delete', {
    method: 'POST',
    body: JSON.stringify({ generation_id: id }),
  })
}

export function safeGenerationId(value: string): string {
  const id = value.trim().toLowerCase()
  if (!/^[0-9a-f]{32}$/u.test(id)) throw new Error('作品编号无效。')
  return id
}

/** 与网页端一致：作品标记不属于生成参数，不会创建新版本。 */
export function libraryFlagsPayload(patch: {
  favorite?: boolean
  rating?: number
  note?: string
}): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  if (Object.prototype.hasOwnProperty.call(patch, 'favorite')) body.favorite = Boolean(patch.favorite)
  if (Object.prototype.hasOwnProperty.call(patch, 'rating') && Number.isFinite(patch.rating)) {
    body.rating = Math.min(5, Math.max(0, Math.round(patch.rating as number)))
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'note')) body.note = String(patch.note ?? '').slice(0, 2000)
  return body
}

/** Mark a generation as 入选 / 评分 / 备注 without touching the recipe. */
export async function setEasyPanelGenerationFlags(
  config: EasyPanelVisualConfig,
  generationId: string,
  patch: { favorite?: boolean; rating?: number; note?: string },
): Promise<EasyPanelLibraryDetailResponse> {
  const id = safeGenerationId(generationId)
  const body = libraryFlagsPayload(patch)
  if (!Object.keys(body).length) throw new Error('没有需要保存的收藏字段。')
  return jsonRequest<EasyPanelLibraryDetailResponse>(config, '/api/rpg/library/favorite', {
    method: 'POST',
    body: JSON.stringify({ generation_id: id, ...body }),
  })
}

function clampInteger(value: number | undefined, fallback: number, minimum: number, maximum: number): number {
  if (!Number.isFinite(value)) return fallback
  return Math.min(maximum, Math.max(minimum, Math.round(value as number)))
}
