"""Anima 专属「细节重绘（Detail Refine）」：不改尺寸的低温 latent 细化。

与 Illustrious 的二次采样（hires）是两套语义，互不参与：

* hires        = 放大 + 扩散重绘，属于 SDXL / Illustrious 路线；
* Detail Refine = 同尺寸、低 denoise，只让 Anima 在已有结构上补高频细节。

第一版刻意只做「不加 Tile、不放大」的最小链路：
VAEEncode → KSampler(低 denoise) → VAEDecode →（由主流程保存成品）。
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

from easy_panel_app.prompt_utils import unique_prompt_terms

#: 模式 → (最小 denoise, 最大 denoise, 预设 denoise)。上限刻意压得很低：
#: 这个功能的产品目标是「增加细节」，不是重新生成。
REFINE_MODES: Dict[str, Tuple[float, float, float]] = {
    "preserve": (0.06, 0.10, 0.08),
    "balanced": (0.10, 0.15, 0.12),
    "scene": (0.14, 0.20, 0.16),
}
REFINE_MODE_LABELS = {"preserve": "保构图", "balanced": "均衡", "scene": "场景强化"}
DEFAULT_REFINE_MODE = "balanced"
REFINE_HARD_MIN = 0.05
REFINE_HARD_MAX = 0.20
REFINE_DEFAULT_STEPS = 16
REFINE_MIN_STEPS = 6
REFINE_MAX_STEPS = 40

#: 快速增强模块：只追加细节类词汇，不引入新的角色、构图或镜头描述。
DETAIL_MODULES: Dict[str, str] = {
    "hair": "fine individual hair strands, detailed hair texture",
    "eyes": "detailed iris, subtle eye highlights",
    "clothing": "refined fabric folds, subtle material texture",
    "accessory": "small accessory details, clean metal highlights",
    "prop": "detailed prop components, realistic material details",
    "foliage": "detailed foliage, layered vegetation",
    "water": "rain ripples, subtle water reflections",
    "rain": "fine rain streaks, wet reflective surfaces",
    "light": "soft reflected light, gentle volumetric atmosphere",
    "line": "clean line details, crisp outline",
    "texture": "fine surface texture, subtle grain",
}
DETAIL_MODULE_LABELS: Dict[str, str] = {
    "hair": "发丝", "eyes": "眼睛", "clothing": "服装", "accessory": "饰品",
    "prop": "道具", "foliage": "植物", "water": "水面", "rain": "雨景",
    "light": "光影", "line": "线稿", "texture": "材质",
}


def _bounded(value, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if number != number:  # NaN
        return float(default)
    return max(low, min(high, number))


def normalize_anima_detail_refine(data: dict) -> dict:
    """把请求里的 animaDetailRefine 收敛成一组安全参数（含模式限幅）。"""

    raw = (data or {}).get("animaDetailRefine")
    if not isinstance(raw, dict):
        raw = {}
    mode = str(raw.get("mode", DEFAULT_REFINE_MODE) or DEFAULT_REFINE_MODE).strip().lower()
    if mode not in REFINE_MODES:
        mode = DEFAULT_REFINE_MODE
    low, high, preset = REFINE_MODES[mode]
    denoise = round(_bounded(raw.get("denoise"), preset, low, high), 3)
    steps = int(round(_bounded(raw.get("steps"), REFINE_DEFAULT_STEPS,
                               REFINE_MIN_STEPS, REFINE_MAX_STEPS)))
    modules = [str(item) for item in (raw.get("modules") or [])
               if str(item) in DETAIL_MODULES]
    seed_mode = str(raw.get("seedMode", "inherit") or "inherit").strip().lower()
    if seed_mode not in {"inherit", "random"}:
        seed_mode = "inherit"
    return {
        "enabled": bool(raw.get("enabled")),
        "mode": mode,
        "denoise": denoise,
        "steps": steps,
        "seedMode": seed_mode,
        "modules": list(dict.fromkeys(modules)),
        "prompt": str(raw.get("prompt", "") or "").strip(),
        "limits": {"min": low, "max": high},
    }


def merge_anima_detail_prompt(base_positive: str, params: dict) -> str:
    """首采提示词 + 细节词（模块 + 自定义）；不改动首采提示词本身。"""

    extras: List[str] = [DETAIL_MODULES[name] for name in params.get("modules") or []]
    custom = str(params.get("prompt") or "").strip()
    if custom:
        extras.append(custom)
    if not extras:
        return str(base_positive or "")
    return unique_prompt_terms(base_positive, *extras)


def build_anima_detail_refine(*, alloc, image_ref, model_ref, vae_ref, clip_ref,
                              positive_text: str, negative_text: str, params: dict,
                              cfg: float, sampler_name: str, scheduler: str, seed: int,
                              base_prefix: str) -> tuple[dict, list]:
    """同尺寸细节重绘；成品沿用主流程的 SaveImage。

    输入 image_ref 就是首采解码结果，所以尺寸天然与首采一致 —— 第一版不做任何
    放大或 Tile，保证「细节有没有增加」可以被单独判断。
    """

    if not params.get("enabled"):
        return {}, image_ref
    encode_id, positive_id, negative_id, sampler_id, decode_id = (alloc() for _ in range(5))
    base_save_id = alloc()
    refine_seed = (int(seed) if params.get("seedMode") != "random"
                   else random.randint(0, 2**31 - 1))
    nodes: dict = {
        # 首采图另存为 _base 对照：作品库代表图、手机端列表与预览画廊都会跳过它。
        base_save_id: {"class_type": "SaveImage", "inputs": {
            "filename_prefix": base_prefix, "images": image_ref}},
        encode_id: {"class_type": "VAEEncode", "inputs": {
            "pixels": image_ref, "vae": vae_ref}},
        positive_id: {"class_type": "CLIPTextEncode", "inputs": {
            "text": positive_text, "clip": clip_ref}},
        negative_id: {"class_type": "CLIPTextEncode", "inputs": {
            "text": negative_text, "clip": clip_ref}},
        sampler_id: {"class_type": "KSampler", "inputs": {
            "seed": refine_seed, "steps": int(params["steps"]), "cfg": float(cfg),
            "sampler_name": sampler_name, "scheduler": scheduler,
            "denoise": float(params["denoise"]), "model": model_ref,
            "positive": [positive_id, 0], "negative": [negative_id, 0],
            "latent_image": [encode_id, 0]}},
        decode_id: {"class_type": "VAEDecode", "inputs": {
            "samples": [sampler_id, 0], "vae": vae_ref}},
    }
    return nodes, [decode_id, 0]


__all__ = [
    "DEFAULT_REFINE_MODE", "DETAIL_MODULES", "DETAIL_MODULE_LABELS", "REFINE_DEFAULT_STEPS",
    "REFINE_HARD_MAX", "REFINE_HARD_MIN", "REFINE_MAX_STEPS", "REFINE_MIN_STEPS",
    "REFINE_MODES", "REFINE_MODE_LABELS", "build_anima_detail_refine",
    "merge_anima_detail_prompt", "normalize_anima_detail_refine",
]
