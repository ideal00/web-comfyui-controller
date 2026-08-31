/// <reference types="vite/client" />

interface Window {
  EasyPanelClipboard?: {
    copyText(value: string): boolean
  }
  rpgboxDesktop?: {
    platform: 'desktop'
    version: string
    readValue(key: string): Promise<string | null>
    writeValue(key: string, value: string): Promise<void>
    savePortrait(gameId: string, characterId: string, fileName: string, base64: string): Promise<string>
    readPortrait(uri: string): Promise<string>
    deletePortrait(uri: string): Promise<void>
  }
}
