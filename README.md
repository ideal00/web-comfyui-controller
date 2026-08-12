# ComfyUI Easy Panel（web-comfyui-controller）

ComfyUI Easy Panel 是一个面向动漫、二次元和角色 LoRA 出图的本地 Web 控制面板。它不替代 ComfyUI，而是在 ComfyUI 前面提供更容易理解的中文界面，自动整理提示词、选择模型参数并生成 ComfyUI 工作流。

面板默认运行在 `http://127.0.0.1:8190`，连接本机 `http://127.0.0.1:8188` 的 ComfyUI。图片仍由 ComfyUI 生成并保存到 ComfyUI 的 `output` 目录。

> 本 README 按 Windows + ComfyUI 官方便携版编写。新手请先完成“安装与首次启动”，再照“10 分钟生成第一张图”操作。不要一开始同时启用 LoRA、姿势、多人、高清、调色和重绘；先确认基础出图正常，再逐项增加功能。

## 目录

- [1. 项目如何工作](#1-项目如何工作)
- [2. 功能与模型兼容性](#2-功能与模型兼容性)
- [3. 安装前准备](#3-安装前准备)
- [4. Windows 安装与首次启动](#4-windows-安装与首次启动)
- [5. 10 分钟生成第一张图](#5-10-分钟生成第一张图)
- [6. 界面与提示词完整教程](#6-界面与提示词完整教程)
- [7. 模型与 LoRA 完整教程](#7-模型与-lora-完整教程)
- [8. OpenPose 姿势控制](#8-openpose-姿势控制)
- [9. Illustrious、Anima、Krea 2 专用功能](#9-illustriousanimakrea-2-专用功能)
- [10. 高级参数与推荐组合](#10-高级参数与推荐组合)
- [11. 多人区域提示词](#11-多人区域提示词)
- [12. 局部修复、整图重绘与调色](#12-局部修复整图重绘与调色)
- [13. 直接生成与任务队列](#13-直接生成与任务队列)
- [14. 常用完整工作流程](#14-常用完整工作流程)
- [15. 显存、速度与画质建议](#15-显存速度与画质建议)
- [16. 数据保存、备份与升级](#16-数据保存备份与升级)
- [17. 故障排查](#17-故障排查)
- [18. 开发、自检与目录结构](#18-开发自检与目录结构)
- [19. 安全与隐私](#19-安全与隐私)

## 1. 项目如何工作

生成链路如下：

```text
浏览器中的 Easy Panel（8190）
        ↓ 读取模型、LoRA、节点列表
easy_panel.py 本地服务
        ↓ 生成 ComfyUI API 工作流 JSON
ComfyUI（8188）
        ↓ 加载模型并采样
ComfyUI/output 中的图片
        ↓
Easy Panel 预览区
```

需要记住三个概念：

1. **ComfyUI 必须先启动。** Easy Panel 只负责组织参数和提交任务，不执行扩散模型。
2. **Easy Panel 与 ComfyUI 使用同一套模型目录。** 不需要复制 checkpoint 或 LoRA。
3. **面板中显示“自动”的参数也会真实传给 ComfyUI。** 后端会根据模型选择采样器、调度器、预测类型和质量前缀。

## 2. 功能与模型兼容性

| 功能 | 标准 SDXL | Illustrious / ILXL | Anima | Krea 2 Turbo |
| --- | --- | --- | --- | --- |
| 文生图 | 支持 | 支持 | 支持 | 支持 |
| 普通 LoRA | 支持 | 支持 | 支持，使用模型侧加载 | 支持，使用模型侧加载 |
| 中文转换 / 提示词编译 | 支持 | 支持 | 支持，额外提供分层提示词 | 支持，偏自然语言 |
| 精准 / 高清模式 | 支持，按模型参数 | 支持，按模型参数 | 不显示 | 不显示 |
| 局部蒙版修复 | 支持 | 支持 | 不显示 | 不显示 |
| OpenPose ControlNet | 支持 | 支持 | 不支持当前 SDXL ControlNet | 不支持当前 SDXL ControlNet |
| 多人区域提示词 | 支持 | 支持 | 不支持 | 不支持 |
| SAG / PAG | 支持 | 支持 | 支持，建议谨慎使用 | 不支持，自动锁定关闭 |
| 整图 img2img | 支持 | 支持 | 支持 | 支持 |
| 生成后调色 | 支持 | 支持 | 支持 | 支持 |
| Anime6B / SeedVR2 后处理超分 | 支持 | 支持 | 支持 | 支持 |
| Ultimate SD Upscale | 支持 | 支持 | 不支持 | 不支持 |
| 读图还原参数 | 支持 | 支持 | 支持 | 支持 |

主要功能包括：

- 中文自然描述转换为结构化英文提示词。
- DeepSeek、OpenAI、OpenRouter、硅基流动、Anthropic、Gemini、Ollama 和自定义 AI 接口。
- 本地常用词转换和 Danbooru 中英文标签搜索。
- 人物、外貌、服装、姿势、构图、场景、光线、画风、自然语言等提示词分区。
- LoRA 自动触发词、备忘、推荐权重、同名 TXT 说明和多套服装预设。
- WAI、Milmu、Spectacular、Gock、Anima、Krea 2 等模型的专用采样组合。
- DWPose / OpenPose 骨架提取、预览、缓存和手动编辑。
- 双人及多人柔边区域 conditioning，以及角色 LoRA 空间隔离。
- Illustrious 精准、高清二次采样和局部蒙版修复。
- Krea 2 底图转 Illustrious / Anima 二次元画风。
- 读取 ComfyUI、A1111 WebUI、NovelAI 图片元数据并回填参数。
- LayerStyle 亮度、对比度、RGB、HSV、Gamma 和 Levels 调色。
- 最多 50 个逻辑任务、200 张图片的会话任务队列。

## 3. 安装前准备

### 3.1 最低条件

- Windows 10 或 Windows 11。
- 已能正常运行的 ComfyUI。
- Python 3.10+；推荐直接使用 ComfyUI 便携版自带的 Python。
- 至少一个完整 SDXL / Illustrious checkpoint，或者完整的 Anima / Krea 2 分体模型文件。
- 建议使用 NVIDIA GPU。8 GB 显存可以运行常用尺寸，但多人、高清和大图会明显变慢。

### 3.2 推荐目录结构

以下结构最容易配置：

```text
G:\ComfyUI\
├── ComfyUI_windows_portable\
│   ├── python_embeded\python.exe
│   └── ComfyUI\
│       ├── input\
│       ├── output\
│       ├── models\
│       └── custom_nodes\
└── ComfyUI_Easy_Panel\
    ├── easy_panel.py
    ├── index.html
    └── README.md
```

盘符和文件夹名称可以不同，但稍后必须把 `easy_panel.py` 顶部路径改成真实位置。

### 3.3 模型文件应该放在哪里

| 文件类型 | ComfyUI 目录 | 示例 |
| --- | --- | --- |
| 完整 SDXL / Illustrious checkpoint | `ComfyUI\models\checkpoints` | `waiIllustriousSDXL_v140.safetensors` |
| Anima / Krea 2 扩散模型 | `ComfyUI\models\diffusion_models` | `anima-base-v1.0.safetensors`、Krea 2 Turbo 文件 |
| Anima 文本编码器 | `ComfyUI\models\text_encoders` | `qwen_3_06b_base.safetensors` |
| Krea 2 文本编码器 | `ComfyUI\models\text_encoders` | `qwen3VL4BAbliteratedComfyui_v10.safetensors` |
| Anima / Krea 2 VAE | `ComfyUI\models\vae` | `qwen_image_vae.safetensors` |
| LoRA | `ComfyUI\models\loras` | 任意子目录中的 `.safetensors` |
| OpenPose ControlNet | `ComfyUI\models\controlnet` | 与 SDXL / Illustrious 兼容的 Xinsir OpenPose 模型 |

文件名与代码中的名称必须一致。Anima 和 Krea 2 如果缺少文本编码器或 VAE，面板会显示预检错误，而不是把任务送进队列后才失败。

### 3.4 可选第三方节点

基础文生图、LoRA、img2img、局部编码、Hook LoRA、SAG/PAG 和区域蒙版使用当前 ComfyUI 节点。以下功能需要额外节点：

| 功能 | 需要安装 | 用到的节点 |
| --- | --- | --- |
| 从人物图片提取骨架 | [comfyui_controlnet_aux](https://github.com/Fannovel16/comfyui_controlnet_aux) | `DWPreprocessor`、`OpenposePreprocessor` |
| 编辑提取后的骨架 | [ComfyUI-openpose-editor](https://github.com/huchenlei/ComfyUI-openpose-editor) | `huchenlei.LoadOpenposeJSON` |
| 生成后调色 | [ComfyUI_LayerStyle](https://github.com/chflame163/ComfyUI_LayerStyle) | `LayerColor: Brightness & Contrast` 等 |

推荐在 ComfyUI Manager 中搜索并安装。也可以把仓库克隆到 `ComfyUI\custom_nodes`，安装仓库要求的依赖后重启 ComfyUI。

> 安装顺序建议：先更新 ComfyUI，再装 `comfyui_controlnet_aux`，然后装 `ComfyUI-openpose-editor`，最后按需装 `ComfyUI_LayerStyle`。每次安装后都要完整重启 ComfyUI。

使用 ComfyUI Manager 的具体步骤：

1. 打开 `http://127.0.0.1:8188`。
2. 点击 ComfyUI Manager 的 `Manager` 按钮。
3. 打开 `Custom Nodes Manager`。
4. 搜索 `comfyui_controlnet_aux`，点击安装。
5. 搜索 `ComfyUI-openpose-editor`，点击安装。
6. 搜索 `ComfyUI_LayerStyle`，点击安装。
7. 关闭 ComfyUI，包括它的终端窗口。
8. 重新启动 ComfyUI，观察终端中是否出现 `IMPORT FAILED`。

没有 Manager 时，可以在 `ComfyUI\custom_nodes` 中手动克隆：

```powershell
Set-Location G:\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes
git clone https://github.com/Fannovel16/comfyui_controlnet_aux.git
git clone https://github.com/huchenlei/ComfyUI-openpose-editor.git
git clone https://github.com/chflame163/ComfyUI_LayerStyle.git
```

然后按照各仓库 README 安装 requirements。官方便携版的 Python 位于 `ComfyUI_windows_portable\python_embeded\python.exe`，不要误装到系统 Python。LayerStyle 官方仓库还提供便携版依赖安装批处理；优先按该仓库当前说明执行。

重启后可以在 ComfyUI 画布双击搜索以下节点来验证：

```text
DWPreprocessor
Load Openpose JSON
LayerColor: Brightness & Contrast
```

三者都能找到，表示姿势提取、骨架编辑和调色所需节点已经载入。

## 4. Windows 安装与首次启动

### 第 1 步：安装并验证 ComfyUI

如果还没有 ComfyUI，从 [ComfyUI 官方仓库](https://github.com/Comfy-Org/ComfyUI) 获取 Windows 便携版并解压。NVIDIA 便携版通常通过 `run_nvidia_gpu.bat` 启动。

启动后浏览器打开：

```text
http://127.0.0.1:8188
```

能看到 ComfyUI 页面才继续。若 8188 打不开，先解决 ComfyUI 本身的问题。

### 第 2 步：下载 Easy Panel

使用 Git：

```powershell
Set-Location G:\ComfyUI
git clone https://github.com/ideal00/web-comfyui-controller.git ComfyUI_Easy_Panel
```

也可以在 GitHub Releases / Code 页面下载 ZIP，解压并把文件夹命名为 `ComfyUI_Easy_Panel`。

### 第 3 步：配置本机路径

推荐直接使用 Core / All 一键包：安装器会识别 ComfyUI，并生成已经写好环境变量的 `启动面板.cmd`，不需要改 Python 源码。

手动启动时也不要再修改 `easy_panel.py`。在同一个 PowerShell 窗口设置环境变量：

```powershell
$env:EASY_PANEL_COMFY_ROOT = "G:\ComfyUI\ComfyUI_windows_portable\ComfyUI"
$env:EASY_PANEL_COMFY_URL = "http://127.0.0.1:8188"
$env:EASY_PANEL_PORT = "8190"
& "G:\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe" .\easy_panel.py
```

可用配置如下；未设置时继续使用原有本机默认值：

| 环境变量 | 用途 |
| --- | --- |
| `EASY_PANEL_COMFY_ROOT` | 包含 `main.py`、`models`、`input`、`output` 的 ComfyUI 根目录 |
| `EASY_PANEL_COMFY_URL` | ComfyUI API 地址，默认 `http://127.0.0.1:8188` |
| `EASY_PANEL_HOST` / `EASY_PANEL_PORT` | 面板监听地址与端口，默认 `127.0.0.1:8190` |
| `EASY_PANEL_ROOT` | Easy Panel 项目目录 |
| `EASY_PANEL_COMFY_INPUT` | 单独覆盖 ComfyUI `input` 目录 |
| `EASY_PANEL_OUTPUT` | 单独覆盖 ComfyUI `output` 目录 |
| `EASY_PANEL_LORA_DIR` | 单独覆盖 LoRA 目录 |

保持 `127.0.0.1` 最安全；不要为了“方便”改成公网可访问地址。

### 第 4 步：准备 Python

官方便携版推荐直接使用：

```text
你的路径\ComfyUI_windows_portable\python_embeded\python.exe
```

后端主要使用 Python 标准库。读取图片元数据、调色预览和图片检查需要 Pillow。便携版通常已经包含；若缺少，执行：

```powershell
& "G:\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe" -m pip install pillow
```

如果使用系统 Python：

```powershell
py -3.10 -m pip install pillow
```

### 第 5 步：准备可选标签数据

要使用完整 Danbooru 搜索，请从 [a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete) 获取标签文件，并把需要的 CSV 复制到：

```text
ComfyUI_Easy_Panel\vendor\tagcomplete-data\
```

面板至少会查找 `danbooru.csv`，中文检索还需要 `danbooru-0-zh.csv` 或对应中文标签表。

要使用 Anima 硬标签验证，把 Anima 标签表保存为：

```text
ComfyUI_Easy_Panel\vendor\anima-tags\anima-1.0.csv
```

标签数据不是生成模型。缺少时仍可正常出图，只会失去搜索或验证功能。

### 第 6 步：启动顺序

当前推荐直接双击工作目录中的：

```text
G:\ComfyUI\Start_ComfyUI_and_EasyPanel.bat
```

它会检查模块化后端、模型配置目录和前端 JS 是否完整，设置新版所需环境变量，启动 ComfyUI 与 Easy Panel，并自动打开 Easy Panel（`http://127.0.0.1:8190`）和 ComfyUI（`http://127.0.0.1:8188`）两个网页。首次启动 ComfyUI 较慢时，脚本会等待 8188 就绪后再打开，不会提前显示连接失败页。

全部使用结束后双击：

```text
G:\ComfyUI\Stop_ComfyUI_and_EasyPanel.bat
```

关闭脚本会核对进程命令行，只停止确认为 ComfyUI / Easy Panel 的 8188、8190 进程，不会误关碰巧占用端口的其他程序。

每次使用都按以下顺序：

1. 启动 ComfyUI。
2. 等待 ComfyUI 终端显示服务已启动。
3. 启动 Easy Panel。
4. 打开 8190 页面。

使用便携版 Python 启动面板：

```powershell
Set-Location G:\ComfyUI\ComfyUI_Easy_Panel
& "G:\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe" .\easy_panel.py
```

看到下面的文字表示面板服务已启动：

```text
Easy Panel: http://127.0.0.1:8190
```

浏览器打开：

```text
http://127.0.0.1:8190
```

不要关闭运行 `easy_panel.py` 的终端窗口；关闭后 8190 页面就无法继续工作。

### 第 7 步：确认连接正常

页面应该满足以下条件：

- “基础模型”下拉框中能看到 checkpoint。
- LoRA 分类旁显示 LoRA 数量。
- 右侧显示“当前队列：运行 0 · 等待 0”。
- 页面底部状态不再显示“模型列表加载失败”。

还可以直接访问：

```text
http://127.0.0.1:8190/api/status
```

正常空闲状态类似：

```json
{"running": 0, "pending": 0}
```

### 第 8 步：使用一键模块安装包

项目已经在 `installers\packages` 提供独立 Windows ZIP。下载或复制所需 ZIP，完整解压后双击其中的中文 `.cmd` 文件即可。

| 安装包 | 用途 | 安装后还需手动准备 |
| --- | --- | --- |
| [EasyPanel-Core-OneClick.zip](installers/packages/EasyPanel-Core-OneClick.zip) | 安装 / 更新核心面板、自动配置路径、创建启动入口 | 至少一个可用模型 |
| [EasyPanel-LoRA-Tools-OneClick.zip](installers/packages/EasyPanel-LoRA-Tools-OneClick.zip) | 单独安装同名 TXT 生成器和 TXT 智能分区 JSON 导入器 | 本机 LoRA；不要求安装第三方节点 |
| [EasyPanel-Pose-OneClick.zip](installers/packages/EasyPanel-Pose-OneClick.zip) | 安装 ControlNet Aux 与 OpenPose Editor | OpenPose ControlNet 权重 |
| [EasyPanel-Color-OneClick.zip](installers/packages/EasyPanel-Color-OneClick.zip) | 安装 LayerStyle 和 Python 依赖 | 通常无需额外文件 |
| [EasyPanel-Tags-OneClick.zip](installers/packages/EasyPanel-Tags-OneClick.zip) | 下载 Danbooru 和 Anima 标签索引 | 安装时需要联网 |
| [EasyPanel-Models-Check.zip](installers/packages/EasyPanel-Models-Check.zip) | 检查 checkpoint、LoRA、ControlNet、编码器和 VAE | 根据报告自行下载缺少的权重 |
| [EasyPanel-All-OneClick.zip](installers/packages/EasyPanel-All-OneClick.zip) | 核心 + 姿势 + 调色 + 标签 + 模型检查 | 大模型和 ControlNet 权重 |

安装器行为：

1. 自动寻找 ComfyUI 根目录；找不到时让用户输入包含 `main.py` 的文件夹。
2. 核心更新前自动备份原核心文件。
3. 保留 `lora_notes.json`，不会覆盖个人 LoRA 备忘。
4. 不改 Python 源码；在生成的 `启动面板.cmd` 中写入本机环境变量，日后更新不会产生路径冲突。
5. 第三方节点已是 Git 仓库时执行安全更新；发现不明非 Git 目录时跳过，不直接覆盖。
6. 模型检查包只报告缺失文件，不会自动下载受许可证和体积限制的模型权重。
7. LoRA 工具包只安装程序和双击入口，不会在安装过程中生成 TXT，也不会修改 `lora_notes.json`。

下载后可用 [SHA256SUMS.txt](installers/packages/SHA256SUMS.txt) 校验文件：

```powershell
Get-FileHash .\EasyPanel-Core-OneClick.zip -Algorithm SHA256
```

输出应与 `SHA256SUMS.txt` 对应条目一致。安装器源码和命令行参数说明见 [installers/README.md](installers/README.md)。

## 5. 10 分钟生成第一张图

先完成最小可用测试。第一次不要添加 LoRA、姿势或调色。

1. 在“基础模型”选择一个完整的 Illustrious checkpoint，例如 WAI Illustrious。
2. 点击“应用画风测试预设”。
3. 在“人物与角色”保留：

   ```text
   1girl, solo
   ```

4. 在“外貌”填写：

   ```text
   long hair, blue eyes
   ```

5. 在“服装与材质”填写：

   ```text
   white shirt, pleated skirt
   ```

6. 在“姿势”保留 `standing`。
7. 在“场景”保留 `simple background`。
8. 点击“编译并检查”，确认没有红色错误。
9. 尺寸先选“小竖图 512 × 768”。
10. 种子填 `-1`，生成数量填 `1`。
11. “高级参数”保持自动。
12. 点击“生成图片”。

生成时右侧会显示 ComfyUI 队列状态。完成后图片显示在预览区，也会保存在：

```text
ComfyUI\output\EasyPanel_*.png
```

如果最小测试成功，再把尺寸提高到 `832 × 1216`，然后逐项添加 LoRA 或其他功能。

## 6. 界面与提示词完整教程

### 6.1 输入框和预览区大小

- 页面顶部“输入框字号”只改变界面文字大小，不影响图片。
- 右侧“生成预览”的宽度和高度只改变预览框，不改变实际生成分辨率。
- 实际图片尺寸只由左侧“尺寸”和 Illustrious 高清倍率决定。

### 6.2 中文描述转换

在最上方输入中文描述，例如：

```text
蓝色长发的成年女性，白衬衫和黑色轻薄丝袜，站在教室窗边，下午阳光，全身像
```

有三种转换方式：

#### AI 结构化标签转换（推荐）

适合长句、复杂构图、多人关系和 Anima / Krea 2。配置方法：

1. 选择“服务预设”。
2. 确认接口协议和鉴权方式。
3. 填写 API 请求地址。
4. 填写 API Key。
5. 填写服务商要求的模型 ID。
6. 点击“AI 结构化标签转换”。
7. 检查英文结果，再点击“加入正向提示词”或“加入负面提示词”。

| 服务 | 常用协议 | 常用鉴权 |
| --- | --- | --- |
| DeepSeek / OpenAI / OpenRouter / 硅基流动 | OpenAI 兼容 | `Authorization: Bearer` |
| Anthropic Claude | Anthropic Messages | `x-api-key` |
| Google Gemini | Gemini generateContent | `x-goog-api-key` |
| 本机 Ollama | OpenAI 兼容 | 无需密钥 |
| Azure / 自建接口 | 按服务说明选择 | Bearer、`api-key` 或无密钥 |

远程接口必须使用 HTTPS；HTTP 只允许 `127.0.0.1` / `localhost` 等本机服务。不要把 API Key 拼进 URL。

#### Google 英文直译

需要单独填写 Google Cloud Translation API Key。它更接近普通翻译，不会像结构化 AI 那样主动拆分人物、服装和构图。

#### 本地常用词转换

完全离线，不需要密钥。它只识别面板内置的常见中文词组，适合简单描述；复杂句子请用 AI 转换或手动填写。

### 6.3 提示词快捷库

快捷词按质量、人物、皮肤、发型、眼睛、服装、丝袜、场景和光线分类。

- 点击圆形词条会写入对应提示词分区。
- 发型 / 发色、服装 / 颜色使用两个下拉框，选择后点“确认加入”。
- “撤销上一个词条”只撤销最近一次由快捷库加入的内容。
- “复制提示词”复制编译后的最终正向提示词，不只是某个输入框。
- “重置为初始提示词”恢复画风测试基础状态，并清除已应用预设的状态。

### 6.4 Danbooru 标签补全

输入英文、别名或中文译名，例如：

```text
blue hair
蓝发
黑色丝袜
```

先在右侧选择写入分区，再点击搜索结果。这样可避免把服装标签误放进场景或手动区。

标签功能依赖：

```text
vendor\tagcomplete-data\danbooru.csv
vendor\tagcomplete-data\danbooru-0-zh.csv
```

缺少数据时不影响生成，只是无法进行完整标签搜索。

### 6.5 读取 AI 图片参数

支持读取原始 PNG / WebP / JPG 中的 ComfyUI、A1111 WebUI 和 NovelAI 元数据。

操作方法：

1. 上传原始图片，或从最近输出中选择。
2. 查看解析出的模型、采样器、调度器、步数、CFG、种子、尺寸、LoRA、正向和负向提示词。
3. 点击“填入生成面板”。
4. 检查提示词分区和模型匹配结果。
5. 固定原种子后生成，比较复现效果。

社交平台、聊天软件和图片编辑器经常删除元数据。若提示“未找到 AI 生成参数”，请换未经二次压缩的原图。

### 6.6 结构化提示词编译器

编译器不是简单地把文本框拼起来。它会：

- 自动加入当前模型的质量前缀。
- 把选中 LoRA 的触发词放到最终正向提示词前部。
- 去除重复标签。
- 检查人数、安全等级和部分语义冲突。
- 自动加入基础负面词。
- 根据模型族调整标签与自然语言的顺序。
- 检查 LoRA 标注底模是否可能不兼容。

各分区用途：

| 分区 | 应写内容 | 示例 |
| --- | --- | --- |
| 人物与角色 | 数量、角色名、作品名 | `1girl, solo, alice (game)` |
| 外貌 | 发色、瞳色、皮肤、体型 | `blue hair, red eyes, pale skin` |
| 服装与材质 | 衣服、配饰、布料 | `white dress, black pantyhose, silk` |
| 姿势 | 站坐、动作、表情、视线 | `standing, smile, looking at viewer` |
| 构图与镜头 | 景别、角度、镜头 | `full body, low angle, depth of field` |
| 场景 | 地点、背景、时间 | `classroom, afternoon` |
| 光线 | 光源、色温、阴影 | `window light, soft daylight` |
| 画风与上色 | 风格、媒介、上色方式 | `anime illustration, clean lineart` |
| 自然语言关系 | 多人互动、动作归属、空间关系 | `Alice stands to the left of Bob.` |
| 其他补充标签 | 无法分类的额外标签 | 自定义标签 |
| 额外负面词 | 只写额外想排除的内容 | `extra fingers, logo` |

“提示词用途”有三种：

- **画风测试**：提示词尽量中性，便于判断 checkpoint / LoRA 自身风格。
- **正式出图**：自动补充更完整的构图和背景起点。
- **自定义**：不套用上述用途习惯，适合熟悉提示词后使用。

“安全等级”会影响质量 / rating 标签和基础负面词。选择后仍应检查最终编译结果。

最终正向和最终负向现在都是可编辑文本框：

- 自动模式会把分区、模型质量词、LoRA 触发词和动态负面词完整显示出来。
- 直接修改任一最终文本后进入“手动原样提交”，生成时不会重新加入被删除的默认词。
- “从分区重新编译”会退出手动模式，并明确覆盖最终文本。
- “清空最终正负向”允许提交空正向或空负向；手动内容会按模型族保存在当前浏览器会话。
- 可选手脚修复的正负提示词也位于高级参数中，可分别编辑或清空。

点击“检查当前最终文本”后：

- 红色表示必须修复的错误。
- 黄色表示可以生成，但有冲突或质量风险。
- 无警告表示当前结构检查通过，不代表模型一定会得到完美画面。

## 7. 模型与 LoRA 完整教程

### 7.1 选择基础模型

模型列表来自 ComfyUI 的 `/object_info`。面板会把模型分为：

- SDXL / Illustrious 完整 checkpoint。
- Anima 分体扩散模型。
- Krea 2 分体扩散模型。
- 只有 UNet、缺少内置 CLIP / VAE 的不可用 checkpoint。

若模型在 ComfyUI 中可见但面板标记“仅 UNet”，不要用 `CheckpointLoaderSimple` 强行生成；应按模型类型放入 `diffusion_models`，并补齐对应 text encoder 和 VAE。

### 7.2 添加 LoRA

1. 点击“+ 添加 LoRA”。
2. 使用“LoRA 分类”缩小文件夹范围。
3. 选择 LoRA 文件。
4. 设置权重。
5. 抓住“↕序号”拖动排序，或使用 ↑ / ↓ 精确调整。
6. 查看下方备忘、触发词和适用底模。

常用权重起点：

| LoRA 类型 | 建议起点 |
| --- | --- |
| 角色 LoRA | `0.75–0.95` |
| 服装 LoRA | `0.65–0.9` |
| 画风 LoRA | `0.55–0.8` |
| 姿势 / 概念 LoRA | `0.6–0.85` |

权重不是越高越好。出现脸崩、服装粘连、颜色过饱和或背景被角色特征污染时，先降低到 `0.6–0.75`。

LoRA 从上到下依次进入加载链，自动触发词也使用同一顺序。拖动或使用 ↑ / ↓ 后，面板会立即更新最终提示词，并把新顺序保存到当前浏览器会话。刷新页面后，LoRA 选择、权重和顺序都会恢复。移除 LoRA 或点击“清空 LoRA”时，只会撤销由该 LoRA 预设自动加入的词，用户手写提示词会保留。

### 7.3 自动触发词

若 `lora_notes.json` 中记录了 `trigger`，选择 LoRA 后编译器会自动把触发词放到最终提示词前部。通常不需要再次手动粘贴，否则可能重复强化。

界面中的“自动触发词”标签可以确认哪些词会自动加入。切换或移除 LoRA 后，最终编译结果会同步更新。

### 7.4 LoRA 备忘和服装预设

选择 LoRA 后可以查看：

- 标题。
- 适用底模。
- 推荐权重。
- 触发词。
- CivitAI 链接。
- 多套提示词预设。
- 同名 TXT 的原始说明。

点击某套预设会把内容写入人物、服装、姿势、构图、场景、光线、画风、上色或负面分区。再次点击同一预设会撤销它加入的内容。

同一个 LoRA 可以叠加多套预设。面板会记录每套预设实际新增的词，取消时尽量只移除这些词。

### 7.5 编辑自己的 LoRA 备忘

1. 选择 LoRA。
2. 点击“编辑此 LoRA 备忘”。
3. 填写标题、底模、推荐权重、触发词和链接。
4. 点击“新增服装预设”。
5. 按分区填写预设内容。
6. 点击“保存备忘”。

数据保存到面板目录中的 `lora_notes.json`。此文件属于个人数据，默认被 `.gitignore` 忽略。

示例：

```json
{
  "some_lora.safetensors": {
    "title": "示例角色",
    "base_model": "illustrious",
    "weight": "0.8",
    "trigger": "example_character",
    "url": "https://example.com/model-page",
    "outfits": [
      {
        "name": "默认服装",
        "subject": "example_character, 1girl",
        "appearance": "long black hair, blue eyes",
        "clothing": "white dress, black pantyhose",
        "pose": "standing",
        "composition": "full body",
        "scene": "simple background",
        "lighting": "soft daylight",
        "style": "",
        "negative": "",
        "other": ""
      }
    ]
  }
}
```

### 7.6 LoRA 同名 TXT

同名 TXT 是与 LoRA 放在同一目录、主文件名完全相同的说明文件：

```text
角色A.safetensors
角色A.txt
```

面板会显示 TXT 原文，并把识别结果做成可点击预设。点击预设时，标签会分别进入人物、角色外貌、服装、姿势、构图、场景、光线、画风、负面和其他分区；不会把整篇说明无条件塞进一个提示词框。

项目提供两个互相独立的本地工具。它们都不联网，也不会上传 TXT、模型或提示词：

| 工具 | 双击入口 | 作用 | 默认安全行为 |
| --- | --- | --- | --- |
| LoRA 同名 TXT 生成器 | `生成-LoRA同名TXT.bat` | 从 `.safetensors` 的 JSON 头部元数据生成结构化同名 TXT | 只生成缺失 TXT，已有 TXT 一律跳过 |
| TXT 智能分区 JSON 导入器 | `智能导入-LoRA-TXT到JSON.bat` | 理解现有 TXT，把各类标签分别合并进 `lora_notes.json` | 先完整分析，必须输入 `YES`；写入前自动备份；不覆盖手写非空字段 |

#### 7.6.1 一键生成缺失的同名 TXT

1. 先关闭正在编辑 LoRA TXT 的记事本，避免文件占用。
2. 双击面板目录中的 `生成-LoRA同名TXT.bat`。
3. 查看“扫描到 LoRA”“准备生成”和“保护并跳过已有 TXT”数量。
4. 确认目标正确后输入大写 `YES`。
5. 工具会在每个 LoRA 旁创建同名 `.txt`。

生成器只读取 safetensors 开头的 JSON 元数据，不读取或加载后面的模型张量，所以速度快且不会占用生成显存。它会尝试提取模型标题、适用底模、推荐权重、显式触发词和训练标签，再按语义写入不同分区。某些 LoRA 没有训练元数据，此时仍会生成可手工补充的结构化模板，并将触发词留空，不能凭文件名猜造触发词。

默认模式永远不覆盖已有 TXT。需要先预演时，在 PowerShell 中运行：

```powershell
Set-Location G:\ComfyUI\ComfyUI_Easy_Panel
.\生成-LoRA同名TXT.bat --dry-run
```

常用参数：

| 参数 | 含义 |
| --- | --- |
| `--dry-run` | 只显示会处理哪些文件，不写入 |
| `--max-tags 120` | 每个模型最多保留 120 个训练标签；默认 80，允许 10–300 |
| `--overwrite-generated` | 只覆盖带 `Easy Panel LoRA Sidecar v2` 标记的旧自动生成 TXT，并先备份 |
| `--force` | 覆盖任意已有同名 TXT，并先备份；可能替换手写说明，非必要不要使用 |
| 路径参数 | 可把单个 LoRA 或文件夹拖到 `.bat` 上，也可在命令后写多个路径 |

被允许覆盖的旧 TXT 会按原相对目录备份到 `backup\lora-txt-generator-日期_时间\`。

#### 7.6.2 智能识别 TXT 并分区保存 JSON

1. 双击 `智能导入-LoRA-TXT到JSON.bat`。
2. 程序扫描 LoRA 目录中的全部 TXT，只处理旁边存在同名 `.safetensors`、`.pt` 或 `.ckpt` 的文件。
3. 它先完成全部识别并显示统计，此时尚未修改 JSON。
4. 检查“成功识别”“会改变 JSON 条目”“无有效内容”“无同名 LoRA”和“错误”。
5. 确认后输入大写 `YES`；输入其他内容会安全取消。
6. 写入成功后，重新打开或刷新面板即可看到新预设。

识别器支持中文或英文标题、冒号字段、`[预设名称]` / `【预设名称】`、一行逗号标签、只有一个触发词的 TXT、多套服装连续段落，以及“角色Yoruno Sakura,...”这类标题与英文标签粘连的文本。标签会独立保存为：

| JSON 字段 | 内容示例 |
| --- | --- |
| `subject` | 角色触发词、人物数量、角色或作品名 |
| `appearance` | 发色、发型、眼睛、体型、身体特征 |
| `clothing` | 服装、丝袜、鞋帽、首饰和配件 |
| `pose` | 站、坐、躺、手部动作、互动动作 |
| `composition` | 全身、半身、特写、俯视、仰视、镜头角度 |
| `scene` | 室内外、房间、街道、海滩和背景元素 |
| `lighting` | 日光、背光、霓虹、阴影和电影光效 |
| `style` | 画风、媒介、渲染方式和画师触发词 |
| `negative` | 低质量、错误肢体、水印等反向标签 |
| `other` | 无法可靠归入上述类别但仍需保留的标签 |

程序优先相信明确的分区标题，再使用本地语义词典判断无标题标签。对于 `HGK` 之类无法仅凭文字理解的短触发词，会把所在目录名作为低优先级提示，例如“画风”目录归入 `style`、“服装”目录归入 `clothing`、“角色”目录归入 `subject`。已明确识别出的发色、服装、姿势等不会被目录提示强行改类。

默认合并不会覆盖已有的标题、触发词或预设非空字段，只补空字段并加入新预设；旧版 JSON 的 `prompt` 会自动按 `clothing` 读取，`manual` 会按 `other` 读取。不同子目录若存在同名 LoRA，程序会自动改用相对路径作为 JSON 键，避免两份模型的角色与服装预设互相覆盖。写入前，旧文件自动备份为：

```text
backup\lora_notes.before-smart-import.日期_时间.json
```

完整导入明细保存为：

```text
backup\lora-smart-import-report-日期_时间.json
```

只查看识别结果、不生成备份也不写 JSON：

```powershell
Set-Location G:\ComfyUI\ComfyUI_Easy_Panel
.\智能导入-LoRA-TXT到JSON.bat --dry-run
```

只处理一个 TXT、一个 LoRA 或一个子目录，可以把目标拖到 `.bat` 上，或写在命令末尾。`--replace` 会以 TXT 结果替换同名预设，适合明确要重建自动数据时使用，但它会改变原预设，建议先运行 `--dry-run` 并确认备份。

`.bat` 是推荐的双击入口；同名 `.cmd` 仅为旧版本和已有快捷方式保留，功能完全相同。

#### 7.6.3 推荐的 TXT 写法

识别器能兼容杂乱旧文本，但新文件建议使用下面的结构，结果最稳定，也方便人工阅读：

```text
名称：示例角色
适用底模：Illustrious
推荐权重：0.8
触发词：example_character
来源：https://example.com/model-page

[基础角色]
人物与角色：example_character, 1girl
角色外貌：long black hair, blue eyes

[默认服装]
服装与配饰：white dress, black pantyhose, black heels
姿势与动作：standing, looking at viewer
构图与镜头：full body, front view
场景与背景：simple background
光线：soft daylight
画风与媒介：anime illustration
负面标签：watermark, bad hands
其他标签：sparkles

[校服]
服装与配饰：school uniform, white shirt, pleated skirt
```

逗号建议使用英文半角逗号；文件建议保存为 UTF-8。读取器也会自动兼容 UTF-8 BOM、UTF-16、GB18030/GBK 和常见日文 CP932 文本。自动识别是确定性的语义分类，不是联网大模型推理，优点是隐私安全、结果可重复；极少见的缩写或自定义训练词仍应在面板中人工检查，必要时直接编辑 `lora_notes.json` 或 TXT 后重新导入。

需要把所有同名 TXT 批量解析进 `lora_notes.json` 时，可以运行：

```powershell
& "G:\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe" .\import_all_sidecars.py
```

使用前检查 `import_all_sidecars.py` 顶部的面板路径是否与本机一致，并先备份 `lora_notes.json`。

## 8. OpenPose 姿势控制

### 8.1 使用条件

- 当前模型必须是 SDXL / Illustrious。
- 已安装 `comfyui_controlnet_aux`。
- ComfyUI 能看到兼容的 OpenPose ControlNet。
- 若要手动编辑骨架，还需安装 `ComfyUI-openpose-editor`。

Anima 和 Krea 2 会自动禁用当前 Xinsir SDXL OpenPose 链路。

### 8.2 从人物图片提取动作

1. 勾选“启用姿势控制”。
2. 姿势图类型选择“人物动作参考图”。
3. 骨架提取方式先选“自动”。
4. 上传清晰人物图，建议完整露出头部、躯干、手臂和腿。
5. 点击“提取骨架预览”。
6. 检查骨架是否跟随人物。
7. 姿势强度先用 `0.82`。
8. 控制结束步数先用 `0.75`。
9. 正常生成。

自动模式会按顺序尝试：

1. `dwpose-full`：适合动漫单角色，不依赖 YOLO 先检测人物框。
2. `dwpose-yolo`：适合真人或多人照片。
3. `openpose`：备用方案，首次可能下载约 700 MB 模型并耗时较长。

同一张图、同一提取模式会复用上次骨架结果。需要重新识别时点击“强制重新提取”。

### 8.3 直接使用骨架图

如果已经有 OpenPose 彩色骨架图：

1. 姿势图类型选择“已绘制的 OpenPose 骨架图”。
2. 上传骨架图。
3. 生成时不再执行人物检测。

### 8.4 编辑提取后的骨架

提取成功后，“编辑已提取骨架”按钮会启用。打开编辑器后移动关节点，保存并返回面板。若编辑器无法打开：

- 确认安装了 `ComfyUI-openpose-editor`。
- 确认 ComfyUI 中存在 `huchenlei.LoadOpenposeJSON`。
- 检查是否能访问编辑器使用的网页资源。

也可以点击“下载空白骨架编辑工作流”，在 ComfyUI 中加载 JSON，右键 `Load Openpose JSON` 节点并选择打开编辑器。

### 8.5 参数解释

| 参数 | 作用 | 建议 |
| --- | --- | --- |
| 姿势强度 | 对骨架的服从程度 | `0.7–0.9` 常用，过高可能僵硬 |
| 控制结束步数 | 前多少比例采样受骨架控制 | `0.65–0.8` 常用 |
| 提取分辨率 | 由面板工作流自动处理 | 默认即可 |

## 9. Illustrious、Anima、Krea 2 专用功能

### 9.1 Illustrious 精准模式

精准模式只进行一次采样，最适合：

- 测试 checkpoint。
- 比较 LoRA 权重。
- 检查角色触发词。
- 快速判断提示词是否正确。

先用精准模式确认画面，再考虑高清模式。点击“预检提示词与 LoRA”可以检查底模、提示词长度、LoRA 兼容性和显存风险。

### 9.2 Illustrious 高清模式

高清模式先解码第一次采样结果，使用 `RealESRGAN_x4plus_anime_6B` 在像素域执行动漫专用 AI 超分，再用 Lanczos 缩到目标尺寸，经 VAE 编码执行第二次低重绘采样。这能重建轮廓与纹理，避免 latent 插值造成的整体柔糊。

所需模型：`ComfyUI/models/upscale_models/RealESRGAN_x4plus_anime_6B.pth`。缺少该文件时，ComfyUI 会在提交高清任务时报告模型不存在。

默认思路：

- 放大倍率：`1.25×`
- 重绘幅度：`0.30–0.40`（默认 `0.35`）
- 二次步数：`18–24`（默认 `20`）
- 二次 CFG：`4.0–4.5`

8 GB 显存建议：

- 基础尺寸较小时使用 `1.25×`。
- 基础尺寸已经较大时改为 `1.10–1.15×`。
- 显存紧张时启用分块 VAE；高清链路的首次解码、重新编码和最终解码都会使用同一分块设置。
- 若只是判断 LoRA 风格，继续用精准模式。

#### 9.2.1 输出增强工作流

“模型增强与低显存 VAE”面板提供与高清二次采样互斥的整图输出增强。面板会读取 `/api/models` 的真实节点与权重清单；依赖不完整的选项会直接禁用，不会提交一个必然缺节点的工作流。

| 模式 | 适用场景 | 实际链路 |
| --- | --- | --- |
| Anime6B 后处理超分 | Anima、Krea 2 或不希望再次改变构图 | `RealESRGAN_x4plus_anime_6B` → Lanczos 精确目标尺寸；不做扩散重绘 |
| SeedVR2 生成式超分 | 小图修复、轮廓与纹理重建 | 原生 SeedVR2 3B Int8，一步采样，支持 LAB / Wavelet / AdaIN 色彩回正 |
| Ultimate SD Upscale | SDXL / Illustrious 的 2× 以上大图 | Anime6B 预放大后按 tile 扩散细化，默认 512 tile、20 步、denoise 0.2 |

可选后级：

- `FaceDetailer` 在超分后检测单人脸并局部重绘。多人分区与 Krea 2 会安全禁用，避免一条检测支路错误覆盖多个人物。
- “自动修复手指”和“自动修复脚趾/鞋形”默认关闭，按需使用专用 YOLO 检测器定位局部，再以 `512` 引导尺寸、`12` 步、`0.35` 重绘幅度串行重绘。检测置信度提高到 `0.50`，并缩小裁剪和膨胀范围，避免把绳结、灯笼和背景小装饰误画成手脚。
- 手脚局部修复在多人分区、Krea 2 和手绘蒙版修复模式下自动禁用。复杂背景、严重遮挡或极小手脚优先使用手绘蒙版修复；检测器没有可靠命中时图像保持不变。
- 结构化提示词的“场景”为空时，编译器会使用简洁背景兜底；`solo` 会自动排除背景人物、漂浮肢体和重复人物。需要具体环境时，请在“场景”中明确填写。
- 原生 `ColorTransfer` 可在最终输出前把颜色匹配回第一次解码的基准图，默认 Reinhard LAB、强度 `0.7`。
- 高清二次采样现在同时支持通用 SDXL / Gock 和 Illustrious，并按具体模型配置二次倍率、denoise、步数、CFG、采样器和调度器。

本机依赖位置：

```text
ComfyUI/custom_nodes/ComfyUI_UltimateSDUpscale/
ComfyUI/custom_nodes/ComfyUI-Impact-Subpack/
ComfyUI/models/ultralytics/bbox/face_yolov8m.pt
ComfyUI/models/ultralytics/bbox/hand_yolov8s.pt
ComfyUI/models/ultralytics/bbox/foot_yolov8x.pt
ComfyUI/models/diffusion_models/seedvr2_3b_int8_convrot.safetensors
ComfyUI/models/vae/seedvr2_ema_vae_fp16.safetensors
```

检测模型来源：[`hand_yolov8s.pt`](https://huggingface.co/Bingsu/adetailer) 与 [`foot_yolov8x.pt`](https://huggingface.co/MonetEinsley/ADetailer_CM)。请分别阅读模型卡与许可证；权重不随 Easy Panel 安装包分发。

安装或更新自定义节点后必须重启 ComfyUI。画质判断请固定 checkpoint、VAE、提示词、LoRA、seed 和基础尺寸，每次只切换一个增强模式做 GPU A/B；不要把高清二次采样、SeedVR2 和 Ultimate 同时叠加。

### 9.3 Illustrious 局部修复

选择“局部修复”后：

1. 上传原图。
2. 在画布中用红色画笔涂需要重绘的位置。
3. 用橡皮修正边缘。
4. 点击“上传蒙版”。
5. 蒙版膨胀先用 `6`。
6. 重绘幅度先用 `0.5`。
7. 修改提示词，描述修复后应该出现的内容。
8. 生成。

建议：

- `0.35–0.5`：轻微修脸、衣服或小错误。
- `0.5–0.7`：明显更换局部内容。
- 接近 `1.0`：容易把蒙版区域完全重画。
- 蒙版越精确，未涂区域越容易保持不变。

### 9.4 Anima 分层提示词

选择 Anima 后会显示三个专用输入层：

1. **硬标签**：角色、服装、发型、动作等可验证 tag。
2. **质感短语**：肌肤、布料、丝袜、光线和画风描述。
3. **自然语言关系 / 镜头**：人物动作归属、空间关系和光线方向。

推荐示例：

```text
硬标签：1girl, solo, long_hair, black_hair, pantyhose, full_body
质感：smooth ivory skin, semi-sheer nylon texture, soft matte-satin sheen
关系句：She stands beside the window and looks at the viewer. Soft daylight falls from the left.
```

点击“验证硬标签”后，已知 tag 会规范化，未知 tag 会给出候选。该功能依赖 `vendor\anima-tags\anima-1.0.csv`。

“高分辨美学补强”会尝试加入本机指定 boost LoRA；本机没有该 LoRA 时会提示未找到，不影响 Base 模式。

### 9.5 Krea 2 Turbo

Krea 2 是蒸馏免引导模型，面板锁定：

```text
8 steps · CFG 1.0 · euler / simple
```

使用 Krea 2 时：

- 不要手动提高 CFG。
- 不支持 SAG / PAG。
- 不支持当前 SDXL OpenPose。
- 不支持多人区域提示词。
- 更适合自然语言描述。
- 8 GB 显存下大图可能因 CPU 卸载而明显变慢。

常用方法是先用 Krea 2 生成构图和真实底图，再用 Illustrious / Anima 的整图 img2img 转成二次元。

## 10. 高级参数与推荐组合

### 10.1 最安全的用法

新手请保持：

```text
采样器：自动（按模型预设）
调度器：自动（按模型预设）
注意力引导：关闭
```

模型切换时，面板会清除上一模型遗留的手动覆盖。高级参数顶部会显示当前模型来源、推荐组合和“快速 / 推荐 / 细节”按钮。

### 10.2 本机模型推荐表

| 模型 | 推荐组合 | 说明 |
| --- | --- | --- |
| WAI Illustrious v14 | 28 步 · CFG 6.0 · `euler_ancestral / normal` | 作者范围 25–40 步、CFG 5–7 |
| REED Illustrious v15 | 30 步 · CFG 7.0 · `euler_ancestral / normal` | 作者示例约 30 / 7；高清可用 1.5 倍、降噪 0.35–0.5 |
| Illustrious XL Base | 24 步 · CFG 6.0 · `euler_ancestral / normal` | 官方范围 20–28 步、CFG 5–7.5 |
| Spectacular Anime ILXL | 24 步 · CFG 7.0 · `euler_ancestral / beta` | 作者要求 Simple / Beta，不推荐 Normal |
| Milmu Anime Illustrious v-pred | 30 步 · CFG 6.0 · `euler / normal` | 自动应用 `v_prediction`；CFG Rescale 可用 |
| Gock So Anime Love Song | 30 步 · CFG 7.0 · `dpmpp_2m_sde / karras` | 材质细节可试 34 步 / CFG 6.5 |
| PlantMilk Walnut | 28 步 · CFG 3.0 · `euler / normal` | 作者建议从 CFG 3 起步，常用约 28 步 |
| Anima Base | 34 步 · CFG 4.8 · `er_sde / simple` | 官方范围 30–50 步、CFG 4–5 |
| Hoseki LustrousMix Anima | 24 步 · CFG 4.5 · `er_sde / simple` | 作者推荐 ER SDE / Euler a、CFG 4–5 |
| Nova Anime Anima | 24 步 · CFG 4.5 · `euler_ancestral / normal` | 发布配置 |
| Krea 2 Turbo FP8 / INT8 | 8 步 · CFG 1.0 · `euler / simple` | 后端锁定 |

每个模型的“快速 / 推荐 / 细节”组合、来源链接、分辨率上限和能力开关由 `easy_panel_app/data/model_profiles.json` 统一管理；切换模型时界面会同步更新，不再把上一模型参数误带到下一模型。

### 10.3 模型增强与显存选项

- **FreeU V2**：无需额外模型的结构增强；SDXL / Illustrious 可试，功能默认关闭。开启时默认选择“官方 SDXL / ComfyUI V2”：`b1 1.3`、`b2 1.4`、`s1 0.9`、`s2 0.2`。这组数值同时来自 [FreeU 作者给出的 SDXL 参数](https://github.com/ChenyangSi/FreeU#parameters)和 [ComfyUI FreeU_V2 官方节点默认值](https://docs.comfy.org/built-in-nodes/FreeU_V2)。
- 如果官方组合让画面对比过重、暗部压黑或风格变化太大，可一键切换“SDXL 柔和参考（Diffusers）”：`b1 1.1`、`b2 1.2`、`s1 0.6`、`s2 0.4`。此组合来自 [Hugging Face Diffusers 的 SDXL FreeU 示例](https://huggingface.co/docs/diffusers/v0.22.0/en/using-diffusers/freeu)，它作为备选，不取代与本项目实际 ComfyUI V2 节点完全一致的默认组合。
- **CFG Rescale**：只对 v-pred 模型开放，例如 Milmu；建议从 `0.7` 起步。普通 eps 模型会被后端拒绝，避免“看似生效、实际不适用”。
- **Tiled VAE**：大图或显存紧张时选择，默认 tile `512`、overlap `64`。它降低 VAE 峰值显存，但编码/解码会变慢；显存足够时保持标准 VAE。
- **Krea 2 Turbo 2K**：允许对齐后的最高 `2048 × 2048`；8 GB 显存不建议直接从 2K 起步。

所有增强默认关闭，因此升级后旧任务的工作流和速度不会被自动改变。

### 10.4 SAG 与 PAG

- **SAG**：增强主体与背景的整体自注意力一致性。建议 `scale 0.35–0.5`、`blur 2.0` 起步。
- **PAG**：更偏向主体和细节强化。建议 `1.5–2.0`，通常不要超过 `2.5`。

使用限制：

- 二者都会增加耗时。
- 默认关闭通常最稳定。
- 多人区域模式禁止同时启用 SAG / PAG。
- Krea 2 不支持。
- 如果出现过锐、颜色过冲、脸部结构异常，先关闭注意力引导。

## 11. 多人区域提示词

### 11.1 它解决什么问题

普通提示词同时写两个人时，模型容易交换发色、服装、角色 LoRA 和性别特征。多人区域模式通过柔边蒙版分别编码各角色，并把绑定的角色 LoRA 限制在对应位置。

它不能保证百分之百隔离，但比把所有角色标签混在一个正向提示词中更稳定。

### 11.2 双人推荐设置

- 模型：SDXL / Illustrious。
- 尺寸：横图 `1216 × 832` 起步。
- 区域：点击“左右双人”。
- 两个角色强度：先用 `1.0`。
- 左右区域允许少量柔边重叠，但不要大面积交叉。
- 注意力引导：关闭。
- 第一次生成数量：`1`。

### 11.3 正确填写方式

“全局场景 / 关系 / 画风补充”只写双方共享内容：

```text
classroom, two girls hugging, afternoon sunlight, cowboy shot, continuous background
```

角色 1 只写角色 1：

```text
alice, 1girl, blue hair, blue eyes, white dress
```

角色 2 只写角色 2：

```text
bobette, 1girl, red hair, green eyes, black uniform
```

不要这样写：

```text
角色 1：alice hugging bobette in classroom
角色 2：bobette hugging alice in classroom
```

共享互动重复进入两个角色区，会增强特征融合和双画面倾向。

### 11.4 绑定角色 LoRA

1. 先在普通 LoRA 区添加两个角色 LoRA。
2. 在角色 1 中绑定第一个 LoRA。
3. 在角色 2 中绑定第二个 LoRA。
4. 未绑定到角色区的 LoRA 会作为全局 LoRA，适合画风或通用材质。

如果角色区绑定的 LoRA 已从普通 LoRA 列表移除，生成前会报错并要求重新选择。

### 11.5 区域参数

- `X / Y`：区域左上角，范围 `0–1`。
- `宽 / 高`：区域相对画布的宽高，范围 `0–1`。
- 强度：conditioning 权重，建议从 `1.0` 开始。
- 预设：左、右、上、下或自定义。

角色区域如果大面积重叠，面板会阻止生成并提示缩小范围。小幅重叠用于柔和过渡是允许的。

### 11.6 常见错误

| 现象 | 调整方法 |
| --- | --- |
| 两个人发色 / 服装互换 | 确认角色标签只写在各自区域，并正确绑定 LoRA |
| 图片从中间变成两张独立画面 | 全局加入互动和连续背景，避免 `split screen`、`two panels` 类词，区域不要完全硬切 |
| 意外出现男性 | 两个角色的人物类型都选 `1girl`，不要在全局写含混的 `couple` |
| 角色靠得太远 | 全局明确写 `standing close together`、`hugging` 等关系 |
| 双人特别慢 | Hook LoRA 和多路 conditioning 本来就比单人慢；先用 512/768 级尺寸、单张、关闭高清与 SAG/PAG |

## 12. 局部修复、整图重绘与调色

### 12.1 整图 img2img

整图重绘以底图 latent 为起点，用当前模型重新采样。

1. 展开“整图重绘”。
2. 勾选启用。
3. 上传底图，或从最近输出中选择。
4. 设置重绘幅度。
5. 选择要使用的目标模型和 LoRA。
6. 修改提示词描述目标结果。
7. 生成。

重绘幅度：

| 范围 | 效果 |
| --- | --- |
| `0.2–0.35` | 保留原图，微调细节和色彩 |
| `0.35–0.55` | 改变风格但保留主要结构 |
| `0.55–0.7` | 明显改画风，Krea 2 转二次元常用 |
| `0.7–1.0` | 大幅重画，越接近 1 越像重新生成 |

底图超过 2.5 MP 会被后端拒绝，以防 8 GB 显存直接溢出；实际建议控制在 1.5 MP 以内。

### 12.2 Krea 2 转二次元示例

1. 用 Krea 2 生成构图正确的底图。
2. 切换到 WAI / Milmu / Anima。
3. 展开整图重绘并从最近输出选择 Krea 2 图片。
4. 重绘幅度设为 `0.55–0.65`。
5. 加入目标二次元 LoRA 和提示词。
6. 先生成 1 张比较。

### 12.3 生成后调色

勾选调色后，工作流会在解码后加入 LayerStyle 节点：

- 亮度：大于 1 变亮，小于 1 变暗。
- 对比度：大于 1 增强反差。
- 整体饱和度：大于 1 更鲜艳。
- Gamma：调整暗部和中间调。
- RGB：单独增加或减少红、绿、蓝。
- HSV：调整色相、饱和度和明度。
- Levels：黑场、白场和中灰。

推荐先用默认值生成，再进行小幅调整。评估 checkpoint / 画风 LoRA 时先关闭调色，否则无法判断颜色来自模型还是后处理。

“实时预览调色效果”只在生成单张图片时可用。它用于预览参数，不会自动替换已经保存的原图；重新生成才会在工作流中正式应用。

## 13. 直接生成与任务队列

### 13.1 直接生成

点击“生成图片”会立即提交当前配置。

- 生成数量范围为 `1–16`。
- 每张图作为独立 ComfyUI prompt 提交。
- 种子为 `-1` 时，每张图独立随机。
- 固定种子时，后续图片按 `种子 + 1` 递增。
- 面板单个 prompt 最长等待 60 分钟。
- 点击生成后会显示实时进度条：包含当前第几张、已经完成几张以及 ComfyUI 当前采样步数。
- 实时采样步数通过 ComfyUI WebSocket 获取；连接暂时中断时，进度条仍会按每张图片完成情况更新，不影响生成任务。

### 13.2 暂存任务队列

适合先配置多组模型、LoRA 和提示词，再一次发送：

1. 设置第一组完整参数。
2. 设置“生成数量”。
3. 点击“＋ 加入任务队列”。
4. 修改成第二组参数。
5. 再点击“＋ 加入任务队列”。
6. 重复直到配置完成。
7. 检查按钮上的“任务数 / 图片数”。
8. 点击“发送队列”。

加入队列时会保存当前模型、LoRA、提示词、尺寸、种子、高级参数和生成数量的快照。加入后再修改界面，不会改变已经暂存的旧任务。

### 13.3 队列数量规则

- 最多 50 个逻辑任务。
- 展开后最多 200 张图片。
- 单个逻辑任务最多 16 张。
- `22 个任务 × 每个 3 张 = 66 张`。
- 队列按钮会明确显示 `22任务 / 66张`。
- 未发送队列在当前浏览器会话刷新后恢复。
- 浏览器窗口 / 会话完全关闭后，`sessionStorage` 可能被清除。

### 13.4 发送失败时怎么办

如果浏览器提示等待失败，已经提交到 ComfyUI 的任务仍可能继续执行。先查看：

```text
http://127.0.0.1:8188
```

以及 ComfyUI 的 `output` 目录，不要立刻重复发送整个队列，否则可能重复生成。

## 14. 常用完整工作流程

### 14.1 测试一个画风 LoRA

1. 选择匹配底模。
2. 应用画风测试预设。
3. 使用简单人物、站立和纯背景。
4. 加 LoRA，权重先用 `0.6–0.7`。
5. 关闭调色、姿势、多人、SAG/PAG 和高清。
6. 固定一个种子。
7. 分别生成无 LoRA、0.6、0.7、0.8 对照图。

### 14.2 正式单人角色图

1. 先通过最小画风测试确认模型和 LoRA。
2. 改为正式出图预设。
3. 补充外貌、服装、姿势、构图、场景和光线。
4. 尺寸使用 `832×1216` 或 `896×1344`。
5. 使用模型“推荐”组合。
6. 需要更大图时再启用 Illustrious 高清模式。

### 14.3 双角色互动图

1. 选择横图 `1216×832`。
2. 添加两个角色 LoRA。
3. 启用多人区域并点击“左右双人”。
4. 每个角色只写自己的外貌和服装。
5. 全局写互动、场景、镜头和连续背景。
6. 绑定对应 LoRA。
7. 关闭 SAG/PAG 和高清，先生成 1 张。
8. 构图正确后再提高尺寸或批量。

### 14.4 复现一张旧图

1. 上传原始 AI 图片到“读取 AI 图片参数”。
2. 点击“填入生成面板”。
3. 检查本机是否有同名模型和 LoRA。
4. 保持原始种子、尺寸、步数、CFG、采样器和调度器。
5. 关闭原图没有使用的新功能。
6. 生成并比较。

不同 ComfyUI / PyTorch / CUDA / 模型文件版本仍可能产生像素级差异。

## 15. 显存、速度与画质建议

### 15.1 8 GB 显存建议

- 初次测试：`512×768`，单张。
- 常规二次元：`768×1024` 或 `832×1216`，单张。
- Anima / Krea 2：尽量控制在 1024 级或约 1.25 MP 以内。
- img2img 底图：建议 1.5 MP 以内。
- 高清模式：基础图不要过大，倍率先用 `1.10–1.25`。
- 多人：关闭 SAG/PAG、高清和实时调色，先跑 1 张。

### 15.2 为什么双人会比单人慢很多

多人区域需要为多个角色分别执行提示词编码、蒙版 conditioning 和角色 Hook LoRA。若再叠加大尺寸、高清二次采样、多个 LoRA 或姿势控制，耗时会成倍增加。十分钟不一定代表卡死，应同时查看 ComfyUI 是否仍在采样。

### 15.3 判断卡死还是仍在运行

- Easy Panel 或 ComfyUI 的实时进度条仍在更新：任务仍在运行。
- GPU 有占用，终端持续更新：通常仍在运行。
- Easy Panel 显示运行 1：任务仍在 ComfyUI。
- ComfyUI 终端出现 traceback / `error`：查看最后一个节点错误。
- 长时间 GPU 0%、队列不变且无终端输出：可能节点下载、CPU 卸载或异常。

## 16. 数据保存、备份与升级

### 16.1 哪些内容保存在哪里

| 内容 | 保存位置 | 刷新后 |
| --- | --- | --- |
| AI 服务、接口、Key、字体和预览大小 | 浏览器 `localStorage` | 保留 |
| 各模型族提示词 | 浏览器 `sessionStorage` | 当前会话保留 |
| LoRA 选择和权重 | 浏览器 `sessionStorage` | 当前会话保留 |
| 已应用 LoRA 预设状态 | 浏览器 `sessionStorage` | 当前会话保留 |
| 未发送任务队列 | 浏览器 `sessionStorage` | 当前会话保留 |
| LoRA 备忘和预设 | `lora_notes.json` | 文件永久保留 |
| 上传的姿势 / 重绘图片 | `ComfyUI\input\easy_panel` | 文件保留，需自行清理 |
| 生成结果 | `ComfyUI\output` | 文件永久保留 |

API Key 不写入 `easy_panel.py` 或 `lora_notes.json`，但点击 AI 转换时会发送给你配置的服务商。使用公共电脑后应清除浏览器站点数据。

### 16.2 更新项目前先备份

至少备份：

```text
easy_panel.py          # 兼容入口与工作流编排
easy_panel_app\        # 后端模块、模型数据和配置
web\                   # 前端 CSS / JS 模块
index.html             # 页面结构
lora_notes.json        # 个人 LoRA 数据（若存在）
pose_editor_workflow.json
```

Git 更新：

```powershell
Set-Location G:\ComfyUI\ComfyUI_Easy_Panel
git status
git pull
```

本机路径现在由环境变量或 `启动面板.cmd` 管理，不再需要修改 `easy_panel.py`，因此更新时更不容易产生冲突。Core / All 安装器也会先把旧核心文件和模块目录备份到 `backup\installer-日期时间`。

### 16.3 restore_backup.ps1

仓库提供本地备份恢复脚本。使用前必须打开脚本，把 `$PanelDir` 改为自己的面板路径。

恢复最新备份：

```powershell
.\restore_backup.ps1
```

恢复指定目录：

```powershell
.\restore_backup.ps1 -Backup "2026-08-05_2110"
```

脚本执行恢复前会再次备份当前状态，并要求输入 `Y` 确认。

## 17. 故障排查

### 17.1 面板打不开

**现象：** `127.0.0.1:8190` 拒绝连接。

检查：

1. `easy_panel.py` 的终端窗口是否仍开着。
2. 终端是否提示端口被占用。
3. `PORT` 是否被改过。
4. 是否使用了正确 Python。

端口占用可用 PowerShell 查看：

```powershell
Get-NetTCPConnection -LocalPort 8190 -ErrorAction SilentlyContinue
```

### 17.2 面板打开但模型列表失败

**现象：** 显示“模型列表加载失败”或一直读取。

检查：

1. ComfyUI 8188 是否已启动。
2. `COMFY = "http://127.0.0.1:8188"` 是否正确。
3. 浏览器能否打开 `http://127.0.0.1:8188/object_info`。
4. ComfyUI 是否卡在第三方节点导入错误。

### 17.3 模型显示“仅 UNet，不能直接使用”

该文件没有可供 `CheckpointLoaderSimple` 使用的内置 CLIP / VAE。解决方法：

- 换完整 checkpoint；或者
- 按 Anima / Krea 2 分体模型方式放入 `diffusion_models`；并
- 补齐面板要求的 text encoder 和 VAE。

### 17.4 LoRA 看不到

检查：

- 文件是否在配置的 `LORA_DIR` 下。
- 文件是否为 ComfyUI 能识别的格式。
- 当前模型族筛选是否隐藏了不兼容 LoRA。
- “LoRA 分类”是否选了其他文件夹。
- 放入新 LoRA 后是否重启 / 刷新了 ComfyUI 和面板。

### 17.5 刷新后 LoRA 或提示词不一致

当前版本会恢复 LoRA 和权重。移除 / 清空 LoRA 会自动撤销它通过预设加入的词，并保留手写内容。若仍异常：

1. 强制刷新页面。
2. 点击“清空 LoRA”。
3. 点击“重置为初始提示词”。
4. 重新选择 LoRA 和预设。

### 17.6 缺少节点 / `class_type ... does not exist`

| 缺少节点 | 解决方法 |
| --- | --- |
| `DWPreprocessor` / `OpenposePreprocessor` | 安装或修复 `comfyui_controlnet_aux` |
| `huchenlei.LoadOpenposeJSON` | 安装 `ComfyUI-openpose-editor` |
| `LayerColor: ...` | 安装 `ComfyUI_LayerStyle` 及其 requirements |
| `SelfAttentionGuidance` / `PerturbedAttentionGuidance` / Hook 节点 | 更新 ComfyUI |

安装后必须重启 ComfyUI，再刷新 Easy Panel。

### 17.7 OpenPose 提取失败

- 换清晰、无遮挡、人物占画面较大的图片。
- 动漫单人先用 `dwpose-full`。
- 真人 / 多人先用 `dwpose-yolo`。
- 等待首次模型下载完成。
- 检查 ComfyUI 终端是否有 ONNX、OpenCV 或模型下载错误。
- 实在无法检测时，直接上传已绘制的骨架图。

### 17.8 生成出现显存不足 / OOM

按顺序处理：

1. 生成数量改成 1。
2. 尺寸改成 `512×768` 或 `768×1024`。
3. 关闭高清模式。
4. 关闭多人区域。
5. 关闭 SAG / PAG。
6. 减少 LoRA。
7. 缩小 img2img 底图。
8. 重启 ComfyUI 释放显存。

### 17.9 图片从中间分成两幅画面

这通常是提示词和区域设置问题，不是输出文件被切开：

- 删除 `split screen`、`two panels`、`comic panels` 等词。
- 多人互动只写在全局区。
- 全局加入 `single continuous scene`、共享场景和明确互动。
- 左右区域保持少量柔边过渡，不要硬切且完全无共同提示。

### 17.10 双人出现错误性别或人物融合

- 为每个区域明确选择 `1girl` / `1boy`。
- 每个角色区只写自己的外貌和衣服。
- 将角色 LoRA 绑定到对应区域。
- 不要把两个角色触发词同时写进全局区。
- 降低过高 LoRA 权重。
- 先关闭姿势、SAG/PAG 和高清排查。

### 17.11 每个队列任务只生成一张

当前版本会把每个任务的“生成数量”一起保存，并在按钮上显示总图片数。确认：

- 页面显示类似 `22任务 / 66张`，而不是只显示 22。
- 加入任务前已经把生成数量设为 3。
- 刷新到最新前端后重新建立旧队列。

旧版本建立但未发送的内存队列无法自动补回缺失的生成数量。

### 17.12 AI 翻译失败

- 检查服务预设、协议、鉴权和模型 ID 是否匹配。
- 远程 URL 必须为完整 HTTPS 地址。
- 本机 Ollama 才使用 HTTP + 无密钥。
- 检查 API 余额、配额和模型权限。
- 从服务商错误信息中确认是 401、403、404、429 还是模型输出为空。
- 中文描述不要超过 6000 字符。

### 17.13 读不到图片参数

请使用未经编辑、未经聊天软件压缩的原始 PNG / WebP。JPG 的生成元数据更容易在导出时丢失。

### 17.14 等待超过 60 分钟

前端超时不等于 ComfyUI 已取消。打开 ComfyUI 检查队列和 `output` 目录。确认任务仍在运行时不要重复发送。

## 18. 开发、自检与目录结构

### 18.1 运行自动测试

```powershell
Set-Location G:\ComfyUI\ComfyUI_Easy_Panel
& "G:\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe" -m py_compile .\easy_panel.py .\lora_txt_generator.py .\lora_txt_to_json.py .\easy_panel_app\config.py .\easy_panel_app\model_profiles.py .\easy_panel_app\lora_sidecars.py .\easy_panel_app\tag_classifier.py
& "G:\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe" -m unittest discover -s tests -v
& "C:\Program Files\nodejs\node.exe" --check .\web\assets\js\panel.js
```

测试覆盖模型推荐、高级参数、SAG/PAG、模型级高清采样、Anime6B / SeedVR2 / Ultimate 输出增强、FaceDetailer、原生色彩匹配、元数据恢复、多人区域隔离、任务队列展开、LoRA 标签分类、TXT 解析、safetensors 头部读取和 JSON 安全合并等核心逻辑。真实 GPU 多模型画质 A/B 与外部翻译端到端测试仍分别需要显卡运行和有效 API Key。

### 18.2 目录结构

```text
ComfyUI_Easy_Panel\
├── easy_panel.py             # 向后兼容入口、工作流编排和 HTTP 门面
├── easy_panel_app\           # 模块化后端
│   ├── config.py             # 环境变量与路径配置
│   ├── model_profiles.py     # 模型检测、推荐组合和能力
│   ├── queueing.py           # 任务展开、种子和数量限制
│   ├── validation.py         # checkpoint 完整性检查
│   ├── media_storage.py      # 上传、input/output 安全访问
│   ├── metadata.py           # ComfyUI / A1111 / NovelAI 元数据
│   ├── image_ops.py          # 调色预览
│   ├── prompt_utils.py       # 提示词规范化公共函数
│   ├── tag_classifier.py     # 人物/外貌/服装/姿势/场景等本地语义分类
│   ├── lora_sidecars.py      # LoRA 元数据、TXT 智能解析和 JSON 安全合并
│   ├── integrations\         # ComfyUI 客户端和 AI 服务边界
│   │   ├── comfy_client.py
│   │   └── ai.py
│   └── data\model_profiles.json
├── index.html                # 只保留页面结构
├── web\assets\
│   ├── css\panel.css         # 主样式
│   └── js\
│       ├── panel.js          # 原有界面逻辑
│       └── model-advanced.js # 模型能力与高级参数扩展
├── README.md                 # 本说明
├── installers\              # 各模块的一键安装器、构建脚本和 ZIP
├── tests\                    # 自动测试
├── launchers\                # 标准便携版的一键启动 / 关闭 BAT 模板
├── lora_txt_generator.py     # 从 safetensors 头部生成缺失的同名 TXT
├── lora_txt_to_json.py       # 智能分区并安全合并 lora_notes.json
├── 生成-LoRA同名TXT.bat      # TXT 生成器推荐双击入口
├── 智能导入-LoRA-TXT到JSON.bat # 智能导入器推荐双击入口
├── 生成-LoRA同名TXT.cmd      # 旧快捷方式兼容入口
├── 智能导入-LoRA-TXT到JSON.cmd # 旧快捷方式兼容入口
├── classify_tags.py          # 新分类器的旧脚本兼容入口
├── import_all_sidecars.py    # 新导入器的旧脚本兼容入口
├── pose_editor_workflow.json # 空白 OpenPose 编辑工作流
├── restore_backup.ps1        # 本地备份恢复脚本
├── lora_notes.json           # 个人 LoRA 备注，不提交 Git
├── backup\                   # 本地备份，不提交 Git
└── vendor\                   # 可选第三方标签数据，不提交 Git
```

### 18.3 vendor 数据

```text
vendor\tagcomplete-data\
├── danbooru.csv
├── danbooru-0-zh.csv
├── Tags-zh-full.csv / Tags-zh-lite.csv
└── LICENSE.tagcomplete

vendor\anima-tags\
├── anima-1.0.csv
└── SOURCE.md
```

来源：

- [a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete)
- Anima 标签来源和授权见本地 `vendor\anima-tags\SOURCE.md`

缺失这些数据时，基础生成、LoRA、姿势、重绘和队列仍可使用。

## 19. 安全与隐私

- 面板设计为本机单人使用，只监听 `127.0.0.1`。
- 不要将 8190 或 ComfyUI 8188 端口直接暴露到公网。
- API Key 保存在当前浏览器本地，并只在请求你配置的 AI 服务时使用。
- 不要把 `lora_notes.json`、浏览器数据、私人模型或 API Key 提交到公开仓库。
- 上传的图片会复制到 `ComfyUI\input\easy_panel`；包含私人内容时请定期手动清理。
- 生成图片保存在 ComfyUI `output`，由用户自行管理和备份。
- 下载和使用模型、LoRA、数据集及第三方节点时，请遵守其许可证、平台规则和当地法律。

---

如果遇到问题，提交反馈时请附上：Easy Panel 页面错误文字、ComfyUI 终端最后 30–50 行、所选模型文件名、尺寸、生成模式以及启用的 LoRA / 姿势 / 多人 / 调色设置。不要附带 API Key。
