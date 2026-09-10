import { useEffect, useMemo, useState } from 'react'
import type { EasyPanelWorkspace } from '../hooks/useEasyPanelWorkspace'
import { taskStatusLabel } from '../services/easyPanelTasks'
import type { EasyPanelTaskItem } from '../services/easyPanelTasks'

interface TaskCenterProps {
  workspace: EasyPanelWorkspace
  onClose: () => void
}

interface DuplicateProps {
  workspace: EasyPanelWorkspace
  onStillGenerate: () => void
  onOpenExisting: (generationId: string) => void
}

interface PickerProps {
  workspace: EasyPanelWorkspace
  onAdded: (projectId: string) => void
  onClose: () => void
}

/** 任务批处理控制：运行 / 暂停 / 取消当前 / 取消后续 / 只运行入选实验 / 清理失败任务。 */
export function EasyPanelTaskCenter({ workspace, onClose }: TaskCenterProps) {
  const snapshot = workspace.tasks
  const counts = snapshot?.counts
  const items = useMemo<EasyPanelTaskItem[]>(() => snapshot?.items ?? [], [snapshot?.items])

  return (
    <div className="epm-library-layer" role="dialog" aria-modal="true" aria-label="任务批处理控制">
      <button type="button" className="epm-library-backdrop" aria-label="关闭任务控制" onClick={onClose} />
      <section className="epm-library-dialog epm-task-dialog">
        <header className="epm-library-header">
          <div>
            <strong>任务批处理控制</strong>
            <p className="epm-hint">{workspace.taskSummary}</p>
          </div>
          <div className="epm-task-header-actions">
            <button type="button" className="epm-quiet-button" onClick={() => void workspace.refreshTasks()}>
              {workspace.tasksLoading ? '刷新中…' : '刷新'}
            </button>
            <button type="button" className="epm-quiet-button" onClick={onClose}>关闭</button>
          </div>
        </header>

        <div className="epm-task-controls">
          <button type="button" className="epm-secondary-button" disabled={!snapshot?.paused}
            onClick={() => void workspace.controlTask('run')}>▶ 运行</button>
          <button type="button" className="epm-secondary-button" disabled={snapshot?.paused !== false}
            onClick={() => void workspace.controlTask('pause')}>⏸ 暂停</button>
          <button type="button" className="epm-secondary-button"
            onClick={() => void workspace.controlTask('cancel-current')}>⛔ 取消当前</button>
          <button type="button" className="epm-secondary-button"
            onClick={() => void workspace.controlTask('cancel-pending')}>🚫 取消后续</button>
          <button type="button" className="epm-secondary-button" disabled={workspace.cleanableCount <= 0}
            onClick={() => void workspace.controlTask('clean-failed')}>🧹 清理失败任务</button>
          <button type="button" className="epm-secondary-button"
            onClick={() => void workspace.controlTask('clean-finished')}>🧽 清理已结束</button>
        </div>

        <label className="epm-task-switch">
          <input type="checkbox" checked={snapshot?.auto_skip !== false}
            onChange={(event) => void workspace.controlTask('auto-skip', { value: event.target.checked })} />
          <span>
            失败自动跳过
            <small>单个任务失败（例如显存不足）只标记它，队列继续跑后面的；关闭后失败会暂停队列。</small>
          </span>
        </label>
        <label className="epm-task-switch">
          <input type="checkbox" checked={snapshot?.selected_only === true}
            onChange={(event) => void workspace.controlTask('select-only', { value: event.target.checked })} />
          <span>
            只运行入选实验
            <small>只执行勾选的任务／实验项，其余自动跳过。</small>
          </span>
        </label>

        {workspace.tasksError ? <p className="epm-error-banner" role="alert">{workspace.tasksError}</p> : null}
        {workspace.tasksMessage ? <p className="epm-hint" role="status">{workspace.tasksMessage}</p> : null}

        <div className="epm-task-list">
          {items.length === 0 ? (
            <p className="epm-hint">
              队列为空。电脑端「发送队列」或单变量实验加入的任务会出现在这里，可随时暂停或取消。
            </p>
          ) : items.map((item) => (
            <article key={item.id} className={`epm-task-item is-${item.status}`}>
              <label className="epm-task-item-check">
                <input type="checkbox" checked={item.selected !== false}
                  onChange={(event) => void workspace.toggleTaskSelected(item.id, event.target.checked)} />
                <span className="epm-task-item-label">{item.label}</span>
              </label>
              <div className="epm-task-item-meta">
                <span className={`epm-task-badge is-${item.status}`}>{taskStatusLabel(item.status)}</span>
                {item.experiment_value ? <span className="epm-hint">{item.experiment_value}</span> : null}
                {item.error ? <span className="epm-task-error">{item.error}</span> : null}
              </div>
            </article>
          ))}
        </div>

        {counts && counts.total > items.length ? (
          <p className="epm-hint">仅显示前 {items.length} 条（共 {counts.total} 条）。</p>
        ) : null}
      </section>
    </div>
  )
}

/** 重复任务提示：仍然生成 / 取消重复任务 / 打开已有结果。 */
export function EasyPanelDuplicateLayer({ workspace, onStillGenerate, onOpenExisting }: DuplicateProps) {
  const duplicate = workspace.duplicate
  if (!duplicate || !duplicate.duplicates.length) return null
  const first = duplicate.duplicates[0]
  return (
    <div className="epm-library-layer" role="dialog" aria-modal="true" aria-label="重复任务提示">
      <button type="button" className="epm-library-backdrop" aria-label="取消重复任务"
        onClick={() => workspace.dismissDuplicate()} />
      <section className="epm-library-dialog epm-duplicate-dialog">
        <header className="epm-library-header">
          <strong>{workspace.duplicateTitle}</strong>
        </header>
        <p className="epm-hint">
          同样的模型、LoRA、提示词、seed 与采样参数已经生成过（共找到 {duplicate.duplicates.length} 条）。
        </p>
        <ul className="epm-duplicate-list">
          {duplicate.duplicates.map((entry) => (
            <li key={entry.generation_id}>
              <code>{entry.generation_id.slice(0, 12)}</code>
              {entry.created_at ? <span> · {new Date(entry.created_at).toLocaleString()}</span> : null}
              {entry.model ? <span> · {entry.model.split(/[\\/]/).pop()}</span> : null}
            </li>
          ))}
        </ul>
        <div className="epm-task-controls">
          <button type="button" className="epm-secondary-button" onClick={() => workspace.dismissDuplicate()}>
            取消重复任务
          </button>
          <button type="button" className="epm-secondary-button" onClick={() => onOpenExisting(first.generation_id)}>
            打开已有结果
          </button>
          <button type="button" className="epm-generate-button epm-task-still-button"
            onClick={() => { workspace.dismissDuplicate(); onStillGenerate() }}>
            仍然生成
          </button>
        </div>
      </section>
    </div>
  )
}

/** 从作品库详情「加入项目」打开的选择层。 */
export function EasyPanelProjectPickerLayer({ workspace, onAdded, onClose }: PickerProps) {
  const [projectId, setProjectId] = useState('')
  const [section, setSection] = useState('')

  useEffect(() => {
    setProjectId((current) => current || workspace.projects[0]?.project_id || '')
  }, [workspace.projects])

  const selected = workspace.projects.find((project) => project.project_id === projectId)
  const sections = selected?.sections ?? []
  const busy = workspace.projectsLoading

  return (
    <div className="epm-library-layer" role="dialog" aria-modal="true" aria-label="加入作品项目">
      <button type="button" className="epm-library-backdrop" aria-label="取消加入项目" onClick={onClose} />
      <section className="epm-library-dialog epm-project-picker">
        <header className="epm-library-header">
          <strong>加入作品项目</strong>
        </header>
        {workspace.projects.length === 0 ? (
          <p className="epm-hint">还没有项目：请先在「作品项目」里新建一个角色图集。</p>
        ) : (
          <>
            <label className="epm-field">
              <span>项目</span>
              <select value={projectId} onChange={(event) => { setProjectId(event.target.value); setSection('') }}>
                {workspace.projects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>
                    {project.name}（{project.item_count} 件）
                  </option>
                ))}
              </select>
            </label>
            <label className="epm-field">
              <span>分区</span>
              <select value={section} onChange={(event) => setSection(event.target.value)}>
                <option value="">（未分组）</option>
                {sections.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
          </>
        )}
        {workspace.projectError ? <p className="epm-error-banner" role="alert">{workspace.projectError}</p> : null}
        <div className="epm-task-controls">
          <button type="button" className="epm-secondary-button" onClick={onClose}>取消</button>
          <button type="button" className="epm-generate-button epm-task-still-button" disabled={!projectId || busy}
            onClick={async () => {
              const ok = await workspace.addGenerationToProject(projectId, workspace.pickerGenerationId, section)
              if (ok) {
                onAdded(projectId)
                onClose()
              }
            }}>
            加入项目
          </button>
        </div>
      </section>
    </div>
  )
}
