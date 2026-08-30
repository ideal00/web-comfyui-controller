# Easy Panel Mobile Android 客户端

这个目录是 Easy Panel 的 Android 客户端源码。它只控制电脑上的 Easy Panel / ComfyUI，不在手机上运行模型。

![Easy Panel Mobile 品牌图标](android/app/src/main/res/drawable-nodpi/easy_panel_brand_source.png)

图标源图保存在 `android/app/src/main/res/drawable-nodpi/easy_panel_brand_source.png`；Android 自适应图标、圆形/传统密度图标和启动图均由同一品牌标记生成，前景内容留在安全区内，未修改包名。

## 两种模式

- **快速生图**：手机编辑正向提示词、负向提示词、Checkpoint、质量档位、宽高和轮询间隔；只有点击“生成图片”才提交任务。模型列表来自 Easy Panel 的 `/api/rpg/models`，任务通过 API v2 异步执行。
- **高级面板**：打开电脑端正在运行的完整 Easy Panel 页面，继续使用角色、LoRA、ControlNet、OpenPose、多人区域、修复、透明背景、调色、历史和快照等原有功能。客户端没有复制这些工作流逻辑；同一地址下的提示词预设和角色/LoRA 收藏会由网页自动读取共享状态。

Android 高级面板通过原生 WebView 承载电脑页面，支持返回键、刷新、加载/错误提示、系统文件选择器和页面下载。手机快速页的图片保存到系统 `Downloads`。

## 连接电脑

1. 先在电脑启动 Easy Panel 和 ComfyUI。推荐使用仓库中的 `launchers/Start_EasyPanel_Mobile_RPG.bat`。
2. ComfyUI 继续只监听电脑本机 `127.0.0.1:8188`；手机只访问 Easy Panel `8190`。
3. 手机与电脑同一局域网时，在 App 填写 `http://<电脑当前局域网IP>:8190`。
4. 跨网络时，确保两端登录同一个 Tailscale 网络，填写 `http://<电脑的100.x.x.x地址>:8190` 或 `http://<电脑MagicDNS主机名>:8190`。
5. Token 文件位于 Easy Panel 运行目录：`rpg_mobile_token.txt`。将文件内容粘贴到 App 的 RPG Token 输入框；首尾空白会清理，Token 不会写入高级面板 URL。
6. 点击“测试连接”。成功后点击“读取模型”，或重新测试连接让客户端自动读取模型。

不要把 `8188` 或 `8190` 端口直接映射到公网。优先使用 Tailscale；如果必须跨网络暴露，应使用受控的 HTTPS 反向代理和额外访问控制。

### 跨设备预设与收藏

桌面浏览器首次打开新版 Easy Panel 会自动把已有的 `easyPanelPromptPresetsV1` 和 `easyPanelLoraFavoritesV1` 合并到服务器的 `easy_panel_shared_state.json`；高级面板在 Android 上打开同一个 Easy Panel 地址后会自动读取，也可以点击页面里的“立即同步”。同步不会把 Token 放进 URL。服务器文件位于 Easy Panel 项目目录，上一版成功内容在 `easy_panel_shared_state.json.bak`；主文件读取失败时优先用备份恢复，只有主文件与备份都不可用时才会把损坏主文件改名为 `.corrupt.*.json`。离线时本机数据不清除，revision 冲突时服务器较新的记录不被手机覆盖，空手机集合也不会清空服务器收藏。

升级代码后请手动重启电脑端 Easy Panel 进程，再在 Android 高级面板刷新页面；不需要为这项同步重启 ComfyUI 8188。

## 安装与下载

发布页：<https://github.com/ideal00/web-comfyui-controller/releases/tag/mobile-v1.2.5>

该发布物是 Debug / 测试签名 APK，不是 Google Play 发布签名。可直接下载 `app-debug.apk` 安装；卸载旧测试版或使用 `adb install -r` 覆盖安装。

安装后验收：

1. 连接电脑并测试 Token。
2. 确认 Checkpoint 下拉框出现电脑端实际模型。
3. 修改质量、模型、尺寸和提示词，确认不会自动生成；点击“生成图片”后才提交一次。
4. 出图后点击“下载图片”，在系统 `Downloads` 中检查文件。重复下载会自动使用不覆盖的文件名。
5. 点击“高级面板”，测试完整页面的上传、生成、当前图/历史图下载、Blob/Data URL 下载、刷新和返回。

## 权限与下载

- Android 10 及以上使用 MediaStore 写入公共 `Downloads`，不要求旧式外部存储权限。
- Android 9 及以下在首次保存时请求 `WRITE_EXTERNAL_STORAGE`；拒绝后会显示明确失败信息，不会静默丢文件。
- 高级面板的同源 HTTP/HTTPS 下载由原生流式下载写入公共 `Downloads`；Blob / data URL 和脚本触发的下载由 WebView 桥接到同一目录。文件名、MIME、大小、重定向和来源会在原生侧复核。
- 浏览器运行时仍使用普通 Blob 下载，不依赖 Android 原生插件。

## 本地构建

需要 Node.js、pnpm、Java 21 和 Android SDK 35。进入本目录后执行：

```powershell
corepack enable
pnpm install --frozen-lockfile
pnpm test
pnpm build
pnpm android:apk
```

如需单独运行 Android 原生单测：

```powershell
Set-Location android
.\gradlew.bat testDebugUnitTest --no-daemon
```

APK 输出到：

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

GitHub Actions 只构建 Debug artifact，不使用秘密、不发布未签名 Release，也不会上传 Token、密钥或本地配置。完整 RPG / CG 源码仍保留在客户端目录，因为 Vite 的类型检查和构建入口会编译这些现有模块；模型权重、角色资源、个人数据和 Electron 构建文件不包含在 Android 发布包中。

## 安全与已知限制

- 手机端保存的 Token 使用本机存储，仅作为 `X-RPG-Token` 请求头发送到用户填写的 Easy Panel 地址。
- 高级面板 URL 只允许 HTTP/HTTPS 根地址，并最多附带 `mobile=1`；不会附带 Token。
- 高级面板下载桥只接受已验证的 Easy Panel 同源地址；Token、Authorization、API key 和 secret 不允许出现在下载 URL，也不会写入日志。
- ComfyUI `8188` 不应从手机直接访问；高级页面中电脑专用入口会隐藏，原生容器也会拦截到 `8188` 的导航。
- 本次发布已完成 TypeScript、Vitest/Node、Android 原生单测、Web、Capacitor、Gradle、APK 元数据、敏感信息和局域网只读检查；发布环境没有连接 Android 真机。
- 因此 Android 文件选择器、返回键、MediaStore 实际落盘、不同系统版本权限弹窗、Tailscale 从手机的实际可达性和真实 GPU 出图仍需在目标设备上验收。

## APK 校验

下载 APK 后，在 PowerShell 执行：

```powershell
Get-FileHash -Algorithm SHA256 .\app-debug.apk
```

发布 APK 的 SHA256 以发布页附件旁的 `app-debug.apk.sha256` 为准。

本次 `mobile-v1.2.5` Debug APK（不含本机模型与个人 RPG 资源）的 SHA256：

```text
8368123CE0BF543AD7F2DAB9E12C739F4C0930E18EE57FA16D4B8C7038DF804A
```
