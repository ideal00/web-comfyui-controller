import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  checkEasyPanelDuplicate,
  cleanableTaskCount,
  controlEasyPanelTask,
  getEasyPanelTasks,
  isEasyPanelTaskAction,
  safeTaskId,
  taskCountsSummary,
  taskStatusLabel,
} from './easyPanelTasks'

afterEach(() => vi.restoreAllMocks())

const config = { baseUrl: 'http://192.168.1.10:8190', token: 'local-token' }

describe('Easy Panel mobile task queue API', () => {
  it('reads the queue snapshot with the RPG token header', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({
      version: 1,
      paused: false,
      auto_skip: true,
      selected_only: false,
      message: '',
      counts: { pending: 2, running: 1, completed: 3, error: 1, cancelled: 0, skipped: 0, total: 7 },
      running: null,
      items: [],
    }), { status: 200 }))

    const snapshot = await getEasyPanelTasks(config)

    expect(snapshot.counts.total).toBe(7)
    expect(fetchMock.mock.calls[0][0]).toBe('http://192.168.1.10:8190/api/rpg/tasks')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ headers: { 'X-RPG-Token': 'local-token' } })
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('local-token')
  })

  it('posts queue control actions and rejects unknown ones before any request', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({
      paused: true, counts: {}, items: [], message: '队列已暂停：当前任务跑完，不再投递新任务。',
    }), { status: 200 }))

    await controlEasyPanelTask(config, 'pause')
    await controlEasyPanelTask(config, 'select', { ids: ['task_0123456789abcdef'], selected: false })
    await controlEasyPanelTask(config, 'auto-skip', { value: false })

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://192.168.1.10:8190/api/rpg/tasks/control',
      'http://192.168.1.10:8190/api/rpg/tasks/control',
      'http://192.168.1.10:8190/api/rpg/tasks/control',
    ])
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      action: 'select', ids: ['task_0123456789abcdef'], selected: false,
    })
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({
      action: 'auto-skip', value: false,
    })

    await expect(controlEasyPanelTask(config, 'explode' as never)).rejects.toThrow('不支持的任务队列操作')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('checks duplicates with the built payload', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({
      duplicate: true,
      fingerprint: 'f'.repeat(64),
      duplicates: [{ generation_id: 'a'.repeat(32), created_at: 1730000000000 }],
    }), { status: 200 }))

    const result = await checkEasyPanelDuplicate(config, { model: 'wai.safetensors', seed: '1' })

    expect(result.duplicate).toBe(true)
    expect(fetchMock.mock.calls[0][0]).toBe('http://192.168.1.10:8190/api/rpg/generate-check')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      payload: { model: 'wai.safetensors', seed: '1' },
    })
    await expect(checkEasyPanelDuplicate(config, undefined as never)).rejects.toThrow('缺少生成参数')
  })
})

describe('Easy Panel mobile task helpers', () => {
  it('labels statuses and summarizes counts in Chinese', () => {
    expect(taskStatusLabel('running')).toBe('执行中')
    expect(taskStatusLabel('skipped')).toBe('已跳过')
    expect(taskStatusLabel('weird')).toBe('weird')
    expect(taskCountsSummary({
      pending: 1, running: 0, completed: 2, error: 1, cancelled: 0, skipped: 0, total: 4,
    })).toBe('排队中 1 · 执行中 0 · 已完成 2 · 失败 1 · 已取消 0 · 已跳过 0')
    expect(taskCountsSummary(undefined)).toBe('尚未读取任务队列')
    expect(cleanableTaskCount({
      pending: 1, running: 0, completed: 2, error: 1, cancelled: 1, skipped: 2, total: 7,
    })).toBe(4)
    expect(cleanableTaskCount(undefined)).toBe(0)
  })

  it('validates task ids and actions', () => {
    expect(safeTaskId('task_0123456789abcdef')).toBe('task_0123456789abcdef')
    expect(safeTaskId('  task_0123456789abcdef  ')).toBe('task_0123456789abcdef')
    expect(safeTaskId('bad id')).toBe('')
    expect(safeTaskId(null)).toBe('')
    expect(isEasyPanelTaskAction('cancel-current')).toBe(true)
    expect(isEasyPanelTaskAction('cancel-everything')).toBe(false)
  })
})
