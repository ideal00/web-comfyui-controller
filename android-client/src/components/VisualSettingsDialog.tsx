import { CheckCircle2, Clipboard, Image, RefreshCw, X } from 'lucide-react'
import { useState } from 'react'
import { EasyPanelHttpError, getEasyPanelCapabilities, pingEasyPanel } from '../services/easyPanelVisual'
import { EASY_PANEL_SUGGESTED_BASE_URL, normalizeVisualSettings, type EasyPanelVisualSettings } from '../lib/visualState'

interface Props {
  value: EasyPanelVisualSettings
  onChange: (value: EasyPanelVisualSettings) => void
  onClose: () => void
}

export default function VisualSettingsDialog({ value, onChange, onClose }: Props) {
  const [draft, setDraft] = useState<EasyPanelVisualSettings>(() => ({ ...value }))
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null)
  const [pasteMessage, setPasteMessage] = useState<string | null>(null)

  const hasBaseUrl = Boolean(draft.baseUrl.trim())
  const hasToken = Boolean(draft.token.trim())
  const missingFields = [
    !hasBaseUrl ? '电脑地址' : '',
    !hasToken ? 'Token' : '',
  ].filter(Boolean)

  function patch(next: Partial<EasyPanelVisualSettings>) {
    setDraft((current) => ({ ...current, ...next }))
    if ('baseUrl' in next || 'token' in next) setTestResult(null)
  }

  function finish() {
    onChange(normalizeVisualSettings(draft))
    onClose()
  }

  async function testConnection() {
    const normalized = normalizeVisualSettings(draft)
    if (!normalized.baseUrl || !normalized.token) {
      const missing = [
        !normalized.baseUrl ? '电脑地址' : '',
        !normalized.token ? 'Token' : '',
      ].filter(Boolean)
      setTestResult({ ok: false, text: `无法测试：缺少${missing.join('和')}` })
      return
    }

    setDraft((current) => ({ ...current, baseUrl: normalized.baseUrl, token: normalized.token }))
    setTesting(true)
    setTestResult(null)
    let stage: 'ping' | 'capabilities' = 'ping'
    try {
      const config = { baseUrl: normalized.baseUrl, token: normalized.token, pollIntervalMs: normalized.pollIntervalMs }
      const result = await pingEasyPanel(config)
      if (!result.ok) throw new Error('服务器返回 ok=false')
      stage = 'capabilities'
      await getEasyPanelCapabilities(config)
      setTestResult({ ok: true, text: `连接成功 · ping 正常 · Token 鉴权通过 · capabilities 正常 · API v${result.api_version}` })
    } catch (error) {
      setTestResult({ ok: false, text: describeConnectionFailure(error, stage) })
    } finally {
      setTesting(false)
    }
  }

  async function pasteToken() {
    setPasteMessage(null)
    try {
      if (!navigator.clipboard?.readText) throw new Error('clipboard-unavailable')
      const text = (await navigator.clipboard.readText()).trim()
      if (!text) {
        setPasteMessage('剪贴板为空，请先复制令牌内容')
        return
      }
      patch({ token: text })
      setPasteMessage('已粘贴令牌内容（不会显示明文）')
    } catch {
      setPasteMessage('无法读取剪贴板，请长按输入框粘贴令牌内容')
    }
  }

  const testHint = testing
    ? '正在依次验证 ping、Token 鉴权和 capabilities'
    : missingFields.length > 0
      ? `暂不可测试：请先填写${missingFields.join('和')}`
      : '点击后将依次验证 ping、Token 鉴权和 capabilities'

  return (
    <div className="modal-layer" role="dialog" aria-modal="true">
      <button className="backdrop" onClick={finish} aria-label="关闭" />
      <section className="modal visual-settings-modal">
        <div className="modal-head">
          <div><span className="eyebrow">VISUAL</span><h2>Easy Panel 剧情 CG</h2></div>
          <button className="icon-button" onClick={finish} title="关闭"><X size={20} /></button>
        </div>

        <div className="visual-settings-scroll">
          <div className="form-section">
            <div className="form-section-head"><h3>手机生图服务器</h3><Image size={17} /></div>
            <label className="visual-toggle-row"><input type="checkbox" checked={draft.enabled} onChange={(event) => patch({ enabled: event.target.checked })} /><span>启用 Easy Panel 剧情 CG</span></label>
            <label>Easy Panel 地址<input value={draft.baseUrl} onChange={(event) => patch({ baseUrl: event.target.value })} placeholder="请输入，如 http://电脑IP:8190" autoCapitalize="none" /></label>
            {!hasBaseUrl && <p className="visual-field-status visual-field-missing">当前未配置</p>}
            {EASY_PANEL_SUGGESTED_BASE_URL && <p className="visual-settings-hint visual-address-suggestion">本机当前 WLAN 建议地址（电脑 IP 变化后需更新）：<button type="button" className="visual-suggestion-link" onClick={() => patch({ baseUrl: EASY_PANEL_SUGGESTED_BASE_URL })}>{EASY_PANEL_SUGGESTED_BASE_URL}</button></p>}
            <label>RPG Token（粘贴文件内容）
              <span className="visual-input-action-row">
                <input type="password" value={draft.token} onChange={(event) => patch({ token: event.target.value })} onBlur={() => patch({ token: draft.token.trim() })} placeholder="粘贴令牌内容（不是文件名）" autoCapitalize="none" autoComplete="off" />
                <button type="button" className="secondary-button visual-paste-button" onClick={() => void pasteToken()} disabled={testing}><Clipboard size={15} />粘贴</button>
              </span>
            </label>
            {!hasToken && <p className="visual-field-status visual-field-missing">当前未配置</p>}
            {pasteMessage && <p className="visual-paste-status">{pasteMessage}</p>}
            <div className="visual-test-row">
              <button className="secondary-button" onClick={() => void testConnection()} disabled={testing || !hasBaseUrl || !hasToken}><RefreshCw size={15} className={testing ? 'spin' : ''} />{testing ? '测试中' : '测试连接'}</button>
              <span className="visual-test-hint">{testHint}</span>
              {testResult && <span className={testResult.ok ? 'visual-test-ok' : 'visual-test-error'}>{testResult.ok && <CheckCircle2 size={14} />}{testResult.text}</span>}
            </div>
          </div>

          <div className="form-section">
            <div className="form-section-head"><h3>自动生成</h3></div>
            <label>生成策略
              <select value={draft.autoMode} onChange={(event) => patch({ autoMode: event.target.value as EasyPanelVisualSettings['autoMode'] })}>
                <option value="manual">仅手动</option>
                <option value="scene-change">场景变化时自动生成</option>
                <option value="every-turn">每轮剧情自动生成</option>
              </select>
            </label>
            <p className="visual-settings-hint">推荐“场景变化”：地点、时间、在场角色或主要表情变化时才请求新 CG，不会每句对白都占用显卡。</p>
          </div>

          <div className="form-section">
            <div className="form-section-head"><h3>生成参数</h3></div>
            <label>Checkpoint（留空由 Easy Panel 自动选择）<input value={draft.model} onChange={(event) => patch({ model: event.target.value })} placeholder="waiIllustrious...safetensors" autoCapitalize="none" /></label>
            <div className="visual-grid-two">
              <label>宽度<input type="number" min={512} max={2048} step={64} value={draft.width} onChange={(event) => patch({ width: Number(event.target.value) })} /></label>
              <label>高度<input type="number" min={512} max={2048} step={64} value={draft.height} onChange={(event) => patch({ height: Number(event.target.value) })} /></label>
            </div>
            <label className="visual-toggle-row"><input type="checkbox" checked={draft.regional} onChange={(event) => patch({ regional: event.target.checked })} /><span>双人时启用 Regional Prompting</span></label>
            <label>Safety Level<input value={draft.safetyLevel} onChange={(event) => patch({ safetyLevel: event.target.value })} /></label>
            <label>额外负面词<textarea value={draft.negative} onChange={(event) => patch({ negative: event.target.value })} placeholder="可留空，继续使用 Easy Panel 默认负面词" /></label>
          </div>

          <div className="form-section">
            <div className="form-section-head"><h3>显示</h3></div>
            <label>CG 暗化 {draft.dimPercent}%<input type="range" min={0} max={80} step={1} value={draft.dimPercent} onChange={(event) => patch({ dimPercent: Number(event.target.value) })} /></label>
            <label>轮询间隔（毫秒）<input type="number" min={800} max={10000} step={100} value={draft.pollIntervalMs} onChange={(event) => patch({ pollIntervalMs: Number(event.target.value) })} /></label>
          </div>
        </div>

        <div className="modal-footer"><span>设置仅保存在本机 RPGBox</span><button className="primary-button" onClick={finish}>保存</button></div>
      </section>
    </div>
  )
}

function describeConnectionFailure(error: unknown, stage: 'ping' | 'capabilities'): string {
  const stageLabel = stage === 'ping' ? 'ping' : 'Token 鉴权 / capabilities'
  if (error instanceof EasyPanelHttpError) {
    if (error.status === 401 || error.status === 403) {
      return `${stageLabel}失败（HTTP ${error.status}）：Token 无效或未被接受${error.message && !/^HTTP \d+$/u.test(error.message) ? `：${error.message}` : ''}`
    }
    if (error.status === 404) return `${stageLabel}失败（HTTP 404）：没有找到 Easy Panel 接口，请检查电脑 IP 和 8190 端口`
    return `${stageLabel}失败（HTTP ${error.status}）${error.message && !/^HTTP \d+$/u.test(error.message) ? `：${error.message}` : ''}`
  }
  if (error instanceof Error && error.name === 'TypeError') {
    return `${stageLabel}失败：无法连接到电脑地址，请检查电脑 IP、8190 端口和是否处于同一局域网`
  }
  const detail = error instanceof Error ? error.message.trim() : ''
  return `${stageLabel}失败${detail ? `：${detail}` : '：连接失败，请检查电脑地址和 Easy Panel 服务'}`
}
