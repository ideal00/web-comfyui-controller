"""生成失败的「用户可读」解释与工作流阶段标签（唯一实现）。

Desktop 面板、RPG/手机接口都从这里取；新增常见错误只需在这里加一条规则，
不要再在各自的 handler 里手写字符串匹配。
"""

from __future__ import annotations

from typing import Any, Mapping

#: 按顺序匹配；命中第一条即使用。
GENERATION_ERROR_HINTS: tuple[dict[str, Any], ...] = (
    {
        "match": ("out of memory", "allocation on device", "insufficient memory",
                  "cuda_error_out_of_memory", "failed to allocate"),
        "title": "显存不足",
        "reason": "ComfyUI 在采样或放大时用尽了显存（大图、二次采样、输出增强最容易触发）。",
        "solutions": [
            "只生成 1 张，或把尺寸降到 864×1152 以内。",
            "关闭「高清二次采样 / 输出增强 / 面部手脚修复」中的一项。",
            "关掉其他占用显存的程序（浏览器硬件加速、游戏、另一份 ComfyUI）。",
            "给 ComfyUI 加 --lowvram 启动参数后重启。",
        ],
    },
    {
        "match": ("missing node", "cannot execute because node", "node type not found",
                  "has no attribute", "importerror"),
        "title": "缺少自定义节点",
        "reason": "工作流用到当前 ComfyUI 未安装（或版本不符）的节点。",
        "solutions": [
            "用 ComfyUI Manager 安装 / 更新缺失节点并重启。",
            "或先关闭用到该节点的功能（面部手脚修复、SeedVR2、调色等）。",
        ],
    },
    {
        "match": ("value not in list", "no such file", "does not exist", "cannot find",
                  "not a valid", "invalid file", "filenotfound"),
        "title": "模型或文件缺失",
        "reason": "工作流引用的模型 / LoRA / 图片文件不在 ComfyUI 的目录里（可能被移动、改名或删除）。",
        "solutions": [
            "回到面板重新选择模型与 LoRA。",
            "重新上传姿势图 / 参考图 / 修复蒙版。",
            "在 ComfyUI 界面按 R 刷新模型列表，或重启 ComfyUI。",
            "确认文件确实存在（models\\checkpoints、models\\loras）。",
        ],
    },
    {
        "match": ("prompt outputs failed validation", "failed validation", "invalid input"),
        "title": "节点参数校验失败",
        "reason": "提交的参数超出了某个节点允许的范围（步数 / CFG / 尺寸 / 放大倍率等）。",
        "solutions": [
            "按消息中的节点名检查对应参数，或恢复模型默认值后重试。",
            "确认尺寸是 8 的倍数（面板已自动对齐）。",
        ],
    },
    {
        "match": ("interrupted", "interrupt"),
        "title": "生成已中断",
        "reason": "任务被取消，或被新的提交 / 中断操作打断。",
        "solutions": ["重新生成即可；多个任务请用「发送队列」排队。"],
    },
    {
        "match": ("tuple index out of range", "resolve_areas_and_cond_masks"),
        "title": "区域提示词与当前模型不兼容",
        "reason": "该模型（如 Anima / Krea 2）不支持多人区域 Conditioning。",
        "solutions": ["关闭多人分区，或改用支持分区的 SDXL / Illustrious 模型。"],
    },
    {
        "match": ("cuda", "cudnn", "device-side assert"),
        "title": "显卡运行出错",
        "reason": "CUDA / 驱动层面的错误（驱动版本、显存碎片或显卡状态异常）。",
        "solutions": [
            "关闭其他占用显卡的程序后重试。",
            "更新显卡驱动，或重启电脑。",
            "仍然失败时把技术细节发给开发者。",
        ],
    },
)

#: 工作流节点 → 用户可读阶段（生成进度条使用）。
STAGE_LABELS: dict[str, str] = {
    "CheckpointLoaderSimple": "加载模型",
    "UNETLoader": "加载模型",
    "CLIPLoader": "加载文本编码器",
    "VAELoader": "加载 VAE",
    "LoraLoader": "应用 LoRA",
    "LoraLoaderModelOnly": "应用 LoRA",
    "ModelSamplingDiscrete": "模型采样设置",
    "FreeU_V2": "模型增强（FreeU）",
    "RescaleCFG": "CFG 重缩放",
    "SelfAttentionGuidance": "注意力引导（SAG）",
    "PerturbedAttentionGuidance": "注意力引导（PAG）",
    "CLIPTextEncode": "编码提示词",
    "EmptyLatentImage": "创建画布",
    "LoadImage": "读取图片",
    "LoadImageMask": "读取蒙版",
    "VAEEncode": "编码潜空间",
    "VAEEncodeForInpaint": "编码修复区域",
    "VAEEncodeTiled": "分块编码",
    "VAEDecode": "解码图像",
    "VAEDecodeTiled": "分块解码",
    "UpscaleModelLoader": "加载超分模型",
    "ImageUpscaleWithModel": "超分放大",
    "ImageScale": "缩放",
    "UltimateSDUpscale": "分块放大（Ultimate）",
    "FaceDetailer": "面部 / 肢体细化",
    "UltralyticsDetectorProvider": "加载检测器",
    "SeedVR2Preprocess": "输出增强预处理",
    "SeedVR2Conditioning": "输出增强",
    "SeedVR2PostProcessing": "输出增强后处理",
    "DWPreprocessor": "提取骨架",
    "ControlNetLoader": "加载 ControlNet",
    "ControlNetApplyAdvanced": "应用 ControlNet",
    "DepthAnythingV2Preprocessor": "提取深度",
    "SolidMask": "准备蒙版",
    "FeatherMask": "羽化蒙版",
    "MaskComposite": "合成蒙版",
    "ConditioningSetMask": "区域条件",
    "ConditioningSetAreaPercentage": "区域条件",
    "ConditioningCombine": "合并条件",
    "ConditioningSetDefaultCombine": "合并条件",
    "SaveImage": "保存作品",
}


def _error_payloads(item: Any) -> tuple[str, str]:
    """从 ComfyUI history 条目提取 (节点名, 原始文本)。"""

    status = item.get("status") if isinstance(item, Mapping) and isinstance(item.get("status"), Mapping) else {}
    messages = status.get("messages") if isinstance(status.get("messages"), list) else []
    node = ""
    raw = ""
    for message in messages:
        if not (isinstance(message, (list, tuple)) and len(message) >= 2 and isinstance(message[1], Mapping)):
            continue
        payload = message[1]
        if str(message[0]) == "execution_error":
            node = str(payload.get("node_title") or payload.get("node_type") or "")
            raw = " ".join(str(payload.get(key) or "")
                           for key in ("exception_type", "exception_message")).strip()
            if not raw:
                traceback_lines = payload.get("traceback")
                if isinstance(traceback_lines, list) and traceback_lines:
                    raw = str(traceback_lines[-1])
        elif str(message[0]) == "execution_interrupted" and not raw:
            raw = "interrupted"
    return node, raw.strip()


def friendly_comfy_error(item: Any) -> dict[str, Any]:
    """把 ComfyUI 执行错误整理成 {title, reason, solutions, technical}。"""

    node, raw = _error_payloads(item)
    raw = raw or "ComfyUI 返回了未分类的错误。"
    lowered = raw.lower()
    node_suffix = f"（节点：{node}）" if node else ""
    for rule in GENERATION_ERROR_HINTS:
        if any(token in lowered for token in rule["match"]):
            return {
                "title": rule["title"],
                "reason": rule["reason"] + node_suffix,
                "solutions": list(rule["solutions"]),
                "technical": raw[:600],
            }
    return {
        "title": "生成失败",
        "reason": raw[:200] + node_suffix,
        "solutions": ["按技术细节检查参数或模型；无法判断时可把技术细节发给开发者。"],
        "technical": raw[:600],
    }


def friendly_error_text(friendly: Mapping[str, Any] | None, limit: int = 3) -> str:
    """一行式文本（手机端 / RPG 接口 / 日志共用）。"""

    if not isinstance(friendly, Mapping):
        return ""
    parts = [f"{friendly.get('title') or '生成失败'}：{friendly.get('reason') or ''}".strip()]
    solutions = [str(item) for item in (friendly.get("solutions") or []) if str(item).strip()]
    if solutions:
        parts.append("建议：" + "；".join(solutions[: max(1, int(limit))]))
    return " ".join(part for part in parts if part)


__all__ = [
    "GENERATION_ERROR_HINTS",
    "STAGE_LABELS",
    "friendly_comfy_error",
    "friendly_error_text",
]
