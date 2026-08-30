# Easy Panel 更新记录

## Android 客户端 mobile-v1.2.4（2026-08-30）

- 新增 `android-client/`，包含快速生图与电脑端完整高级面板入口。
- 快速页支持 LAN / Tailscale / MagicDNS 地址、实际模型列表选择、异步任务恢复和显式生成。
- Android 下载保存到系统 `Downloads`，兼容 MediaStore、旧版存储权限和重复文件名。
- 高级面板当前图、历史/画廊原图、HTTP、Blob、data URL 与脚本下载统一接入同源校验、大小限制和安全文件名处理。
- Android 客户端补充 Easy Panel 品牌图标、圆形/自适应密度资源与启动图；前景保持在安全区内。
- 高级面板支持移动响应式布局、文件选择器、返回键、刷新、加载错误提示和页面下载。
- 提供 Android Debug 构建 CI；Debug APK 仅用于测试，不代表商店签名版本。
- 未提交 Token、API Key、模型权重、个人局域网地址、构建缓存或签名文件。

详细安装和验收步骤见 [android-client/README.md](android-client/README.md)。

## 工作树发布版（2026-08-30）

本次发布把本机已完成并经过本地测试的功能、前端资源和一键安装包统一同步到仓库：

- 增加提示词冲突诊断、提示词来源追踪和可关闭的自动提示词片段开关。
- 增加生成快照与模型/LoRA 文件指纹，支持恢复参数、复现任务和检查环境差异。
- 完善 LoRA 同名 TXT 读取、分项备忘、别名迁移和安全的 LoRA 导入工具。
- 增加 RPGBox 手机视觉接口、质量档、轮询状态、图片回传和移动端启动入口。
- 增加手部修复工作台、内置 miniPaint、透明背景、功能编辑器、提示词预设和图片查看辅助功能。
- 保留 Illustrious、Anima、Krea 2、姿势、多人区域、局部修复、调色和模型检查功能。
- 更新 Core / LoRA Tools / Pose / Color / Tags / Models / All 七个安装包及 SHA-256 清单。

## 发布边界

- 安装包不包含模型权重、API Key、RPG Token、运行日志、生成历史和任务队列。
- `lora_notes.json`、备份目录及本机导入审计属于本地数据，不应提交到公共仓库。
- RPG Token 由用户在本机运行目录配置，接口文档只描述变量和请求格式，不记录令牌值。

## 安装

解压 `installers/packages/EasyPanel-All-OneClick.zip`，双击其中的安装命令文件；只安装核心时使用 `EasyPanel-Core-OneClick.zip`。安装器会在覆盖前备份已有面板文件。

