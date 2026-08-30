import { ImageOff, RefreshCw, Sparkles } from 'lucide-react'
import type { VisualRuntimeStatus } from '../hooks/useEasyPanelVisual'

interface Props {
  source: string
  status: VisualRuntimeStatus
  error: string
  dimPercent: number
  enabled: boolean
  onGenerate: () => void
  onClear: () => void
}

function statusText(status: VisualRuntimeStatus): string {
  if (status === 'queued') return 'CG 排队中'
  if (status === 'running') return 'CG 生成中'
  if (status === 'saving') return 'CG 保存中'
  if (status === 'completed') return 'CG 已更新'
  if (status === 'error') return 'CG 失败'
  return ''
}

export default function VisualCgLayer({ source, status, error, dimPercent, enabled, onGenerate, onClear }: Props) {
  const working = status === 'queued' || status === 'running' || status === 'saving'
  return (
    <>
      {source && <div className="visual-cg-layer" aria-hidden="true">
        <img src={source} alt="" />
        <div className="visual-cg-dim" style={{ background: `rgba(0, 0, 0, ${Math.max(0, Math.min(80, dimPercent)) / 100})` }} />
      </div>}
      <div className="visual-cg-controls" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
        {(working || status === 'completed' || status === 'error') && <span className={`visual-cg-status ${status}`}>{working && <RefreshCw size={13} className="spin" />}{statusText(status)}{status === 'error' && error ? `：${error}` : ''}</span>}
        {enabled && <button type="button" className="visual-cg-icon-button" onClick={onGenerate} disabled={working} title="重新生成当前剧情 CG"><Sparkles size={16} /></button>}
        {source && <button type="button" className="visual-cg-icon-button" onClick={onClear} title="隐藏并删除当前 CG"><ImageOff size={16} /></button>}
      </div>
    </>
  )
}
