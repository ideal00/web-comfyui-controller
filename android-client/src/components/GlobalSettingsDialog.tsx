import { Check, Plus, RefreshCw, RotateCcw, Search, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { DEFAULT_PROVIDER } from '../config'
import { loadBundledDefaultPrompt } from '../lib/defaultPrompt'
import { fetchAvailableModelsWithSource, isGeminiOpenAiBaseUrl, normalizeBaseUrl, normalizeProviderModelId, normalizeProviderModelIds } from '../services/openai'
import type { ProviderProfile } from '../types'

interface Props {
  providers: ProviderProfile[]
  activeProviderId: string
  globalJailbreakPrompt: string
  onClose: () => void
  onChangeProviders: (providers: ProviderProfile[]) => void
  onChangeActive: (id: string) => void
  onChangeGlobalJailbreakPrompt: (value: string) => void
}

const newId = () => `provider-${Date.now()}-${Math.random().toString(16).slice(2)}`

function isLikelyGeminiModel(model: string): boolean {
  return /^(?:models\/)?gemini(?:[-/]|$)/iu.test(model.trim())
}

export default function GlobalSettingsDialog(props: Props) {
  const [draftProviders, setDraftProviders] = useState(() => props.providers.map((provider) => ({ ...provider, models: [...provider.models] })))
  const [draftActiveProviderId, setDraftActiveProviderId] = useState(props.activeProviderId)
  const [draftGlobalJailbreakPrompt, setDraftGlobalJailbreakPrompt] = useState(props.globalJailbreakPrompt)
  const active = draftProviders.find((provider) => provider.id === draftActiveProviderId) ?? draftProviders[0]
  const [remoteModels, setRemoteModels] = useState<string[] | null>(null)
  const [remoteSpecializedModels, setRemoteSpecializedModels] = useState<string[]>([])
  const [modelSearch, setModelSearch] = useState('')
  const [manualModel, setManualModel] = useState('')
  const [modelLoading, setModelLoading] = useState(false)
  const [modelError, setModelError] = useState('')
  const [modelNotice, setModelNotice] = useState('')
  const [defaultPromptLoading, setDefaultPromptLoading] = useState(false)
  const [defaultPromptError, setDefaultPromptError] = useState('')
  const activeModels = normalizeProviderModelIds(active.models?.length ? active.models : active.model ? [active.model] : [], active.baseUrl)
  const activeModel = normalizeProviderModelId(active.model, active.baseUrl)
  const filteredRemoteModels = (remoteModels ?? []).filter((model) => model.toLocaleLowerCase().includes(modelSearch.trim().toLocaleLowerCase()))
  const filteredSpecializedModels = remoteSpecializedModels.filter((model) => model.toLocaleLowerCase().includes(modelSearch.trim().toLocaleLowerCase()))
  const allFilteredModelsAdded = filteredRemoteModels.length > 0 && filteredRemoteModels.every((model) => activeModels.includes(model))

  useEffect(() => {
    setRemoteModels(null)
    setRemoteSpecializedModels([])
    setModelSearch('')
    setManualModel('')
    setModelError('')
    setModelNotice('')
    if (isGeminiOpenAiBaseUrl(active.baseUrl)) {
      const geminiModels = activeModels.filter(isLikelyGeminiModel)
      if (geminiModels.length !== activeModels.length) {
        setDraftProviders((providers) => providers.map((provider) => provider.id === active.id
          ? { ...provider, models: geminiModels, model: geminiModels.includes(activeModel) ? activeModel : '' }
          : provider))
        setModelNotice('Gemini 配置中的旧非 Gemini 模型已清除，请重新获取模型。')
      }
    }
  }, [active.id])

  function updateActive(patch: Partial<ProviderProfile>) {
    const nextBaseUrl = typeof patch.baseUrl === 'string' ? patch.baseUrl : undefined
    const switchedToGemini = nextBaseUrl !== undefined && isGeminiOpenAiBaseUrl(nextBaseUrl) && !isGeminiOpenAiBaseUrl(active.baseUrl)
    const modelBaseUrl = nextBaseUrl ?? active.baseUrl
    const normalizedPatch: Partial<ProviderProfile> = {
      ...patch,
      ...(typeof patch.model === 'string' ? { model: normalizeProviderModelId(patch.model, modelBaseUrl) } : {}),
      ...(Array.isArray(patch.models) ? { models: normalizeProviderModelIds(patch.models, modelBaseUrl) } : {}),
    }
    setDraftProviders((providers) => providers.map((provider) => {
      if (provider.id !== active.id) return provider
      if (switchedToGemini) return { ...provider, ...normalizedPatch, models: [], model: '' }
      return { ...provider, ...normalizedPatch }
    }))
    if (nextBaseUrl !== undefined) {
      setRemoteModels(null)
      setRemoteSpecializedModels([])
      setModelSearch('')
      setModelError('')
      if (switchedToGemini) setModelNotice('已切换到 Gemini，旧的非 Gemini 模型已清除，请重新获取模型。')
      else setModelNotice('')
    }
  }

  function addProvider() {
    const provider = { ...DEFAULT_PROVIDER, models: [...DEFAULT_PROVIDER.models], id: newId(), name: `备用 API ${draftProviders.length}` }
    setDraftProviders((providers) => [...providers, provider])
    setDraftActiveProviderId(provider.id)
  }

  function removeProvider() {
    if (draftProviders.length === 1) return
    const remaining = draftProviders.filter((provider) => provider.id !== active.id)
    setDraftProviders(remaining)
    setDraftActiveProviderId(remaining[0].id)
  }

  function finish() {
    const normalizedProviders = draftProviders.map((provider) => ({
      ...provider,
      model: normalizeProviderModelId(provider.model, provider.baseUrl),
      models: normalizeProviderModelIds(provider.models, provider.baseUrl),
    }))
    props.onChangeProviders(normalizedProviders)
    props.onChangeActive(draftActiveProviderId)
    props.onChangeGlobalJailbreakPrompt(draftGlobalJailbreakPrompt)
    props.onClose()
  }

  async function loadRemoteModels() {
    setModelLoading(true)
    setModelError('')
    try {
      const normalizedBaseUrl = normalizeBaseUrl(active.baseUrl)
      const gemini = isGeminiOpenAiBaseUrl(normalizedBaseUrl)
      if (normalizedBaseUrl !== active.baseUrl.trim()) updateActive({ baseUrl: normalizedBaseUrl })

      // A provider can already be persisted with a Gemini URL and an old
      // OpenAI model from before the URL switch. Remove those before a request
      // so a failed lookup cannot leave gpt-4o-mini looking verified.
      if (gemini) {
        const geminiModels = activeModels.filter(isLikelyGeminiModel)
        if (geminiModels.length !== activeModels.length) {
          updateActive({ models: geminiModels, model: geminiModels.includes(activeModel) ? activeModel : '' })
        }
      }

      const result = await fetchAvailableModelsWithSource({ ...active, baseUrl: normalizedBaseUrl })
      setRemoteModels(result.models)
      setRemoteSpecializedModels(result.specializedModels ?? [])
      if (gemini) {
        // Gemini discovery is authoritative for this provider. Replace the
        // cached model list and select a returned model rather than preserving
        // a model from another provider.
        updateActive({ models: result.models, model: result.models[0] ?? '' })
      }
      setModelNotice(result.warning ?? (result.specializedModels?.length ? `已折叠 ${result.specializedModels.length} 个非文本模型；如确有需要，可展开后手动添加。` : ''))
    } catch (error) {
      setModelError(error instanceof Error ? error.message : '获取模型失败')
      setRemoteModels(null)
      setRemoteSpecializedModels([])
      if (isGeminiOpenAiBaseUrl(active.baseUrl)) setModelNotice('模型获取失败，当前 Gemini 模型列表未验证；请查看上方详情或重新获取。')
    } finally {
      setModelLoading(false)
    }
  }

  function addModels(models: string[]) {
    const additions = models.map((model) => model.trim()).filter(Boolean)
    if (!additions.length) return
    const nextModels = Array.from(new Set([...activeModels, ...additions]))
    updateActive({ models: nextModels, model: activeModel || nextModels[0] })
  }

  function removeModel(model: string) {
    const nextModels = activeModels.filter((item) => item !== model)
    updateActive({ models: nextModels, model: activeModel === model ? (nextModels[0] ?? '') : activeModel })
  }

  function toggleRemoteModel(model: string) {
    if (activeModels.includes(model)) removeModel(model)
    else addModels([model])
  }

  function toggleFilteredRemoteModels() {
    if (allFilteredModelsAdded) {
      const filtered = new Set(filteredRemoteModels)
      const nextModels = activeModels.filter((model) => !filtered.has(model))
      updateActive({ models: nextModels, model: filtered.has(activeModel) ? (nextModels[0] ?? '') : activeModel })
    } else {
      addModels(filteredRemoteModels)
    }
  }

  async function useDefaultPrompt() {
    if (draftGlobalJailbreakPrompt.trim() && !window.confirm('这将删除现有提示词，是否继续？')) return
    setDefaultPromptLoading(true)
    setDefaultPromptError('')
    try {
      const prompt = await loadBundledDefaultPrompt()
      if (!prompt) {
        setDefaultPromptError('无法读取默认提示词')
        return
      }
      setDraftGlobalJailbreakPrompt(prompt)
    } finally {
      setDefaultPromptLoading(false)
    }
  }

  return (
    <div className="modal-layer" role="dialog" aria-modal="true">
      <button className="backdrop" onClick={finish} aria-label="关闭" />
      <section className="modal settings-modal">
        <div className="modal-head"><div><span className="eyebrow">GLOBAL</span><h2>全局设置</h2></div><button className="icon-button" onClick={finish} title="关闭"><X size={20} /></button></div>
        <div className="settings-grid">
          <nav className="provider-nav">
            {draftProviders.map((provider) => <button className={provider.id === active.id ? 'active' : ''} key={provider.id} onClick={() => setDraftActiveProviderId(provider.id)}><span className={provider.apiKey ? 'status-dot online' : 'status-dot'} />{provider.name}</button>)}
            <button className="add-provider" onClick={addProvider}><Plus size={16} />添加 API</button>
          </nav>
          <div className="settings-content">
            <div className="form-section global-prompt-section">
              <div className="form-section-head"><h3>全局破限提示词</h3><button type="button" className="secondary-button compact" onClick={() => void useDefaultPrompt()} disabled={defaultPromptLoading}><RotateCcw size={14} />{defaultPromptLoading ? '读取中' : '使用默认设置'}</button></div>
              <label>提示词<textarea value={draftGlobalJailbreakPrompt} onChange={(event) => setDraftGlobalJailbreakPrompt(event.target.value)} placeholder="对所有RPG生效的全局附加提示词" /></label>
              {defaultPromptError && <div className="inline-error">{defaultPromptError}</div>}
            </div>
            <div className="form-section">
              <div className="form-section-head"><h3>API 配置</h3><button className="danger-icon" onClick={removeProvider} disabled={draftProviders.length === 1} title="删除当前配置"><Trash2 size={17} /></button></div>
              <label>配置名称<input value={active.name} onChange={(event) => updateActive({ name: event.target.value })} /></label>
              <label>Base URL<input value={active.baseUrl} onChange={(event) => updateActive({ baseUrl: event.target.value })} placeholder="https://api.openai.com/v1 或 generativelanguage.googleapis.com/v1beta" autoCapitalize="none" /><small className="field-note">Gemini 地址可填写 googleapis.com、generativelanguage.googleapis.com/v1beta 或 /v1beta/openai，获取模型时会自动规范化。</small></label>
              <label>API Key<input type="password" value={active.apiKey} onChange={(event) => updateActive({ apiKey: event.target.value })} autoCapitalize="none" /></label>
            </div>
            <div className="form-section model-section">
              <div className="form-section-head"><div><h3>模型</h3><span className="section-meta">已添加 {activeModels.length} 个</span></div><button className="secondary-button" onClick={() => void loadRemoteModels()} disabled={modelLoading || !active.baseUrl.trim()}><RefreshCw className={modelLoading ? 'spin' : ''} size={15} />从接口获取</button></div>
              {activeModels.length > 0 ? <div className="added-model-list">{activeModels.map((model) => <div className={`added-model-row ${model === activeModel ? 'active' : ''}`} key={model}><button className="model-select-button" onClick={() => updateActive({ model })}><span className="model-radio">{model === activeModel && <Check size={13} />}</span><span>{model}</span></button><button className="model-remove-button" onClick={() => removeModel(model)} title={`删除 ${model}`}><X size={15} /></button></div>)}</div> : <p className="empty-models">尚未添加模型</p>}
              <div className="manual-model-row"><input value={manualModel} onChange={(event) => setManualModel(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addModels([manualModel]); setManualModel('') } }} placeholder="手动输入模型 ID" autoCapitalize="none" /><button className="icon-button" onClick={() => { addModels([manualModel]); setManualModel('') }} disabled={!manualModel.trim()} title="添加模型"><Plus size={17} /></button></div>
              {modelNotice && <div className="inline-note">{modelNotice}</div>}
              {modelError && <div className="inline-error">{modelError}</div>}
              {remoteModels && <div className="remote-model-picker"><div className="model-picker-head"><div className="model-search"><Search size={15} /><input value={modelSearch} onChange={(event) => setModelSearch(event.target.value)} placeholder="搜索接口模型" /></div><button className="text-button" onClick={toggleFilteredRemoteModels} disabled={!filteredRemoteModels.length}>{allFilteredModelsAdded ? '取消全选' : '全选'}</button></div><div className="remote-model-list">{filteredRemoteModels.map((model) => { const added = activeModels.includes(model); return <label className={added ? 'remote-model-row added' : 'remote-model-row'} key={model}><input type="checkbox" checked={added} onChange={() => toggleRemoteModel(model)} /><span>{model}</span>{added && <small>已添加</small>}</label> })}</div><div className="model-picker-footer"><span>接口返回 {remoteModels.length} 个推荐文本模型，勾选后立即添加</span></div>{remoteSpecializedModels.length > 0 && <details className="specialized-models"><summary>其他模型（不推荐用于纯文本 RPG）<span>{filteredSpecializedModels.length}/{remoteSpecializedModels.length}</span></summary><div className="remote-model-list">{filteredSpecializedModels.map((model) => { const added = activeModels.includes(model); return <label className={added ? 'remote-model-row added' : 'remote-model-row'} key={model}><input type="checkbox" checked={added} onChange={() => toggleRemoteModel(model)} /><span>{model}</span>{added && <small>已添加</small>}</label> })}</div></details>}</div>}
            </div>
          </div>
        </div>
        <div className="modal-footer"><span>这里只管理接口与可用模型</span><button className="primary-button" onClick={finish}>完成</button></div>
      </section>
    </div>
  )
}
