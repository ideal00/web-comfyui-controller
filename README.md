# web-comfyui-controller（ComfyUI Easy Panel）

一个简单的、基于 Web UI 的 ComfyUI 控制面板。面向动漫 / 二次元出图场景，提供中文提示词编辑、AI 翻译、LoRA 备忘、姿势控制、注意力引导、多角色分区、整图重绘、调色、任务队列等功能。

> 本项目为本地单机工具：`easy_panel.py` 启动一个本地 HTTP 服务（默认 `http://127.0.0.1:8190`），桥接本机 ComfyUI（默认 `http://127.0.0.1:8188`），直接组装工作流 JSON 提交给 ComfyUI 执行。

## 功能特性

- **多模型族支持**：SDXL / Illustrious / Anima / Krea 2 四族模型，自动匹配采样器 / 调度器 / 预测类型与质量前缀
- **提示词编译器**：分区化提示词编辑（人物 / 外貌 / 服装 / 姿势 / 构图 / 场景 / 光线 / 画风 / 自然语言 / 手动），质量标签、安全标签、LoRA 触发词置顶、动态负面词、冲突检测
- **AI 结构化翻译**：中文描述 → 英文标签，支持 DeepSeek / OpenAI / Anthropic / Gemini / Ollama 等协议，自动识别推理模型并扩容 token 预算；另含 Google 直译
- **注意力引导（SAG / PAG）**：在 LoRA 之后、采样前注入 Self-Attention Guidance 或 Perturbed Attention Guidance，提升构图与主体一致性（Krea 2 除外）
- **多角色分区提示**：用 ConditioningSetAreaPercentage 把各角色提示词绑定到画布不同区域，避免多角色特征互相混合（Krea 2 除外）
- **自定义采样器 / 调度器**：手动覆盖采样参数并实时显示徽标（Krea 2 固定免引导 euler / simple）
- **Danbooru 标签搜索**：中英标签补全（依赖 `vendor/tagcomplete-data`，需自行下载）
- **LoRA 备忘与服装预设**：同名 TXT 解析导入、多分区服装预设（人物 / 服装 / 姿势 / 场景等 9 分区）、多套预设叠加
- **OpenPose 姿势控制**：DWPose 骨架提取（自动回退 dwpose-full → dwpose-yolo）+ 骨架编辑器 + ControlNet，结果缓存复用
- **蒙版局部重绘**：浏览器内画笔蒙版编辑器 + `VAEEncodeForInpaint` 局部重绘
- **整图重绘（img2img）**：Krea 2 出真实底图 → Illustrious / Anima 二次元化（内置超大底图 OOM 防护）
- **读取 AI 图片参数**：解析 PNG / WebP / JPG 内嵌元数据（ComfyUI / A1111 / NovelAI），一键回填面板
- **生成后调色实时预览**：复刻 ComfyUI_LayerStyle 的亮度对比度 / RGB / HSV / Gamma / Levels 节点
- **任务队列**：多任务排队，每个任务独立 LoRA，先暂存再一次性发送

## 安装教程（Windows）

### 第 1 步：下载

从 **GitHub Releases** 页面下载最新版本源码（`Source code (zip)`），或使用 git 克隆：

```bash
git clone https://github.com/ideal00/web-comfyui-controller.git
```

将 `ComfyUI_Easy_Panel` 目录解压 / 放置到任意位置，**建议与 ComfyUI 同级**，例如 `G:\ComfyUI\ComfyUI_Easy_Panel`。

### 第 2 步：准备 ComfyUI

- 需要本机已安装并启动 **ComfyUI**（便携版即可），默认地址 `http://127.0.0.1:8188`
- 按需安装第三方节点（用不到的可以跳过）：
  - **OpenPose 姿势控制**：`comfyui_controlnet_aux`（DWPose）、Xinsir OpenPose ControlNet 模型、[huchenlei/sd-webui-openpose-editor](https://github.com/huchenlei/sd-webui-openpose-editor)（骨架编辑器）
  - **生成后调色**：`ComfyUI_LayerStyle`
  - **局部重绘 / img2img / 注意力引导 / 多角色分区**：均为 ComfyUI 内置节点，无需额外安装

### 第 3 步：修改配置路径（重要）

用任意文本编辑器打开 `easy_panel.py`，修改**顶部硬编码路径**为你自己的实际路径：

```python
OUTPUT       = Path(r"你的ComfyUI\output")           # ComfyUI 输出目录
COMFY_INPUT  = Path(r"你的ComfyUI\input")            # ComfyUI 输入目录
LORA_DIR     = Path(r"你的ComfyUI\models\loras")     # ComfyUI LoRA 目录
COMFY        = "http://127.0.0.1:8188"               # ComfyUI 地址
```

### 第 4 步：Python 环境

推荐直接使用 **ComfyUI 便携版自带的 Python**（`ComfyUI_windows_portable\python_embeded\python.exe`，自带 Pillow），无需额外安装依赖。

如果使用系统 Python，需要 Python 3.10+ 并安装：

```bash
pip install pillow
```

### 第 5 步：（可选）下载 vendor 标签数据

标签搜索与 Anima 硬标签校验依赖 `vendor/` 下的第三方数据（体积较大未随仓库分发），按需放置（详见下方「vendor/ 数据说明」）。缺失时程序仍可运行，仅标签搜索功能不可用。

### 第 6 步：启动面板

```bash
# 在面板目录下执行
python easy_panel.py
```

浏览器打开 **http://127.0.0.1:8190** 即可使用。

> **首次使用**：在「AI 翻译」卡片填入你的服务商 API Key（DeepSeek / OpenAI 等）与模型名，点击保存。密钥仅保存在浏览器 `localStorage`，不会写入任何文件，也不会提交到仓库。

### 常见问题

- **面板打不开 / 连接失败**：确认 ComfyUI 已启动且 `COMFY` 地址正确
- **提示词 / 标签搜索没反应**：未放置 `vendor/tagcomplete-data`，按第 5 步补齐即可
- **生成报错 / 显存不足**：在面板下调小分辨率（8GB 显存建议 1.25MP 以内）；img2img 底图建议 1.5MP 以内
- **AI 翻译返回空**：确认模型名正确；推理模型（如 deepseek-v4-flash）会自动扩容 token 预算重试

## 目录结构

```
ComfyUI_Easy_Panel/
├── easy_panel.py            # 主程序：本地 HTTP 服务器（端口 8190），桥接 ComfyUI 并组装工作流
├── index.html               # 前端 UI（中文生成面板）
├── classify_tags.py         # 标签分类辅助脚本
├── import_all_sidecars.py   # 批量导入 LoRA 同名 TXT 辅助脚本
├── pose_editor_workflow.json# 骨架编辑器工作流文件
├── restore_backup.ps1       # 备份恢复脚本
├── backup/                  # 本地备份快照（不入库）
├── vendor/                  # 第三方标签数据（不入库，见下方说明）
└── lora_notes.json          # 本地 LoRA 备注 / 服装预设（个人数据，不入库，首次保存自动生成）
```

## 运行要求

- 本机已安装并启动 **ComfyUI**（默认地址 `http://127.0.0.1:8188`）
- Python 3.10+（推荐直接使用 ComfyUI 便携版自带的 `python_embeded\python.exe`，自带 Pillow）
- 依赖仅标准库 + Pillow（后端已内置 json / http.server / urllib 等）

## vendor/ 数据说明（按需下载）

标签搜索与 Anima 硬标签校验依赖 `vendor/` 下的第三方数据，体积较大未入库，请自行放置：

```
vendor/tagcomplete-data/          # a1111-sd-webui-tagcomplete 的 Danbooru 标签数据
├── danbooru.csv                  # Danbooru 主标签库（约 3.5MB）
├── danbooru-0-zh.csv             # 社区中文翻译
├── Tags-zh-full.csv / Tags-zh-lite.csv
└── LICENSE.tagcomplete
vendor/anima-tags/
└── anima-1.0.csv                 # Anima 硬标签库（约 2.6MB）
```

数据来源：
- TagComplete：https://github.com/DominikDoom/a1111-sd-webui-tagcomplete
- Anima tags：见 `vendor/anima-tags/SOURCE.md`

缺失时程序仍可运行，仅标签搜索 / 硬标签校验功能不可用。

## lora_notes.json 说明

该文件保存个人 LoRA 备注与服装预设（含触发词、底模、多分区预设等），属于个人数据不入库。程序检测不到该文件时自动按空数据处理，首次在前端保存后自动生成。格式示例：

```json
{
  "some_lora.safetensors": {
    "name": "示例LoRA",
    "trigger": "trigger_word",
    "base_model": "illustrious",
    "weight": "0.8",
    "note": "备注文字",
    "outfits": [
      { "name": "默认服装", "prompt": "dress, ...", "subject": "...", "pose": "...", "negative": "..." }
    ]
  }
}
```

## 安全提示

- 本项目仅供本地使用，请勿将面板端口暴露到公网
- 请勿将个人 API Key 提交到任何公开仓库（本项目所有密钥仅存于浏览器本地）
