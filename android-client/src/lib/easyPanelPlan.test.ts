import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  ARTIFACT_STAGE_LABELS,
  artifactStageLabel,
  artifactState,
  artifactStateText,
  executionPlanText,
  generationIsPending,
  PENDING_ARTIFACT_TEXT,
  planFromSnapshot,
} from './easyPanelPlan'

const PLAN = {
  stages: { '1': '首采采样', '2': '高清二采', '3': '局部重绘' },
  samplers: { '1': 24, '2': 20 },
  samplerOrder: ['1', '2'],
  detailers: [{ node: '3' }],
  upscalers: ['ImageUpscaleWithModel'],
  samplerCount: 2,
  detailerCount: 1,
  outputStage: 'highres',
  output: { width: 1152, height: 1728 },
}

describe('executionPlanText', () => {
  it('renders the backend plan with stages, steps, detailers and output size', () => {
    expect(executionPlanText(PLAN)).toBe(
      '执行链：首采采样 24 步 → 高清二采 20 步 → 局部重绘 ×1｜实际 2 次主采样 + 1 次局部重绘 · 计划输出 1152×1728',
    )
  })

  it('never invents a plan for missing or empty payloads', () => {
    expect(executionPlanText(undefined)).toBe('')
    expect(executionPlanText({})).toBe('')
    expect(executionPlanText('nope')).toBe('')
    expect(executionPlanText({ samplerOrder: [] })).toBe('')
  })

  it('falls back to a generic label when a stage has no name', () => {
    expect(executionPlanText({ samplerOrder: ['9'], samplers: {} })).toContain('执行链：采样')
  })

  it('omits the output size when the backend did not declare one', () => {
    const text = executionPlanText({ samplerOrder: ['1'], samplers: { '1': 8 }, samplerCount: 1 })
    expect(text).toBe('执行链：采样 8 步｜实际 1 次主采样')
  })
})

describe('planFromSnapshot', () => {
  it('reads the plan recorded with the snapshot', () => {
    expect(planFromSnapshot({ plan: PLAN })?.outputStage).toBe('highres')
  })

  it('returns undefined for legacy snapshots', () => {
    expect(planFromSnapshot({ id: 'a' })).toBeUndefined()
    expect(planFromSnapshot(null)).toBeUndefined()
  })
})

describe('artifact stage and file state', () => {
  it('maps every backend stage to Chinese', () => {
    expect(Object.values(ARTIFACT_STAGE_LABELS)).toEqual(
      ['首采', '高清二采', '细节重绘', '面部修复', '手部修复', '脚部修复', '输出放大'],
    )
    expect(artifactStageLabel('highres')).toBe('高清二采')
    expect(artifactStageLabel('unknown_stage')).toBe('unknown_stage')
    expect(artifactStageLabel('')).toBe('')
  })

  it('treats a file still being written as pending, not missing', () => {
    const pending = { exists: false, metadata: { file_state: 'pending' } }
    expect(artifactState(pending)).toBe('pending')
    expect(artifactStateText(pending)).toBe(PENDING_ARTIFACT_TEXT)
    expect(artifactState({ exists: false, metadata: { file_state: 'missing' } })).toBe('missing')
    expect(artifactStateText({ exists: false, metadata: {} })).toBe('文件缺失')
    expect(artifactState({ exists: true, metadata: {} })).toBe('ready')
    expect(artifactStateText({ exists: true, metadata: {} })).toBe('')
  })

  it('flags generations whose outputs are still being written', () => {
    expect(generationIsPending({ file_state: 'pending' })).toBe(true)
    expect(generationIsPending({ pending_artifacts: 2 })).toBe(true)
    expect(generationIsPending({ file_state: 'ready', pending_artifacts: 0 })).toBe(false)
    expect(generationIsPending(undefined)).toBe(false)
  })
})

const source = (relative: string) => readFileSync(resolve(__dirname, '..', relative), 'utf8')

describe('手机端接线', () => {
  it('shows the backend execution plan instead of estimating on the phone', () => {
    const controller = source('hooks/useEasyPanelController.ts')
    expect(controller).toContain('setJobPlan(initial.plan)')
    expect(controller).toContain('executionPlanText(jobPlan)')
    const app = source('components/EasyPanelMobileApp.tsx')
    expect(app).toContain('controller.executionPlanText')
  })

  it('keeps internal error codes behind the 技术详情 fold-out', () => {
    const service = source('services/easyPanelVisual.ts')
    expect(service).toContain('error_detail?: EasyPanelFriendlyError')
    expect(service).toContain('分类：${code}')
    const app = source('components/EasyPanelMobileApp.tsx')
    expect(app).toContain('controller.errorTechnical')
    expect(app).toContain('<summary>技术详情</summary>')
  })

  it('marks pending outputs in the library instead of calling them broken', () => {
    const app = source('components/EasyPanelMobileApp.tsx')
    expect(app).toContain('artifactStageLabel(item.stage)')
    expect(app).toContain('PENDING_ARTIFACT_TEXT')
    expect(app).toContain("artifactState(artifact) !== 'ready'")
    const library = source('services/easyPanelLibrary.ts')
    expect(library).toContain('pending_artifacts?: number')
    expect(library).toContain('stage?: string')
  })
})
