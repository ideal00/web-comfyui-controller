# LoRA 画风参考图

在顶部 **LoRA 与模型** 中选择基础模型，展开 **画风参考图**。浏览区跟随当前模型族、LoRA 分类和搜索筛选；点击缩略图查看大图，点击 **加入 LoRA** 使用这张参考图记录的测试权重。已经加载的同一个 LoRA 会更新权重，不会重复添加。

选择已有 LoRA 后，备忘上方也会显示对应参考图。弹窗标明测试权重、图片尺寸和步数。这些是参考图的条件，不代表作者推荐值；实际效果还取决于底模、提示词和其他 LoRA。需要的触发词仍从有来源的备忘或同名 TXT 选用。

手机端在 Android 高级面板刷新即可使用。图片按需加载，不必一次下载整个参考库。

## 图片如何对应模型

绑定时核对测试清单中的 **模型 SHA256** 与当前已安装文件，支持同一个模型更改文件名；再检查 PNG 的 ComfyUI 工作流，确认只有目标 LoRA，权重、尺寸、步数和种子与测试一致。缺少模型或图片时不会猜测对应关系。

- 模型旁保存严格同名的 `<模型名>.preview.png`，原 PNG 的生成信息保留。
- 面板查看的副本存入个人 `preset_examples` 目录，图像 ID 写入该 LoRA 备忘的 `referenceImage` 字段。删除原生成结果不会影响参考图。
- 参考图片不是提示词，绑定不会修改触发词、推荐权重、服装或其他分项；编辑备忘也会保留关联。
- 本机 `lora_notes.json`、参考图片及导入审计不进入 Git 仓库或公共安装包。备份或迁移参考库时，同时保留 LoRA 的 `.preview.png`、`lora_notes.json` 和 `preset_examples`。

## 批量绑定测试结果

维护者可使用安装包附带的 `tools/import_lora_previews.py`。测试清单需记录每张图的 `lora_name`、模型 `sha256`、`filename_prefix`，以及统一的 `width`、`height`、`weight`、`steps`、`seed`；输出 PNG 需带原始 ComfyUI 工作流元数据。

```powershell
python tools/import_lora_previews.py --manifest "测试清单.json" --outputs "测试图目录" --model-root "ComfyUI模型目录\loras" --report "本机审计目录\report.json"
```

工具只绑定 SHA256 匹配的已安装 Anima 模型，保留原来的同名 TXT；未核实的触发词不会补写。修改前保存备忘备份，已有不同的 `.preview.png` 也会保留备份。报告分别列出已绑定、缺少图片和缺少模型的项目，重复运行不会重复创建图片。

[返回界面图解](INTERFACE_GUIDE.md)
