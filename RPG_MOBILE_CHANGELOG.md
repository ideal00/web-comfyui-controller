# RPG Mobile Bridge 修改说明

## mobile-v1.4.1（2026-08-31）

- Android versionCode 升级为 `1004001`，配套 Easy Panel 服务端 `2.2.1`。
- 修复只读作品库迁移状态：旧记录只要已有 `outputs`、`images` 或 `artifacts` 就显示为 `completed`；明确 error、completed、cancelled 终态在重复导入时保持不变。
- 重建仍只写 SQLite 索引，不修改快照、任务或其他用户 JSON；缺失的图片文件只显示警告，不删除记录。

## mobile-v1.4.0（2026-08-31）

- Android versionCode 升级为 `1004000`，配套 Easy Panel 服务端 `2.2.0`。
- Android 与桌面 Web 共用只读作品库 API：历史作品、LoRA、输出、父子谱系和有限筛选。
- 作品库的复现、换 Seed、继续编辑只回填当前表单；用户仍需手动点击“生成图片”，不会自动提交。
- 发布物包含 Debug APK、`app-debug.apk.sha256` 和 `SHA256SUMS.txt`；不含 Token、模型权重或个人运行数据。

## mobile-v1.3.0（2026-08-31）

- Android versionCode 升级为 `1003000`；快速页与电脑端高级面板继续使用同一个 Easy Panel `2.1.0` 服务。
- 新增服务端快照摘要/详情鉴权、完整恢复、只换 Seed、继续编辑和解除快照高级配置。
- 新增模型/质量策略、采样原因、LoRA trigger 来源、自动注入、去重/覆盖/冲突诊断和最终提示词的只读解释。
- 高级 WebView 通过原生首请求头引导短时 HttpOnly 会话；DeepSeek 复制失败时显示完整指令，原生剪贴板桥通过 Easy Panel 来源校验。

## mobile-v1.2.5

- Easy Panel 增加独立的跨设备浏览器共享状态 API，覆盖现有提示词预设和角色/LoRA 收藏。
- 同步使用原子 JSON、备份/损坏恢复、大小与 schema 校验、revision 冲突保护；空客户端不会清空服务器数据。
- Android 高级面板沿用同源网页入口，不复制同步业务逻辑；升级后需重启 Easy Panel 进程加载新后端。

## 本次完成

- RPG API 升级到 v2。
- 修复 ComfyUI 子目录输出导致手机端 404。
- 增加 requestId 幂等提交，避免移动网络重试重复生成。
- 增加按 requestId 恢复任务。
- 增加 `/api/rpg/capabilities`。
- 增加安全的输出图片路径解析。
- 增加 RPGBox TypeScript 手机客户端 SDK。
- RPG 专项测试：7/7 通过。
- 全项目测试：运行到 51 项无失败后，被当前执行环境单次命令时限中断，因此未声明全量通过。

## 推荐运行方式

Windows 下运行 `launchers/Start_EasyPanel_Mobile_RPG.bat`。手机与电脑同一局域网时，在 RPGBox 中填写脚本显示的 `http://电脑IP:8190` 和 Token。
