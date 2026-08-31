import { AlertTriangle, ArrowLeft, ArrowUpRight, BookOpen, CheckCircle2, ChevronDown, Download, GitBranch, Image as ImageIcon, LayoutDashboard, LoaderCircle, Maximize2, RefreshCw, Server, ShieldCheck, Sparkles, Wifi, X, XCircle } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { isControllerBusy, reduceEasyPanelControllerInteraction } from '../lib/easyPanelController'
import { explainSnapshot, shouldFocusPromptAfterSnapshotRestore, snapshotPromptSourceLabels } from '../lib/easyPanelSnapshot'
import { useEasyPanelController } from '../hooks/useEasyPanelController'
import { openAdvancedPanel } from '../services/easyPanelAdvanced'
import type { EasyPanelGenerationArtifact, EasyPanelGenerationDetail, EasyPanelGenerationSummary } from '../services/easyPanelLibrary'

export default function EasyPanelMobileApp() {
  const controller = useEasyPanelController()
  const [advancedOpen, setAdvancedOpen] = useState(true)
  const [advancedOpening, setAdvancedOpening] = useState(false)
  const [advancedError, setAdvancedError] = useState('')
  const [libraryOpen, setLibraryOpen] = useState(false)
  const promptEditorRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const previousTitle = document.title
    document.title = 'Easy Panel Mobile'
    return () => { document.title = previousTitle }
  }, [])

  const models = useMemo(() => controller.models.slice().sort((left, right) => left.localeCompare(right)), [controller.models])
  const selectedModel = controller.settings.model.trim()
  const modelOptions = useMemo(() => selectedModel && !models.includes(selectedModel)
    ? [selectedModel, ...models]
    : models, [models, selectedModel])
  const working = isControllerBusy(controller.status)
  const hasConnection = controller.connectionMessage.startsWith('已连接') || controller.connectionMessage.startsWith('已读取')
  const canGenerate = !working
    && Boolean(controller.settings.baseUrl.trim())
    && Boolean(controller.settings.token.trim())
    && Boolean(controller.settings.prompt.trim())
  const restoredExplanation = useMemo(
    () => controller.restoredSnapshot ? explainSnapshot(controller.restoredSnapshot) : undefined,
    [controller.restoredSnapshot],
  )

  function patchSettings(patch: Partial<typeof controller.settings>) {
    const interaction = reduceEasyPanelControllerInteraction(controller.settings, { type: 'settings-changed', patch })
    controller.setSettings(interaction.settings)
  }

  function handleGenerateClick() {
    const interaction = reduceEasyPanelControllerInteraction(controller.settings, { type: 'generate-requested' })
    if (interaction.shouldSubmit) void controller.generate()
  }

  async function restoreSnapshot(id: string, mode: 'full' | 'seed-only' | 'continue-editing') {
    const restored = await controller.restoreSnapshot(id, mode)
    if (!restored || !shouldFocusPromptAfterSnapshotRestore(mode)) return
    window.setTimeout(() => {
      const editor = promptEditorRef.current
      if (!editor) return
      editor.scrollIntoView({ behavior: 'smooth', block: 'center' })
      editor.focus()
    }, 0)
  }

  async function openFullEasyPanel() {
    setAdvancedError('')
    setAdvancedOpening(true)
    try {
      await openAdvancedPanel(controller.settings.baseUrl, controller.settings.token)
    } catch (caught) {
      setAdvancedError(caught instanceof Error ? caught.message : '无法打开高级面板。')
    } finally {
      setAdvancedOpening(false)
    }
  }

  function openLibrary() {
    setLibraryOpen(true)
    void controller.refreshLibrary()
  }

  return (
    <div className="easy-panel-mobile-shell">
      <header className="epm-topbar">
        <div className="epm-brand-block">
          <div className="epm-brand-mark"><Sparkles size={18} /></div>
          <div>
            <span className="epm-eyebrow">EASY PANEL</span>
            <h1>Mobile Studio</h1>
            <p>手机配置 · 电脑 GPU 出图</p>
          </div>
        </div>
        <div className={`epm-connection-badge ${hasConnection ? 'connected' : ''}`}>
          <span className="epm-connection-dot" />
          {hasConnection ? '已连接电脑' : '未连接'}
        </div>
      </header>

      <main className="epm-main">
        <section className="epm-hero-card">
          <div>
            <span className="epm-eyebrow">PRIVATE GPU BRIDGE</span>
            <h2>把电脑上的生成能力带到手机</h2>
            <p>手机只负责配置和查看结果，模型仍运行在电脑 ComfyUI。适合局域网，也支持 Tailscale 私网连接。</p>
          </div>
          <div className="epm-hero-icon"><Server size={28} /></div>
        </section>

        <section className="epm-mode-switch" aria-label="工作模式">
          <div className="epm-mode-option active" aria-current="page">
            <span className="epm-mode-kicker">当前模式 A</span>
            <strong>快速生图</strong>
            <small>手机原生配置 · 电脑 GPU 执行</small>
          </div>
          <button
            type="button"
            className="epm-mode-option epm-mode-action"
            onClick={() => void openFullEasyPanel()}
            disabled={!controller.hydrated || !controller.settings.baseUrl.trim() || advancedOpening}
          >
            <span className="epm-mode-kicker">模式 B</span>
            <strong><LayoutDashboard size={16} />高级面板</strong>
            <small>打开电脑端完整 Easy Panel <ArrowUpRight size={13} /></small>
          </button>
          <button
            type="button"
            className="epm-mode-option epm-mode-action"
            onClick={openLibrary}
            disabled={!controller.hydrated || !controller.settings.baseUrl.trim() || controller.libraryLoading}
          >
            <span className="epm-mode-kicker">作品管理</span>
            <strong><BookOpen size={16} />作品库</strong>
            <small>浏览历史、谱系与恢复参数</small>
          </button>
        </section>
        {advancedError && <div className="epm-advanced-error" role="alert"><XCircle size={15} /><span>{advancedError}</span></div>}

        <section className="epm-card epm-connection-card">
          <div className="epm-section-heading">
            <div>
              <span className="epm-section-kicker">01 · CONNECTION</span>
              <h2>连接电脑</h2>
            </div>
            <Wifi size={20} />
          </div>
          <label className="epm-field">
            <span>Easy Panel 地址</span>
            <input
              value={controller.settings.baseUrl}
              onChange={(event) => patchSettings({ baseUrl: event.target.value })}
              placeholder="http://电脑IP:8190"
              inputMode="url"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              aria-describedby="epm-address-help"
            />
          </label>
          <p id="epm-address-help" className="epm-help">支持局域网 IP、Tailscale 的 100.x.x.x IP，或 MagicDNS 主机名。</p>
          <label className="epm-field">
            <span>RPG Token</span>
            <input
              type="password"
              value={controller.settings.token}
              onChange={(event) => patchSettings({ token: event.target.value })}
              placeholder="粘贴电脑端 Token 内容"
              autoCapitalize="none"
              autoCorrect="off"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <div className="epm-action-row">
            <button type="button" className="epm-secondary-button" onClick={() => void controller.testConnection()} disabled={working}>
              {controller.status === 'checking' ? <LoaderCircle size={16} className="epm-spin" /> : <ShieldCheck size={16} />}
              {controller.status === 'checking' ? '测试中' : '测试连接'}
            </button>
            <button type="button" className="epm-quiet-button" onClick={() => void controller.refreshModels()} disabled={working || controller.modelsLoading}>
              {controller.modelsLoading ? <LoaderCircle size={15} className="epm-spin" /> : <RefreshCw size={15} />}
              读取模型
            </button>
          </div>
          <div className={`epm-connection-message ${hasConnection ? 'success' : controller.status === 'error' ? 'failure' : ''}`} aria-live="polite">
            {hasConnection ? <CheckCircle2 size={15} /> : controller.status === 'error' ? <XCircle size={15} /> : <Wifi size={15} />}
            <span>{controller.connectionMessage}</span>
          </div>
          <p className="epm-security-note"><ShieldCheck size={14} />Tailscale 是私网通道；电脑端 Easy Panel 必须正在运行，不要把 8190 端口直接暴露到公网。</p>
        </section>

        <section className="epm-card">
          <div className="epm-section-heading">
            <div>
              <span className="epm-section-kicker">02 · PROMPT</span>
              <h2>描述画面</h2>
            </div>
            <ImageIcon size={20} />
          </div>
          <label className="epm-field">
            <span>正向提示词 <small>必填</small></span>
            <textarea
              ref={promptEditorRef}
              value={controller.settings.prompt}
              onChange={(event) => patchSettings({ prompt: event.target.value })}
              placeholder="例如：anime illustration, a quiet bookstore at sunset, warm light, detailed background"
              rows={5}
              maxLength={1200}
            />
            <em>{controller.settings.prompt.length} / 1200</em>
          </label>
          <label className="epm-field">
            <span>负向提示词 <small>可选</small></span>
            <textarea
              value={controller.settings.negative}
              onChange={(event) => patchSettings({ negative: event.target.value })}
              placeholder="留空则使用电脑端 Easy Panel 的默认负面词"
              rows={3}
              maxLength={1600}
            />
            <em>{controller.settings.negative.length} / 1600</em>
          </label>
        </section>

        <section className="epm-card">
          <button type="button" className="epm-section-toggle" onClick={() => setAdvancedOpen((value) => !value)} aria-expanded={advancedOpen}>
            <span>
              <span className="epm-section-kicker">03 · PARAMETERS</span>
              <strong>生成参数</strong>
            </span>
            <span className={`epm-toggle-chevron ${advancedOpen ? 'open' : ''}`}>⌄</span>
          </button>
          {advancedOpen && <div className="epm-parameter-body">
            <label className="epm-field">
              <span>Checkpoint <small>从电脑端实际模型列表选择</small></span>
              <select
                value={controller.settings.model}
                onChange={(event) => patchSettings({ model: event.target.value })}
                disabled={controller.modelsLoading && modelOptions.length === 0}
                aria-label="Checkpoint 模型"
              >
                <option value="">自动选择（Easy Panel）</option>
                {modelOptions.map((model) => <option key={model} value={model}>{model}{model === selectedModel && !models.includes(model) ? '（当前保存）' : ''}</option>)}
              </select>
              <small className={`epm-model-status ${controller.modelsError ? 'error' : controller.models.length ? 'success' : ''}`} role="status">
                {controller.modelsLoading ? '正在读取模型列表…' : controller.modelsError || controller.modelsMessage}
              </small>
            </label>
            <div className="epm-quality-block">
              <span className="epm-field-label">质量档位</span>
              <div className="epm-segmented-control" role="group" aria-label="质量档位">
                {([
                  ['fast', '快速', '较少采样，适合预览'],
                  ['balanced', '平衡', '速度和质量均衡'],
                  ['detailed', '细致', '更多采样，耗时更长'],
                ] as const).map(([value, label, hint]) => (
                  <button type="button" key={value} className={controller.settings.quality === value ? 'active' : ''} onClick={() => patchSettings({ quality: value })} title={hint}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div className="epm-size-grid">
              <label className="epm-field">
                <span>宽度</span>
                <input type="number" min={512} max={1920} step={64} value={controller.settings.width} onChange={(event) => patchSettings({ width: Number(event.target.value) })} />
              </label>
              <label className="epm-field">
                <span>高度</span>
                <input type="number" min={512} max={1920} step={64} value={controller.settings.height} onChange={(event) => patchSettings({ height: Number(event.target.value) })} />
              </label>
            </div>
            <label className="epm-field">
              <span>Seed <small>留空则随机</small></span>
              <input
                type="text"
                inputMode="numeric"
                value={controller.settings.seed}
                onChange={(event) => patchSettings({ seed: event.target.value })}
                placeholder="留空随机"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
              />
            </label>
            <label className="epm-field">
              <span>轮询间隔 <small>电脑端任务状态查询</small></span>
              <input type="number" min={800} max={10000} step={100} value={controller.settings.pollIntervalMs} onChange={(event) => patchSettings({ pollIntervalMs: Number(event.target.value) })} />
            </label>
            {controller.capabilities && <p className="epm-capability-note">服务器 API v{String(controller.capabilities.api_version ?? 2)} · 支持异步任务、幂等提交和任务恢复</p>}
          </div>}
        </section>

        <section className="epm-card epm-snapshot-card">
          <div className="epm-section-heading">
            <div>
              <span className="epm-section-kicker">04 · HISTORY</span>
              <h2>历史快照</h2>
            </div>
            <button
              type="button"
              className="epm-quiet-button epm-inline-button"
              onClick={() => void controller.refreshSnapshots()}
              disabled={controller.snapshotsLoading || working || !controller.settings.baseUrl.trim() || !controller.settings.token.trim()}
            >
              {controller.snapshotsLoading ? <LoaderCircle size={15} className="epm-spin" /> : <RefreshCw size={15} />}
              刷新
            </button>
          </div>
          <p className="epm-help epm-snapshot-message">{controller.snapshotsMessage}</p>
          {controller.snapshotsError && <div className="epm-error-banner" role="alert"><AlertTriangle size={16} /><span>{controller.snapshotsError}</span></div>}
          {controller.snapshots.length ? <div className="epm-snapshot-list">
            {controller.snapshots.map((item) => <article className="epm-snapshot-item" key={item.id}>
              <div className="epm-snapshot-head">
                <strong>{item.label || item.model || '生成快照'}</strong>
                <small>{formatSnapshotTime(item.createdAt)}</small>
              </div>
              <div className="epm-snapshot-meta">
                {item.model || '自动模型'} · seed {item.seed == null ? '?' : String(item.seed)} · {item.width || '?'}×{item.height || '?'} · {item.quality || '自定义'}
              </div>
              <div className="epm-snapshot-meta">
                {item.characterCount} 个角色 · {item.loraCount} 个 LoRA · {item.outputCount} 个输出 · schema v{item.schemaVersion}
              </div>
              {item.sourceSections.length > 0 && <div className="epm-snapshot-sources">来源分区：{item.sourceSections.join('、')}</div>}
              <div className="epm-snapshot-actions">
                <button type="button" className="epm-secondary-button" onClick={() => void restoreSnapshot(item.id, 'full')} disabled={controller.snapshotsLoading || working}>完整恢复</button>
                <button type="button" className="epm-quiet-button" onClick={() => void controller.restoreSnapshot(item.id, 'seed-only')} disabled={controller.snapshotsLoading || working}>只换 Seed</button>
                <button type="button" className="epm-quiet-button" onClick={() => void restoreSnapshot(item.id, 'continue-editing')} disabled={controller.snapshotsLoading || working}>继续编辑并聚焦</button>
              </div>
            </article>)}
          </div> : <div className="epm-snapshot-empty">刷新后从电脑端读取历史；列表是服务器摘要，完整内容只在点击恢复时读取。</div>}
          {controller.restoredSnapshot && <div className="epm-restored-snapshot" role="status">
            <div className="epm-restored-heading">
              <strong>当前附加快照高级配置</strong>
              <button
                type="button"
                className="epm-quiet-button"
                onClick={controller.clearSnapshotAdvancedConfig}
                disabled={working}
              >
                解除快照高级配置 / 转为普通生图
              </button>
            </div>
            <span>{snapshotPromptSourceLabels(controller.restoredSnapshot).join(' · ') || '已保留快照来源追踪'}。当前生成会复用该快照的 LoRA、采样、区域和增强配置，直到你解除。</span>
            <span>完整恢复会附加全部快照配置；只换 Seed 只改变 Seed；继续编辑保留附加配置并允许修改当前可见字段。</span>
            {restoredExplanation && <details className="epm-snapshot-explanation">
              <summary>查看只读分层解释（不会改写提示词）</summary>
              <div className="epm-explanation-grid">
                <div>
                  <strong>用户输入来源</strong>
                  <span>{Object.entries(restoredExplanation.sourceSections).map(([key, value]) => `${key}: ${value}`).join(' · ') || '快照未记录用户分区'}</span>
                  <small>{restoredExplanation.userInputSources.map((item) => `${item.label}: ${item.terms.join(', ')}`).join('；') || '未记录独立用户来源条目'}</small>
                </div>
                <div>
                  <strong>可靠 LoRA trigger 来源</strong>
                  <span>{restoredExplanation.loraTriggerSources.map((item) => `${item.name}${item.role ? `（${item.role}）` : ''}: ${item.trigger}`).join('；') || '快照未记录可靠 trigger'}</span>
                  <small>最终实际注入：{restoredExplanation.triggerTerms.join(', ') || '无'}</small>
                </div>
                <div>
                  <strong>模型 profile / 质量策略</strong>
                  <span>{formatExplanationRecord(restoredExplanation.modelStrategy) || '快照未记录 profile'}</span>
                </div>
                <div>
                  <strong>自动注入开关</strong>
                  <span>{formatExplanationRecord(restoredExplanation.automation) || '快照未记录自动注入开关'}</span>
                </div>
                <div>
                  <strong>采样与变化原因</strong>
                  <span>{formatExplanationRecord(restoredExplanation.sampling.settings) || '快照未记录采样值'}</span>
                  <small>{formatExplanationReasons(restoredExplanation.sampling.reasons) || '未记录采样变化原因'}</small>
                </div>
                <div>
                  <strong>去重 / 覆盖 / 冲突诊断</strong>
                  <span>{restoredExplanation.overridden ? '已启用手动最终文本覆盖。' : '未启用手动最终文本覆盖。'} {formatExplanationRecord(restoredExplanation.deduplication) || '未记录去重统计'}</span>
                  <small>{restoredExplanation.diagnostics.map((item) => `${displayExplanationValue(item.code)}：${displayExplanationValue(item.message || item.title)}`).join('；') || '无冲突诊断'}</small>
                  {restoredExplanation.warnings.length > 0 && <small>警告：{restoredExplanation.warnings.join('；')}</small>}
                  {restoredExplanation.errors.length > 0 && <small>错误：{restoredExplanation.errors.join('；')}</small>}
                </div>
                <div className="epm-explanation-final">
                  <strong>最终 positive</strong>
                  <pre>{restoredExplanation.finalPositive || '（空）'}</pre>
                </div>
                <div className="epm-explanation-final">
                  <strong>最终 negative</strong>
                  <pre>{restoredExplanation.finalNegative || '（空）'}</pre>
                </div>
              </div>
            </details>}
          </div>}
        </section>

        {controller.pendingJob && controller.status === 'error' && <section className="epm-resume-card">
          <div className="epm-resume-icon"><AlertTriangle size={20} /></div>
          <div className="epm-resume-copy">
            <strong>检测到未完成任务</strong>
            <span>任务已保存在本机，恢复时会继续使用相同 requestId，避免重复生图。</span>
            <small>{controller.pendingJob.jobId ? `任务 ${controller.pendingJob.jobId.slice(0, 12)}…` : '提交结果尚未确认'}</small>
          </div>
          <div className="epm-resume-actions">
            <button type="button" className="epm-secondary-button" onClick={() => void controller.recoverPending()} disabled={working}><RefreshCw size={16} />恢复任务</button>
            <button type="button" className="epm-quiet-button" onClick={() => void controller.clearPending()} disabled={working}>清除</button>
          </div>
        </section>}

        <section className="epm-result-card">
          <div className="epm-result-heading">
            <div>
              <span className="epm-section-kicker">05 · RESULT</span>
              <h2>生成结果</h2>
            </div>
            {controller.status !== 'idle' && <span className={`epm-status-pill ${controller.status}`}><StatusIcon status={controller.status} />{controller.statusLabel}</span>}
          </div>
          {controller.imageSource ? <div className="epm-image-frame">
            <img src={controller.imageSource} alt={controller.image?.filename || 'Easy Panel 生成结果'} />
            <div className="epm-image-overlay"><span>{controller.image?.filename}</span></div>
          </div> : <div className="epm-empty-result">
            <div className="epm-empty-result-icon"><ImageIcon size={30} /></div>
            <strong>你的下一张图会出现在这里</strong>
            <span>填写提示词后点击底部按钮开始生成。</span>
          </div>}
          {controller.error && <div className="epm-error-banner" role="alert"><AlertTriangle size={16} /><span>{controller.error}</span></div>}
          {controller.image && <div className="epm-result-actions">
            <button type="button" className="epm-secondary-button" onClick={() => void controller.downloadCurrent()} disabled={controller.downloadLoading}>
              {controller.downloadLoading ? <LoaderCircle size={16} className="epm-spin" /> : <Download size={16} />}
              {controller.downloadLoading ? '保存中' : '下载图片'}
            </button>
            <button type="button" className="epm-quiet-button" onClick={() => void controller.clearImage()}>清除结果</button>
          </div>}
          {controller.downloadMessage && <p className={`epm-download-message ${controller.downloadMessage.includes('失败') ? 'failure' : 'success'}`} role="status">{controller.downloadMessage}</p>}
        </section>
      </main>

      {controller.pendingDerivation && <div className="epm-pending-derivation" role="status" aria-live="polite">
        <span>将从作品 {controller.pendingDerivation.parentGenerationId.slice(0, 10)}… 派生（{controller.pendingDerivation.operation}）；下一次生成会记录父子谱系。</span>
        <button type="button" className="epm-quiet-button" onClick={controller.clearPendingDerivation}>取消派生关联</button>
      </div>}
      <footer className="epm-submit-bar">
        <div className="epm-submit-hint">
          <span className="epm-submit-dot" />
          <span>{working ? `${controller.statusLabel} · 请保持电脑端服务运行` : '任务会在电脑 GPU 上执行'}</span>
        </div>
        <button type="button" className="epm-generate-button" onClick={handleGenerateClick} disabled={!canGenerate}>
          {working ? <LoaderCircle size={20} className="epm-spin" /> : <Sparkles size={20} />}
          {working ? controller.statusLabel : '生成图片'}
        </button>
      </footer>
      {libraryOpen && <EasyPanelLibraryDialog controller={controller} onClose={() => setLibraryOpen(false)} />}
    </div>
  )
}

function EasyPanelLibraryDialog({ controller, onClose }: {
  controller: ReturnType<typeof useEasyPanelController>
  onClose: () => void
}) {
  const detail = controller.libraryDetail
  const [viewerArtifact, setViewerArtifact] = useState<EasyPanelGenerationArtifact>()
  const [viewerSource, setViewerSource] = useState('')
  const [viewerLoading, setViewerLoading] = useState(false)
  const [viewerError, setViewerError] = useState('')
  const viewerRequestRef = useRef(0)
  const viewerSourceRef = useRef('')

  useEffect(() => () => {
    viewerRequestRef.current += 1
    if (viewerSourceRef.current) URL.revokeObjectURL(viewerSourceRef.current)
  }, [])

  useEffect(() => {
    if (!viewerArtifact) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeViewer()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [viewerArtifact])

  function clearViewerSource() {
    if (viewerSourceRef.current) URL.revokeObjectURL(viewerSourceRef.current)
    viewerSourceRef.current = ''
    setViewerSource('')
  }

  function closeViewer() {
    viewerRequestRef.current += 1
    clearViewerSource()
    setViewerArtifact(undefined)
    setViewerLoading(false)
    setViewerError('')
  }

  async function openOriginal(artifact: EasyPanelGenerationArtifact) {
    if (!artifact.url || artifact.exists === false || viewerLoading) return
    const requestNumber = viewerRequestRef.current + 1
    viewerRequestRef.current = requestNumber
    clearViewerSource()
    setViewerArtifact(artifact)
    setViewerLoading(true)
    setViewerError('')
    try {
      const blob = await controller.loadLibraryArtifactPreview(artifact)
      const source = URL.createObjectURL(blob)
      if (viewerRequestRef.current !== requestNumber) {
        URL.revokeObjectURL(source)
        return
      }
      viewerSourceRef.current = source
      setViewerSource(source)
    } catch (caught) {
      if (viewerRequestRef.current === requestNumber) {
        setViewerError(caught instanceof Error ? caught.message : '原图读取失败，请稍后重试。')
      }
    } finally {
      if (viewerRequestRef.current === requestNumber) setViewerLoading(false)
    }
  }

  async function restore(mode: 'reproduce' | 'seed-variant' | 'continue-edit') {
    const restored = await controller.restoreLibraryGeneration(mode)
    if (restored) onClose()
  }

  return (
    <div className="epm-library-layer" role="dialog" aria-modal="true" aria-label="作品库">
      <button type="button" className="epm-library-backdrop" onClick={onClose} aria-label="关闭作品库" />
      <section className="epm-library-dialog">
        <header className="epm-library-header">
          <div>
            <span className="epm-section-kicker">CREATIVE LIBRARY</span>
            <h2>作品库</h2>
            <p>{detail ? '只读查看作品参数、输出和谱系' : '历史生成记录与可恢复参数'}</p>
          </div>
          <button type="button" className="epm-library-close" onClick={onClose} title="关闭"><X size={20} /></button>
        </header>
        {detail ? <LibraryDetail
          detail={detail}
          lineage={controller.libraryLineage}
          thumbnailSource={controller.libraryThumbnailSources[detail.generation_id]}
          downloadLoading={controller.libraryDownloadLoading}
          previewLoading={viewerLoading ? viewerArtifact?.artifact_id || '' : ''}
          onBack={controller.clearLibraryDetail}
          onRestore={restore}
          onPreview={(artifact) => void openOriginal(artifact)}
          onDownload={(artifact) => void controller.downloadLibraryArtifact(artifact)}
        /> : <LibraryList
          items={controller.library}
          thumbnailSources={controller.libraryThumbnailSources}
          total={controller.libraryTotal}
          hasMore={controller.libraryHasMore}
          loading={controller.libraryLoading}
          error={controller.libraryError}
          message={controller.libraryMessage}
          onRefresh={() => void controller.refreshLibrary()}
          onLoadMore={() => void controller.loadMoreLibrary()}
          onOpen={(id) => void controller.openLibraryGeneration(id)}
        />}
        {controller.libraryDownloadMessage && <p className={`epm-library-message ${controller.libraryDownloadMessage.includes('失败') ? 'failure' : 'success'}`} role="status">{controller.libraryDownloadMessage}</p>}
      </section>
      {viewerArtifact && <LibraryImageViewer
        artifact={viewerArtifact}
        source={viewerSource}
        loading={viewerLoading}
        error={viewerError}
        downloadLoading={controller.libraryDownloadLoading}
        onClose={closeViewer}
        onDownload={(artifact) => void controller.downloadLibraryArtifact(artifact)}
      />}
    </div>
  )
}

function LibraryList({ items, thumbnailSources, total, hasMore, loading, error, message, onRefresh, onLoadMore, onOpen }: {
  items: EasyPanelGenerationSummary[]
  thumbnailSources: Record<string, string>
  total: number
  hasMore: boolean
  loading: boolean
  error: string
  message: string
  onRefresh: () => void
  onLoadMore: () => void
  onOpen: (id: string) => void
}) {
  return (
    <div className="epm-library-content">
      <div className="epm-library-toolbar">
        <span>{message}</span>
        <button type="button" className="epm-quiet-button epm-inline-button" onClick={onRefresh} disabled={loading}>
          {loading ? <LoaderCircle size={15} className="epm-spin" /> : <RefreshCw size={15} />}刷新
        </button>
      </div>
      {error && <div className="epm-error-banner" role="alert"><AlertTriangle size={16} /><span>{error}</span></div>}
      {items.length ? <>
        <div className="epm-library-list">
          {items.map((item) => <button type="button" className="epm-library-item" key={item.generation_id} onClick={() => onOpen(item.generation_id)}>
            <div className="epm-library-thumb">
              {thumbnailSources[item.generation_id]
                ? <img src={thumbnailSources[item.generation_id]} alt="" />
                : <ImageIcon size={24} />}
            </div>
            <div className="epm-library-item-copy">
              <div className="epm-library-item-heading"><strong>{item.model || '自动模型'}</strong><small>{formatLibraryTime(item.created_at)}</small></div>
              <span>{libraryOperationLabel(item.operation)} · {libraryStatusLabel(item.status)} · seed {item.seed == null ? '?' : String(item.seed)}</span>
              <small>{item.width || '?'}×{item.height || '?'} · {item.artifact_count} 个输出 · 父 {item.parent_count} / 子 {item.child_count}</small>
            </div>
          </button>)}
        </div>
        {hasMore && <button type="button" className="epm-library-load-more" onClick={onLoadMore} disabled={loading}>
          {loading ? <LoaderCircle size={15} className="epm-spin" /> : <ChevronDown size={15} />}
          {loading ? '正在读取…' : `加载更多${total > items.length ? `（还剩 ${total - items.length} 张）` : ''}`}
        </button>}
      </> : <div className="epm-library-empty"><BookOpen size={28} /><strong>暂无作品记录</strong><span>新任务完成后会进入作品库；也可在电脑端执行重建索引。</span></div>}
    </div>
  )
}

function LibraryDetail({ detail, lineage, thumbnailSource, downloadLoading, previewLoading, onBack, onRestore, onPreview, onDownload }: {
  detail: EasyPanelGenerationDetail
  lineage?: ReturnType<typeof useEasyPanelController>['libraryLineage']
  thumbnailSource?: string
  downloadLoading: string
  previewLoading: string
  onBack: () => void
  onRestore: (mode: 'reproduce' | 'seed-variant' | 'continue-edit') => void
  onPreview: (artifact: EasyPanelGenerationDetail['artifacts'][number]) => void
  onDownload: (artifact: EasyPanelGenerationDetail['artifacts'][number]) => void
}) {
  const previewArtifact = detail.artifacts.find((artifact) => artifact.exists !== false && Boolean(artifact.url))

  return (
    <div className="epm-library-content">
      <div className="epm-library-detail-toolbar">
        <button type="button" className="epm-quiet-button epm-inline-button" onClick={onBack}><ArrowLeft size={15} />返回列表</button>
        <span>{libraryOperationLabel(detail.operation)} · {libraryStatusLabel(detail.status)}</span>
      </div>
      <div className="epm-library-detail-grid">
        {previewArtifact ? <button type="button" className="epm-library-detail-preview" onClick={() => onPreview(previewArtifact)} aria-label="点击查看原图">
          {thumbnailSource ? <img src={thumbnailSource} alt="作品缩略图，点击查看原图" /> : <ImageIcon size={34} />}
          <span>{previewLoading === previewArtifact.artifact_id ? <LoaderCircle size={13} className="epm-spin" /> : <Maximize2 size={13} />}点击查看原图</span>
        </button> : <div className="epm-library-detail-preview"><ImageIcon size={34} /></div>}
        <div className="epm-library-detail-copy">
          <h3>{detail.model || '自动模型'}</h3>
          <p>{formatLibraryTime(detail.created_at)} · seed {detail.seed == null ? '?' : String(detail.seed)}</p>
          <p>{detail.width || '?'}×{detail.height || '?'} · {detail.quality || '自定义'} · {detail.lora_count} 个 LoRA</p>
          <p className="epm-library-id">作品 ID：{detail.generation_id}</p>
        </div>
      </div>
      <div className="epm-library-actions">
        <button type="button" className="epm-secondary-button" onClick={() => onRestore('reproduce')}>复现到当前表单</button>
        <button type="button" className="epm-quiet-button" onClick={() => onRestore('seed-variant')}>换 Seed 到当前表单</button>
        <button type="button" className="epm-quiet-button" onClick={() => onRestore('continue-edit')}>继续编辑</button>
      </div>
      <p className="epm-library-note">恢复只会填入当前表单，不会自动生成，也不会自动选择某个输出作为图生图 / 重绘输入；下一次生成会记录派生关系，也可在表单中取消关联。</p>
      <section className="epm-library-detail-section">
        <h3><GitBranch size={16} />谱系</h3>
        <p>父作品 {detail.parent_count} · 子作品 {detail.child_count}</p>
        {lineage && (lineage.ancestors.length > 0 || lineage.descendants.length > 0) && <div className="epm-library-lineage-list">
          {lineage.ancestors.map((item) => <span key={`parent-${item.generation_id}`}>父 · {item.generation_id.slice(0, 10)}… · {libraryOperationLabel(item.operation)}</span>)}
          {lineage.descendants.map((item) => <span key={`child-${item.generation_id}`}>子 · {item.generation_id.slice(0, 10)}… · {libraryOperationLabel(item.operation)}</span>)}
        </div>}
        {lineage && lineage.ancestors.length === 0 && lineage.descendants.length === 0 && <span className="epm-library-muted">暂无父子记录</span>}
      </section>
      <section className="epm-library-detail-section">
        <h3><ImageIcon size={16} />输出文件</h3>
        {detail.artifacts.length ? <div className="epm-library-artifact-list">
          {detail.artifacts.map((artifact) => <div className="epm-library-artifact" key={artifact.artifact_id}>
            <span>{artifact.filename}{artifact.exists === false ? '（文件缺失）' : ''}</span>
            <button type="button" className="epm-quiet-button epm-inline-button" onClick={() => onDownload(artifact)} disabled={artifact.exists === false || !artifact.url || Boolean(downloadLoading)}>
              {downloadLoading === artifact.artifact_id ? <LoaderCircle size={14} className="epm-spin" /> : <Download size={14} />}下载
            </button>
          </div>)}
        </div> : <span className="epm-library-muted">暂无可用输出；索引只跳过缺失文件，不会改写源记录。</span>}
      </section>
      <section className="epm-library-detail-section">
        <h3>提示词预览</h3>
        <pre className="epm-library-prompt">{promptPreview(detail.replay?.payload)}</pre>
        <span className="epm-library-muted">{detail.replay?.note || '只读预览'}</span>
      </section>
    </div>
  )
}

function LibraryImageViewer({ artifact, source, loading, error, downloadLoading, onClose, onDownload }: {
  artifact: EasyPanelGenerationArtifact
  source: string
  loading: boolean
  error: string
  downloadLoading: string
  onClose: () => void
  onDownload: (artifact: EasyPanelGenerationArtifact) => void
}) {
  return (
    <div className="epm-library-viewer-layer" role="dialog" aria-modal="true" aria-label="原图预览">
      <button type="button" className="epm-library-viewer-backdrop" onClick={onClose} aria-label="关闭原图预览" />
      <section className="epm-library-viewer">
        <header className="epm-library-viewer-header">
          <div>
            <span className="epm-section-kicker">ORIGINAL IMAGE</span>
            <strong>原图预览</strong>
            <small>{artifact.filename}</small>
          </div>
          <button type="button" className="epm-library-close" onClick={onClose} title="关闭"><X size={20} /></button>
        </header>
        <div className="epm-library-viewer-viewport">
          {loading ? <div className="epm-library-viewer-state"><LoaderCircle size={28} className="epm-spin" /><span>正在读取原图…</span></div>
            : source ? <img src={source} alt={artifact.filename || '作品原图'} draggable={false} />
              : <div className="epm-library-viewer-state"><ImageIcon size={28} /><span>{error || '原图暂不可用'}</span></div>}
        </div>
        <footer className="epm-library-viewer-footer">
          <span>{source ? '已加载输出文件原图，可双指缩放查看细节。' : '原图加载失败。'}</span>
          {source && <button type="button" className="epm-secondary-button epm-inline-button" onClick={() => onDownload(artifact)} disabled={Boolean(downloadLoading)}>
            {downloadLoading === artifact.artifact_id ? <LoaderCircle size={14} className="epm-spin" /> : <Download size={14} />}下载原图
          </button>}
        </footer>
      </section>
    </div>
  )
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle2 size={14} />
  if (status === 'error') return <AlertTriangle size={14} />
  return <LoaderCircle size={14} className="epm-spin" />
}

function formatSnapshotTime(value: number): string {
  try {
    return new Date(value).toLocaleString()
  } catch {
    return '未知时间'
  }
}

function formatLibraryTime(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '未知时间'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return '未知时间'
  }
}

function libraryOperationLabel(value: string): string {
  const labels: Record<string, string> = {
    txt2img: '文生图',
    seed_variant: '换 Seed',
    img2img: '图生图',
    inpaint: '局部重绘',
    face_fix: '修脸',
    hand_fix: '修手',
    upscale: '放大',
    outfit_change: '换服装',
    scene_change: '换场景',
    style_change: '换风格',
  }
  return labels[value] || '未知操作'
}

function libraryStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '生成中',
    completed: '已完成',
    error: '失败',
    cancelled: '已取消',
  }
  return labels[value] || '状态未知'
}

function promptPreview(payload: Record<string, unknown> | undefined): string {
  if (!payload) return '（没有记录提示词）'
  const prompt = typeof payload.prompt === 'string' ? payload.prompt.trim() : ''
  if (prompt) return prompt
  const sections = payload.promptSections
  if (!sections || typeof sections !== 'object' || Array.isArray(sections)) return '（没有记录提示词）'
  return Object.values(sections as Record<string, unknown>)
    .filter((value): value is string => typeof value === 'string' && Boolean(value.trim()))
    .join(', ') || '（没有记录提示词）'
}

function displayExplanationValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value) ?? ''
  } catch {
    return ''
  }
}

function formatExplanationRecord(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return displayExplanationValue(value)
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => `${key}=${displayExplanationValue(item)}`)
    .join(' · ')
}

function formatExplanationReasons(value: unknown): string {
  if (!Array.isArray(value)) return ''
  return value.map((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return displayExplanationValue(item)
    const record = item as Record<string, unknown>
    const message = displayExplanationValue(record.message)
    return message || formatExplanationRecord(record)
  }).filter(Boolean).join('；')
}
