# Easy Panel 更新记录

## Android 客户端 mobile-v1.4.5（2026-08-31）

- 快速生图新增与桌面高级面板共用的中文描述转换；服务端会把当前模型族规则写入 DeepSeek 指令。
- 手机可复制并打开 DeepSeek、读取或粘贴回答后分别加入正向/负面提示词，不会因转换操作自动提交任务。
- 历史快照默认收起，标题可展开；刷新和恢复操作保持不变。
- 本地构建 Debug APK，未推送仓库或发布 GitHub Release。

## Android 客户端 mobile-v1.4.4（2026-08-31）

- 作品库缩略图改为可视区域优先、限并发队列，并使用服务端 360px 预览图，避免首屏一次性下载整页原图。
- 原图预览支持双指缩放、单指拖动、双击放大/还原。
- 本地生成 Debug APK，未推送仓库或发布 GitHub Release。

## Android 客户端 mobile-v1.4.3（2026-08-31）

- 作品库详情支持点击缩略图查看带鉴权读取的原图，并可在原图预览层下载。
- 作品库新增加载更多分页，可继续浏览最近 30 条之外的历史作品；服务端仍兼容 `2.2.2`。
- 本地生成 Debug APK，未推送仓库或发布 GitHub Release。

## Easy Panel 服务端 2.2.2 + Android 客户端 mobile-v1.4.2（2026-08-31）

- Creative Library Foundation 使用可重建的稳定 generation / artifact ID；保留安全但缺失的输出引用并阻止图片接口提供缺失文件。
- 提供历史随机 ID 的迁移 dry-run、备份、原子应用和回滚工具；本次部署前会先对正式数据库做只读预检。
- Web / Android 作品恢复只记录一次性父作品关系；多图提交共享本次关系，恢复不会自动选择具体输出作为图生图 / 重绘输入。
- Android versionCode 升级为 `1004002`；当前仅生成本地 Debug 验收包，未发布 GitHub Release。

## Easy Panel 服务端 2.2.1 + Android 客户端 mobile-v1.4.1（2026-08-31）

- 修复旧 `generation_snapshots.json` / `rpg_jobs.json` 迁移：已有 `outputs`、`images` 或 `artifacts` 的记录现在显示为 `completed`，不会再因缺少显式 status 被误标为 `queued`。
- 明确错误记录优先保留 `error`；已完成、失败或取消的终态不会在重复导入时被降级或互相覆盖；旧 SQLite 索引可通过幂等重建纠正此前错误的排队状态。
- 迁移仍为单向读取，源 JSON 不会被写回；缺失输出文件只记录警告，不删除作品库记录。
- Android versionCode 升级为 `1004001`；Debug APK 构建产物和 SHA256 清单见发布页附件。

## Easy Panel 服务端 2.2.0 + Android 客户端 mobile-v1.4.0（2026-08-31）

- 新增桌面 Web「作品库」：分页、操作 / 状态 / 模型筛选、排序、缩略图、详情、LoRA、输出下载和父子谱系。
- Android 快速页面与桌面 Web 共享只读 SQLite 创作索引；复现、换 Seed、继续编辑只回填当前表单，必须手动点击“生成图片”。
- 输出图片继续使用带 RPG 鉴权的安全路径；旧服务端、空索引、断网、缺 Token 和缺失输出均显示可读回退。
- Android versionCode 升级为 `1004000`；Debug APK 构建产物和 SHA256 清单见发布页附件。

## Easy Panel 服务端 2.1.0 + Android 客户端 mobile-v1.3.0（2026-08-31）

- 生成快照升级为可审计的完整源数据、最终提示词、采样原因、LoRA trigger、自动注入、去重和冲突诊断记录。
- 远程访问保护完整网页、旧版 API、快照详情/对比和输出图片；浏览器使用 Basic 引导签名 HttpOnly 会话，Android 原生 WebView 只在首个根请求发送 Token 请求头。
- Android 历史快照支持完整恢复、只换 Seed、继续编辑并聚焦提示词；解除附加高级配置后恢复普通生图提交语义。
- DeepSeek 网页转换复制失败时显示完整只读指令，原生剪贴板桥仅接受受信 Easy Panel 页面，复制成功后才打开外部 DeepSeek。
- 保持 Token 不进入 URL、网页 JavaScript、localStorage、剪贴板指令文本或公共仓库。

## Android 客户端 mobile-v1.2.5（2026-08-31）

- 新增跨设备共享状态：把 Easy Panel 浏览器已有的提示词预设和角色/LoRA 收藏安全合并到独立的 `easy_panel_shared_state.json`。
- 桌面浏览器首次升级后自动迁移；Android 高级面板进入同一 Easy Panel 地址时自动读取，页面也提供“立即同步”和冲突/离线状态提示。
- 共享文件使用 schema/version 校验、4 MB 上限、原子写入、`.bak` 备份、损坏恢复和 revision 冲突保护；空手机数据不会清空电脑数据。
- 共享状态不写入日志，不包含 Token；`lora_notes.json`、模型、API Key 和个人数据仍不进入仓库。

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

