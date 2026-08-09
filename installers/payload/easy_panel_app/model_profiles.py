"""Data-driven model detection, sampling profiles, and capability metadata."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path


DATA_FILE = Path(__file__).resolve().parent / "data" / "model_profiles.json"

DEFAULT_RESOLUTION = {
    "min": 512,
    "max": 1920,
    "alignment": 8,
    "recommended": [[1024, 1024], [832, 1216], [1216, 832]],
}
DEFAULT_HIRES = {"scale": 1.25, "denoise": 0.30, "steps": 18, "cfg": 4.5}
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
DEFAULT_CAPABILITIES = {
    "prompt_mode": "tags",
    "negative_prompt": True,
    "regional_prompting": True,
    "hires_fix": True,
    "tiled_vae": True,
    "quoted_text": False,
    "freeu_v2": True,
    "cfg_rescale": False,
}


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
    name = _normalized_name(model_name)
    for profile in load_model_catalog()["profiles"]:
        if any(token.lower() in name for token in profile.get("match", [])):
            return copy.deepcopy(profile)
    return None


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
    capabilities = copy.deepcopy(DEFAULT_CAPABILITIES)
    capabilities.update(profile.get("capabilities") or {})
    if family == "anima":
        capabilities.update({"prompt_mode": "hybrid", "regional_prompting": False,
                             "hires_fix": False, "freeu_v2": False})
    if family == "krea2":
        capabilities.update({"freeu_v2": False, "cfg_rescale": False})
    resolution = copy.deepcopy(profile.get("resolution") or DEFAULT_RESOLUTION)
    if family == "anima" and not profile.get("resolution"):
        resolution.update({"max": 1536, "alignment": 8})
    first = copy.deepcopy(combos[0])
    prediction = profile.get("prediction", "native" if family == "anima" else "eps")
    capabilities["cfg_rescale"] = prediction == "v_prediction"
    return {
        **first,
        "id": profile.get("id", "unknown"),
        "family": family,
        "label": profile.get("label", family),
        "combos": combos,
        "locked": bool(profile.get("locked", False)),
        "prediction": prediction,
        "hires": copy.deepcopy(profile.get("hires") or DEFAULT_HIRES),
        "freeu": copy.deepcopy(profile.get("freeu") or DEFAULT_FREEU),
        "resolution": resolution,
        "capabilities": capabilities,
        "guidance_supported": bool(profile.get("guidance_supported", family != "krea2")),
        "guidance_note": profile.get(
            "guidance_note",
            "默认关闭；单人可试 PAG 1.5–2.0，多人分区应关闭。",
        ),
        "source": profile.get("source", ""),
        "source_url": profile.get("source_url", ""),
    }


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
    "anima_sampling_settings",
    "illustrious_sampling_settings",
    "is_anima_model",
    "is_illustrious_model",
    "is_krea2_model",
    "krea2_sampling_settings",
    "load_model_catalog",
    "model_sampling_profile",
]
