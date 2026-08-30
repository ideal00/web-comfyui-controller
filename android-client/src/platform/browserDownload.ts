import { blobToBase64 } from '../services/easyPanelVisual'
import { saveBase64ToPublicDownloads } from '../services/easyPanelAdvanced'
import { isAndroidRuntime } from './runtime'

export interface BrowserDownloadResult {
  saved: boolean
  filename: string
  location: string
}

export async function downloadBlob(blob: Blob, fileName: string): Promise<BrowserDownloadResult> {
  if (isAndroidRuntime()) {
    const result = await saveBase64ToPublicDownloads(fileName, blob.type || 'application/octet-stream', await blobToBase64(blob))
    return {
      saved: result.saved,
      filename: result.filename,
      location: result.location,
    }
  }

  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.style.display = 'none'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
  return { saved: true, filename: fileName, location: '浏览器下载目录' }
}
