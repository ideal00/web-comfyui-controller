/**
 * 执行链 / 产物阶段的只读展示助手。
 *
 * 真相源在电脑端：`build_workflow()` 为每个产物声明 `artifact_stage`，
 * `generation_plan()` 给出实际执行计划（阶段、主采样、局部重绘、计划输出）。
 * 手机端只负责把这些字段翻译成中文，不再自己推断执行链。
 */

export interface EasyPanelExecutionPlan {
  stages?: Record<string, string>
  samplers?: Record<string, number>
  samplerOrder?: string[]
  detailers?: unknown[]
  upscalers?: string[]
  samplerCount?: number
  detailerCount?: number
  outputStage?: string
  output?: { width?: number; height?: number }
}

/** artifact_stage：这一步产物来自流程的哪一段（电脑端 workflow 直接声明）。 */
export const ARTIFACT_STAGE_LABELS: Record<string, string> = {
  base: '首采',
  highres: '高清二采',
  detail_refine: '细节重绘',
  face: '面部修复',
  hand: '手部修复',
  foot: '脚部修复',
  upscale: '输出放大',
}

const PENDING_TEXT = '⏳ 文件保存中'

export function artifactStageLabel(stage: unknown): string {
  const key = text(stage).toLowerCase()
  if (!key) return ''
  return ARTIFACT_STAGE_LABELS[key] ?? key
}

/** 一句话描述后端实际计划，例如「首采采样 8 步 → 高清二采 20 步 · 局部重绘 ×1 · 计划输出 1152×1152」。 */
export function executionPlanText(plan: unknown): string {
  const value = asPlan(plan)
  if (!value) return ''
  const stages = isRecord(value.stages) ? value.stages : {}
  const steps = isRecord(value.samplers) ? value.samplers : {}
  const order = Array.isArray(value.samplerOrder) ? value.samplerOrder : []
  const items: string[] = []
  for (const nodeId of order) {
    const label = text(stages[String(nodeId)]) || '采样'
    const count = Number(steps[String(nodeId)])
    items.push(Number.isFinite(count) && count > 0 ? `${label} ${count} 步` : label)
  }
  const detailerCount = Number(value.detailerCount) || 0
  if (detailerCount > 0) items.push(`局部重绘 ×${detailerCount}`)
  if (!items.length) return ''
  const samplerCount = Number(value.samplerCount) || order.length
  const output = isRecord(value.output) ? value.output : {}
  const width = Number(output.width) || 0
  const height = Number(output.height) || 0
  const tail = [`实际 ${samplerCount} 次主采样${detailerCount ? ` + ${detailerCount} 次局部重绘` : ''}`]
  if (width > 0 && height > 0) tail.push(`计划输出 ${width}×${height}`)
  return `执行链：${items.join(' → ')}｜${tail.join(' · ')}`
}

/** 快照里记录的计划（提交时写入）；旧快照没有该字段时返回 undefined。 */
export function planFromSnapshot(snapshot: unknown): EasyPanelExecutionPlan | undefined {
  if (!isRecord(snapshot)) return undefined
  return asPlan(snapshot.plan)
}

/** 产物文件状态：ready / pending（还在写盘）/ missing。 */
export function artifactState(artifact: unknown): 'ready' | 'pending' | 'missing' {
  if (!isRecord(artifact)) return 'ready'
  const metadata = isRecord(artifact.metadata) ? artifact.metadata : {}
  if (text(metadata.file_state).toLowerCase() === 'pending') return 'pending'
  if (artifact.exists === false) return 'missing'
  return 'ready'
}

export function artifactStateText(artifact: unknown): string {
  const state = artifactState(artifact)
  if (state === 'pending') return PENDING_TEXT
  if (state === 'missing') return '文件缺失'
  return ''
}

/** 作品是否还有文件在写盘：此时不能当“图片损坏”，只提示稍后刷新。 */
export function generationIsPending(generation: unknown): boolean {
  if (!isRecord(generation)) return false
  if (text(generation.file_state).toLowerCase() === 'pending') return true
  return Number(generation.pending_artifacts) > 0
}

export const PENDING_ARTIFACT_TEXT = PENDING_TEXT

function asPlan(value: unknown): EasyPanelExecutionPlan | undefined {
  if (!isRecord(value)) return undefined
  const hasShape = Array.isArray(value.samplerOrder)
    || isRecord(value.stages)
    || Number.isFinite(Number(value.samplerCount))
  return hasShape ? value as EasyPanelExecutionPlan : undefined
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function text(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value).trim() : ''
}
