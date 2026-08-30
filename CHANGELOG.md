# Easy Panel 更新记录

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

