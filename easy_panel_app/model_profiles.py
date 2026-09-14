"""Data-driven model detection, sampling profiles, and capability metadata."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path


DATA_FILE = Path(__file__).resolve().parent / "data" / "model_profiles.json"

DEFAULT_RESOLUTION = {
    "min": 512,
    "max": 2560,
    "alignment": 8,
    "recommended": [[1024, 1024], [832, 1216], [1216, 832]],
}
DEFAULT_HIRES = {
    "scale": 1.25,
    "min_scale": 1.10,
    "max_scale": 1.50,
    "denoise": 0.25,
    "min_denoise": 0.15,
    "max_denoise": 0.45,
    "steps": 20,
    "cfg": 5.0,
    "sampler": "auto",
    "scheduler": "auto",
}
# Anima 的高清重建不是普通 SDXL Hires：倍率 1.15–2.0、denoise 0.20–0.30（默认
# 1.5× / 0.25），长边上限 2560，超分模型固定 Anime6B。数值取自成熟的 Anima
# 工作流（EasyUseAnima ≈1.25×/0.29、AnimaFlow ≈1.5×/0.25）。
ANIMA_HIGHRES_DEFAULTS = {
    "scale": 1.50,
    "min_scale": 1.15,
    "max_scale": 2.0,
    "denoise": 0.25,
    "min_denoise": 0.20,
    "max_denoise": 0.30,
    "steps": 20,
    "cfg": 4.8,
    "sampler": "auto",
    "scheduler": "auto",
    "max_long_edge": 2560,
    "upscaler": "RealESRGAN_x4plus_anime_6B.pth",
}
DEFAULT_FREEU = {
    "key": "sdxl_official",
    "label": "官方 SDXL / ComfyUI V2",
    "b1": 1.3,
    "b2": 1.4,
    "s1": 0.9,
    "s2": 0.2,
    "source": "FreeU 作者 SDXL 推荐 + ComfyUI FreeU_V2 默认值",
    "source_url": "https://github.com/ChenyangSi/FreeU#parameters",
    "presets": [
        {
            "key": "sdxl_official",
            "label": "官方 SDXL / ComfyUI V2（推荐）",
            "b1": 1.3,
            "b2": 1.4,
            "s1": 0.9,
            "s2": 0.2,
            "note": "适用于本面板的 SDXL 与 Illustrious；FreeU 作者和 ComfyUI V2 节点数值一致。",
        },
        {
            "key": "sdxl_gentle",
            "label": "SDXL 柔和参考（Diffusers）",
            "b1": 1.1,
            "b2": 1.2,
            "s1": 0.6,
            "s2": 0.4,
            "note": "增强更柔和；画面对比过重、暗部压黑或风格变化太大时可试。",
        },
    ],
}
#: 每个能力既是 UI 开关、preflight 依据，也是 workflow 的唯一判断来源。
#: 新增模型族时只改这里 + profile，不要再去 easy_panel.py / 前端加家族特判。
DEFAULT_CAPABILITIES = {
    "prompt_mode": "tags",
    "negative_prompt": True,
    "regional_prompting": True,
    "controlnet_pose": True,
    "controlnet_depth": True,
    "hires_fix": True,
    "tiled_vae": True,
    "quoted_text": False,
    "freeu_v2": True,
    "cfg_rescale": False,
    "detail_refine": False,
    "highres_reconstruction": False,
    "post_upscale": True,
    "ultimate_upscale": True,
    "face_detailer": True,
    "hand_detailer": True,
    "foot_detailer": True,
    "lora_loader": "full",
}

#: 模型族默认能力，profile.capabilities 可在其上做精细覆盖。
FAMILY_CAPABILITIES = {
    "anima": {
        "prompt_mode": "hybrid",
        "regional_prompting": False,
        "controlnet_pose": False,
        "controlnet_depth": False,
        "freeu_v2": False,
        "detail_refine": True,
        "highres_reconstruction": True,
        "ultimate_upscale": False,
        "lora_loader": "model_only",
    },
    "krea2": {
        "regional_prompting": False,
        "controlnet_pose": False,
        "controlnet_depth": False,
        "hires_fix": False,
        "freeu_v2": False,
        "cfg_rescale": False,
        "ultimate_upscale": False,
        "face_detailer": False,
        "hand_detailer": False,
        "foot_detailer": False,
        "lora_loader": "model_only",
    },
}

#: 模型族加载组件；profile.components 可覆盖任意键（例如派生模型自带 VAE）。
FAMILY_COMPONENTS = {
    "anima": {
        "loader": "unet",
        "text_encoder": "qwen_3_06b_base.safetensors",
        "vae": "qwen_image_vae.safetensors",
        "clip_type": "stable_diffusion",
    },
    "krea2": {
        "loader": "unet",
        "text_encoder": "qwen3VL4BAbliteratedComfyui_v10.safetensors",
        "vae": "qwen_image_vae.safetensors",
        "clip_type": "krea2",
    },
}
DEFAULT_COMPONENTS = {"loader": "checkpoint"}


@lru_cache(maxsize=1)
def load_model_catalog() -> dict:
    with DATA_FILE.open("r", encoding="utf-8") as handle:
        catalog = json.load(handle)
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("profiles"), list):
        raise ValueError("模型配置目录格式无效。")
    return catalog


def _normalized_name(model_name: str) -> str:
    return Path(str(model_name or "").replace("\\", "/")).name.lower()


def _matching_profile(model_name: str) -> dict | None:
    """按「完整文件名 > 高优先级 > 前缀 > 普通子串」选择 profile。

    同分时保持 JSON 内的先后顺序（历史行为），所以旧 catalog 不需要写 priority；
    新增派生模型时只需给更精确的 profile 写 ``match_priority``，避免宽泛 token
    抢先命中。
    """
    name = _normalized_name(model_name)
    stem = name[: -len(".safetensors")] if name.endswith(".safetensors") else name
    best: dict | None = None
    best_key: tuple[int, int, int] | None = None
    for index, profile in enumerate(load_model_catalog()["profiles"]):
        tokens = [str(token).lower() for token in profile.get("match") or []]
        score = -1
        for token in tokens:
            if not token or token not in name:
                continue
            if token == stem or token == name:
                score = max(score, 3)
            elif stem.startswith(token):
                score = max(score, 2)
            else:
                score = max(score, 1)
        if score < 0:
            continue
        priority = int(profile.get("match_priority", 0) or 0)
        key = (score, priority, -index)
        if best_key is None or key > best_key:
            best, best_key = profile, key
    return copy.deepcopy(best) if best is not None else None


def is_anima_model(model_name: str) -> bool:
    matched = _matching_profile(model_name)
    if matched:
        return matched.get("family") == "anima"
    name = _normalized_name(model_name)
    return name.startswith("anima-") or "anima" in name or name.startswith("novaanime")


def is_krea2_model(model_name: str) -> bool:
    matched = _matching_profile(model_name)
    if matched:
        return matched.get("family") == "krea2"
    name = _normalized_name(model_name)
    return "krea2" in name or "krea 2" in name


def is_illustrious_model(model_name: str) -> bool:
    matched = _matching_profile(model_name)
    if matched:
        return matched.get("family") == "illustrious"
    normalized = str(model_name or "").replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    return "illustrious" in normalized or "ilxl" in name or name.startswith("wai")


def _generic_profile(family: str) -> dict:
    if family == "anima":
        combos = [
            {"key": "recommended", "label": "官方均衡", "steps": 34, "cfg": 4.8,
             "sampler": "er_sde", "scheduler": "simple", "guidance": "off",
             "note": "Anima 官方范围：30–50 步、CFG 4–5。"},
            {"key": "fast", "label": "快速", "steps": 30, "cfg": 4.5,
             "sampler": "euler", "scheduler": "simple", "guidance": "off",
             "note": "保持在官方范围内。"},
            {"key": "detail", "label": "细节", "steps": 42, "cfg": 5.0,
             "sampler": "er_sde", "scheduler": "simple", "guidance": "off",
             "note": "细节优先。"},
        ]
        return {"id": "anima-generic", "family": family, "label": "Anima",
                "source": "CircleStone Labs 官方模型卡",
                "source_url": "https://huggingface.co/circlestone-labs/Anima",
                "combos": combos}
    if family == "illustrious":
        combos = [
            {"key": "recommended", "label": "官方均衡", "steps": 24, "cfg": 6.0,
             "sampler": "euler_ancestral", "scheduler": "normal", "guidance": "off",
             "note": "Illustrious 官方起点。"},
            {"key": "fast", "label": "快速", "steps": 20, "cfg": 5.0,
             "sampler": "euler_ancestral", "scheduler": "normal", "guidance": "off",
             "note": "提示词与 LoRA 预览。"},
            {"key": "detail", "label": "细节", "steps": 28, "cfg": 6.5,
             "sampler": "euler_ancestral", "scheduler": "normal", "guidance": "off",
             "note": "官方范围上限。"},
        ]
        return {"id": "illustrious-generic", "family": family, "label": "Illustrious / ILXL",
                "source": "OnomaAI 官方模型卡",
                "source_url": "https://huggingface.co/OnomaAIResearch/Illustrious-xl-early-release-v0",
                "combos": combos}
    combos = [
        {"key": "recommended", "label": "推荐", "steps": 30, "cfg": 6.0,
         "sampler": "dpmpp_2m_sde", "scheduler": "karras", "guidance": "off",
         "note": "通用 SDXL 稳妥配置。"},
        {"key": "fast", "label": "快速", "steps": 24, "cfg": 5.5,
         "sampler": "dpmpp_2m", "scheduler": "karras", "guidance": "off",
         "note": "快速预览。"},
        {"key": "detail", "label": "细节", "steps": 36, "cfg": 6.0,
         "sampler": "dpmpp_2m_sde", "scheduler": "karras", "guidance": "off",
         "note": "细节优先。"},
    ]
    return {"id": "sdxl-generic", "family": "sdxl", "label": "标准 SDXL",
            "source": "SDXL 通用保守配置", "source_url": "", "combos": combos}


def model_sampling_profile(model_name: str) -> dict:
    profile = _matching_profile(model_name)
    if profile is None:
        family = "anima" if is_anima_model(model_name) else (
            "krea2" if is_krea2_model(model_name) else (
                "illustrious" if is_illustrious_model(model_name) else "sdxl"))
        profile = _generic_profile(family)
    combos = profile.get("combos") or []
    if not combos:
        raise ValueError(f"模型配置 {profile.get('id', 'unknown')} 缺少采样组合。")
    family = profile.get("family", "sdxl")
    explicit = profile.get("capabilities") if isinstance(profile.get("capabilities"), dict) else {}
    capabilities = copy.deepcopy(DEFAULT_CAPABILITIES)
    capabilities.update(FAMILY_CAPABILITIES.get(family) or {})
    capabilities.update(explicit)
    if family == "anima":
        # 兼容旧字段名：anima_highres 与 highres_reconstruction 等价，任一显式声明都生效。
        declared = explicit.get("anima_highres", explicit.get("highres_reconstruction"))
        if declared is not None:
            capabilities["anima_highres"] = bool(declared)
            capabilities["highres_reconstruction"] = bool(declared)
        capabilities["anima_highres"] = bool(capabilities.get("highres_reconstruction", True))
        capabilities["highres_reconstruction"] = capabilities["anima_highres"]
    components = copy.deepcopy(DEFAULT_COMPONENTS)
    components.update(FAMILY_COMPONENTS.get(family) or {})
    custom_components = profile.get("components") if isinstance(profile.get("components"), dict) else {}
    components.update({key: value for key, value in custom_components.items()
                       if value not in (None, "")})
    resolution = copy.deepcopy(profile.get("resolution") or DEFAULT_RESOLUTION)
    if family == "anima" and not profile.get("resolution"):
        resolution.update({"max": 1536, "alignment": 8})
    first = copy.deepcopy(combos[0])
    prediction = profile.get("prediction", "native" if family == "anima" else "eps")
    # prediction（技术采样类型）与 capability（是否推荐该增强）是两个维度：
    # profile 显式声明优先，未声明时才按 v-prediction 回退。
    if "cfg_rescale" not in explicit:
        capabilities["cfg_rescale"] = prediction == "v_prediction"
    default_hires = ANIMA_HIGHRES_DEFAULTS if family == "anima" else DEFAULT_HIRES
    hires = copy.deepcopy(default_hires)
    custom_hires = profile.get("hires") if isinstance(profile.get("hires"), dict) else {}
    hires.update({key: value for key, value in custom_hires.items() if value is not None})
    return {
        **first,
        "id": profile.get("id", "unknown"),
        "family": family,
        "label": profile.get("label", family),
        "combos": combos,
        "locked": bool(profile.get("locked", False)),
        "prediction": prediction,
        "zsnr": bool(profile.get("zsnr", False)),
        "hires": hires,
        "freeu": copy.deepcopy(profile.get("freeu") or DEFAULT_FREEU),
        "resolution": resolution,
        "components": components,
        "capabilities": capabilities,
        "guidance_supported": bool(profile.get("guidance_supported", family != "krea2")),
        "guidance_note": profile.get(
            "guidance_note",
            "默认关闭；单人可试 PAG 1.5–2.0，多人分区应关闭。",
        ),
        "source": profile.get("source", ""),
        "source_url": profile.get("source_url", ""),
    }


def model_family(model_name: str) -> str:
    """唯一的模型族判断入口（前端也应只读 /api/models 的 samplingProfiles）。"""
    return str(model_sampling_profile(model_name).get("family") or "sdxl")


def supports_capability(profile: dict, capability: str, default: bool = False) -> bool:
    """按能力契约判断，不要在业务代码里再写 `if anima or krea2`。"""
    capabilities = (profile or {}).get("capabilities") or {}
    return bool(capabilities.get(capability, default))


def anima_sampling_settings(model_name: str) -> tuple[str, str]:
    profile = model_sampling_profile(model_name)
    return profile["sampler"], profile["scheduler"]


def illustrious_sampling_settings(model_name: str) -> dict:
    profile = model_sampling_profile(model_name)
    return {key: profile[key] for key in ("steps", "cfg", "sampler", "scheduler", "prediction")}


def krea2_sampling_settings() -> dict:
    profile = model_sampling_profile("krea2TurboOfficialComfy")
    return {key: profile[key] for key in ("steps", "cfg", "sampler", "scheduler")}


__all__ = [
    "DEFAULT_CAPABILITIES",
    "FAMILY_CAPABILITIES",
    "FAMILY_COMPONENTS",
    "anima_sampling_settings",
    "illustrious_sampling_settings",
    "is_anima_model",
    "is_illustrious_model",
    "is_krea2_model",
    "krea2_sampling_settings",
    "load_model_catalog",
    "model_family",
    "model_sampling_profile",
    "supports_capability",
]
