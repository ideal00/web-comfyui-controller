import { useState } from 'react'
import type { EasyPanelWorkspace } from '../hooks/useEasyPanelWorkspace'
import { projectLinkLabel } from '../services/easyPanelProjects'

interface ProjectCenterProps {
  workspace: EasyPanelWorkspace
  onClose: () => void
  onOpenGeneration: (generationId: string) => void
  /** 作品库已加载的缩略图（没有时显示占位）。 */
  thumbnailSources?: Record<string, string>
  /** 可关联的 Prompt 预设名（来自面板当前选择，可为空）。 */
  presetNames?: string[]
  currentLoras?: string[]
}

const LINK_KINDS = ['lora', 'preset', 'experiment', 'favorite_group'] as const

/** 作品项目：分区 + 项目内作品 + 关联资源（LoRA / Prompt 预设 / 实验 / 收藏组）。 */
export function EasyPanelProjectCenter({
  workspace, onClose, onOpenGeneration, thumbnailSources = {}, presetNames = [], currentLoras = [],
}: ProjectCenterProps) {
  const [newName, setNewName] = useState('')
  const [newSections, setNewSections] = useState('')
  const [linkKind, setLinkKind] = useState<string>('lora')
  const [linkRef, setLinkRef] = useState('')
  const detail = workspace.projectDetail
  const project = detail?.project

  return (
    <div className="epm-library-layer" role="dialog" aria-modal="true" aria-label="作品项目">
      <button type="button" className="epm-library-backdrop" aria-label="关闭作品项目" onClick={onClose} />
      <section className="epm-library-dialog epm-project-dialog">
        <header className="epm-library-header">
          <div>
            <strong>作品项目</strong>
            <p className="epm-hint">{workspace.projectMessage || '把散图整理成角色图集：分区、精选、关联资源。'}</p>
          </div>
          <div className="epm-task-header-actions">
            <button type="button" className="epm-quiet-button" onClick={() => void workspace.refreshProjects()}>
              {workspace.projectsLoading ? '刷新中…' : '刷新'}
            </button>
            <button type="button" className="epm-quiet-button" onClick={onClose}>关闭</button>
          </div>
        </header>

        {workspace.projectError ? <p className="epm-error-banner" role="alert">{workspace.projectError}</p> : null}

        <div className="epm-project-create">
          <label className="epm-field">
            <span>新建项目</span>
            <input value={newName} placeholder="例如：Luna 角色图集" onChange={(event) => setNewName(event.target.value)} />
          </label>
          <label className="epm-field">
            <span>分区（逗号分隔，可留空使用默认）</span>
            <input value={newSections} placeholder="基准角色, 日常服装, 战斗服装, 废墟场景, 夜景, 最终精选"
              onChange={(event) => setNewSections(event.target.value)} />
          </label>
          <button type="button" className="epm-secondary-button" disabled={!newName.trim()}
            onClick={async () => {
              const ok = await workspace.createProject(newName, newSections.trim() || undefined)
              if (ok) { setNewName(''); setNewSections('') }
            }}>
            ＋ 新建项目
          </button>
        </div>

        <div className="epm-project-list">
          {workspace.projects.length === 0 ? (
            <p className="epm-hint">还没有项目。输入名称后点「＋ 新建项目」开始做一个角色作品。</p>
          ) : workspace.projects.map((entry) => (
            <button key={entry.project_id} type="button"
              className={`epm-project-chip${project?.project_id === entry.project_id ? ' is-on' : ''}`}
              onClick={() => void workspace.openProject(entry.project_id)}>
              <b>{entry.name}</b>
              <small>{entry.item_count} 件</small>
            </button>
          ))}
        </div>

        {project ? (
          <div className="epm-project-detail">
            <div className="epm-project-detail-head">
              <div>
                <strong>{project.name}</strong>
                <p className="epm-hint">{(detail?.total ?? 0)} 件作品 · 分区 {project.sections.length} 个</p>
              </div>
              <div className="epm-task-controls">
                <button type="button" className="epm-quiet-button"
                  onClick={async () => {
                    const name = globalThis.prompt('新的项目名称', project.name)
                    if (name && name.trim() && name.trim() !== project.name) await workspace.renameProject(name)
                  }}>改名</button>
                <button type="button" className="epm-quiet-button"
                  onClick={async () => {
                    const text = globalThis.prompt('分区（逗号分隔，顺序即显示顺序）', project.sections.join(', '))
                    if (text && text.trim()) await workspace.updateProjectSections(text)
                  }}>编辑分区</button>
                <button type="button" className="epm-danger-button"
                  onClick={async () => {
                    if (globalThis.confirm(`删除项目「${project.name}」？项目里的作品不会被删除。`)) {
                      await workspace.deleteProject()
                    }
                  }}>删除项目</button>
              </div>
            </div>

            <div className="epm-project-links">
              {(detail?.links ? LINK_KINDS : LINK_KINDS).map((kind) => (
                <div key={kind} className="epm-project-link-row">
                  <span className="epm-hint">{projectLinkLabel(kind)}</span>
                  {(detail?.links?.[kind] ?? []).length === 0 ? <span className="epm-hint">未关联</span> : null}
                  {(detail?.links?.[kind] ?? []).map((link) => (
                    <span key={link.link_id} className="epm-chip">
                      {link.label || link.ref}
                      <button type="button" className="epm-quiet-button"
                        onClick={() => void workspace.removeProjectLink(link.link_id)}>×</button>
                    </span>
                  ))}
                </div>
              ))}
              <div className="epm-project-link-add">
                <select value={linkKind} onChange={(event) => setLinkKind(event.target.value)}>
                  {LINK_KINDS.map((kind) => <option key={kind} value={kind}>{projectLinkLabel(kind)}</option>)}
                </select>
                <input value={linkRef} placeholder="关联内容" onChange={(event) => setLinkRef(event.target.value)}
                  list={linkKind === 'lora' ? 'epmProjectLoraOptions' : linkKind === 'preset' ? 'epmProjectPresetOptions' : undefined} />
                <datalist id="epmProjectLoraOptions">
                  {currentLoras.map((name) => <option key={name} value={name} />)}
                </datalist>
                <datalist id="epmProjectPresetOptions">
                  {presetNames.map((name) => <option key={name} value={name} />)}
                </datalist>
                <button type="button" className="epm-secondary-button" disabled={!linkRef.trim()}
                  onClick={async () => {
                    const ok = await workspace.addProjectLink(linkKind, linkRef.trim(), linkRef.trim())
                    if (ok) setLinkRef('')
                  }}>关联</button>
              </div>
            </div>

            {(detail?.sections ?? []).map((section) => (
              <section key={section.name || 'ungrouped'} className="epm-project-section">
                <header>
                  <strong>{section.name || '（未分组）'}</strong>
                  <span className="epm-hint">{section.items.length} 件</span>
                </header>
                {section.items.length === 0 ? <p className="epm-hint">这个分区还是空的。</p> : (
                  <div className="epm-project-items">
                    {section.items.map((item) => {
                      const generationId = String(item.generation?.generation_id ?? '')
                      const thumbnail = generationId ? thumbnailSources[generationId] : ''
                      return (
                        <article key={item.item_id} className="epm-project-item">
                          {thumbnail
                            ? <img src={thumbnail} alt="" onClick={() => generationId && onOpenGeneration(generationId)} />
                            : <div className="epm-project-item-empty" onClick={() => generationId && onOpenGeneration(generationId)}>
                                {item.generation?.model ? String(item.generation.model).split(/[\\/]/).pop() : '作品'}
                              </div>}
                          <p className="epm-hint">
                            seed {String(item.generation?.seed ?? '—')} · {item.note || '未备注'}
                          </p>
                          <select value={item.section} onChange={(event) => void workspace.moveProjectItem(item.item_id, event.target.value)}>
                            <option value="">（未分组）</option>
                            {project.sections.map((name) => <option key={name} value={name}>{name}</option>)}
                          </select>
                          <div className="epm-task-controls">
                            <button type="button" className="epm-quiet-button"
                              onClick={() => generationId && void workspace.setProjectCover(generationId)}>设为封面</button>
                            <button type="button" className="epm-quiet-button"
                              onClick={() => void workspace.removeProjectItem(item.item_id)}>移出</button>
                          </div>
                        </article>
                      )
                    })}
                  </div>
                )}
              </section>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  )
}
