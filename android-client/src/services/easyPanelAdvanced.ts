import { Capacitor, registerPlugin } from '@capacitor/core'
import { normalizeEasyPanelBaseUrl } from './easyPanelVisual'

export interface EasyPanelAdvancedOpenOptions {
  url: string
}

export interface EasyPanelDownloadResult {
  saved: boolean
  filename: string
  location: string
}

interface EasyPanelAdvancedPlugin {
  open(options: EasyPanelAdvancedOpenOptions): Promise<{ opened: boolean }>
  saveBase64(options: { filename: string; mimeType: string; base64: string }): Promise<EasyPanelDownloadResult>
}

const advancedPanelPlugin = registerPlugin<EasyPanelAdvancedPlugin>('EasyPanelAdvanced')

/** Build the same-origin Easy Panel URL used by the native advanced viewer. */
export function buildAdvancedPanelUrl(value: string): string {
  const baseUrl = normalizeEasyPanelBaseUrl(value)
  const url = new URL(baseUrl)
  url.pathname = '/'
  url.search = ''
  url.hash = ''
  url.searchParams.set('mobile', '1')
  return url.toString()
}

/**
 * Open the computer's complete Easy Panel without copying its workflow logic
 * into the Android quick-generation screen. The RPG token is intentionally not
 * passed to the native Activity or included in the URL.
 */
export async function openAdvancedPanel(value: string): Promise<string> {
  const url = buildAdvancedPanelUrl(value)
  if (Capacitor.getPlatform() === 'android') {
    await advancedPanelPlugin.open({ url })
    return url
  }

  if (typeof window === 'undefined') throw new Error('当前运行环境无法打开高级面板。')
  const opened = window.open(url, '_blank', 'noopener,noreferrer')
  if (!opened) throw new Error('高级面板被浏览器拦截，请允许打开新窗口。')
  return url
}

export async function saveBase64ToPublicDownloads(
  filename: string,
  mimeType: string,
  base64: string,
): Promise<EasyPanelDownloadResult> {
  if (Capacitor.getPlatform() !== 'android') throw new Error('当前运行环境不支持原生下载保存。')
  return advancedPanelPlugin.saveBase64({ filename, mimeType, base64 })
}
