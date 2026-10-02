# 发布、同步与检查

代码、安装器副本、服务端 ZIP 与手机 APK 是四种不同产物。`main` 已同步并不代表下载页的包已经更新。发布时按以下顺序处理。

## 版本约定

- 服务端唯一版本源：`easy_panel.py` 的 `PANEL_VERSION`，标签为 `v<版本>`。
- Android 唯一版本源：`android-client/package.json` 的 `version`，标签为 `mobile-v<版本>`。Gradle 自动计算 versionCode：`major * 1000000 + minor * 1000 + patch`。
- 同步更新 README、快速开始、功能对照、RPG API 与手机说明中的当前版本；历史更新记录保留历史版本。
- 每个标签对应 `docs/releases/<标签>.md`。创建新标签，不移动已经发布的标签。

## 本地验证

需要 Python 3.10+ 与 Pillow、Node.js、PowerShell 7。构建脚本使用 PowerShell 7 的路径与 JSON API；安装器 `.cmd` 仍支持系统自带的 Windows PowerShell。

```powershell
Set-Location <仓库目录>
python -m pip install -r requirements-image-tools.txt
python -m unittest discover -s tests
node --test (Get-ChildItem tests/*.node-test.cjs).FullName
pwsh -NoProfile -File installers/Build-Packages.ps1
python tools/verify_release.py --packages
Set-Location android-client
pnpm install --frozen-lockfile
pnpm test
pnpm android:apk
```

Python 与 pnpm 使用自己的实际命令 / 路径。Android 构建还需要 Java 21 与 Android SDK 35；Windows 可在 `android` 中执行 `gradlew.bat testDebugUnitTest --no-daemon` 验证原生逻辑。

`verify_release.py` 检查当前版本文档、所有前端资源、安装器副本逐字节一致、七个 ZIP、SHA256 和包内个人运行文件。`Build-Packages.ps1` 从源码同步 `easy_panel_app`、`web`、`docs` 等文件，不读取维护者未入库的 LoRA 导入清单。个人图库、预设备份、Token、模型与运行数据库不进入发布包。

历史个人 LoRA 导入审计不属于公开版本回归，默认跳过；需要审核旧导入记录时，准备对应 `lora_imports` 和当时的备注数据，再显式设置 `EASY_PANEL_AUDIT_LOCAL_LORAS=1`。当前备注可继续编辑，不能用旧历史记录的数量断言判断公开代码是否正确。

## GitHub 自动发布

1. 提交源码、教程、安装器副本及本次验证过的 ZIP；用 `git diff --cached --stat` 检查发布范围，不暂存个人数据。
2. 推送 `main`，确认 Easy Panel 和 Android 两个工作流成功。
3. 创建并推送对应版本标签。示例：

```powershell
git tag v2.3.5
git push origin v2.3.5
```

服务端标签触发 Windows 回归、重建七个安装器 ZIP、校验包内容，然后发布 ZIP 与 `SHA256SUMS.txt`。只有 Android 本身有新版本时，再创建新的 `mobile-v<版本>` 标签，触发 JavaScript / 原生测试、Capacitor 同步、Debug APK 构建与发布。双端同时升级时，两个新标签指向本次验证的同一提交；只更新服务端网页时保留现有 APK 和手机标签，不重复创建或移动已发布标签。

工作流运行中的包可从 Actions 下载；正式下载链接只有发布完成后才有效。Android 使用 Debug 签名，自动构建环境与维护者本机的签名可能不同；若覆盖安装提示签名冲突，应先备份客户端设置，再处理安装。正式签名发行需要另行配置自己的稳定签名密钥。

## 发布后验收

- 比较 `git rev-list --left-right --count HEAD...origin/main`，应为 `0 0`；用 `git status --short` 检查剩余改动。
- 确认新标签指向本次验证的提交，Release 的附件数量和校验文件正确；同步发布的双端标签应一致，继续配套的旧 APK 保留原标签。手机发布不会覆盖服务端 Latest。
- 解压 Core，检查版本、前端、教程与源代码一致。APK 的 versionName、versionCode 和包名应与版本约定相符。
- 在目标电脑和手机验证连接、文件选择器、下载、恢复快照与一次实际出图。自动测试和构建成功不等于真机或 GPU 验收完成。

发布说明中列明本次实际完成的检查，避免沿用上一版本的验收结论。
