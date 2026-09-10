/** 面板批量任务队列 + 重复任务检测（移动端，走 /api/rpg/* 入口）。 */

import { jsonRequest, type EasyPanelVisualConfig } from './easyPanelVisual'

export type EasyPanelTaskStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'error'
  | 'cancelled'
  | 'skipped'

export type EasyPanelTaskAction =
  | 'run'
  | 'pause'
  | 'cancel-current'
  | 'cancel-pending'
  | 'clean-failed'
  | 'clean-finished'
  | 'select-only'
  | 'auto-skip'
  | 'select'

export interface EasyPanelTaskItem {
  id: string
  label: string
  kind: string
  task_index: number
  image_index: number
  image_count: number
  selected: boolean
  experiment: string
  experiment_variable: string
  experiment_value: string
  status: EasyPanelTaskStatus
  prompt_id: string
  snapshot_id: string
  generation_id: string
  error: string
  created_at: number
  started_at: number
  finished_at: number
}

export interface EasyPanelTaskCounts {
  pending: number
  running: number
  completed: number
  error: number
  cancelled: number
  skipped: number
  total: number
}

export interface EasyPanelTaskSnapshot {
  version: number
  paused: boolean
  auto_skip: boolean
  selected_only: boolean
  message: string
  counts: EasyPanelTaskCounts
  running: EasyPanelTaskItem | null
  items: EasyPanelTaskItem[]
  truncated?: boolean
  runner?: { alive: boolean; last_error: string }
}

export interface EasyPanelDuplicateItem {
  generation_id: string
  created_at: number
  model?: string
  seed?: string | number | null
  thumbnail_url?: string | null
  status?: string
}

export interface EasyPanelDuplicateCheck {
  duplicate: boolean
  duplicates: EasyPanelDuplicateItem[]
  fingerprint: string
}

/** 后端只接受固定的动作集合，这里做一次白名单校验，避免误写。 */
const TASK_ACTIONS: EasyPanelTaskAction[] = [
  'run', 'pause', 'cancel-current', 'cancel-pending',
  'clean-failed', 'clean-finished', 'select-only', 'auto-skip', 'select',
]

export function safeTaskId(value: unknown): string {
  const text = String(value ?? '').trim()
  return /^task_[0-9a-f]{16}$/.test(text) || /^[0-9a-f]{16,32}$/.test(text) ? text : ''
}

export function isEasyPanelTaskAction(value: unknown): value is EasyPanelTaskAction {
  return TASK_ACTIONS.includes(String(value ?? '').trim() as EasyPanelTaskAction)
}

export async function getEasyPanelTasks(config: EasyPanelVisualConfig): Promise<EasyPanelTaskSnapshot> {
  return jsonRequest<EasyPanelTaskSnapshot>(config, '/api/rpg/tasks')
}

export async function controlEasyPanelTask(
  config: EasyPanelVisualConfig,
  action: EasyPanelTaskAction,
  extra: Record<string, unknown> = {},
): Promise<EasyPanelTaskSnapshot> {
  if (!isEasyPanelTaskAction(action)) throw new Error('不支持的任务队列操作。')
  return jsonRequest<EasyPanelTaskSnapshot>(config, '/api/rpg/tasks/control', {
    method: 'POST',
    body: JSON.stringify({ action, ...extra }),
  })
}

export async function checkEasyPanelDuplicate(
  config: EasyPanelVisualConfig,
  payload: Record<string, unknown>,
): Promise<EasyPanelDuplicateCheck> {
  if (!payload || typeof payload !== 'object') throw new Error('重复检测缺少生成参数。')
  return jsonRequest<EasyPanelDuplicateCheck>(config, '/api/rpg/generate-check', {
    method: 'POST',
    body: JSON.stringify({ payload }),
  })
}

/** 队列状态的中文标签（列表与测试共用）。 */
export function taskStatusLabel(status: EasyPanelTaskStatus | string): string {
  switch (status) {
    case 'pending': return '排队中'
    case 'running': return '执行中'
    case 'completed': return '已完成'
    case 'error': return '失败'
    case 'cancelled': return '已取消'
    case 'skipped': return '已跳过'
    default: return String(status || '未知')
  }
}

/** 「排队中 2 · 执行中 1 · 失败 1」这类摘要文本。 */
export function taskCountsSummary(counts: EasyPanelTaskCounts | undefined): string {
  if (!counts) return '尚未读取任务队列'
  const parts = [
    `排队中 ${counts.pending ?? 0}`,
    `执行中 ${counts.running ?? 0}`,
    `已完成 ${counts.completed ?? 0}`,
    `失败 ${counts.error ?? 0}`,
    `已取消 ${counts.cancelled ?? 0}`,
    `已跳过 ${counts.skipped ?? 0}`,
  ]
  return parts.join(' · ')
}

/** 结束的任务（可被“清理失败任务”清掉）。 */
export function cleanableTaskCount(counts: EasyPanelTaskCounts | undefined): number {
  if (!counts) return 0
  return (counts.error ?? 0) + (counts.cancelled ?? 0) + (counts.skipped ?? 0)
}
