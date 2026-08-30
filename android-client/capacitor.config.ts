import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'app.rpgbox.mobile',
  appName: 'Easy Panel Mobile',
  webDir: 'dist',
  loggingBehavior: 'none',
  android: {
    allowMixedContent: true,
  },
}

export default config
