import { AlertTriangle, ArrowLeft, ArrowUpRight, BookOpen, CheckCircle2, ChevronDown, Copy, Download, GitBranch, Image as ImageIcon, LayoutDashboard, LoaderCircle, Maximize2, RefreshCw, Server, ShieldCheck, Sparkles, Star, Trash2, Wifi, X, XCircle } from 'lucide-react'
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from 'react'
import { isControllerBusy, reduceEasyPanelControllerInteraction } from '../lib/easyPanelController'
import { explainSnapshot, shouldFocusPromptAfterSnapshotRestore, snapshotPromptSourceLabels } from '../lib/easyPanelSnapshot'
import { appendPromptText, parsePromptTranslation, type ParsedPromptTranslation } from '../lib/promptTranslation'
import { useEasyPanelController } from '../hooks/useEasyPanelController'
import { openAdvancedPanel } from '../services/easyPanelAdvanced'
import { getEasyPanelPromptInstruction } from '../services/easyPanelVisual'
import type { EasyPanelGenerationArtifact, EasyPanelGenerationDetail, EasyPanelGenerationSummary } from '../services/easyPanelLibrary'

export default function EasyPanelMobileApp() {
  const controller = useEasyPanelController()
  const [advancedOpen, setAdvancedOpen] = useState(true)
  const [advancedOpening, setAdvancedOpening] = useState(false)
  const [advancedError, setAdvancedError] = useState('')
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [snapshotsOpen, setSnapshotsOpen] = useState(false)
  const [chineseDescription, setChineseDescription] = useState('')
  const [translationInstruction, setTranslationInstruction] = useState('')
  const [translationFamily, setTranslationFamily] = useState('')
  const [translationAnswer, setTranslationAnswer] = useState('')
  const [translationResult, setTranslationResult] = useState<ParsedPromptTranslation>()
  const [translationMessage, setTranslationMessage] = useState('')
  const [translationLoading, setTranslationLoading] = useState(false)
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

  async function copyText(value: string) {
    const bridge = window.EasyPanelClipboard
    if (bridge?.copyText) {
      try {
        if (bridge.copyText(value)) return
      } catch {
        // Continue with the browser clipboard fallbacks below.
      }
    }
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value)
      return
    }
    const area = document.createElement('textarea')
    area.value = value
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.focus()
    area.select()
    try {
      if (!document.execCommand('copy')) throw new Error('浏览器拒绝复制')
    } finally {
      area.remove()
    }
  }

  async function prepareTranslationInstruction(openDeepSeek = false) {
    const source = chineseDescription.trim()
    if (!source) {
      setTranslationMessage('请先输入中文画面描述。')
      return
    }
    if (!controller.settings.baseUrl.trim() || !controller.settings.token.trim()) {
      setTranslationMessage('请先填写 Easy Panel 地址和 RPG Token。')
      return
    }
    setTranslationLoading(true)
    setTranslationMessage('正在读取当前模型并生成适配指令…')
    try {
      const result = await getEasyPanelPromptInstruction(
        { baseUrl: controller.settings.baseUrl, token: controller.settings.token, requestTimeoutMs: 15000 },
        source,
        controller.settings.model,
        'safe',
      )
      setTranslationInstruction(result.instruction)
      setTranslationFamily(`${result.family_label} · ${result.model}`)
      if (openDeepSeek) {
        await copyText(result.instruction)
        window.open('https://chat.deepseek.com/', '_blank', 'noopener,noreferrer')
        setTranslationMessage(`已复制适配【${result.family_label}】的指令，已打开 DeepSeek。粘贴发送后，把回答复制回来再点击“读取 AI 回答”。`)
      } else {
        setTranslationMessage(`已生成适配【${result.family_label}】的 AI 指令。`)
      }
    } catch (caught) {
      setTranslationMessage(caught instanceof Error ? caught.message : '生成 AI 转换指令失败。')
    } finally {
      setTranslationLoading(false)
    }
  }

  async function readTranslationAnswer() {
    try {
      if (!navigator.clipboard?.readText) throw new Error('当前 WebView 不支持读取剪贴板')
      const value = (await navigator.clipboard.readText()).trim()
      if (!value) {
        setTranslationMessage('剪贴板为空，请先复制 AI 的回答。')
        return
      }
      setTranslationAnswer(value)
      const parsed = parsePromptTranslation(value)
      setTranslationResult(parsed)
      setTranslationMessage(parsed.positive || parsed.negative ? '已读取并解析 AI 回答，请检查后加入提示词。' : '没有识别到可用的正向或负面提示词。')
    } catch {
      setTranslationMessage('无法读取剪贴板；请把 AI 回答粘贴到下方文本框后点击“解析回答”。')
    }
  }

  function parseTranslationAnswer() {
    const parsed = parsePromptTranslation(translationAnswer)
    setTranslationResult(parsed)
    setTranslationMessage(parsed.positive || parsed.negative ? '已解析 AI 回答，请检查后加入提示词。' : '没有识别到可用的正向或负面提示词。')
  }

  function applyTranslation(kind: 'positive' | 'negative') {
    const value = translationResult?.[kind] || ''
    if (!value) {
      setTranslationMessage(`没有可加入的${kind === 'positive' ? '正向' : '负面'}提示词。`)
      return
    }
    const patch: Partial<typeof controller.settings> = kind === 'positive'
      ? { prompt: appendPromptText(controller.settings.prompt, value) }
      : { negative: appendPromptText(controller.settings.negative, value) }
    patchSettings(patch)
    setTranslationMessage(`已将 AI 的${kind === 'positive' ? '正向' : '负面'}提示词加入快速生图表单。`)
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
          <div className="epm-prompt-translation">
            <div className="epm-translation-heading">
              <div>
                <span className="epm-section-kicker">AI PROMPT BRIDGE</span>
                <strong>中文描述转换</strong>
              </div>
              <Sparkles size={17} />
            </div>
            <p className="epm-translation-help">复用高级面板的 DeepSeek 流程；指令会带上当前 Checkpoint 的模型族规则。</p>
            <label className="epm-field">
              <span>中文画面描述 <small>先写想法，不会自动提交生成</small></span>
              <textarea
                value={chineseDescription}
                onChange={(event) => setChineseDescription(event.target.value)}
                placeholder="例如：黄昏时安静的书店，窗边暖光，一位金发女孩正在看书"
                rows={3}
                maxLength={1200}
              />
              <em>{chineseDescription.length} / 1200</em>
            </label>
            <div className="epm-action-row epm-translation-actions">
              <button type="button" className="epm-secondary-button" onClick={() => void prepareTranslationInstruction(true)} disabled={translationLoading || working}>
                {translationLoading ? <LoaderCircle size={15} className="epm-spin" /> : <Sparkles size={15} />}
                复制并打开 DeepSeek
              </button>
              <button type="button" className="epm-quiet-button" onClick={() => void prepareTranslationInstruction(false)} disabled={translationLoading || working}>
                <Copy size={15} />复制指令
              </button>
            </div>
            {translationFamily && <div className="epm-translation-family" role="status">当前适配：{translationFamily}</div>}
            {translationInstruction && <details className="epm-translation-instruction">
              <summary>查看已生成的 AI 指令</summary>
              <textarea value={translationInstruction} readOnly rows={7} aria-label="AI 转换指令" />
            </details>}
            <label className="epm-field epm-translation-answer-field">
              <span>AI 回答 <small>可直接粘贴 POSITIVE / NEGATIVE</small></span>
              <textarea
                value={translationAnswer}
                onChange={(event) => setTranslationAnswer(event.target.value)}
                placeholder="复制 DeepSeek 回答后点读取，或直接粘贴到这里"
                rows={4}
              />
            </label>
            <div className="epm-action-row epm-translation-actions">
              <button type="button" className="epm-quiet-button" onClick={() => void readTranslationAnswer()} disabled={working}>
                <Copy size={15} />读取 AI 回答
              </button>
              <button type="button" className="epm-quiet-button" onClick={parseTranslationAnswer} disabled={!translationAnswer.trim()}>
                解析回答
              </button>
            </div>
            {translationResult && <div className="epm-translation-preview">
              <div><strong>正向</strong><span>{translationResult.positive || '（未识别）'}</span><button type="button" className="epm-quiet-button" onClick={() => applyTranslation('positive')} disabled={!translationResult.positive}>加入正向</button></div>
              <div><strong>负面</strong><span>{translationResult.negative || '（无额外负面词）'}</span><button type="button" className="epm-quiet-button" onClick={() => applyTranslation('negative')} disabled={!translationResult.negative}>加入负面</button></div>
            </div>}
            {translationMessage && <p className="epm-translation-message" role="status">{translationMessage}</p>}
          </div>
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
          <div className="epm-section-heading epm-snapshot-heading">
            <button type="button" className="epm-section-toggle epm-snapshot-toggle" onClick={() => setSnapshotsOpen((value) => !value)} aria-expanded={snapshotsOpen}>
              <span>
                <span className="epm-section-kicker">04 · HISTORY</span>
                <strong>历史快照 <small className="epm-snapshot-count">{controller.snapshots.length ? `${controller.snapshots.length} 条记录` : '点击展开查看'}</small></strong>
              </span>
              <span className={`epm-toggle-chevron ${snapshotsOpen ? 'open' : ''}`}>⌄</span>
            </button>
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
          {snapshotsOpen && <div className="epm-snapshot-body">
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
  // Keep the list scroll offset while a detail view is open so returning to the
  // records page lands on the same position instead of the top.
  const listScrollRef = useRef(0)
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

  async function removeGeneration(id: string) {
    const model = controller.libraryDetail?.model || '该作品'
    if (!globalThis.confirm(`删除${model}的记录并删除电脑端对应的本地图片吗？此操作无法撤销。`)) return
    await controller.deleteLibraryGeneration(id)
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
          onToggleFavorite={(id, favorite) => void controller.saveLibraryFlags(id, { favorite })}
          groups={controller.libraryGroups}
          onSaveGroups={(id, groups) => void controller.saveLibraryFlags(id, { groups })}
          onCreateGroup={(name, id) => void controller.createLibraryGroup(name, id)}
          onRenameGroup={(groupId, name) => void controller.renameLibraryGroup(groupId, name)}
          onDeleteGroup={(groupId) => void controller.deleteLibraryGroup(groupId)}
          onDelete={(id) => void removeGeneration(id)}
        /> : <LibraryList
          items={controller.library}
          thumbnailSources={controller.libraryThumbnailSources}
          total={controller.libraryTotal}
          hasMore={controller.libraryHasMore}
          favoriteOnly={controller.libraryFavoriteOnly}
          groups={controller.libraryGroups}
          groupFilter={controller.libraryGroupFilter}
          onSelectGroup={controller.setLibraryGroupFilter}
          thumbnailLoading={controller.libraryThumbnailLoading}
          loading={controller.libraryLoading}
          error={controller.libraryError}
          message={controller.libraryMessage}
          savedScrollTop={listScrollRef.current}
          onScrollTopChange={(top) => { listScrollRef.current = top }}
          onRefresh={() => void controller.refreshLibrary()}
          onToggleFavoriteFilter={controller.toggleLibraryFavoriteFilter}
          onToggleFavorite={(id, favorite) => void controller.saveLibraryFlags(id, { favorite })}
          onLoadMore={() => void controller.loadMoreLibrary()}
          onLoadThumbnail={controller.loadLibraryThumbnail}
          onOpen={(id) => void controller.openLibraryGeneration(id)}
          onDelete={(id) => void removeGeneration(id)}
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

function LibraryList({ items, thumbnailSources, total, hasMore, favoriteOnly, groups, groupFilter, onSelectGroup, thumbnailLoading, loading, error, message, savedScrollTop = 0, onScrollTopChange, onRefresh, onToggleFavoriteFilter, onToggleFavorite, onLoadMore, onLoadThumbnail, onOpen, onDelete }: {
  items: EasyPanelGenerationSummary[]
  thumbnailSources: Record<string, string>
  total: number
  hasMore: boolean
  favoriteOnly: boolean
  groups: ReturnType<typeof useEasyPanelController>['libraryGroups']
  groupFilter: string
  onSelectGroup: (groupId: string) => void
  thumbnailLoading: Record<string, boolean>
  loading: boolean
  error: string
  message: string
  savedScrollTop?: number
  onScrollTopChange?: (top: number) => void
  onRefresh: () => void
  onToggleFavoriteFilter: () => void
  onToggleFavorite: (id: string, favorite: boolean) => void
  onLoadMore: () => void
  onLoadThumbnail: (item: EasyPanelGenerationSummary) => void
  onOpen: (id: string) => void
  onDelete: (id: string) => void
}) {
  const contentRef = useRef<HTMLDivElement>(null)

  // Restore the previously saved scroll offset when the list is remounted after
  // viewing a work detail, so going back stays at the original position.
  useLayoutEffect(() => {
    const root = contentRef.current
    if (!root) return
    const target = Number(savedScrollTop) || 0
    if (target <= 0) return
    root.scrollTop = target
    const raf = requestAnimationFrame(() => {
      if (contentRef.current) contentRef.current.scrollTop = target
    })
    return () => cancelAnimationFrame(raf)
    // Run once on mount only; later prop changes are handled by onScrollTopChange.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const root = contentRef.current
    if (!root || !items.length) return
    const itemsById = new Map(items.map((item) => [item.generation_id, item]))
    const requestThumbnail = (id: string) => {
      const item = itemsById.get(id)
      if (item) onLoadThumbnail(item)
    }
    if (typeof IntersectionObserver !== 'function') {
      items.forEach((item) => onLoadThumbnail(item))
      return
    }
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const id = (entry.target as HTMLElement).dataset.libraryThumbnailId
        if (!id) continue
        observer.unobserve(entry.target)
        requestThumbnail(id)
      }
    }, { root, rootMargin: '180px 0px', threshold: 0.01 })
    root.querySelectorAll<HTMLElement>('[data-library-thumbnail-id]').forEach((element) => observer.observe(element))
    return () => observer.disconnect()
  }, [items, onLoadThumbnail])

  return (
    <div
      ref={contentRef}
      className="epm-library-content"
      onScroll={() => {
        const root = contentRef.current
        if (root) onScrollTopChange?.(root.scrollTop)
      }}
    >
      <div className="epm-library-toolbar">
        <span>{message}</span>
        <div className="epm-library-toolbar-actions">
          <button
            type="button"
            className="epm-quiet-button epm-inline-button"
            aria-pressed={favoriteOnly}
            title="只看标记为入选（最佳版本）的作品"
            onClick={onToggleFavoriteFilter}
          >{favoriteOnly ? <Star size={15} fill="currentColor" /> : <Star size={15} />}只看入选</button>
          <button type="button" className="epm-quiet-button epm-inline-button" onClick={onRefresh} disabled={loading}>
            {loading ? <LoaderCircle size={15} className="epm-spin" /> : <RefreshCw size={15} />}刷新
          </button>
        </div>
      </div>
      {error && <div className="epm-error-banner" role="alert"><AlertTriangle size={16} /><span>{error}</span></div>}
      <div className="epm-library-group-filter">
        <button
          type="button"
          className={groupFilter ? 'epm-chip' : 'epm-chip is-on'}
          onClick={() => onSelectGroup('')}
        >全部收藏组</button>
        <button
          type="button"
          className={groupFilter === 'ungrouped' ? 'epm-chip is-on' : 'epm-chip'}
          onClick={() => onSelectGroup('ungrouped')}
        >未分组</button>
        {groups.map((group) => <button
          type="button"
          key={group.group_id}
          className={groupFilter === group.group_id ? 'epm-chip is-on' : 'epm-chip'}
          onClick={() => onSelectGroup(group.group_id)}
        >{group.name}（{group.item_count}）</button>)}
      </div>
      {items.length ? <>
        <div className="epm-library-list">
          {items.map((item) => <div className="epm-library-item-wrap" key={item.generation_id}>
            <button type="button" className="epm-library-item" data-library-thumbnail-id={item.generation_id} onClick={() => onOpen(item.generation_id)}>
              <div className="epm-library-thumb">
                {thumbnailSources[item.generation_id]
                  ? <img src={thumbnailSources[item.generation_id]} alt="" />
                  : thumbnailLoading[item.generation_id] ? <LoaderCircle size={22} className="epm-spin" /> : <ImageIcon size={24} />}
              </div>
              <div className="epm-library-item-copy">
                <div className="epm-library-item-heading"><strong>{item.model || '自动模型'}</strong><small>{formatLibraryTime(item.created_at)}</small></div>
                <span>{libraryOperationLabel(item.operation)} · {libraryStatusLabel(item.status)} · seed {item.seed == null ? '?' : String(item.seed)}</span>
                <small>{item.width || '?'}×{item.height || '?'} · {item.artifact_count} 个输出 · 父 {item.parent_count} / 子 {item.child_count}</small>
                {Boolean(item.groups?.length) && <div className="epm-library-item-groups">
                  {(item.groups ?? []).slice(0, 4).map((group) => <span key={group.group_id}>{group.name}</span>)}
                  {(item.groups ?? []).length > 4 && <span>+{(item.groups ?? []).length - 4}</span>}
                </div>}
              </div>
            </button>
            <button
              type="button"
              className={item.favorite ? 'epm-library-item-star is-on' : 'epm-library-item-star'}
              aria-pressed={Boolean(item.favorite)}
              aria-label={`${item.favorite ? '取消入选' : '标记为入选'} ${item.model || '作品'}`}
              title={item.favorite ? '取消入选标记' : '标记为入选（最佳版本）'}
              onClick={() => onToggleFavorite(item.generation_id, !item.favorite)}
            >
              {item.favorite ? <Star size={15} fill="currentColor" /> : <Star size={15} />}
            </button>
            <button type="button" className="epm-library-item-delete" title="删除记录与对应本地图片" aria-label={`删除 ${item.model || '作品'}`} onClick={() => onDelete(item.generation_id)}>
              <Trash2 size={15} />
            </button>
          </div>)}
        </div>
        {hasMore && <button type="button" className="epm-library-load-more" onClick={onLoadMore} disabled={loading}>
          {loading ? <LoaderCircle size={15} className="epm-spin" /> : <ChevronDown size={15} />}
          {loading ? '正在读取…' : `加载更多${total > items.length ? `（还剩 ${total - items.length} 张）` : ''}`}
        </button>}
      </> : <div className="epm-library-empty"><BookOpen size={28} /><strong>暂无作品记录</strong><span>新任务完成后会进入作品库；也可在电脑端执行重建索引。</span></div>}
    </div>
  )
}

function isHiresBaseArtifact(filename?: string): boolean {
  const name = String(filename ?? '').replace(/\\/gu, '/').split('/').pop() ?? ''
  return name.includes('_base_')
}

function LibraryDetail({ detail, lineage, thumbnailSource, downloadLoading, previewLoading, onBack, onRestore, onPreview, onDownload, onToggleFavorite, groups, onSaveGroups, onCreateGroup, onRenameGroup, onDeleteGroup, onDelete }: {
  detail: EasyPanelGenerationDetail
  lineage?: ReturnType<typeof useEasyPanelController>['libraryLineage']
  thumbnailSource?: string
  downloadLoading: string
  previewLoading: string
  onBack: () => void
  onRestore: (mode: 'reproduce' | 'seed-variant' | 'continue-edit') => void
  onPreview: (artifact: EasyPanelGenerationDetail['artifacts'][number]) => void
  onDownload: (artifact: EasyPanelGenerationDetail['artifacts'][number]) => void
  onToggleFavorite: (id: string, favorite: boolean) => void
  groups: ReturnType<typeof useEasyPanelController>['libraryGroups']
  onSaveGroups: (id: string, groups: string[]) => void
  onCreateGroup: (name: string, generationId?: string) => void
  onRenameGroup: (groupId: string, name: string) => void
  onDeleteGroup: (groupId: string) => void
  onDelete: (id: string) => void
}) {
  const previewArtifact = (() => {
    // 列表小图取 summary.thumbnail_url，详情大图必须指向同一张（服务端 preview / primary_artifact_id）
    const preferred = detail.preview?.artifact_id || detail.primary_artifact_id || ''
    const matched = preferred
      ? detail.artifacts.find((artifact) => artifact.artifact_id === preferred)
      : undefined
    return matched
      || detail.artifacts.find((artifact) => artifact.exists !== false && Boolean(artifact.url))
      || detail.artifacts[0]
  })()
  const [newGroupName, setNewGroupName] = useState('')
  const [renaming, setRenaming] = useState<{ groupId: string; value: string } | null>(null)
  const assigned = new Set((detail.groups ?? []).map((group) => group.group_id))
  // 收藏组只是用户自己的分类：勾选后立即同步，不涉及任何生成参数。
  const toggleGroup = (groupId: string, checked: boolean) => {
    const next = new Set(assigned)
    if (checked) next.add(groupId)
    else next.delete(groupId)
    onSaveGroups(detail.generation_id, Array.from(next))
  }

  return (
    <div className="epm-library-content">
      <div className="epm-library-detail-toolbar">
        <button type="button" className="epm-quiet-button epm-inline-button" onClick={onBack}><ArrowLeft size={15} />返回列表</button>
        <div className="epm-library-toolbar-actions">
          <span>{libraryOperationLabel(detail.operation)} · {libraryStatusLabel(detail.status)}</span>
          <button
            type="button"
            className={detail.favorite ? 'epm-quiet-button epm-inline-button is-on' : 'epm-quiet-button epm-inline-button'}
            aria-pressed={Boolean(detail.favorite)}
            title={detail.favorite ? '取消入选标记' : '标记为入选（最佳版本）'}
            onClick={() => onToggleFavorite(detail.generation_id, !detail.favorite)}
          >{detail.favorite ? <Star size={14} fill="currentColor" /> : <Star size={14} />}{detail.favorite ? '已入选' : '设为入选'}</button>
        </div>
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
        <button type="button" className="epm-danger-button" onClick={() => onDelete(detail.generation_id)}><Trash2 size={14} />删除此作品</button>
      </div>
      <p className="epm-library-note">恢复只会填入当前表单，不会自动生成，也不会自动选择某个输出作为图生图 / 重绘输入；下一次生成会记录派生关系，也可在表单中取消关联。</p>
      <section className="epm-library-detail-section">
        <h3><Star size={16} />收藏组</h3>
        <p>{groups.length ? '一张图可以同时加入多个组；勾选后立即同步到电脑端。' : '还没有收藏组，在下面新建第一个。'}</p>
        {groups.length > 0 && <div className="epm-library-group-list">
          {groups.map((group) => <div className="epm-library-group-row" key={group.group_id}>
            {renaming && renaming.groupId === group.group_id
              ? <>
                <input
                  className="epm-library-group-input"
                  value={renaming.value}
                  maxLength={60}
                  onChange={(event) => setRenaming({ groupId: group.group_id, value: event.target.value })}
                />
                <button
                  type="button"
                  className="epm-quiet-button epm-inline-button"
                  onClick={() => {
                    const name = renaming.value.trim()
                    if (name) onRenameGroup(group.group_id, name)
                    setRenaming(null)
                  }}
                >保存</button>
                <button type="button" className="epm-quiet-button epm-inline-button" onClick={() => setRenaming(null)}>取消</button>
              </>
              : <>
                <label className="epm-library-group-check">
                  <input
                    type="checkbox"
                    checked={assigned.has(group.group_id)}
                    onChange={(event) => toggleGroup(group.group_id, event.target.checked)}
                  />
                  <span>{group.name}（{group.item_count}）</span>
                </label>
                <button
                  type="button"
                  className="epm-quiet-button epm-inline-button"
                  onClick={() => setRenaming({ groupId: group.group_id, value: group.name })}
                >改名</button>
                <button
                  type="button"
                  className="epm-danger-button epm-inline-button"
                  onClick={() => onDeleteGroup(group.group_id)}
                >删除组</button>
              </>}
          </div>)}
        </div>}
        <div className="epm-library-group-create">
          <input
            className="epm-library-group-input"
            value={newGroupName}
            maxLength={60}
            placeholder="新建收藏组名称，例如 成图候选"
            onChange={(event) => setNewGroupName(event.target.value)}
          />
          <button
            type="button"
            className="epm-quiet-button epm-inline-button"
            onClick={() => {
              const name = newGroupName.trim()
              if (!name) return
              onCreateGroup(name, detail.generation_id)
              setNewGroupName('')
            }}
          >新建并加入</button>
        </div>
      </section>
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
            <span>{artifact.filename}{isHiresBaseArtifact(artifact.filename) ? '（首采对照，非成品）' : ''}{artifact.exists === false ? '（文件缺失）' : ''}</span>
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

type LibraryViewerPoint = { x: number; y: number }
type LibraryViewerGesture =
  | { kind: 'pan'; lastPoint: LibraryViewerPoint; moved: boolean }
  | { kind: 'pinch'; startDistance: number; startZoom: number; startOffset: LibraryViewerPoint; startCenter: LibraryViewerPoint; moved: boolean }

function libraryViewerDistance(left: LibraryViewerPoint, right: LibraryViewerPoint): number {
  return Math.hypot(right.x - left.x, right.y - left.y)
}

function libraryViewerCenter(left: LibraryViewerPoint, right: LibraryViewerPoint): LibraryViewerPoint {
  return { x: (left.x + right.x) / 2, y: (left.y + right.y) / 2 }
}

function libraryViewerZoom(value: number): number {
  return Math.min(4, Math.max(1, value))
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
  const viewportRef = useRef<HTMLDivElement>(null)
  const pointersRef = useRef(new Map<number, LibraryViewerPoint>())
  const gestureRef = useRef<LibraryViewerGesture | undefined>(undefined)
  const lastTapRef = useRef<{ time: number; point: LibraryViewerPoint } | undefined>(undefined)
  const zoomRef = useRef(1)
  const offsetRef = useRef<LibraryViewerPoint>({ x: 0, y: 0 })
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState<LibraryViewerPoint>({ x: 0, y: 0 })

  useEffect(() => {
    pointersRef.current.clear()
    gestureRef.current = undefined
    lastTapRef.current = undefined
    zoomRef.current = 1
    offsetRef.current = { x: 0, y: 0 }
    setZoom(1)
    setOffset({ x: 0, y: 0 })
  }, [artifact.artifact_id, source])

  function constrainedOffset(nextOffset: LibraryViewerPoint, nextZoom: number): LibraryViewerPoint {
    const viewport = viewportRef.current
    if (!viewport || nextZoom <= 1) return { x: 0, y: 0 }
    const maxX = Math.max(0, viewport.clientWidth * (nextZoom - 1) * 0.5 + 48)
    const maxY = Math.max(0, viewport.clientHeight * (nextZoom - 1) * 0.5 + 48)
    return {
      x: Math.min(maxX, Math.max(-maxX, nextOffset.x)),
      y: Math.min(maxY, Math.max(-maxY, nextOffset.y)),
    }
  }

  function updateTransform(nextZoom: number, nextOffset: LibraryViewerPoint) {
    const safeZoom = libraryViewerZoom(nextZoom)
    const safeOffset = constrainedOffset(nextOffset, safeZoom)
    zoomRef.current = safeZoom
    offsetRef.current = safeOffset
    setZoom(safeZoom)
    setOffset(safeOffset)
  }

  function pointFromEvent(event: ReactPointerEvent<HTMLDivElement>): LibraryViewerPoint {
    const rect = event.currentTarget.getBoundingClientRect()
    return { x: event.clientX - rect.left, y: event.clientY - rect.top }
  }

  function beginGesture() {
    const points = [...pointersRef.current.values()]
    if (points.length >= 2) {
      gestureRef.current = {
        kind: 'pinch',
        startDistance: Math.max(1, libraryViewerDistance(points[0], points[1])),
        startZoom: zoomRef.current,
        startOffset: { ...offsetRef.current },
        startCenter: libraryViewerCenter(points[0], points[1]),
        moved: false,
      }
    } else if (points.length === 1) {
      gestureRef.current = { kind: 'pan', lastPoint: points[0], moved: false }
    } else {
      gestureRef.current = undefined
    }
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (loading || !source) return
    event.preventDefault()
    const point = pointFromEvent(event)
    pointersRef.current.set(event.pointerId, point)
    try { event.currentTarget.setPointerCapture(event.pointerId) } catch { /* WebView may reject capture after teardown. */ }
    if (pointersRef.current.size > 1) lastTapRef.current = undefined
    beginGesture()
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!pointersRef.current.has(event.pointerId)) return
    event.preventDefault()
    const point = pointFromEvent(event)
    pointersRef.current.set(event.pointerId, point)
    const points = [...pointersRef.current.values()]
    const gesture = gestureRef.current
    if (points.length >= 2) {
      if (!gesture || gesture.kind !== 'pinch') {
        beginGesture()
        return
      }
      const center = libraryViewerCenter(points[0], points[1])
      const distance = Math.max(1, libraryViewerDistance(points[0], points[1]))
      const nextZoom = libraryViewerZoom(gesture.startZoom * distance / gesture.startDistance)
      const viewport = viewportRef.current
      const viewportCenter = viewport ? { x: viewport.clientWidth / 2, y: viewport.clientHeight / 2 } : { x: 0, y: 0 }
      const scale = nextZoom / gesture.startZoom
      const centerDelta = { x: center.x - gesture.startCenter.x, y: center.y - gesture.startCenter.y }
      const anchor = { x: gesture.startCenter.x - viewportCenter.x, y: gesture.startCenter.y - viewportCenter.y }
      updateTransform(nextZoom, {
        x: gesture.startOffset.x * scale + centerDelta.x + anchor.x * (1 - scale),
        y: gesture.startOffset.y * scale + centerDelta.y + anchor.y * (1 - scale),
      })
      gesture.moved = true
      return
    }
    if (!gesture || gesture.kind !== 'pan') {
      beginGesture()
      return
    }
    const delta = { x: point.x - gesture.lastPoint.x, y: point.y - gesture.lastPoint.y }
    if (Math.abs(delta.x) > 1 || Math.abs(delta.y) > 1) gesture.moved = true
    updateTransform(zoomRef.current, { x: offsetRef.current.x + delta.x, y: offsetRef.current.y + delta.y })
    gesture.lastPoint = point
  }

  function handleTap(point: LibraryViewerPoint) {
    const now = Date.now()
    const previous = lastTapRef.current
    const doubleTap = previous
      && now - previous.time < 320
      && libraryViewerDistance(previous.point, point) < 28
    if (doubleTap) {
      lastTapRef.current = undefined
      const nextZoom = zoomRef.current > 1.05 ? 1 : 2
      if (nextZoom === 1) {
        updateTransform(1, { x: 0, y: 0 })
      } else {
        const viewport = viewportRef.current
        const center = viewport ? { x: viewport.clientWidth / 2, y: viewport.clientHeight / 2 } : { x: 0, y: 0 }
        const ratio = nextZoom / zoomRef.current
        updateTransform(nextZoom, {
          x: offsetRef.current.x + (point.x - center.x) * (1 - ratio),
          y: offsetRef.current.y + (point.y - center.y) * (1 - ratio),
        })
      }
      return
    }
    lastTapRef.current = { time: now, point }
  }

  function finishPointer(event: ReactPointerEvent<HTMLDivElement>, allowTap: boolean) {
    const point = pointersRef.current.get(event.pointerId)
    const wasSingle = pointersRef.current.size === 1
    const gesture = gestureRef.current
    const endedPinch = gesture?.kind === 'pinch'
    pointersRef.current.delete(event.pointerId)
    try { event.currentTarget.releasePointerCapture(event.pointerId) } catch { /* Pointer may already be released. */ }
    if (allowTap && wasSingle && point && gesture?.kind === 'pan' && !gesture.moved) handleTap(point)
    if (pointersRef.current.size > 0) {
      beginGesture()
      if (endedPinch && gestureRef.current?.kind === 'pan') gestureRef.current.moved = true
    }
    else gestureRef.current = undefined
  }

  function handleWheel(event: ReactWheelEvent<HTMLDivElement>) {
    if (!source) return
    event.preventDefault()
    const nextZoom = libraryViewerZoom(zoomRef.current - event.deltaY * 0.002)
    if (nextZoom === zoomRef.current) return
    const rect = event.currentTarget.getBoundingClientRect()
    const center = { x: rect.width / 2, y: rect.height / 2 }
    const point = { x: event.clientX - rect.left, y: event.clientY - rect.top }
    const ratio = nextZoom / zoomRef.current
    updateTransform(nextZoom, {
      x: offsetRef.current.x + (point.x - center.x) * (1 - ratio),
      y: offsetRef.current.y + (point.y - center.y) * (1 - ratio),
    })
  }

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
        <div
          ref={viewportRef}
          className="epm-library-viewer-viewport"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={(event) => finishPointer(event, true)}
          onPointerCancel={(event) => finishPointer(event, false)}
          onWheel={handleWheel}
          onContextMenu={(event) => event.preventDefault()}
        >
          {loading ? <div className="epm-library-viewer-state"><LoaderCircle size={28} className="epm-spin" /><span>正在读取原图…</span></div>
            : source ? <img src={source} alt={artifact.filename || '作品原图'} draggable={false} style={{ transform: `translate3d(${offset.x}px, ${offset.y}px, 0) scale(${zoom})` }} />
              : <div className="epm-library-viewer-state"><ImageIcon size={28} /><span>{error || '原图暂不可用'}</span></div>}
        </div>
        <footer className="epm-library-viewer-footer">
          <span>{source ? `已加载原图 · ${Math.round(zoom * 100)}% · 双指缩放，单指拖动，双击放大/还原。` : '原图加载失败。'}</span>
          {source && <div className="epm-library-viewer-footer-actions">
            {zoom > 1.05 && <button type="button" className="epm-quiet-button epm-inline-button" onClick={() => updateTransform(1, { x: 0, y: 0 })}>还原</button>}
            <button type="button" className="epm-secondary-button epm-inline-button" onClick={() => onDownload(artifact)} disabled={Boolean(downloadLoading)}>
              {downloadLoading === artifact.artifact_id ? <LoaderCircle size={14} className="epm-spin" /> : <Download size={14} />}下载原图
            </button>
          </div>}
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
