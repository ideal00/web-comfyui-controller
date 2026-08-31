import { jsonRequest, type EasyPanelVisualConfig } from './easyPanelVisual'

export interface EasyPanelSnapshotSummary {
  id: string
  createdAt: number
  promptId?: string
  label?: string
  schemaVersion: number
  workflow?: Record<string, unknown>
  model: string
  seed?: number | string | null
  width?: number | null
  height?: number | null
  quality?: string
  loraCount: number
  outputCount: number
  outputs?: string[]
  characterCount: number
  sourceSections: string[]
  promptSources: Array<{
    key: string
    label: string
    kind: string
    enabled: boolean
    termCount: number
  }>
}

export type EasyPanelSnapshotObject = Record<string, unknown>

export interface EasyPanelSnapshotRecord {
  id: string
  createdAt: number
  schemaVersion: number
  promptId?: string
  label?: string
  experiment?: EasyPanelSnapshotObject | null
  payload: EasyPanelSnapshotObject
  source: EasyPanelSnapshotObject
  compiled: EasyPanelSnapshotObject
  workflow?: EasyPanelSnapshotObject
  outputs: string[]
  environment?: EasyPanelSnapshotObject
}

export interface EasyPanelSnapshotListResponse {
  api_version: number
  schema_version: number
  snapshots: EasyPanelSnapshotSummary[]
}

export interface EasyPanelSnapshotDetailResponse {
  api_version: number
  schema_version: number
  snapshot: EasyPanelSnapshotRecord
}

export async function getEasyPanelSnapshots(
  config: EasyPanelVisualConfig,
  limit = 20,
): Promise<EasyPanelSnapshotListResponse> {
  const safeLimit = Math.max(1, Math.min(50, Math.round(limit)))
  return jsonRequest<EasyPanelSnapshotListResponse>(config, `/api/rpg/snapshots?limit=${safeLimit}`)
}

export async function getEasyPanelSnapshot(
  config: EasyPanelVisualConfig,
  snapshotId: string,
): Promise<EasyPanelSnapshotDetailResponse> {
  if (!/^[0-9a-f]{32}$/iu.test(snapshotId.trim())) throw new Error('快照编号无效。')
  return jsonRequest<EasyPanelSnapshotDetailResponse>(
    config,
    `/api/rpg/snapshots/${encodeURIComponent(snapshotId.trim())}`,
  )
}
