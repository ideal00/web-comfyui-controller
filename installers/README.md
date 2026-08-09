# Easy Panel 一键模块安装器

解压对应 ZIP 后，双击其中的 `.cmd` 文件。安装器会自动寻找 ComfyUI；找不到时会要求输入包含 `main.py` 的 ComfyUI 根目录。

## 模块

| 安装包 | 内容 | 是否包含模型权重 |
| --- | --- | --- |
| Core | Easy Panel 核心入口、后端与前端、LoRA 同名 TXT 生成器、TXT 智能分区 JSON 导入器、路径配置和启动入口 | 否 |
| LoRA Tools | 可独立安装的同名 TXT 生成器和 TXT 智能分区 JSON 导入器 | 否 |
| Pose | `comfyui_controlnet_aux` + `ComfyUI-openpose-editor` | 不包含 OpenPose ControlNet |
| Color | `ComfyUI_LayerStyle` + Python 依赖 | 不包含额外模型 |
| Tags | Danbooru TagComplete + Anima 标签索引 | 包内不预置，安装时从官方仓库下载 |
| Models | 检查 checkpoint、LoRA、ControlNet、文本编码器和 VAE | 否，只检查 |
| All | Core + Pose + Color + Tags + Models 检查 | 否 |

## 命令行用法

```powershell
.\Install-EasyPanelModule.ps1 -Module pose -ComfyRoot "G:\ComfyUI\ComfyUI_windows_portable\ComfyUI"
```

安装核心到指定位置：

```powershell
.\Install-EasyPanelModule.ps1 -Module core `
  -ComfyRoot "G:\ComfyUI\ComfyUI_windows_portable\ComfyUI" `
  -PanelRoot "G:\ComfyUI\ComfyUI_Easy_Panel"
```

只安装 LoRA TXT 工具：

```powershell
.\Install-EasyPanelModule.ps1 -Module lora-tools `
  -ComfyRoot "G:\ComfyUI\ComfyUI_windows_portable\ComfyUI" `
  -PanelRoot "G:\ComfyUI\ComfyUI_Easy_Panel"
```

跳过第三方节点的 Python requirements：

```powershell
.\Install-EasyPanelModule.ps1 -Module pose -SkipDependencies
```

## 安全行为

- 核心更新前备份现有入口、页面、README、LoRA TXT 工具、姿势工作流以及 `easy_panel_app` / `web` 模块目录。
- 不覆盖或删除 `lora_notes.json`。
- 第三方节点目录存在但不是 Git 仓库时不会覆盖。
- 只在验证后的 ComfyUI `custom_nodes` 下安装节点。
- 模型权重不随安装包分发。

核心安装器不再改写 Python 源码中的路径。它会在 `启动面板.cmd` 中设置 `EASY_PANEL_COMFY_ROOT`、`EASY_PANEL_COMFY_INPUT`、`EASY_PANEL_OUTPUT` 和 `EASY_PANEL_LORA_DIR`，所以以后更新模块不会覆盖本机路径配置。

核心安装后还会生成 `生成-LoRA同名TXT.cmd` 和 `智能导入-LoRA-TXT到JSON.cmd`。这两个入口写入安装时发现的 Python、ComfyUI 和 LoRA 路径，因此自定义安装位置也可以直接双击使用。生成器默认不覆盖已有 TXT；导入器默认先分析、要求输入 `YES`，并在写入前备份 `lora_notes.json`。

## 维护者：重新生成全部 ZIP

源文件更新后，在项目根目录执行：

```powershell
.\installers\Build-Packages.ps1
```

脚本会先把当前核心文件同步到 `installers\payload`，再重建七个 ZIP，并更新 `installers\packages\SHA256SUMS.txt`。`__pycache__` 和 `.pyc` 不会进入安装包。
