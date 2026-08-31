# Easy Panel 3.x 创作状态（Phase 1）

本阶段在现有 Easy Panel 2.x JSON 快照 / RPG job 记录旁边增加一个可重建、只读查询优先的 SQLite 索引，并在 Android 快速页面提供最小作品库。JSON 仍是复现的唯一事实来源；SQLite 只做旁路索引，不会改写、删除或替代 `generation_snapshots.json`、`rpg_jobs.json`。

## 数据边界

- 默认索引：`creative_index.sqlite3`。
- 可通过 `EASY_PANEL_CREATIVE_INDEX` 指定路径。
- 新提交的 `/api/rpg/generate`、`/api/generate` 和 `/api/generate-batch` 在已有 JSON 快照写入后 best-effort 建索引；索引失败不会让原有生图请求失败。
- RPG job 查询和 `/api/snapshot-outputs` 完成回写时同步状态 / 输出引用。状态同步同样 best-effort。
- 输出文件只接受安全的 ComfyUI `{filename, subfolder, type}` 引用；指定 `output_root` 时，缺失文件、路径穿越和越出输出目录的引用会跳过并进入 warnings。
- 索引 JSON 字段经过限制和 credential-shaped key 清理；Token、Authorization、Cookie、密码、API key 等不会进入新索引。

## SQLite v1

`CreativeIndex` 在每个写操作中使用事务、`PRAGMA foreign_keys=ON` 和 busy timeout。生成 ID 是首次入索引时产生的 32 位十六进制随机值，之后通过 `snapshot_id` / `prompt_id` / `request_id` 幂等定位，不使用可预测的时间戳 ID。

| 表 | 作用 |
| --- | --- |
| `generations` | 作品摘要、状态、模型 / Seed / 尺寸 / 版本，以及完整的 `snapshot_json` 和分层 `input_json`、`compiled_json`、`inference_json`、`workflow_json`、`error_json` |
| `artifacts` | 输出文件引用、存在性、类型和安全 URL；外键删除随生成记录级联 |
| `derivations` | 父 / 子作品或父 / 子 artifact 的有向边，记录操作和元数据 |
| `generation_loras` | 按 position 保存 LoRA 名称、权重、trigger、role、source；角色和画风仍按已有来源分层 |
| `schema_meta` | 当前索引 schema 版本 |

当前操作枚举为 `txt2img`、`seed_variant`、`img2img`、`inpaint`、`face_fix`、`hand_fix`、`upscale`、`outfit_change`、`scene_change`、`style_change`。无法判断的新操作安全落为 `unknown`，不会阻止索引或读取。

## 迁移与重建

首次打开空库或 v0 库会在事务中创建 v1 表；已存在的部分 v0 表只执行可回滚的加法列迁移。版本高于当前代码时拒绝写入，避免误降级。迁移失败不会修改源 JSON。

已有数据可显式重建：

```powershell
python tools/rebuild_creative_index.py
```

也可为测试 / 复制数据指定 `--db`、`--snapshots`、`--jobs` 和 `--output-root`。命令只读两个 JSON，输出 inserted / updated / skipped / warnings / errors 报告；坏行不会中断其他行。

## 只读 Library API

所有 `/api/rpg/library/*` 路由复用现有 RPG Token / HttpOnly session 边界；没有 Library POST 路由。

- `GET /api/rpg/library/generations`：分页列表。支持 `limit`、`offset`、`operation`、`status`、`model`、`sort`（`created_at` / `updated_at` / `status` / `operation` / `model`）和 `order`。
- `GET /api/rpg/library/generations/{generation_id}`：摘要、分层参数、LoRA、artifact、完整快照、`replay` 和 `variation` 预览。
- `GET /api/rpg/library/generations/{generation_id}/lineage`：父 / 子作品和有界谱系边。

`replay.can_submit` 和 `variation.can_submit` 永远为 `false`。它们只返回结构化恢复 payload 与说明，服务端不会因为读取或恢复预览而调用 `/prompt`。

artifact URL 仍指向已有的 `/api/rpg/image`，客户端下载时带 Token；服务端不把 Token 拼到 URL。

## Android 最小作品库

快速页面新增“作品库”入口：

- 列表显示缩略图（通过带 Token 的现有图片下载链路）、模型、Seed、时间、操作、输出数和父 / 子计数。
- 详情显示只读参数、输出、父子谱系和提示词预览。
- “复现到当前表单”和“换 Seed 到当前表单”只更新当前编辑状态，用户仍需显式点击底部“生成图片”。
- 下载复用现有 `downloadBlob` / Android `Downloads` 原生实现。
- 旧服务端、断网、缺 Token、缺失输出或不支持谱系时保留页面并显示可读回退，不自动提交任务。

## Phase 2 明确延期

本阶段不实现 Character-first 数据模型、角色 / 关系工作室、设备配对、通知、自动检测、完整队列重排和作品库写入编辑器。也不改变现有 JSON 源文件格式、已有生图工作流或 Token 位置。

## 验证边界

本分支只进行 Python / TypeScript / Vitest 测试和静态构建验证；不重启 live Easy Panel / ComfyUI，不调用 `/generate`，不构建、安装、发布或部署 APK。
