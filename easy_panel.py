"""A small local-only UI that submits SDXL/Illustrious jobs to ComfyUI."""
from __future__ import annotations

import json
import html
import csv
import bisect
import mimetypes
import os
import random
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8190
COMFY = "http://127.0.0.1:8188"
DEFAULT_AI_CHAT = "https://api.deepseek.com/chat/completions"
DEFAULT_ANTHROPIC_MESSAGES = "https://api.anthropic.com/v1/messages"
DEFAULT_GEMINI_GENERATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GOOGLE_TRANSLATE = "https://translation.googleapis.com/language/translate/v2"
ROOT = Path(__file__).resolve().parent
OUTPUT = Path(r"G:\ComfyUI\ComfyUI_windows_portable\ComfyUI\output")
COMFY_INPUT = Path(r"G:\ComfyUI\ComfyUI_windows_portable\ComfyUI\input")
LORA_DIR = Path(r"G:\ComfyUI\ComfyUI_windows_portable\ComfyUI\models\loras")
TAG_DATA = ROOT / "vendor" / "tagcomplete-data"
LORA_NOTES = ROOT / "lora_notes.json"
TAG_CATEGORIES = {0: "通用", 1: "画师", 3: "作品", 4: "角色", 5: "元数据"}
ANIMA_TEXT_ENCODER = "qwen_3_06b_base.safetensors"
ANIMA_VAE = "qwen_image_vae.safetensors"
ANIMA_TAG_DATA = ROOT / "vendor" / "anima-tags" / "anima-1.0.csv"
COMFY_MODELS = COMFY_INPUT.parent / "models"
CHECKPOINT_DIR = COMFY_MODELS / "checkpoints"


def is_anima_model(model_name: str) -> bool:
    """Anima ships as a separate UNet, unlike the SDXL checkpoints in this panel."""
    name = Path(model_name).name.lower()
    # Both local checkpoints below are Anima fine-tunes even though their file
    # names do not all begin with ``anima-``.  They use the same Qwen encoder
    # and qwen_image_vae bundle as anima-base-v1.0.
    return name.startswith("anima-") or "anima" in name or name.startswith("novaanime")


def anima_sampling_settings(model_name: str) -> tuple[str, str]:
    """Use each installed Anima fine-tune's published sampler family."""
    name = Path(model_name).name.lower()
    if name.startswith("hosekilustrousmixanima"):
        return "er_sde", "beta"
    if name.startswith("novaanime"):
        return "euler_ancestral", "normal"
    # Match ComfyUI's bundled "Text to Image (Anima Base 1.0)" blueprint.
    # Euler works, but ER-SDE follows prompts and trained LoRA colour/style
    # more consistently at Anima's normal 30-step quality setting.
    return "er_sde", "simple"


def _sampling_combo(key: str, label: str, steps: int, cfg: float, sampler: str,
                    scheduler: str, note: str) -> dict:
    return {"key": key, "label": label, "steps": steps, "cfg": cfg,
            "sampler": sampler, "scheduler": scheduler, "guidance": "off", "note": note}


def anima_sampling_profile(model_name: str) -> dict:
    """Model-card and locally validated presets for installed Anima variants."""
    name = Path(str(model_name or "")).name.lower()
    if name.startswith("hosekilustrousmixanima"):
        combos = [
            _sampling_combo("recommended", "推荐", 24, 4.5, "er_sde", "beta", "模型发布配置，色彩与细节均衡。"),
            _sampling_combo("fast", "快速", 20, 4.2, "euler", "simple", "更快预览构图与 LoRA。"),
            _sampling_combo("detail", "细节", 30, 4.6, "er_sde", "beta", "增加收敛，不建议超过 34 步。"),
        ]
        label = "Hoseki LustrousMix Anima"
    elif name.startswith("novaanime"):
        combos = [
            _sampling_combo("recommended", "推荐", 24, 4.5, "euler_ancestral", "normal", "模型发布配置，线条较柔和。"),
            _sampling_combo("fast", "快速", 20, 4.2, "euler", "simple", "快速检查构图。"),
            _sampling_combo("detail", "细节", 30, 4.6, "er_sde", "simple", "更稳定的细节与色块。"),
        ]
        label = "Nova Anime Anima"
    else:
        combos = [
            _sampling_combo("recommended", "推荐", 34, 4.8, "er_sde", "simple", "本地 Anima 风格包已验证。"),
            _sampling_combo("fast", "快速", 28, 4.5, "euler", "simple", "速度优先，适合提示词预览。"),
            _sampling_combo("detail", "细节", 38, 4.8, "er_sde", "simple", "细节上限；40 步以上收益通常有限。"),
        ]
        label = "Anima Base"
    return {**combos[0], "family": "anima", "label": label, "combos": combos,
            "locked": False, "prediction": "native", "guidance_supported": True,
            "guidance_note": "默认关闭；单人构图可试 SAG 0.35–0.5，多人或 8GB 显存建议关闭。",
            "source": "模型发布配置 / 本地 Anima Soft Illustration 工作流"}


def is_illustrious_model(model_name: str) -> bool:
    """Recognize the installed Illustrious / ILXL checkpoint family."""
    normalized = str(model_name or "").replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    return ("illustrious" in normalized or "ilxl" in name or
            name.startswith(("wai", "milmu", "spectacular")))


def illustrious_sampling_settings(model_name: str) -> dict:
    """Return conservative, model-aware defaults for the installed IL family.

    Milmu's checkpoint metadata explicitly declares v-prediction.  The other
    installed checkpoints are epsilon models and must not share that override.
    """
    name = Path(str(model_name or "")).name.lower()
    if name.startswith("milmu") or "vpred" in name:
        return {"steps": 30, "cfg": 5.5, "sampler": "dpmpp_2m_sde",
                "scheduler": "karras", "prediction": "v_prediction"}
    if name.startswith("spectacular"):
        return {"steps": 30, "cfg": 5.0, "sampler": "dpmpp_2m_sde",
                "scheduler": "simple", "prediction": "eps"}
    if name.startswith("wai"):
        return {"steps": 28, "cfg": 5.0, "sampler": "euler_ancestral",
                "scheduler": "normal", "prediction": "eps"}
    if name.startswith("illustriousxl"):
        return {"steps": 30, "cfg": 5.5, "sampler": "euler_ancestral",
                "scheduler": "normal", "prediction": "eps"}
    return {"steps": 28, "cfg": 5.0, "sampler": "euler_ancestral",
            "scheduler": "normal", "prediction": "eps"}


KREA2_TEXT_ENCODER = "qwen3VL4BAbliteratedComfyui_v10.safetensors"
KREA2_VAE = ANIMA_VAE


def is_krea2_model(model_name: str) -> bool:
    """Krea 2 is a single-stream MMDiT UNet, loaded like Anima via UNETLoader."""
    name = Path(str(model_name or "")).name.lower()
    return "krea2" in name or "krea 2" in name


def krea2_sampling_settings() -> dict:
    """Krea 2 Turbo: guidance-free flow sampling, very few steps."""
    return {"steps": 8, "cfg": 1.0, "sampler": "euler", "scheduler": "simple"}


def model_sampling_profile(model_name: str) -> dict:
    """Return the UI/backend sampling contract for one installed model."""
    name = Path(str(model_name or "")).name.lower()
    if is_krea2_model(model_name):
        base = krea2_sampling_settings()
        combo = _sampling_combo("recommended", "官方 Turbo", base["steps"], base["cfg"],
                                base["sampler"], base["scheduler"],
                                "8 步蒸馏模型；ComfyUI CFG 1 等价于关闭 CFG。")
        return {**combo, "family": "krea2", "label": "Krea 2 Turbo", "combos": [combo],
                "locked": True, "prediction": "flow", "guidance_supported": False,
                "guidance_note": "固定免引导；SAG/PAG 与手动采样覆盖均禁用。",
                "source": "Krea 官方 Turbo 模型卡"}
    if is_anima_model(model_name):
        return anima_sampling_profile(model_name)
    if is_illustrious_model(model_name):
        base = illustrious_sampling_settings(model_name)
        if name.startswith("milmu") or "vpred" in name:
            label = "Milmu Anime Illustrious v-pred"
            combos = [
                _sampling_combo("recommended", "推荐", 30, 5.5, "dpmpp_2m_sde", "karras", "本地材质测试已验证。"),
                _sampling_combo("fast", "快速", 24, 5.0, "euler", "karras", "减少步数，保留 v-pred 处理。"),
                _sampling_combo("detail", "细节", 34, 5.5, "dpmpp_2m_sde", "karras", "更充分收敛，适合材质。"),
            ]
        elif name.startswith("spectacular"):
            label = "Spectacular Anime ILXL"
            combos = [
                _sampling_combo("recommended", "推荐", 30, 5.0, "dpmpp_2m_sde", "simple", "本地测试明确要求 Simple，禁止 Normal。"),
                _sampling_combo("fast", "快速", 24, 5.0, "euler_ancestral", "simple", "快速预览，保持 Simple 调度。"),
                _sampling_combo("detail", "细节", 34, 5.0, "dpmpp_2m_sde", "simple", "细节增加但不提高 CFG。"),
            ]
        elif name.startswith("wai"):
            label = "WAI Illustrious SDXL"
            combos = [
                _sampling_combo("recommended", "推荐", 28, 5.0, "euler_ancestral", "normal", "当前本机出图链路已验证。"),
                _sampling_combo("fast", "快速", 22, 4.5, "euler_ancestral", "normal", "LoRA 与构图预览。"),
                _sampling_combo("detail", "细节", 32, 5.0, "dpmpp_2m_sde", "karras", "提高纹理细节，风格会略有变化。"),
            ]
        elif name.startswith("illustriousxl"):
            label = "Illustrious XL Base"
            combos = [
                _sampling_combo("recommended", "推荐", 30, 5.5, "euler_ancestral", "normal", "基础模型稳妥配置。"),
                _sampling_combo("fast", "快速", 24, 5.0, "euler_ancestral", "normal", "快速检查提示词。"),
                _sampling_combo("detail", "细节", 34, 5.5, "dpmpp_2m_sde", "karras", "细节优先。"),
            ]
        else:
            label = "Illustrious / ILXL"
            combos = [
                _sampling_combo("recommended", "推荐", base["steps"], base["cfg"], base["sampler"], base["scheduler"], "保守的 Illustrious 通用配置。"),
                _sampling_combo("fast", "快速", 22, 4.5, "euler_ancestral", "normal", "提示词与 LoRA 预览。"),
                _sampling_combo("detail", "细节", 32, 5.0, "dpmpp_2m_sde", "karras", "纹理与背景细节优先。"),
            ]
        hires = {"scale": 1.25, "denoise": 0.30, "steps": 18, "cfg": 4.5}
        return {**combos[0], "family": "illustrious", "label": label, "combos": combos,
                "locked": False, "prediction": base["prediction"], "hires": hires,
                "guidance_supported": True,
                "guidance_note": "默认关闭；单人主体可试 PAG 1.5–2.0，多人分区应关闭。",
                "source": "本地模型元数据与已验证 Prompt Library"}
    if name.startswith("gockso"):
        combos = [
            _sampling_combo("recommended", "推荐", 30, 7.0, "dpmpp_2m_sde", "karras", "本地作者风格基线已验证。"),
            _sampling_combo("fast", "快速", 24, 6.5, "dpmpp_2m", "karras", "快速构图预览。"),
            _sampling_combo("detail", "材质细节", 34, 6.5, "dpmpp_2m_sde", "karras", "本地皮肤与丝袜材质测试配置。"),
        ]
        label = "Gock So Anime Love Song (SDXL)"
    elif name.startswith("plantmilk"):
        combos = [
            _sampling_combo("recommended", "推荐", 30, 6.5, "dpmpp_2m_sde", "karras", "SDXL 写实模型的稳妥起点。"),
            _sampling_combo("fast", "快速", 24, 6.0, "dpmpp_2m", "karras", "构图预览。"),
            _sampling_combo("detail", "细节", 36, 6.5, "dpmpp_2m_sde", "karras", "写实纹理优先。"),
        ]
        label = "PlantMilk Model Suite (SDXL)"
    else:
        combos = [
            _sampling_combo("recommended", "推荐", 30, 6.0, "dpmpp_2m_sde", "karras", "通用 SDXL 稳妥配置。"),
            _sampling_combo("fast", "快速", 24, 5.5, "dpmpp_2m", "karras", "快速预览。"),
            _sampling_combo("detail", "细节", 36, 6.0, "dpmpp_2m_sde", "karras", "细节优先。"),
        ]
        label = "标准 SDXL"
    return {**combos[0], "family": "sdxl", "label": label, "combos": combos,
            "locked": False, "prediction": "eps", "guidance_supported": True,
            "guidance_note": "默认关闭；单人可试 PAG 1.5–2.0，背景整体增强可试 SAG 0.35–0.5。",
            "source": "本地验证记录 / SDXL 通用保守配置"}


def checkpoint_issue(model_name: str) -> str | None:
    """Return a user-facing reason when a checkpoint cannot supply CLIP and VAE.

    Some diffusion-only UNets were placed in ``models/checkpoints``.  ComfyUI
    lists them beside normal checkpoints, but CheckpointLoaderSimple then emits
    a ``None`` CLIP and the job fails only after it has entered the queue.
    """
    relative = Path(str(model_name or "").replace("\\", "/"))
    if not relative.name or relative.is_absolute() or ".." in relative.parts:
        return "基础模型路径无效。"
    root = CHECKPOINT_DIR.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_file() or not candidate.is_relative_to(root):
        return "找不到基础模型文件。"
    try:
        with candidate.open("rb") as handle:
            header_size = int.from_bytes(handle.read(8), "little")
            if not 2 <= header_size <= 8_000_000:
                return "模型文件格式无效。"
            header = json.loads(handle.read(header_size).decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return "无法读取模型元数据。"
    if not isinstance(header, dict):
        return "模型文件格式无效。"
    keys = header.keys()
    has_clip = any(key.startswith("cond_stage_model.") or
                   (key.startswith("conditioner.embedders.") and ".transformer." in key)
                   for key in keys)
    has_vae = any(key.startswith("first_stage_model.") or key.startswith("vae.") for key in keys)
    if has_clip and has_vae:
        return None
    return "这是仅含扩散网络（UNet）的拆分模型，缺少内置 CLIP / VAE，不能作为本面板的 SDXL Checkpoint 使用。"


def load_anima_tag_index() -> dict[str, dict]:
    """Load the local Anima/Danbooru index for hard-tag confirmation, not prompting."""
    if not ANIMA_TAG_DATA.is_file():
        return {}
    tags: dict[str, dict] = {}
    with ANIMA_TAG_DATA.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 3 or not row[0].strip():
                continue
            tag = row[0].strip()
            try:
                category, count = int(row[1]), int(row[2])
            except ValueError:
                category, count = -1, 0
            tags[tag.lower()] = {"tag": tag, "category": category, "count": count}
    return tags


def load_tag_index() -> list[dict]:
    """Read TagComplete's Danbooru data plus its community Chinese translations."""
    translations: dict[str, str] = {}
    # The small curated table wins; the full community table fills remaining tags.
    for zh_file in [TAG_DATA / "Tags-zh-full.csv", TAG_DATA / "danbooru-0-zh.csv"]:
        if not zh_file.is_file():
            continue
        with zh_file.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.reader(handle):
                if len(row) >= 3 and row[2].strip():
                    translations.setdefault(row[0].strip(), row[2].strip())
    tags: list[dict] = []
    source = TAG_DATA / "danbooru.csv"
    if not source.is_file():
        return tags
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 3:
                continue
            try:
                category, count = int(row[1]), int(row[2])
            except ValueError:
                continue
            tag = row[0].strip()
            aliases = row[3].strip("\"").split(",") if len(row) > 3 and row[3] else []
            tags.append({"tag": tag, "search": tag.lower().replace("_", " "), "aliases": aliases,
                         "translation": translations.get(tag, ""), "count": count, "category": category})
    return tags


TAG_INDEX = load_tag_index()
ANIMA_TAG_INDEX = load_anima_tag_index()
ANIMA_TAG_NAMES = tuple(sorted(ANIMA_TAG_INDEX))


def split_prompt_terms(value: str, limit: int = 48) -> list[str]:
    return [term.strip() for term in re.split(r"[,;\n]+", str(value or "")) if term.strip()][:limit]


def normalize_anima_tag(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip().lower())


def anima_tag_candidates(term: str, limit: int = 8) -> list[str]:
    normalized = normalize_anima_tag(term)
    if not normalized:
        return []
    start = bisect.bisect_left(ANIMA_TAG_NAMES, normalized)
    results: list[str] = []
    for candidate in ANIMA_TAG_NAMES[start:]:
        if not candidate.startswith(normalized):
            break
        results.append(ANIMA_TAG_INDEX[candidate]["tag"])
        if len(results) >= limit:
            break
    return results


def validate_anima_tags(data: dict) -> dict:
    terms = split_prompt_terms(data.get("tags", ""))
    results = []
    for original in terms:
        normalized = normalize_anima_tag(original)
        item = ANIMA_TAG_INDEX.get(normalized)
        results.append({"input": original, "normalized": normalized,
                        "confirmed": item["tag"] if item else "",
                        "category": item["category"] if item else -1,
                        "candidates": [] if item else anima_tag_candidates(normalized)})
    return {"results": results, "total": len(ANIMA_TAG_INDEX)}


def unique_prompt_terms(*chunks: str) -> str:
    seen: set[str] = set()
    terms: list[str] = []
    for chunk in chunks:
        for term in split_prompt_terms(chunk, limit=180):
            key = normalize_prompt_key(term)
            if key not in seen:
                seen.add(key)
                terms.append(term)
    return ", ".join(terms)


PROMPT_SECTION_KEYS = ("subject", "appearance", "clothing", "pose", "composition",
                       "scene", "lighting", "style", "manual")
PROMPT_SECTION_LABELS = {
    "subject": "人物与角色", "appearance": "外貌", "clothing": "服装与材质",
    "pose": "姿势", "composition": "构图", "scene": "场景",
    "lighting": "光线", "style": "画风与上色", "manual": "其他补充",
}
MATURE_NEGATIVE_TERMS = ("nsfw", "nude", "nudity", "explicit", "sex", "sexual",
                         "porn", "hentai", "uncensored")


def normalize_prompt_key(value: str) -> str:
    """Normalize one comma-delimited term for exact, not substring, deduping."""
    term = str(value or "").strip().casefold().replace("\\(", "(").replace("\\)", ")")
    weighted = re.fullmatch(r"\((.*):\s*(?:0(?:\.\d+)?|1(?:\.\d+)?|2(?:\.0+)?)\)", term)
    if weighted:
        term = weighted.group(1).strip()
    return re.sub(r"\s+", " ", term.replace("_", " ")).strip(" .")


def exact_unique_terms(*chunks: str, limit: int = 360) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for chunk in chunks:
        for term in split_prompt_terms(chunk, limit=limit):
            key = normalize_prompt_key(term)
            if key and key not in seen:
                seen.add(key)
                result.append(term)
    return result


def prompt_family(model_name: str) -> str:
    if is_anima_model(model_name):
        return "anima"
    if is_krea2_model(model_name):
        return "krea2"
    if is_illustrious_model(model_name):
        return "illustrious"
    return "sdxl"


def lora_folder(lora_name: str) -> str:
    """Folder part of a ComfyUI lora_name (relative path with backslashes)."""
    norm = str(lora_name or "").replace("\\", "/")
    if "/" in norm:
        return norm.rsplit("/", 1)[0]
    return ""


def infer_lora_family(lora_name: str, base_model: str = "") -> str:
    """Best-effort model-family classification for a LoRA.

    Folder name wins (the user organizes files by family), then note base_model
    metadata, then file name. Returns anima / krea2 / illustrious / sd15 / sdxl / general.
    """
    norm = str(lora_name or "").replace("\\", "/").lower()
    bm = str(base_model or "").lower()
    if "anima" in norm:
        return "anima"
    if "krea" in norm:
        return "krea2"
    if any(key in norm for key in ("illustrious", "noobai", "wai", "ilxl", "hosiery")):
        return "illustrious"
    if "/sd15" in norm or norm.startswith("sd15"):
        return "sd15"
    if "/sdxl" in norm or norm.startswith("sdxl"):
        return "sdxl"
    if "krea" in bm:
        return "krea2"
    if "anima" in bm:
        return "anima"
    if any(key in bm for key in ("illustrious", "noobai", "wai", "ilxl")):
        return "illustrious"
    if any(key in bm for key in ("sd 1.5", "sd15")):
        return "sd15"
    if "sdxl" in bm:
        return "sdxl"
    return "general"


def lora_meta_map(lora_names: list) -> dict:
    """Build {lora_name: {folder, family}} using note base_model metadata."""
    notes = load_lora_notes()
    meta: dict = {}
    for name in lora_names:
        base_name = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
        note = notes.get(name) or notes.get(base_name)
        base_model = str(note.get("base_model", "") or "") if isinstance(note, dict) else ""
        meta[name] = {"folder": lora_folder(name), "family": infer_lora_family(name, base_model)}
    return meta


def normalized_safety_level(data: dict) -> str:
    level = str(data.get("safetyLevel", "")).strip().lower()
    if level not in {"safe", "sensitive", "nsfw", "explicit"}:
        level = "nsfw" if data.get("mature") else "safe"
    return level


def model_prompt_profile(model_name: str, safety_level: str) -> dict:
    family = prompt_family(model_name)
    name = Path(str(model_name or "")).name.lower()
    if family == "krea2":
        # Qwen-based MMDiT understands prompts directly; no tag boilerplate.
        quality: list[str] = []
        negative: list[str] = []
    elif family == "anima":
        aesthetic = "aesthetic" in name
        quality = ["masterpiece", "best quality"]
        if not aesthetic:
            quality.append("score_7")
        quality.append(safety_level)
        negative = ["worst quality", "low quality", "artist name", "blurry",
                    "jpeg artifacts", "chromatic aberration"]
        if not aesthetic:
            negative[2:2] = ["score_1", "score_2", "score_3"]
    elif family == "illustrious":
        quality = illustrious_quality_prefix(model_name)
        negative = ["worst quality", "low quality", "lowres", "bad anatomy",
                    "bad hands", "text", "watermark", "signature"]
    else:
        quality = ["masterpiece", "best quality", "highres"]
        negative = ["worst quality", "low quality", "lowres", "bad anatomy",
                    "bad hands", "text", "watermark", "signature", "blurry"]
    if safety_level == "safe":
        negative.extend(MATURE_NEGATIVE_TERMS)
    elif safety_level == "sensitive":
        negative.extend(("nude", "nudity", "explicit", "sex", "sexual", "porn", "hentai"))
    return {"family": family, "quality": quality, "negative": negative,
            "safety": safety_level, "aesthetic": "aesthetic" in name}


def prompt_sections(data: dict) -> dict[str, str]:
    supplied = data.get("promptSections")
    sections = {key: "" for key in PROMPT_SECTION_KEYS}
    if isinstance(supplied, dict):
        for key in PROMPT_SECTION_KEYS:
            sections[key] = str(supplied.get(key, "") or "").strip()
        natural_language = str(supplied.get("naturalLanguage", "") or "").strip()
    else:
        # Backward-compatible route for saved callers from the previous UI.
        natural_language = str(data.get("animaNLTags", "") or "").strip()
        if is_anima_model(str(data.get("model", ""))):
            sections["manual"] = canonical_anima_hard_tags(data.get("animaHardTags", ""))
            sections["style"] = str(data.get("animaSoftPhrases", "") or "").strip()
        sections["manual"] = unique_prompt_terms(sections["manual"], str(data.get("prompt", "") or ""))
    if isinstance(supplied, dict):
        sections["manual"] = unique_prompt_terms(sections["manual"], str(data.get("prompt", "") or ""))
        if is_anima_model(str(data.get("model", ""))):
            sections["manual"] = unique_prompt_terms(sections["manual"],
                                                      canonical_anima_hard_tags(data.get("animaHardTags", "")))
            sections["style"] = unique_prompt_terms(sections["style"],
                                                     str(data.get("animaSoftPhrases", "") or ""))
            natural_language = " ".join(part for part in
                                        (natural_language, str(data.get("animaNLTags", "") or "").strip()) if part)
    sections["naturalLanguage"] = natural_language
    return sections


def prompt_conflicts(terms: list[str], natural_language: str, safety_level: str) -> list[str]:
    keys = {normalize_prompt_key(term) for term in terms}
    warnings: list[str] = []

    def report(label: str, options: tuple[str, ...]) -> None:
        present = [option for option in options if normalize_prompt_key(option) in keys]
        if len(present) > 1:
            warnings.append(f"{label}可能冲突：" + "、".join(present))

    report("画面范围", ("full body", "upper body", "cowboy shot", "portrait", "close-up"))
    report("基础姿势", ("standing", "sitting", "lying"))
    report("人物朝向", ("front view", "from behind", "side view"))
    report("场景", ("indoors", "outdoors"))
    report("头发颜色", tuple(f"{color} hair" for color in
                          ("black", "white", "silver", "grey", "gray", "blonde", "brown",
                           "red", "pink", "purple", "blue", "aqua", "green")))
    report("眼睛颜色", tuple(f"{color} eyes" for color in
                          ("black", "white", "blue", "aqua", "green", "golden", "amber",
                           "red", "pink", "purple", "brown")))
    multiple = any(item in keys for item in {"2girls", "2boys", "multiple girls", "multiple boys",
                                             "group", "crowd", "multiple people"})
    mixed_pair = "1girl" in keys and "1boy" in keys
    if "solo" in keys and (multiple or mixed_pair):
        warnings.append("人数可能冲突：solo 与多人标签同时存在。")
    mature_positive = keys.intersection(MATURE_NEGATIVE_TERMS)
    if safety_level == "safe" and mature_positive:
        warnings.append("安全等级为 SFW，但正向提示词含有：" + "、".join(sorted(mature_positive)))
    if natural_language and len(natural_language) < 24:
        warnings.append("自然语言描述较短；Anima 纯自然语言模式建议至少写两个具体句子。")
    return warnings


def dynamic_negative_terms(positive: str) -> list[str]:
    normalized = positive.lower().replace("_", " ")
    additions: list[str] = []
    if any(token in normalized for token in ("hand", "holding", "touching", "grasping", "fingers")):
        additions += ["bad hands", "extra digits", "missing fingers", "fused fingers"]
    if any(token in normalized for token in ("full body", "thigh", "leg", "feet", "foot", "pantyhose", "thighhigh")):
        additions += ["bad feet", "extra legs", "missing legs", "malformed limbs"]
    if any(token in normalized for token in ("2girls", "2boys", "multiple girls", "multiple people", "group", "crowd")):
        additions += ["duplicate person", "fused bodies", "merged limbs", "extra arms"]
    if any(token in normalized for token in ("low angle", "from above", "foreshortening", "dynamic pose", "dutch angle")):
        additions += ["bad perspective", "warped background", "distorted body"]
    return exact_unique_terms(", ".join(additions))


def compile_prompt(data: dict) -> dict:
    model = str(data.get("model", ""))
    safety = normalized_safety_level(data)
    profile = model_prompt_profile(model, safety)
    sections = prompt_sections(data)
    trigger_terms = exact_unique_terms(", ".join(selected_lora_triggers(data)))
    ordered: list[str] = []
    seen: set[str] = set()

    def extend(chunk) -> None:
        source = ", ".join(chunk) if isinstance(chunk, (list, tuple)) else str(chunk or "")
        for term in split_prompt_terms(source, limit=360):
            key = normalize_prompt_key(term)
            if key and key not in seen:
                seen.add(key)
                ordered.append(term)

    extend(trigger_terms)
    extend(profile["quality"])
    for key in PROMPT_SECTION_KEYS:
        value = sections[key]
        if profile["family"] == "anima" and key == "manual":
            value = canonical_anima_hard_tags(value)
        extend(value)
    natural_language = sections["naturalLanguage"].strip()
    positive = ", ".join(ordered)
    if natural_language:
        positive = positive.rstrip(" .") + ". " + natural_language

    manual_negative = str(data.get("negative", "") or "").strip()
    negative_terms = exact_unique_terms(", ".join(profile["negative"]), manual_negative)
    negative_terms = exact_unique_terms(", ".join(negative_terms),
                                        ", ".join(dynamic_negative_terms(positive)))
    warnings = prompt_conflicts(ordered, natural_language, safety)
    warnings.extend(lora_compatibility_warnings(data, profile["family"]))
    style_count = len(split_prompt_terms(sections["style"], limit=180))
    if str(data.get("promptMode", "style_test")) == "style_test" and style_count:
        warnings.append("当前为画风测试模式，但“画风与上色”分区不为空；这些词可能掩盖 LoRA 自身表现。")
    errors: list[str] = []
    user_term_count = sum(len(split_prompt_terms(sections[key], limit=360)) for key in PROMPT_SECTION_KEYS)
    region_term_count = sum(len(split_prompt_terms(item.get("prompt", ""), limit=180))
                            for item in (data.get("regions") or []) if isinstance(item, dict))
    if not user_term_count and not trigger_terms and not natural_language and not region_term_count:
        errors.append("请至少填写人物、场景、姿势、其他标签或自然语言描述中的一项。")
    return {"positive": positive, "negative": ", ".join(negative_terms),
            "errors": errors, "warnings": warnings, "sections": sections,
            "triggers": trigger_terms, "profile": profile,
            "positiveTerms": len(ordered), "negativeTerms": len(negative_terms)}


def canonical_anima_hard_tags(value: str) -> str:
    canonical = []
    for term in split_prompt_terms(value, limit=180):
        item = ANIMA_TAG_INDEX.get(normalize_anima_tag(term))
        canonical.append(item["tag"] if item else term)
    return unique_prompt_terms(", ".join(canonical))


def compose_anima_prompt(data: dict) -> str:
    """Keep verifiable tags, style phrases and spatial language separate until submission."""
    return unique_prompt_terms(canonical_anima_hard_tags(data.get("animaHardTags", "")), data.get("animaSoftPhrases", ""),
                               data.get("animaNLTags", ""), data.get("prompt", ""))


def anima_dynamic_negative(existing: str, positive: str) -> str:
    """Add only failure-prevention terms relevant to the requested composition."""
    base = ["worst quality", "low quality", "lowres", "jpeg artifacts", "bad anatomy",
            "bad proportions", "text", "watermark", "signature"]
    normalized = positive.lower().replace("_", " ")
    additions = list(base)
    if any(token in normalized for token in ("hand", "holding", "touching", "grasping", "fingers")):
        additions += ["bad hands", "extra digits", "missing fingers", "fused fingers"]
    if any(token in normalized for token in ("full body", "thigh", "leg", "feet", "foot", "pantyhose", "thighhigh")):
        additions += ["bad feet", "extra legs", "missing legs", "malformed limbs"]
    if any(token in normalized for token in ("2girls", "2boys", "multiple girls", "multiple people", "group", "crowd")):
        additions += ["duplicate person", "fused bodies", "merged limbs", "extra arms"]
    if any(token in normalized for token in ("low angle", "from above", "foreshortening", "dynamic pose", "dutch angle")):
        additions += ["bad perspective", "warped background", "distorted body"]
    return unique_prompt_terms(existing, ", ".join(additions))


def anima_preflight(data: dict) -> dict:
    model = str(data.get("model", ""))
    compiled = compile_prompt(data)
    errors: list[str] = list(compiled["errors"])
    warnings: list[str] = list(compiled["warnings"])
    if not is_anima_model(model):
        return {"isAnima": False, "errors": errors, "warnings": warnings}
    for path, label in ((COMFY_MODELS / "text_encoders" / ANIMA_TEXT_ENCODER, "Qwen 文本编码器"),
                        (COMFY_MODELS / "vae" / ANIMA_VAE, "Qwen Image VAE")):
        if not path.is_file():
            errors.append(f"缺少 {label}：{path.name}")
    if (data.get("pose") or {}).get("enabled"):
        errors.append("当前 Xinsir OpenPose ControlNet 仅适用于 SDXL，不能与 Anima 一起使用。")
    sections = compiled["sections"]
    hard_source = unique_prompt_terms(sections.get("subject", ""), sections.get("appearance", ""),
                                      sections.get("clothing", ""), sections.get("pose", ""),
                                      sections.get("composition", ""),
                                      sections.get("manual", ""), data.get("animaHardTags", ""))
    hard_tags = split_prompt_terms(hard_source, limit=180)
    unknown = [term for term in hard_tags if normalize_anima_tag(term) not in ANIMA_TAG_INDEX]
    if unknown:
        warnings.append("未确认硬标签：" + "、".join(unknown[:6]))
    if not hard_tags:
        warnings.append("尚未填写已验证的硬标签；可在“Anima 提示词分层”中校验角色、服装和姿势标签。")
    steps = bounded(data.get("steps"), 30, 8, 60)
    cfg = bounded(data.get("cfg"), 4.0, 1, 15, integer=False)
    width = bounded(data.get("width"), 832, 512, 1920)
    height = bounded(data.get("height"), 1216, 512, 1920)
    if width * height > 1_250_000:
        warnings.append(f"Anima 当前尺寸为 {width}×{height}；8GB 显存压力较大，显存不足时请改用 896×1344 或 1024×1024。")
    if not 20 <= steps <= 50:
        warnings.append("Anima Base 通常建议 20–50 步；当前步数为 " + str(steps) + "。")
    if not 3.5 <= cfg <= 5.5:
        warnings.append("Anima Base 通常建议 CFG 约 4–5；当前 CFG 为 " + str(cfg) + "。")
    return {"isAnima": True, "errors": errors, "warnings": warnings,
            "prompt": compiled["positive"], "negative": compiled["negative"],
            "compiled": compiled}


def krea2_preflight(data: dict) -> dict:
    """Check the Krea 2 chain: Qwen3-VL text encoder, VAE and prompt sanity."""
    model = str(data.get("model", ""))
    compiled = compile_prompt(data)
    errors: list[str] = list(compiled["errors"])
    warnings: list[str] = list(compiled["warnings"])
    if not is_krea2_model(model):
        return {"isKrea2": False, "errors": errors, "warnings": warnings}
    if not (COMFY_MODELS / "text_encoders" / KREA2_TEXT_ENCODER).is_file():
        errors.append(f"缺少 Krea 2 文本编码器：请下载 Qwen3-VL-4B 并保存为 models\\text_encoders\\{KREA2_TEXT_ENCODER}。")
    if not (COMFY_MODELS / "vae" / KREA2_VAE).is_file():
        errors.append(f"缺少 VAE：{KREA2_VAE}")
    width = bounded(data.get("width"), 832, 512, 1920)
    height = bounded(data.get("height"), 1216, 512, 1920)
    if width * height > 1_250_000:
        warnings.append(
            f"Krea 2 当前尺寸 {width}×{height}（{width * height / 1e6:.2f} MP）；8GB 显存建议用 "
            f"896×1344 或 1024×1024 以内，超出时会走 CPU 卸载（明显变慢）。"
        )
    return {"isKrea2": True, "errors": errors, "warnings": warnings}


def illustrious_preflight(data: dict) -> dict:
    """Check the choices that most often hide an Illustrious style LoRA."""
    model = str(data.get("model", ""))
    compiled = compile_prompt(data)
    errors: list[str] = list(compiled["errors"])
    warnings: list[str] = list(compiled["warnings"])
    if not is_illustrious_model(model):
        return {"isIllustrious": False, "errors": errors, "warnings": warnings}
    issue = checkpoint_issue(model)
    if issue:
        errors.append(issue)
    positive_terms = split_prompt_terms(compiled["positive"], limit=360)
    negative_terms = split_prompt_terms(compiled["negative"], limit=360)
    if len(positive_terms) > 45:
        warnings.append(f"正向提示词有 {len(positive_terms)} 项；画风 LoRA 测试建议先压到 15–35 项，避免底模描述盖过上色。")
    if len(negative_terms) > 30:
        warnings.append(f"负向提示词有 {len(negative_terms)} 项；Illustrious 通常更适合短负面词，过长可能削弱构图和色彩。")
    color = data.get("colorCorrection") or {}
    if isinstance(color, dict) and color.get("enabled"):
        warnings.append("已启用生成后调色；评估画风 LoRA 时建议关闭，以免把后处理误认为模型效果。")
    mode = str(data.get("illustriousMode", "precision"))
    if mode == "repair":
        repair = data.get("repair") or {}
        image_name = str(repair.get("image", "") or "")
        mask_name = str(repair.get("mask", "") or "")
        if not (image_name and mask_name):
            errors.append("局部修复需要先上传原图并涂出蒙版（在“局部修复”面板中完成）。")
        else:
            for name in (image_name, mask_name):
                try:
                    validate_input_image(name)
                except ValueError as exc:
                    errors.append(str(exc))
        denoise = bounded(repair.get("denoise"), 0.5, 0.2, 1.0, integer=False)
        if denoise >= 0.95:
            warnings.append("重绘幅度接近 1.0 会整图重绘；局部修复建议 0.4–0.7。")
    scale = bounded(data.get("hiresScale"), 1.25, 1.1, 1.5, integer=False)
    width = bounded(data.get("width"), 832, 512, 1920)
    height = bounded(data.get("height"), 1216, 512, 1920)
    projected_pixels = width * height * (scale ** 2 if mode == "hires" else 1)
    if mode == "hires" and scale > 1.3:
        warnings.append("高清倍率高于 1.30×，8GB 显存更容易溢出；建议先用 1.25×。")
    if mode == "hires" and projected_pixels > 1_900_000:
        out_width = round(width * scale / 8) * 8
        out_height = round(height * scale / 8) * 8
        warnings.append(f"预计高清成图为 {out_width}×{out_height}；8GB 显存风险较高，建议改用精准模式或 1.10–1.15×。")
    profile = illustrious_sampling_settings(model)
    return {"isIllustrious": True, "errors": errors, "warnings": warnings,
            "profile": profile, "mode": mode,
            "positiveTerms": len(positive_terms), "negativeTerms": len(negative_terms),
            "prompt": compiled["positive"], "negative": compiled["negative"],
            "compiled": compiled}


def search_tags(query: str, limit: int = 28) -> list[dict]:
    query = query.strip().lower()
    if not query:
        return []
    normalized = query.replace("_", " ")
    candidates: list[tuple[tuple, dict]] = []
    for item in TAG_INDEX:
        tag = item["search"]
        translation = item["translation"].lower()
        aliases = " ".join(item["aliases"]).replace("_", " ").lower()
        if tag.startswith(normalized):
            rank = 0
        elif normalized in tag:
            rank = 1
        elif normalized in aliases:
            rank = 2
        elif translation and normalized in translation:
            rank = 3
        else:
            continue
        candidates.append(((rank, -item["count"], item["tag"]), item))
    candidates.sort(key=lambda pair: pair[0])
    return [{"tag": item["tag"].replace("_", " "), "translation": item["translation"],
             "count": item["count"], "category": TAG_CATEGORIES.get(item["category"], "其他")}
            for _, item in candidates[:limit]]


def load_lora_notes() -> dict:
    if not LORA_NOTES.is_file():
        return {}
    with LORA_NOTES.open("r", encoding="utf-8") as handle:
        content = json.load(handle)
    return content if isinstance(content, dict) else {}


def normalized_lora_name(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().casefold()


def lora_note(notes: dict, lora_name: str) -> dict:
    """Resolve notes saved either by relative LoRA path or by basename."""
    raw = str(lora_name or "")
    normalized = raw.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    note = notes.get(raw) or notes.get(normalized) or notes.get(basename) or {}
    return note if isinstance(note, dict) else {}


def selected_lora_trigger_entries(data: dict) -> list[tuple[str, str]]:
    """Return ``(selected LoRA name, documented trigger)`` pairs."""
    notes = load_lora_notes()
    entries: list[tuple[str, str]] = []
    for lora in data.get("loras", []):
        name = str(lora.get("name", "") or "").strip()
        trigger = str(lora_note(notes, name).get("trigger", "") or "").strip()
        if name and trigger:
            entries.append((name, trigger))
    return entries


def selected_lora_triggers(data: dict, exclude_names: set[str] | None = None) -> list[str]:
    """Return documented triggers, optionally excluding region-bound LoRAs."""
    excluded = {normalized_lora_name(name) for name in (exclude_names or set())}
    return [trigger for name, trigger in selected_lora_trigger_entries(data)
            if normalized_lora_name(name) not in excluded]


REGION_SUBJECT_TAGS = {"1girl", "1boy", "1other", "person"}
REGION_GLOBAL_SECTION_KEYS = ("composition", "scene", "lighting", "style")
REGION_LAYOUT_POSITIVE = (
    "single continuous scene", "one image", "same background", "coherent composition",
)
REGION_LAYOUT_NEGATIVE = (
    "split screen", "collage", "diptych", "triptych", "multiple views",
    "comic panels", "panel layout", "border", "frame between characters",
)


def _region_number(value, default: float, low: float, high: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    return min(high, max(low, result))


def normalized_regions(data: dict) -> list[dict]:
    """Validate and normalize regional characters before constructing nodes.

    A modest overlap is allowed because regional conditioning is applied through
    feathered masks.  Excessive overlap still recreates the fused faces, hair
    colours and limbs this feature is meant to prevent.
    """
    raw_regions = data.get("regions") or []
    if not isinstance(raw_regions, list):
        return []
    selected = {normalized_lora_name(item.get("name")): str(item.get("name", ""))
                for item in data.get("loras", []) if str(item.get("name", "")).strip()}
    regions: list[dict] = []
    for index, raw in enumerate(raw_regions[:6]):
        if not isinstance(raw, dict):
            continue
        prompt = str(raw.get("prompt", "") or "").strip()
        if not prompt:
            continue
        x = _region_number(raw.get("x"), 0.0, 0.0, 0.95)
        y = _region_number(raw.get("y"), 0.0, 0.0, 0.95)
        width = min(_region_number(raw.get("width"), 0.5, 0.05, 1.0), 1.0 - x)
        height = min(_region_number(raw.get("height"), 1.0, 0.05, 1.0), 1.0 - y)
        subject = str(raw.get("subject", "1girl") or "1girl").strip().lower()
        if subject not in REGION_SUBJECT_TAGS:
            subject = "1girl"
        requested_lora = str(raw.get("lora", "") or "").strip()
        lora_name = selected.get(normalized_lora_name(requested_lora), "") if requested_lora else ""
        if requested_lora and not lora_name:
            raise ValueError(f"角色 {index + 1} 绑定的 LoRA 已不在当前选择列表中，请重新选择。")
        regions.append({
            "name": str(raw.get("name", "") or "").strip(),
            "prompt": prompt,
            "subject": subject,
            "lora": lora_name,
            "x": x, "y": y, "width": width, "height": height,
            # Values below 0.75 are routinely drowned out by the base prompt.
            "strength": _region_number(raw.get("strength"), 1.0, 0.75, 1.5),
        })
    if raw_regions and len(regions) < 2:
        raise ValueError("多人区域至少需要两个已填写专属提示词的角色。")
    for left_index, left in enumerate(regions):
        for right_index in range(left_index + 1, len(regions)):
            right = regions[right_index]
            overlap_width = max(0.0, min(left["x"] + left["width"], right["x"] + right["width"])
                                - max(left["x"], right["x"]))
            overlap_height = max(0.0, min(left["y"] + left["height"], right["y"] + right["height"])
                                 - max(left["y"], right["y"]))
            overlap = overlap_width * overlap_height
            smaller = min(left["width"] * left["height"], right["width"] * right["height"])
            if smaller and overlap / smaller > 0.35:
                raise ValueError(f"角色 {left_index + 1} 与角色 {right_index + 1} 的区域发生重叠；"
                                 "重叠范围过大，会同时混合两套人物特征，请缩小到约 10%–20%。")
    return regions


def regional_shared_terms(regions: list[dict]) -> list[str]:
    """Terms repeated in every character belong to their shared relationship.

    Keeping e.g. ``hug, kiss`` in both half-frame prompts asks each half to draw
    a complete couple.  Moving exact common terms to the group prompt makes the
    interaction happen once, between the declared characters.
    """
    if len(regions) < 2:
        return []
    term_lists = [split_prompt_terms(region["prompt"], limit=180) for region in regions]
    common = {normalize_prompt_key(term) for term in term_lists[0]}
    for terms in term_lists[1:]:
        common &= {normalize_prompt_key(term) for term in terms}
    return [term for term in term_lists[0] if normalize_prompt_key(term) in common]


def regional_group_prompt(regions: list[dict]) -> str:
    girls = sum(region["subject"] == "1girl" for region in regions)
    boys = sum(region["subject"] == "1boy" for region in regions)
    others = len(regions) - girls - boys
    counts: list[str] = []
    if girls:
        counts.extend(([f"{girls}girls"] if girls > 1 else ["1girl"]))
    if boys:
        counts.extend(([f"{boys}boys"] if boys > 1 else ["1boy"]))
    if others:
        counts.append(f"{others}other" if others > 1 else "1other")
    if len(regions) > 1:
        counts.append("multiple people")
    if girls > 1 and not boys and not others:
        counts.extend(("multiple girls", "all female"))
    return unique_prompt_terms(", ".join(counts), ", ".join(REGION_LAYOUT_POSITIVE))


def regional_negative_prompt(negative: str, regions: list[dict]) -> str:
    additions = list(REGION_LAYOUT_NEGATIVE)
    if regions and all(region["subject"] == "1girl" for region in regions):
        additions.extend(("1boy", "male", "man", "boys"))
    elif regions and all(region["subject"] == "1boy" for region in regions):
        additions.extend(("1girl", "female", "woman", "girls"))
    return unique_prompt_terms(negative, ", ".join(additions))


def regional_position_prompt(region: dict) -> str:
    center_x = region["x"] + region["width"] / 2
    center_y = region["y"] + region["height"] / 2
    if region["width"] < 0.8:
        return "character on the left" if center_x < 0.5 else "character on the right"
    if region["height"] < 0.8:
        return "character at the top" if center_y < 0.5 else "character at the bottom"
    return ""


def regional_mask_layout(regions: list[dict], width: int, height: int) -> list[dict]:
    """Convert percentage boxes to slightly overlapping, cross-faded masks.

    Adjacent 50/50 boxes are expanded four percent into the neighbour.  Each
    inner edge is feathered across the complete overlap, so the two conditions
    cross-fade instead of producing a visible diptych boundary.
    """
    boxes = [{**region} for region in regions]
    for left_index, left in enumerate(boxes):
        for right_index in range(left_index + 1, len(boxes)):
            right = boxes[right_index]
            vertical = max(0.0, min(left["y"] + left["height"], right["y"] + right["height"])
                           - max(left["y"], right["y"]))
            horizontal = max(0.0, min(left["x"] + left["width"], right["x"] + right["width"])
                             - max(left["x"], right["x"]))
            vertical_ratio = vertical / min(left["height"], right["height"])
            horizontal_ratio = horizontal / min(left["width"], right["width"])
            if vertical_ratio >= 0.5:
                first, second = (left, right) if left["x"] <= right["x"] else (right, left)
                gap = second["x"] - (first["x"] + first["width"])
                if abs(gap) <= 0.011:
                    blend = 0.04
                    first["width"] = min(1.0 - first["x"], first["width"] + blend)
                    second["x"] = max(0.0, second["x"] - blend)
                    second["width"] = min(1.0 - second["x"], second["width"] + blend)
            elif horizontal_ratio >= 0.5:
                first, second = (left, right) if left["y"] <= right["y"] else (right, left)
                gap = second["y"] - (first["y"] + first["height"])
                if abs(gap) <= 0.011:
                    blend = 0.04
                    first["height"] = min(1.0 - first["y"], first["height"] + blend)
                    second["y"] = max(0.0, second["y"] - blend)
                    second["height"] = min(1.0 - second["y"], second["height"] + blend)

    layouts: list[dict] = []
    for index, box in enumerate(boxes):
        feathers = {"left": 0, "top": 0, "right": 0, "bottom": 0}
        for other_index, other in enumerate(boxes):
            if index == other_index:
                continue
            overlap_x = max(0.0, min(box["x"] + box["width"], other["x"] + other["width"])
                            - max(box["x"], other["x"]))
            overlap_y = max(0.0, min(box["y"] + box["height"], other["y"] + other["height"])
                            - max(box["y"], other["y"]))
            if not overlap_x or not overlap_y:
                continue
            if abs((box["x"] + box["width"] / 2) - (other["x"] + other["width"] / 2)) >= \
                    abs((box["y"] + box["height"] / 2) - (other["y"] + other["height"] / 2)):
                side = "right" if other["x"] > box["x"] else "left"
                feathers[side] = max(feathers[side], round(overlap_x * width))
            else:
                side = "bottom" if other["y"] > box["y"] else "top"
                feathers[side] = max(feathers[side], round(overlap_y * height))
        x = round(box["x"] * width)
        y = round(box["y"] * height)
        box_width = max(1, min(width - x, round(box["width"] * width)))
        box_height = max(1, min(height - y, round(box["height"] * height)))
        layouts.append({"x": x, "y": y, "width": box_width, "height": box_height,
                        "feathers": feathers})
    return layouts


def regional_global_prompt(data: dict, compiled: dict, bound_loras: set[str]) -> str:
    """Build a character-free scene/style prompt shared by every region."""
    sections = compiled["sections"]
    explicit = str(data.get("regionGlobalPrompt", "") or "").strip()
    regions = normalized_regions(data)
    return unique_prompt_terms(
        ", ".join(selected_lora_triggers(data, exclude_names=bound_loras)),
        ", ".join(compiled["profile"]["quality"]),
        regional_group_prompt(regions),
        ", ".join(regional_shared_terms(regions)),
        *(sections[key] for key in REGION_GLOBAL_SECTION_KEYS),
        explicit,
    )


def regional_character_prompt(data: dict, compiled: dict, region: dict,
                              bound_loras: set[str]) -> str:
    """Build one isolated character prompt with its optional hooked LoRA trigger."""
    trigger = ""
    if region["lora"]:
        wanted = normalized_lora_name(region["lora"])
        trigger = next((value for name, value in selected_lora_trigger_entries(data)
                        if normalized_lora_name(name) == wanted), "")
    global_triggers = selected_lora_triggers(data, exclude_names=bound_loras)
    global_prompt = regional_global_prompt(data, compiled, bound_loras)
    quality_keys = {normalize_prompt_key(term)
                    for term in compiled["profile"]["quality"]}
    trigger_keys = {normalize_prompt_key(term) for term in global_triggers}
    all_regions = normalized_regions(data)
    shared_keys = {normalize_prompt_key(term) for term in regional_shared_terms(all_regions)}
    group_keys = {normalize_prompt_key(term)
                  for term in split_prompt_terms(regional_group_prompt(all_regions), limit=80)}
    context_terms = [term for term in split_prompt_terms(global_prompt, limit=180)
                     if normalize_prompt_key(term)
                     not in quality_keys | trigger_keys | shared_keys | group_keys]
    local_terms = [term for term in split_prompt_terms(region["prompt"], limit=180)
                   if normalize_prompt_key(term) not in shared_keys]
    return unique_prompt_terms(
        trigger,
        ", ".join(global_triggers),
        ", ".join(compiled["profile"]["quality"]),
        region["subject"],
        regional_position_prompt(region),
        ", ".join(local_terms),
        ", ".join(context_terms),
    )


def lora_compatibility_warnings(data: dict, family: str) -> list[str]:
    notes = load_lora_notes()
    warnings: list[str] = []
    for lora in data.get("loras", []):
        raw_name = str(lora.get("name", ""))
        key = raw_name.replace("\\", "/").rsplit("/", 1)[-1]
        note = notes.get(key, {})
        declared = str(note.get("base_model", "") if isinstance(note, dict) else "").lower()
        filename = key.lower()
        expected = ""
        if "anima" in declared or "anima" in filename:
            expected = "anima"
        elif "illustrious" in declared or "ilxl" in declared or "illustrious" in filename:
            expected = "illustrious"
        elif any(token in declared for token in ("sd 1.5", "sd1.5", "sd15")) or "sd15" in filename:
            expected = "sd15"
        if expected and expected != family:
            warnings.append(f"LoRA 底模可能不兼容：{key} 标注为 {expected}，当前为 {family}。")
    return warnings


def save_lora_notes(notes: dict) -> None:
    if not isinstance(notes, dict):
        raise ValueError("LoRA 备忘格式不正确。")
    with LORA_NOTES.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(notes, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def load_lora_sidecars() -> dict:
    """Return same-name LoRA .txt files, keyed like ComfyUI's relative LoRA names."""
    if not LORA_DIR.is_dir():
        return {}
    entries: dict[str, dict] = {}
    for text_file in LORA_DIR.rglob("*.txt"):
        if not text_file.with_suffix(".safetensors").is_file():
            continue
        try:
            content = text_file.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        relative = text_file.relative_to(LORA_DIR)
        key = relative.with_suffix("").as_posix()
        limit = 16_000
        entries[key] = {
            "file": relative.as_posix(),
            "content": content[:limit],
            "truncated": len(content) > limit,
        }
    return entries


_SIDECAR_SKIP_PREFIX = (
    "备注", "提示", "说明", "注意", "额外", "需要", "如需", "可以", "想要", "可惜",
    "这个", "总之", "本质上", "总体上", "作者", "官方", "已移除", "若想", "适用",
    "重量", "触发", "给她的", "给他的", "武器", "翅膀", "角色提示", "每套服装", "提示包含",
    "本文件", "当前", "用途",
)


def _clean_sidecar_block(lines: list[str]) -> str:
    """Join the English tag lines of a parsed block; Chinese notes are dropped."""
    kept: list[str] = []
    for raw in lines:
        ln = str(raw or "").strip().rstrip("，,、；;")
        if not ln:
            continue
        latin = len(re.findall(r"[A-Za-z]", ln))
        cjk = len(re.findall(r"[\u4e00-\u9fff]", ln))
        if latin == 0:
            continue
        # Chinese-dominated lines (Chinese description + a stray Latin word such as
        # "ahoge") are notes, not tags: drop them.
        if cjk > 0 and latin < max(3, cjk * 2):
            continue
        # strip trailing sentence notes on the same line after the last tag
        ln = re.split(r"(?:可选|备注|提示|说明|注意|如需|推荐|适用|若想|给她的|给他的)", ln)[0].strip().rstrip("，,、；; ")
        kept.append(ln)
    return ", ".join(x for x in kept if x).strip()


_COMMON_FIRST_TAGS = {
    "1girl", "1boy", "solo", "multiple", "group", "character", "animal",
    "girl", "boy", "girls", "boys", "no", "very", "long", "short", "white",
    "black", "blue", "red", "pink", "purple", "green", "brown", "yellow",
    "hair", "eyes", "dress", "swimsuit", "school", "uniform", "the", "a",
}


_EN_HEADER_MAP = {
    "appearance": "基础角色",
    "character": "基础角色",
    "character description": "基础角色",
    "character design": "基础角色",
    "default": "默认服装",
    "default outfit": "默认服装",
    "outfit": "默认服装",
    "clothing": "默认服装",
    "swimsuit": "泳装",
    "bikini": "泳装",
    "costume": "服装",
}


def _infer_sidecar_trigger(blocks: list[tuple[str, list[str]]]) -> str:
    """Best-effort trigger extraction when the TXT has no explicit 触发词 line.

    Only looks at character blocks so clothing tags are never mistaken for a trigger.
    """
    for header, tag_lines in blocks:
        if header != "基础角色" and not header.startswith("角色"):
            continue
        prompt = _clean_sidecar_block(tag_lines)
        first = (prompt.split(",", 1)[0] if prompt else "").strip()
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{2,30}", first) and first.casefold() not in _COMMON_FIRST_TAGS:
            return first
    return ""


def parse_lora_sidecar(content: str, filename: str = "") -> dict:
    """Parse a same-name LoRA .txt into note fields + Chinese-named outfit presets.

    Returns {"base_model", "weight", "trigger", "outfits": [{"name","prompt"}, ...]}.
    Handles the common CivitAI / Anima-pack layouts:
      - titled blocks: "角色：" / "默认服装：" / "正式礼服（圣痕）：" + tag lines
      - paired Chinese-description line + English tag line ("触发点：中文…")
      - keyword blocks without colons: "角色Yoruno Sakura,long hair,…" / "服装"
      - a single bare tag line (fallback)
    """
    text = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
    meta: dict[str, str] = {"base_model": "", "weight": "", "trigger": ""}
    blocks: list[tuple[str, list[str]]] = []
    current_header: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_header, current_lines
        if current_header is not None:
            blocks.append((current_header, current_lines))
        current_header = None
        current_lines = []

    for raw in text.split("\n"):
        ln = raw.strip()
        if not ln:
            continue
        # ---- meta lines ----
        m = re.search(r"适用底模[:：]\s*([^\n。；]+)", ln)
        if m and not meta["base_model"]:
            meta["base_model"] = m.group(1).strip()
        m = re.search(r"(?:权重|重量|强度|推荐)(?:约|为|设定为|[:：])?\s*([0-9]+(?:\.[0-9]+)?)\s*[-~]\s*([0-9]+(?:\.[0-9]+)?)", ln)
        if m and not meta["weight"]:
            meta["weight"] = m.group(1) + "-" + m.group(2)
        else:
            m = re.search(r"(?:权重|重量|强度|推荐)(?:约|为|设定为|[:：])?\s*([0-9]+(?:\.[0-9]+)?)", ln)
            if m and not meta["weight"]:
                meta["weight"] = m.group(1)
        m = re.search(r"触发(?:点|词)(?:为|[:：])\s*([^\s，,。；]+)", ln)
        if m and not meta["trigger"]:
            cand = m.group(1).strip()
            if re.fullmatch(r"[A-Za-z0-9_\- ]{1,80}", cand):
                meta["trigger"] = cand
        # English meta lines (CivitAI-style): "Weight: 1.0" / "Best weight : 1.0" / "Trigger: Mobius"
        m = re.search(r"\b(?:weight|strength)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*[-~]\s*([0-9]+(?:\.[0-9]+)?)", ln, re.I)
        if m and not meta["weight"]:
            meta["weight"] = m.group(1) + "-" + m.group(2)
        else:
            m = re.search(r"\b(?:weight|strength)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)", ln, re.I)
            if m and not meta["weight"]:
                meta["weight"] = m.group(1)
        m = re.search(r"\btrigger[:：]\s*([^\s,，;]+)", ln, re.I)
        if m and not meta["trigger"]:
            meta["trigger"] = m.group(1).strip()
        # ---- skip comment / note / meta-only lines ----
        if re.match(r"^(?:%s)" % "|".join(_SIDECAR_SKIP_PREFIX), ln):
            continue
        # ---- titled block header: "中文标题：…" ----
        colon = re.match(r"^([^，,]{1,40}?)[：:]\s*(.*)$", ln)
        if colon and not re.search(r"[A-Za-z]", colon.group(1)) and colon.group(1).strip():
            header = colon.group(1).strip()
            if header in ("触发点", "触发词", "触发", "推荐权重", "推荐强度", "推荐重量", "适用底模", "重量", "权重"):
                flush()
                continue
            if re.search(r"免责声明|有趣的事实|附言|备注|注释|前言|说明|感言", header):
                flush()
                continue
            flush()
            current_header = header
            rest = colon.group(2).strip()
            if rest:
                current_lines.append(rest)
            continue
        # ---- English titled block headers: "Appearance : tags" / "Default outfit : tags" ----
        if colon and re.search(r"[A-Za-z]", colon.group(1)):
            header = colon.group(1).strip()
            low_header = header.lower()
            if any(key in low_header for key in ("weight", "strength", "trigger")):
                flush()
                continue
            flush()
            current_header = header
            rest = colon.group(2).strip()
            if rest:
                current_lines.append(rest)
            continue
        # ---- bare header lines ending with a colon (title may start with English) ----
        if ln.endswith(("：", ":")) and not re.search(r",\s*[A-Za-z]", ln):
            if re.search(r"免责声明|附言|备注|注释|感言|有趣的事实|前言|说明", ln):
                flush()
                continue
            flush()
            current_header = ln.rstrip("：:").strip()
            continue
        # ---- keyword blocks without a colon ----
        if re.match(r"^(?:角色|服装|制服|礼服|泳装)", ln):
            if not re.search(r"[A-Za-z]", ln) and len(ln) <= 8:
                flush()
                current_header = ln
                continue
            if ln.startswith("角色"):
                rest = ln[2:].strip()
                parts = rest.split(",", 1)
                flush()
                current_header = ("角色 " + parts[0].strip()).strip()
                if len(parts) > 1:
                    current_lines.append(parts[1].strip())
                continue
        # ---- ordinary tag line ----
        if current_header is None:
            flush()
            current_header = "基础角色"
        current_lines.append(ln)
    flush()

    # ---- assemble Chinese-named presets ----
    role_idx = 0
    cloth_idx = 0
    used_names: set[str] = set()
    outfits: list[dict] = []

    def unique_name(candidate: str) -> str:
        base = candidate
        n = 1
        while base in used_names:
            n += 1
            base = f"{candidate} {n}"
        used_names.add(base)
        return base

    bare = [b for b in blocks if b[0] == "基础角色"]
    for header, tag_lines in blocks:
        prompt = _clean_sidecar_block(tag_lines)
        if not prompt:
            continue
        low = (header + " " + prompt).lower()
        if header == "基础角色":
            if len(blocks) == 1:
                # Single bare block: name it by content (clothing-ish or character-ish).
                clothing_hint = ("swimsuit", "school", "uniform", "dress", "skirt", "pantyhose",
                                 "stocking", "sock", "thighhigh", "服装", "泳装", "制服", "丝袜")
                is_clothing = any(k in low for k in clothing_hint) and not any(
                    k in low for k in ("1girl", "1boy", "girl,", "boy,", "solo", "角色"))
                name = unique_name("默认服装" if is_clothing else "基础角色")
            else:
                name = unique_name("基础角色")
        elif header.startswith("角色"):
            role_idx += 1
            role_name = header[len("角色"):].strip()
            name = unique_name(f"角色 {role_name}" if role_name else f"角色 {role_idx}")
        elif header in ("推荐", "可选tags", "可选标签"):
            role_idx += 1
            name = unique_name("基础角色" if header == "推荐" else "可选标签")
        else:
            header_low = header.lower().strip()
            if header_low in _EN_HEADER_MAP:
                name = unique_name(_EN_HEADER_MAP[header_low])
            elif header in ("服装触发条件", "服装"):
                cloth_idx += 1
                name = unique_name("默认服装" if cloth_idx == 1 else f"服装 {cloth_idx}")
            elif header in ("替代服装触发", "替换服装"):
                cloth_idx += 1
                name = unique_name("替代服装")
            elif header in ("第二副替代服装触发", "第二套", "第二套服装"):
                cloth_idx += 1
                name = unique_name("第二套服装")
            elif any(k in header for k in ("服装", "制服", "礼服", "泳装")):
                cloth_idx += 1
                if re.search(r"[\u4e00-\u9fff]", header):
                    name = unique_name(header)
                else:
                    name = unique_name(f"服装 {cloth_idx}")
            else:
                if re.search(r"[\u4e00-\u9fff]", header):
                    name = unique_name(header)
                elif any(k in header_low for k in ("outfit", "dress", "uniform", "swimsuit", "bikini", "costume", "clothing", "look", "outfits")):
                    cloth_idx += 1
                    name = unique_name(f"服装 {cloth_idx}")
                else:
                    cloth_idx += 1
                    name = unique_name(f"补充 {cloth_idx}")
        outfits.append({"name": name, "prompt": prompt})
    if not meta["trigger"]:
        meta["trigger"] = _infer_sidecar_trigger(blocks)
    return {**meta, "outfits": outfits}


def import_lora_sidecar(lora_filename: str) -> dict:
    """Parse the same-name .txt for a LoRA and merge presets into lora_notes.json."""
    target = Path(str(lora_filename or "")).name
    if target.lower() not in {".safetensors", ".pt", ".ckpt"} and not target.lower().endswith(
            (".safetensors", ".pt", ".ckpt")):
        raise ValueError("请选择有效的 LoRA 文件。")
    stem = target.rsplit(".", 1)[0]
    txt_file: Path | None = None
    if LORA_DIR.is_dir():
        for tf in LORA_DIR.rglob("*.txt"):
            if tf.with_suffix(".safetensors").name.lower() == target.lower() or tf.stem == stem:
                txt_file = tf
                break
    if txt_file is None:
        raise ValueError(f"未找到 {target} 的同名 TXT；请把 TXT 放在 models\\loras 下与 LoRA 同名。")
    content = txt_file.read_text(encoding="utf-8-sig", errors="replace")
    parsed = parse_lora_sidecar(content, txt_file.name)
    notes = load_lora_notes()
    note = notes.get(target, {})
    if not isinstance(note, dict):
        note = {}
    for key in ("base_model", "weight", "trigger"):
        if not str(note.get(key, "")).strip() and parsed.get(key):
            note[key] = parsed[key]
    existing = [o for o in (note.get("outfits") or []) if isinstance(o, dict)]
    existing_names = {str(o.get("name", "")).strip() for o in existing}
    added: list[str] = []
    for outfit in parsed["outfits"]:
        name = str(outfit.get("name", "")).strip()
        if not name:
            continue
        if name in existing_names:
            existing = [o for o in existing if str(o.get("name", "")).strip() != name]
        existing.append(outfit)
        added.append(name)
    note["outfits"] = existing
    notes[target] = note
    save_lora_notes(notes)
    return {
        "noteKey": target,
        "meta": {k: note.get(k, "") for k in ("base_model", "weight", "trigger")},
        "added": added,
        "total": len(existing),
    }


def save_pose_upload(content_type: str, body: bytes) -> str:
    """Store a locally uploaded pose reference under ComfyUI/input/easy_panel."""
    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;\s]+))", content_type, re.I)
    if not match:
        raise ValueError("姿势图片上传格式不正确。")
    boundary = (match.group(1) or match.group(2)).encode("utf-8")
    marker = b"--" + boundary
    for part in body.split(marker):
        if b"name=\"pose\"" not in part or b"filename=" not in part:
            continue
        try:
            headers, content = part.split(b"\r\n\r\n", 1)
        except ValueError:
            continue
        if content.endswith(b"\r\n"):
            content = content[:-2]
        filename_match = re.search(br'filename="([^\"]*)"', headers)
        filename = filename_match.group(1).decode("utf-8", "replace") if filename_match else "pose.png"
        suffix = Path(filename).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("姿势图仅支持 PNG、JPG 或 WEBP。")
        if not content:
            raise ValueError("姿势图文件为空。")
        target_dir = COMFY_INPUT / "easy_panel"
        target_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"easy_panel/pose_{uuid.uuid4().hex[:12]}{suffix}"
        (COMFY_INPUT / stored_name).write_bytes(content)
        return stored_name
    raise ValueError("未找到姿势图片文件。")


def extract_image_upload(content_type: str, body: bytes, field: str = "image") -> bytes:
    """Return the raw bytes of an uploaded image field from a multipart body."""
    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;\s]+))", content_type, re.I)
    if not match:
        raise ValueError("图片上传格式不正确。")
    boundary = (match.group(1) or match.group(2)).encode("utf-8")
    marker = b"--" + boundary
    field_bytes = ('name="' + field + '"').encode("utf-8")
    for part in body.split(marker):
        if field_bytes not in part or b"filename=" not in part:
            continue
        try:
            headers, content = part.split(b"\r\n\r\n", 1)
        except ValueError:
            continue
        if content.endswith(b"\r\n"):
            content = content[:-2]
        if not content:
            raise ValueError("图片文件为空。")
        return content
    raise ValueError("未找到图片文件。")


def save_inpaint_upload(content_type: str, body: bytes) -> dict:
    """Save an original image plus its hand-drawn mask for local repainting.

    The mask is normalized to match the original's pixel size so ComfyUI's
    VAEEncodeForInpaint receives mask and pixels at the same resolution.
    """
    image_bytes = extract_image_upload(content_type, body, field="image")
    mask_bytes = extract_image_upload(content_type, body, field="mask")
    target_dir = COMFY_INPUT / "easy_panel"
    target_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"easy_panel/inpaint_{uuid.uuid4().hex[:12]}.png"
    mask_name = f"easy_panel/inpaint_mask_{uuid.uuid4().hex[:12]}.png"
    try:
        from PIL import Image
        import io
    except ImportError:
        (COMFY_INPUT / image_name).write_bytes(image_bytes)
        (COMFY_INPUT / mask_name).write_bytes(mask_bytes)
        return {"image": image_name, "mask": mask_name}
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
    except Exception as exc:
        raise ValueError("原图或蒙版无法解析：" + str(exc)) from exc
    if mask.size != image.size:
        mask = mask.resize(image.size, Image.LANCZOS)
    image.save(COMFY_INPUT / image_name, format="PNG")
    mask.save(COMFY_INPUT / mask_name, format="PNG")
    return {"image": image_name, "mask": mask_name}


def _num(value):
    """Best-effort numeric conversion returning None for non-numeric values."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        value = value.strip()
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
    return None


def _resolve_clip_text(nodes: dict, ref) -> str:
    """Trace a node reference back to the CLIPTextEncode text it originates from."""
    queue = [ref]
    seen: set[str] = set()
    while queue:
        current = queue.pop(0)
        if not (isinstance(current, list) and current):
            continue
        node_id = str(current[0])
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs", {}) or {}
        if class_type == "CLIPTextEncode":
            return str(inputs.get("text", "") or "")
        for value in inputs.values():
            if isinstance(value, list) and value:
                queue.append(value)
    return ""


def _empty_image_result(source: str) -> dict:
    return {"source": source, "model": "", "family": "sdxl", "positive": "",
            "negative": "", "steps": None, "cfg": None, "sampler": "", "scheduler": "",
            "seed": None, "width": None, "height": None, "loras": [], "prediction": ""}


def parse_comfyui_prompt(workflow: dict) -> dict:
    """Extract generation parameters from a ComfyUI API-format workflow (the 'prompt' chunk)."""
    result = _empty_image_result("comfyui")
    nodes = workflow if isinstance(workflow, dict) else {}
    ksamplers: list[dict] = []
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs", {}) or {}
        if class_type == "KSampler":
            ksamplers.append(node)
        elif class_type == "CheckpointLoaderSimple":
            result["model"] = str(inputs.get("ckpt_name", "") or "")
        elif class_type == "UNETLoader":
            result["model"] = str(inputs.get("unet_name", "") or "")
            result["family"] = "anima"
        elif class_type in ("LoraLoader", "LoraLoaderModelOnly"):
            name = str(inputs.get("lora_name", "") or "")
            if name:
                result["loras"].append({"name": name,
                                         "strength": _num(inputs.get("strength_model", 0.7)) or 0.7})
        elif class_type == "EmptyLatentImage":
            result["width"] = _num(inputs.get("width"))
            result["height"] = _num(inputs.get("height"))
        elif class_type == "ModelSamplingDiscrete":
            result["prediction"] = str(inputs.get("sampling", "") or "")
    if ksamplers:
        inputs = ksamplers[0].get("inputs", {}) or {}
        result["seed"] = _num(inputs.get("seed"))
        result["steps"] = _num(inputs.get("steps"))
        result["cfg"] = _num(inputs.get("cfg"))
        result["sampler"] = str(inputs.get("sampler_name", "") or "")
        result["scheduler"] = str(inputs.get("scheduler", "") or "")
        result["positive"] = _resolve_clip_text(nodes, inputs.get("positive"))
        result["negative"] = _resolve_clip_text(nodes, inputs.get("negative"))
    return result


def parse_comfyui_ui_workflow(data: dict) -> dict:
    """Extract parameters from ComfyUI's UI-format workflow (the 'workflow' chunk)."""
    result = _empty_image_result("comfyui")
    nodes = data.get("nodes", []) or []
    links = data.get("links", []) or []

    def node_by_id(node_id):
        for node in nodes:
            if isinstance(node, dict) and node.get("id") == node_id:
                return node
        return None

    def resolve_text(node, input_name):
        seen: set = set()
        queue = [(node, input_name)]
        while queue:
            current, name = queue.pop(0)
            if not isinstance(current, dict):
                continue
            node_id = current.get("id")
            if node_id in seen:
                continue
            seen.add(node_id)
            ntype = str(current.get("type", ""))
            widgets = current.get("widgets_values", []) or []
            if ntype == "CLIPTextEncode" and widgets:
                return str(widgets[0] or "")
            if name == "__any__":
                for entry in current.get("inputs", []) or []:
                    link_id = entry.get("link")
                    if link_id is None:
                        continue
                    for link in links:
                        if isinstance(link, list) and link and link[0] == link_id:
                            upstream = node_by_id(link[1])
                            if upstream:
                                queue.append((upstream, "__any__"))
                            break
                continue
            link_id = None
            for entry in current.get("inputs", []) or []:
                if str(entry.get("name", "")) == name:
                    link_id = entry.get("link")
                    break
            if link_id is None:
                continue
            for link in links:
                if isinstance(link, list) and link and link[0] == link_id:
                    upstream = node_by_id(link[1])
                    if upstream:
                        queue.append((upstream, "__any__"))
                    break
        return ""

    ksamplers: list[dict] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type", ""))
        widgets = node.get("widgets_values", []) or []
        if ntype == "KSampler":
            result["seed"] = _num(widgets[0] if len(widgets) > 0 else None)
            result["steps"] = _num(widgets[2] if len(widgets) > 2 else None)
            result["cfg"] = _num(widgets[3] if len(widgets) > 3 else None)
            result["sampler"] = str(widgets[4] or "") if len(widgets) > 4 else ""
            result["scheduler"] = str(widgets[5] or "") if len(widgets) > 5 else ""
            ksamplers.append(node)
        elif ntype == "CheckpointLoaderSimple":
            if widgets:
                result["model"] = str(widgets[0] or "")
        elif ntype == "UNETLoader":
            if widgets:
                result["model"] = str(widgets[0] or "")
                result["family"] = "anima"
        elif ntype in ("LoraLoader", "LoraLoaderModelOnly"):
            if widgets and widgets[0]:
                result["loras"].append({"name": str(widgets[0]),
                                         "strength": _num(widgets[1] if len(widgets) > 1 else 0.7) or 0.7})
        elif ntype == "EmptyLatentImage":
            if len(widgets) >= 2:
                result["width"] = _num(widgets[0])
                result["height"] = _num(widgets[1])
    if ksamplers:
        result["positive"] = resolve_text(ksamplers[0], "positive")
        result["negative"] = resolve_text(ksamplers[0], "negative")
    return result


def parse_a1111_parameters(text: str) -> dict:
    """Parse A1111 / WebUI 'parameters' text into generation fields."""
    result = _empty_image_result("a1111")
    parts = str(text or "").split("Negative prompt:", 1)
    result["positive"] = parts[0].strip()
    rest = parts[1] if len(parts) > 1 else ""
    if "Steps:" in rest:
        negative, params = rest.split("Steps:", 1)
        result["negative"] = negative.strip()
        # The value of "Steps:" directly follows the split, so restore the key
        # to make the first "key: value" pair parseable.
        params = "Steps:" + params
        for pair in params.split(","):
            if ":" not in pair:
                continue
            key, value = pair.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "steps":
                result["steps"] = _num(value)
            elif key == "cfg scale":
                result["cfg"] = _num(value)
            elif key == "sampler":
                result["sampler"] = value
            elif key == "scheduler":
                result["scheduler"] = value
            elif key == "seed":
                result["seed"] = _num(value)
            elif key == "model":
                result["model"] = value
            elif key == "size":
                wh = re.split(r"[xX×]", value)
                if len(wh) == 2:
                    result["width"] = _num(wh[0])
                    result["height"] = _num(wh[1])
    else:
        result["negative"] = rest.strip()
    return result


def parse_novelai_comment(text: str) -> dict:
    """Parse NovelAI's 'Comment' JSON metadata."""
    result = _empty_image_result("novelai")
    try:
        data = json.loads(str(text or ""))
    except (TypeError, json.JSONDecodeError):
        return result
    if not isinstance(data, dict):
        return result
    result["positive"] = str(data.get("prompt", "") or "")
    result["negative"] = str(data.get("uc", "") or "")
    params = data.get("parameters", {}) or {}
    if isinstance(params, dict):
        result["steps"] = _num(params.get("steps"))
        result["cfg"] = _num(params.get("scale"))
        result["sampler"] = str(params.get("sampler", "") or "")
        result["seed"] = _num(params.get("seed"))
        result["model"] = str(params.get("model", "") or "")
    return result


def _read_exif_user_comment(image) -> str:
    """Best-effort EXIF UserComment extraction for WebP / JPEG images."""
    try:
        exif = image.getexif()
        if not exif:
            return ""
        raw = None
        try:
            raw = exif.get_ifd(0x8769).get(37510)
        except Exception:
            pass
        if raw is None:
            raw = exif.get(37510)
        if isinstance(raw, bytes):
            for prefix in (b"ASCII\x00\x00\x00", b"\x00" * 8):
                if raw.startswith(prefix):
                    return raw[len(prefix):].decode("utf-8", "replace").rstrip("\x00")
            if raw.startswith(b"UNICODE\x00"):
                try:
                    return raw[8:].decode("utf-16", "replace").rstrip("\x00")
                except Exception:
                    pass
            return raw.decode("utf-8", "replace").rstrip("\x00")
        return str(raw or "")
    except Exception:
        return ""


def parse_generation_info(content: bytes) -> dict:
    """Read AI-generation metadata (prompt/params) embedded in a PNG/WebP/JPEG image."""
    try:
        from PIL import Image
        import io
    except ImportError as exc:
        raise ValueError("缺少 Pillow 库，无法读取图片元数据。") from exc
    try:
        image = Image.open(io.BytesIO(content))
        image.load()
        info = dict(getattr(image, "info", {}) or {})
    except Exception as exc:
        raise ValueError("无法解析图片文件：" + str(exc)) from exc
    chunks: dict[str, str] = {}
    for key, value in info.items():
        if isinstance(value, str):
            chunks[str(key)] = value
    if not any(key in chunks for key in ("parameters", "prompt", "Comment", "Description", "workflow")):
        user_comment = _read_exif_user_comment(image)
        if user_comment:
            chunks["parameters"] = user_comment
    if "parameters" in chunks:
        result = parse_a1111_parameters(chunks["parameters"])
    elif "prompt" in chunks or "workflow" in chunks:
        workflow_text = chunks.get("prompt") or chunks.get("workflow")
        try:
            parsed = json.loads(workflow_text)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("nodes"), list):
            result = parse_comfyui_ui_workflow(parsed)
        elif isinstance(parsed, dict):
            result = parse_comfyui_prompt(parsed)
        else:
            result = _empty_image_result("comfyui")
            result["positive"] = str(workflow_text or "")[:2000]
    elif "Comment" in chunks:
        result = parse_novelai_comment(chunks["Comment"])
    elif "Description" in chunks:
        result = parse_a1111_parameters(chunks["Description"])
    else:
        raise ValueError("未在图片中找到 AI 生成参数。请使用未经二次压缩的原始 PNG / WebP（ComfyUI、WebUI 或 NovelAI 生成）。")
    model = result.get("model", "")
    if is_anima_model(model):
        result["family"] = "anima"
    elif is_krea2_model(model):
        result["family"] = "krea2"
    elif is_illustrious_model(model):
        result["family"] = "illustrious"
    else:
        result["family"] = "sdxl"
    return result


def list_output_images(limit: int = 80) -> list[dict]:
    """Return recent generated images from the ComfyUI output directory."""
    if not OUTPUT.is_dir():
        return []
    entries: list[dict] = []
    try:
        candidates = sorted(OUTPUT.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    for file in candidates:
        if file.suffix.lower() not in {".png", ".webp", ".jpg", ".jpeg"}:
            continue
        try:
            mtime = int(file.stat().st_mtime)
        except OSError:
            continue
        entries.append({"name": file.name, "mtime": mtime})
        if len(entries) >= limit:
            break
    return entries


def validate_input_image(name: str) -> str:
    """Only allow a saved file below ComfyUI/input to enter a LoadImage node."""
    relative = Path(str(name or "").replace("\\", "/"))
    if not relative.name or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("姿势图片路径无效。")
    file = (COMFY_INPUT / relative).resolve()
    try:
        file.relative_to(COMFY_INPUT.resolve())
    except ValueError as exc:
        raise ValueError("姿势图片路径无效。") from exc
    if not file.is_file():
        raise ValueError("找不到已上传的姿势图片，请重新上传。")
    return relative.as_posix()


def prepare_generation_image(name: str) -> str:
    """Return an input-relative image name for LoadImage (img2img base).

    Accepts either an already-uploaded input path or a filename from ComfyUI's
    output directory (e.g. a Krea 2 base image picked from the recent outputs);
    output images are copied into ComfyUI/input so LoadImage can read them.
    """
    raw = str(name or "").replace("\\", "/").strip()
    if not raw:
        raise ValueError("请先选择要重绘的底图。")
    try:
        return validate_input_image(raw)
    except ValueError:
        pass
    base = raw.rsplit("/", 1)[-1]
    if base != raw:
        raise ValueError("找不到要重绘的底图。")
    source = OUTPUT / base
    if not source.is_file() or source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("找不到要重绘的底图。")
    target_dir = COMFY_INPUT / "easy_panel"
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = f"easy_panel/img2img_{uuid.uuid4().hex[:12]}{source.suffix.lower()}"
    (COMFY_INPUT / stored).write_bytes(source.read_bytes())
    return stored


def validate_pose_json(value: object) -> str:
    """Validate editor keypoints before passing them to a ComfyUI node."""
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if not raw or len(raw.encode("utf-8")) > 1_000_000:
        raise ValueError("骨架数据为空或过大。")
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("骨架编辑器返回的数据格式不正确。") from exc
    # DWpose extraction stores one-or-more pose documents as a list, while the
    # OpenPose editor posts a single standard OpenPose document.  Normalize the
    # latter so both the preview and generation workflows use the same shape.
    if isinstance(parsed, dict):
        parsed = [parsed]

    if not isinstance(parsed, list) or not parsed or len(parsed) > 8:
        raise ValueError("骨架数据必须包含一组或多组人物关键点。")
    if not all(isinstance(item, dict) and isinstance(item.get("people"), list) for item in parsed):
        raise ValueError("骨架数据缺少人物关键点。")
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def build_pose_preview_workflow(data: dict) -> dict:
    """Render an uploaded person reference into the exact pose image used by the panel."""
    mode = str(data.get("mode", "extract"))
    if mode not in {"extract", "skeleton", "edited"}:
        raise ValueError("未知的姿势图模式。")
    if mode == "edited":
        pose_json = validate_pose_json(data.get("poseJson"))
        nodes = {
            "1": {"class_type": "huchenlei.LoadOpenposeJSON", "inputs": {"json_str": pose_json}},
            "2": {"class_type": "EasyPanelRenderPoseXinsir", "inputs": {
                "kps": ["1", 0], "render_body": True, "render_hand": True, "render_face": True,
                "scale_stick_for_xinsr_cn": "enable",
            }},
            "3": {"class_type": "SaveImage", "inputs": {"filename_prefix": "EasyPanelPose", "images": ["2", 0]}},
        }
        return {"prompt": nodes, "client_id": "easy-panel-pose-preview"}
    pose_image = validate_input_image(data.get("image", ""))
    nodes: dict[str, dict] = {
        "1": {"class_type": "LoadImage", "inputs": {"image": pose_image}},
    }
    image_ref = ["1", 0]
    if mode == "extract":
        # Extract mode: several keypoint back-ends give different results on
        # anime vs photoreal / single vs multi-person references.
        #   dwpose-full : whole-image regression, best for a single anime character
        #   dwpose-yolo : YOLO person detection then per-box regression (real photo / multi-person)
        #   openpose    : CMU OpenPose, no person-box stage (robust fallback)
        # ComfyUI caches node outputs by input signature: submitting the exact
        # same workflow a second time hits the cache and returns an EMPTY ui
        # payload (openpose_json disappears, so the panel wrongly reports
        # "关键点可信度偏低"). Jittering the resolution a few pixels each time
        # forces real re-execution so the keypoint JSON is always present.
        try:
            res = int(data.get("resolution") or 1024)
        except (TypeError, ValueError):
            res = 1024
        res = max(256, min(2048, res + random.randint(-4, 4)))
        extract_mode = str(data.get("extractMode", "dwpose-full"))
        if extract_mode == "dwpose-yolo":
            nodes["2"] = {
                "class_type": "DWPreprocessor",
                "inputs": {
                    "image": image_ref,
                    "bbox_detector": "yolox_l.onnx",
                    "pose_estimator": "dw-ll_ucoco_384.onnx",
                    "resolution": res,
                    "scale_stick_for_xinsr_cn": "enable",
                },
            }
        elif extract_mode == "openpose":
            nodes["2"] = {
                "class_type": "OpenposePreprocessor",
                "inputs": {
                    "image": image_ref,
                    "detect_hand": "enable",
                    "detect_body": "enable",
                    "detect_face": "enable",
                    "scale_stick_for_xinsr_cn": "enable",
                    "resolution": res,
                },
            }
        else:
            # dwpose-full: Anime illustrations often fail YOLO's photoreal-person
            # detector. Bypassing it treats the whole reference as the subject,
            # which is more reliable for a single-character pose reference.
            nodes["2"] = {
                "class_type": "DWPreprocessor",
                "inputs": {
                    "image": image_ref,
                    "bbox_detector": "None",
                    "pose_estimator": "dw-ll_ucoco_384.onnx",
                    "resolution": res,
                    "scale_stick_for_xinsr_cn": "enable",
                },
            }
        image_ref = ["2", 0]
    nodes["3"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "EasyPanelPose", "images": image_ref}}
    return {"prompt": nodes, "client_id": "easy-panel-pose-preview"}


def comfy_json(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        COMFY + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def bounded(value, default, low, high, integer=True):
    try:
        value = int(value) if integer else float(value)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _gray_offset(channel: "Image.Image", offset: int, wrap: bool = False) -> "Image.Image":
    """LayerStyle image_gray_offset / image_hue_offset equivalent."""
    import numpy as np
    from PIL import Image
    arr = np.array(channel, dtype=np.int16)
    if wrap:
        arr = (arr + offset) % 256
    else:
        arr = np.clip(arr + offset, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "L")


def apply_color_correction(image_bytes: bytes, params: dict) -> bytes:
    """Replicate the LayerStyle post chain (Brightness&Contrast -> RGB -> HSV -> Gamma -> Levels)
    with PIL + numpy so the live preview matches the generated output exactly.

    Algorithms mirror ComfyUI_LayerStyle/py/color_correct_*.py + imagefunc.py:
      - Brightness/Contrast/Color : PIL ImageEnhance
      - RGB offsets               : per-channel clip(add, 0..255)
      - HSV offsets               : H wraps mod 256, S/V clip
      - Gamma                     : LUT (x/255)^gamma * 255
      - Levels                    : input remap + midtone power + output remap
    """
    import io
    import numpy as np
    from PIL import Image, ImageEnhance

    brightness = bounded(params.get("brightness"), 1.0, 0.0, 3.0, integer=False)
    contrast = bounded(params.get("contrast"), 1.0, 0.0, 3.0, integer=False)
    saturation = bounded(params.get("saturation"), 1.0, 0.0, 3.0, integer=False)
    red = bounded(params.get("red"), 0, -255, 255)
    green = bounded(params.get("green"), 0, -255, 255)
    blue = bounded(params.get("blue"), 0, -255, 255)
    hue = bounded(params.get("hue"), 0, -255, 255)
    hsv_saturation = bounded(params.get("hsvSaturation"), 0, -255, 255)
    value = bounded(params.get("value"), 0, -255, 255)
    gamma = bounded(params.get("gamma"), 1.0, 0.1, 10.0, integer=False)
    black_point = bounded(params.get("blackPoint"), 0, 0, 254)
    white_point = bounded(params.get("whitePoint"), 255, 1, 255)
    if black_point >= white_point:
        black_point, white_point = 0, 255
    gray_point = bounded(params.get("grayPoint"), 1.0, 0.01, 9.99, integer=False)

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # 1) LayerColor: Brightness & Contrast
    if brightness != 1:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if contrast != 1:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if saturation != 1:
        img = ImageEnhance.Color(img).enhance(saturation)

    # 2) LayerColor: RGB
    if red or green or blue:
        arr = np.array(img).astype(np.int16)
        if red:
            arr[:, :, 0] = np.clip(arr[:, :, 0] + red, 0, 255)
        if green:
            arr[:, :, 1] = np.clip(arr[:, :, 1] + green, 0, 255)
        if blue:
            arr[:, :, 2] = np.clip(arr[:, :, 2] + blue, 0, 255)
        img = Image.fromarray(arr.astype(np.uint8), "RGB")

    # 3) LayerColor: HSV
    if hue or hsv_saturation or value:
        h, s, v = img.convert("HSV").split()
        if hue:
            h = _gray_offset(h, hue, wrap=True)
        if hsv_saturation:
            s = _gray_offset(s, hsv_saturation)
        if value:
            v = _gray_offset(v, value)
        img = Image.merge("HSV", (h, s, v)).convert("RGB")

    # 4) LayerColor: Gamma
    if gamma != 1:
        arr = np.array(img).astype(np.float64)
        arr = 255.0 * np.power(arr / 255.0, gamma)
        arr = np.clip(arr, 0, 255)
        img = Image.fromarray(arr.astype(np.uint8), "RGB")

    # 5) LayerColor: Levels
    if black_point > 0 or white_point < 255 or gray_point != 1:
        arr = np.array(img).astype(np.float64)
        if black_point > 0 or white_point < 255:
            arr = 255.0 * (arr - black_point) / (white_point - black_point)
            arr = np.clip(arr, 0, 255)
        if gray_point != 1.0:
            arr = 255.0 * np.power(arr / 255.0, 1.0 / gray_point)
            arr = np.clip(arr, 0, 255)
        img = Image.fromarray(arr.astype(np.uint8), "RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_workflow(data: dict) -> dict:
    model = str(data.get("model", ""))
    if not model:
        raise ValueError("请选择基础模型。")
    anima = is_anima_model(model)
    krea2 = is_krea2_model(model)
    illustrious = (not anima and not krea2) and is_illustrious_model(model)
    illustrious_profile = illustrious_sampling_settings(model) if illustrious else None
    sampling_profile = model_sampling_profile(model)
    if not anima and not krea2:
        issue = checkpoint_issue(model)
        if issue:
            raise ValueError(issue + "请选择 WAI、Milmu、Spectacular 或 Gock So 等完整模型。")
    compiled = compile_prompt(data)
    if compiled["errors"]:
        raise ValueError("；".join(compiled["errors"]))
    prompt = compiled["positive"]
    negative = compiled["negative"]

    width = bounded(data.get("width"), 832, 512, 1920)
    height = bounded(data.get("height"), 1216, 512, 1920)
    width -= width % 8
    height -= height % 8
    regions = normalized_regions(data)
    if regions and (anima or krea2):
        family_name = "Anima" if anima else "Krea 2"
        raise ValueError(f"{family_name} 暂不支持区域提示词；请切回 SDXL / Illustrious，或关闭多人分区。")
    regional_mode = bool(regions and not anima and not krea2)
    if regional_mode:
        negative = regional_negative_prompt(negative, regions)
    bound_lora_names = {region["lora"] for region in regions if region["lora"]}
    bound_lora_keys = {normalized_lora_name(name) for name in bound_lora_names}
    selected_loras = {normalized_lora_name(item.get("name")): item
                      for item in data.get("loras", []) if str(item.get("name", "")).strip()}
    # Keep API callers aligned with the model family even when a frontend omits
    # these fields.  Illustrious derivatives do not all share a prediction type
    # or their preferred sampler, so their model-aware profile is authoritative.
    default_steps, default_cfg = sampling_profile["steps"], sampling_profile["cfg"]
    if sampling_profile.get("locked"):
        steps, cfg = default_steps, default_cfg
    else:
        steps = bounded(data.get("steps"), default_steps, 8, 60)
        cfg = bounded(data.get("cfg"), default_cfg, 1, 15, integer=False)
    seed_value = data.get("seed", -1)
    seed = random.randrange(1, 2**63 - 1) if str(seed_value) in {"", "-1", "random"} else bounded(seed_value, 1, 0, 2**63 - 1)

    if anima:
        # This mirrors ComfyUI's official Anima Base v1 template.  The model is
        # a diffusion-model file and must not be sent through CheckpointLoaderSimple.
        nodes: dict[str, dict] = {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": model, "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": ANIMA_TEXT_ENCODER,
                                                          "type": "stable_diffusion"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": ANIMA_VAE}},
        }
        model_ref, clip_ref, vae_ref = ["1", 0], ["2", 0], ["3", 0]
        next_id = 4
    elif krea2:
        # Krea 2 is a single-stream MMDiT UNet; it uses a Qwen3-VL-4B text encoder
        # (CLIPLoader type "krea2") and a Qwen-family VAE.
        nodes = {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": model, "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": KREA2_TEXT_ENCODER,
                                                            "type": "krea2"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": KREA2_VAE}},
        }
        model_ref, clip_ref, vae_ref = ["1", 0], ["2", 0], ["3", 0]
        next_id = 4
    else:
        nodes = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}}}
        model_ref, clip_ref, vae_ref = ["1", 0], ["1", 1], ["1", 2]
        next_id = 2

    def alloc() -> str:
        nonlocal next_id
        node_id = str(next_id)
        next_id += 1
        return node_id

    if illustrious_profile and illustrious_profile["prediction"] == "v_prediction":
        sampling_id = alloc()
        nodes[sampling_id] = {
            "class_type": "ModelSamplingDiscrete",
            "inputs": {"model": model_ref, "sampling": "v_prediction", "zsnr": False},
        }
        model_ref = [sampling_id, 0]

    for lora in data.get("loras", []):
        name = str(lora.get("name", ""))
        if not name:
            continue
        # Character LoRAs assigned to a region are attached later as conditioning
        # hooks. Loading them here would patch the whole model and blend every
        # character's face, hair, outfit and body shape across all regions.
        if regional_mode and normalized_lora_name(name) in bound_lora_keys:
            continue
        weight = bounded(lora.get("weight"), 0.7, 0, 1.5, integer=False)
        node_id = alloc()
        if anima or krea2:
            # Official Anima/Krea 2 LoRAs are model-only; applying them to the
            # text encoder is neither required nor compatible.
            nodes[node_id] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": model_ref, "lora_name": name, "strength_model": weight,
            }}
            model_ref = [node_id, 0]
        else:
            nodes[node_id] = {
                "class_type": "LoraLoader",
                "inputs": {"model": model_ref, "clip": clip_ref, "lora_name": name,
                           "strength_model": weight, "strength_clip": weight},
            }
            model_ref, clip_ref = [node_id, 0], [node_id, 1]

    # Attention guidance after LoRA, before the KSampler. SAG (Self-Attention
    # Guidance) guides the whole image (subject + background); PAG (Perturbed
    # Attention Guidance) focuses on the subject/person only. Not supported for
    # Krea 2 (single-stream MMDiT has no SD-style attention map).
    guidance = data.get("guidance") or {}
    if not guidance and isinstance(data.get("sag"), dict):
        # Back-compat with the older sag:{enabled,scale,blur} payload.
        guidance = {"mode": "sag" if data["sag"].get("enabled") else "off",
                    "sagScale": data["sag"].get("scale", 0.5),
                    "sagBlur": data["sag"].get("blur", 2.0)}
    if not isinstance(guidance, dict):
        guidance = {}
    mode = str(guidance.get("mode", "off"))
    if mode not in {"off", "sag", "pag"}:
        raise ValueError("未知的注意力引导模式。")
    if regional_mode and mode != "off":
        raise ValueError("多人分区不能同时启用 SAG/PAG；这会重复模型 Hook、显著变慢并干扰人物隔离。")
    if mode != "off" and not sampling_profile["guidance_supported"]:
        raise ValueError(f"{sampling_profile['label']} 不支持 SAG/PAG，请关闭注意力引导。")
    if sampling_profile["guidance_supported"] and mode == "sag":
        guide_id = alloc()
        nodes[guide_id] = {
            "class_type": "SelfAttentionGuidance",
            "inputs": {
                "model": model_ref,
                "scale": bounded(guidance.get("sagScale"), 0.5, -2.0, 5.0, integer=False),
                "blur_sigma": bounded(guidance.get("sagBlur"), 2.0, 0.0, 10.0, integer=False),
            },
        }
        model_ref = [guide_id, 0]
    elif sampling_profile["guidance_supported"] and mode == "pag":
        guide_id = alloc()
        nodes[guide_id] = {
            "class_type": "PerturbedAttentionGuidance",
            "inputs": {
                "model": model_ref,
                "scale": bounded(guidance.get("pagScale"), 2.0, 0.0, 100.0, integer=False),
            },
        }
        model_ref = [guide_id, 0]

    base_positive = regional_global_prompt(data, compiled, bound_lora_names) if regional_mode else prompt
    positive_id, negative_id = alloc(), alloc()
    nodes[positive_id] = {"class_type": "CLIPTextEncode", "inputs": {"text": base_positive, "clip": clip_ref}}
    nodes[negative_id] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": clip_ref}}
    negative_ref = [negative_id, 0]

    # Each character gets a feathered mask conditioning. A bound character LoRA
    # is also attached as a hook, so its model and CLIP patches are active only
    # while ComfyUI evaluates that character. Soft overlap at adjacent boundaries
    # preserves one continuous scene instead of producing a visible split-screen.
    # The character-free base remains the DEFAULT for background and interaction.
    if regional_mode:
        conds = []
        mask_layouts = regional_mask_layout(regions, width, height)
        empty_mask_id = alloc()
        nodes[empty_mask_id] = {"class_type": "SolidMask", "inputs": {
            "value": 0.0, "width": width, "height": height,
        }}
        for region_index, r in enumerate(regions):
            region_clip_ref = clip_ref
            if r["lora"]:
                lora = selected_loras[normalized_lora_name(r["lora"])]
                weight = bounded(lora.get("weight"), 0.7, 0, 1.5, integer=False)
                hook_id, hooked_clip_id = alloc(), alloc()
                nodes[hook_id] = {"class_type": "CreateHookLora", "inputs": {
                    "lora_name": r["lora"], "strength_model": weight, "strength_clip": weight,
                }}
                nodes[hooked_clip_id] = {"class_type": "SetClipHooks", "inputs": {
                    "clip": clip_ref, "hooks": [hook_id, 0],
                    "apply_to_conds": True, "schedule_clip": False,
                }}
                region_clip_ref = [hooked_clip_id, 0]
            enc_id = alloc()
            nodes[enc_id] = {"class_type": "CLIPTextEncode",
                             "inputs": {"text": regional_character_prompt(
                                 data, compiled, r, bound_lora_names), "clip": region_clip_ref}}
            layout = mask_layouts[region_index]
            solid_id = alloc()
            nodes[solid_id] = {"class_type": "SolidMask", "inputs": {
                "value": 1.0, "width": layout["width"], "height": layout["height"],
            }}
            mask_ref = [solid_id, 0]
            if any(layout["feathers"].values()):
                feather_id = alloc()
                nodes[feather_id] = {"class_type": "FeatherMask", "inputs": {
                    "mask": mask_ref, **layout["feathers"],
                }}
                mask_ref = [feather_id, 0]
            composite_id = alloc()
            nodes[composite_id] = {"class_type": "MaskComposite", "inputs": {
                "destination": [empty_mask_id, 0], "source": mask_ref,
                "x": layout["x"], "y": layout["y"], "operation": "add",
            }}
            masked_id = alloc()
            nodes[masked_id] = {"class_type": "ConditioningSetMask", "inputs": {
                "conditioning": [enc_id, 0], "mask": [composite_id, 0],
                "strength": r["strength"], "set_cond_area": "mask bounds",
            }}
            conds.append([masked_id, 0])
        ref = conds[0]
        for c in conds[1:]:
            comb_id = alloc()
            nodes[comb_id] = {"class_type": "ConditioningCombine",
                              "inputs": {"conditioning_1": ref, "conditioning_2": c}}
            ref = [comb_id, 0]
        default_id = alloc()
        nodes[default_id] = {"class_type": "ConditioningSetDefaultCombine", "inputs": {
            "cond": ref, "cond_DEFAULT": [positive_id, 0],
        }}
        positive_ref = [default_id, 0]
    else:
        positive_ref = [positive_id, 0]

    # Local repaint: encode the uploaded image with a hand-drawn mask so the
    # KSampler only re-draws the masked region (denoise < 1 keeps the rest).
    # Whole-image redraw (img2img): encode a base image (e.g. a Krea 2 render) and
    # re-draw it with the current model at denoise < 1. Works for Anima / Krea 2 /
    # Illustrious alike, which is how the Krea 2 -> Illustrious/Anima anime pass works.
    img2img_data = data.get("img2img") or {}
    img2img = bool(isinstance(img2img_data, dict) and img2img_data.get("enabled"))
    repair = (not anima) and str(data.get("illustriousMode", "precision")) == "repair"
    if img2img:
        image_name = prepare_generation_image(str(img2img_data.get("image", "") or ""))
        denoise = bounded(img2img_data.get("denoise"), 0.6, 0.1, 1.0, integer=False)
        # Guard against OOM: img2img encodes the base latent at full source
        # resolution, so an oversized base image can overflow 8GB VRAM.
        try:
            from PIL import Image as _PILImage
            with _PILImage.open(COMFY_INPUT / image_name) as _probe:
                _iw, _ih = _probe.size
        except Exception:
            _iw = _ih = 0
        if _iw * _ih > 2_500_000:
            raise ValueError(
                f"底图 {_iw}×{_ih}（{_iw * _ih / 1e6:.2f} MP）过大，8GB 显存容易溢出；"
                "请先用较小的底图（建议 1.5 MP 以内）再重绘。"
            )
        load_id, encode_id = alloc(), alloc()
        nodes[load_id] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
        nodes[encode_id] = {"class_type": "VAEEncode",
                            "inputs": {"pixels": [load_id, 0], "vae": vae_ref}}
        latent_ref = [encode_id, 0]
    elif repair:
        repair_data = data.get("repair") or {}
        image_name = validate_input_image(str(repair_data.get("image", "") or ""))
        mask_name = validate_input_image(str(repair_data.get("mask", "") or ""))
        grow = bounded(repair_data.get("grow"), 6, 0, 64)
        denoise = bounded(repair_data.get("denoise"), 0.5, 0.2, 1.0, integer=False)
        load_id, mask_load_id, encode_id = alloc(), alloc(), alloc()
        nodes[load_id] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
        nodes[mask_load_id] = {"class_type": "LoadImageMask",
                               "inputs": {"image": mask_name, "channel": "red"}}
        nodes[encode_id] = {
            "class_type": "VAEEncodeForInpaint",
            "inputs": {"pixels": [load_id, 0], "vae": vae_ref, "mask": [mask_load_id, 0],
                       "grow_mask_by": grow},
        }
        latent_ref = [encode_id, 0]
    else:
        latent_id = alloc()
        nodes[latent_id] = {"class_type": "EmptyLatentImage",
                            "inputs": {"width": width, "height": height, "batch_size": 1}}
        latent_ref = [latent_id, 0]
        denoise = 1

    pose = data.get("pose") or {}
    if pose.get("enabled"):
        if anima or krea2:
            raise ValueError("当前安装的 Xinsir OpenPose ControlNet 仅适用于 SDXL，不能与 Anima / Krea 2 一起使用。")
        controlnet = str(pose.get("controlnet", ""))
        if not controlnet:
            raise ValueError("请选择 OpenPose ControlNet。")
        strength = bounded(pose.get("strength"), 0.82, 0, 2, integer=False)
        start = bounded(pose.get("start"), 0, 0, 1, integer=False)
        end = bounded(pose.get("end"), 0.75, 0, 1, integer=False)
        if end < start:
            raise ValueError("姿势控制结束步数不能早于开始步数。")
        pose_json = pose.get("poseJson")
        if pose_json:
            normalized_pose_json = validate_pose_json(pose_json)
            pose_load_id, render_id = alloc(), alloc()
            nodes[pose_load_id] = {
                "class_type": "huchenlei.LoadOpenposeJSON",
                "inputs": {"json_str": normalized_pose_json},
            }
            nodes[render_id] = {
                "class_type": "EasyPanelRenderPoseXinsir",
                "inputs": {"kps": [pose_load_id, 0], "render_body": True, "render_hand": True, "render_face": True,
                           "scale_stick_for_xinsr_cn": "enable"},
            }
            pose_image_ref = [render_id, 0]
        else:
            pose_image = validate_input_image(pose.get("image", ""))
            mode = str(pose.get("mode", "extract"))
            if mode not in {"extract", "skeleton"}:
                raise ValueError("未知的姿势图模式。")
            pose_load_id = alloc()
            nodes[pose_load_id] = {"class_type": "LoadImage", "inputs": {"image": pose_image}}
            pose_image_ref = [pose_load_id, 0]
            if mode == "extract":
                preprocessor_id = alloc()
                nodes[preprocessor_id] = {
                    "class_type": "DWPreprocessor",
                    "inputs": {
                        "image": pose_image_ref,
                        "bbox_detector": "None",
                        "pose_estimator": "dw-ll_ucoco_384.onnx",
                        "resolution": 1024,
                        "scale_stick_for_xinsr_cn": "enable",
                    },
                }
                pose_image_ref = [preprocessor_id, 0]
        controlnet_id, apply_id = alloc(), alloc()
        nodes[controlnet_id] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": controlnet}}
        nodes[apply_id] = {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {"positive": positive_ref, "negative": negative_ref, "control_net": [controlnet_id, 0],
                       "image": pose_image_ref, "strength": strength, "start_percent": start, "end_percent": end},
        }
        positive_ref, negative_ref = [apply_id, 0], [apply_id, 1]

    sampler_name, scheduler = sampling_profile["sampler"], sampling_profile["scheduler"]
    # Optional manual sampler/scheduler override; locked distilled profiles keep
    # the exact sampler contract they were trained for.
    if not sampling_profile.get("locked"):
        custom_sampler = str(data.get("sampler", "") or "").strip()
        custom_scheduler = str(data.get("scheduler", "") or "").strip()
        if custom_sampler and custom_sampler != "auto":
            sampler_name = custom_sampler
        if custom_scheduler and custom_scheduler != "auto":
            scheduler = custom_scheduler
    sampler_id = alloc()
    nodes[sampler_id] = {
        "class_type": "KSampler",
        "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                   "sampler_name": sampler_name, "scheduler": scheduler, "denoise": denoise, "model": model_ref,
                   "positive": positive_ref, "negative": negative_ref, "latent_image": latent_ref},
    }

    sample_ref = [sampler_id, 0]
    hires_enabled = illustrious and str(data.get("illustriousMode", "precision")) == "hires"
    if hires_enabled:
        hires_defaults = sampling_profile.get("hires") or {}
        scale = bounded(data.get("hiresScale"), hires_defaults.get("scale", 1.25), 1.1, 1.5, integer=False)
        hires_denoise = bounded(data.get("hiresDenoise"), hires_defaults.get("denoise", 0.30), 0.15, 0.45, integer=False)
        hires_steps = bounded(data.get("hiresSteps"), hires_defaults.get("steps", 18), 8, 30)
        hires_cfg = bounded(data.get("hiresCfg"), hires_defaults.get("cfg", 4.5), 3, 7, integer=False)
        upscale_id, hires_sampler_id = alloc(), alloc()
        nodes[upscale_id] = {
            "class_type": "LatentUpscaleBy",
            "inputs": {"samples": sample_ref, "upscale_method": "bislerp", "scale_by": scale},
        }
        nodes[hires_sampler_id] = {
            "class_type": "KSampler",
            "inputs": {"seed": seed, "steps": hires_steps, "cfg": hires_cfg,
                       "sampler_name": sampler_name, "scheduler": scheduler,
                       "denoise": hires_denoise, "model": model_ref,
                       "positive": positive_ref, "negative": negative_ref,
                       "latent_image": [upscale_id, 0]},
        }
        sample_ref = [hires_sampler_id, 0]

    decode_id = alloc()
    nodes[decode_id] = {"class_type": "VAEDecode", "inputs": {"samples": sample_ref, "vae": vae_ref}}

    # Optional post-processing uses the single installed ComfyUI_LayerStyle pack.
    # The chain is deliberately absent when disabled, so the default workflow stays unchanged.
    color = data.get("colorCorrection", {})
    image_ref = [decode_id, 0]
    if isinstance(color, dict) and bool(color.get("enabled")):
        brightness = bounded(color.get("brightness"), 1.0, 0.0, 3.0, integer=False)
        contrast = bounded(color.get("contrast"), 1.0, 0.0, 3.0, integer=False)
        saturation = bounded(color.get("saturation"), 1.0, 0.0, 3.0, integer=False)
        red = bounded(color.get("red"), 0, -255, 255)
        green = bounded(color.get("green"), 0, -255, 255)
        blue = bounded(color.get("blue"), 0, -255, 255)
        hue = bounded(color.get("hue"), 0, -255, 255)
        hsv_saturation = bounded(color.get("hsvSaturation"), 0, -255, 255)
        value = bounded(color.get("value"), 0, -255, 255)
        gamma = bounded(color.get("gamma"), 1.0, 0.1, 10.0, integer=False)
        black_point = bounded(color.get("blackPoint"), 0, 0, 254)
        white_point = bounded(color.get("whitePoint"), 255, 1, 255)
        if black_point >= white_point:
            black_point, white_point = 0, 255
        gray_point = bounded(color.get("grayPoint"), 1.0, 0.01, 9.99, integer=False)

        brightness_id, rgb_id, hsv_id, gamma_id, levels_id = [alloc() for _ in range(5)]
        nodes[brightness_id] = {
            "class_type": "LayerColor: Brightness & Contrast",
            "inputs": {"image": image_ref, "brightness": brightness, "contrast": contrast, "saturation": saturation},
        }
        nodes[rgb_id] = {
            "class_type": "LayerColor: RGB",
            "inputs": {"image": [brightness_id, 0], "R": red, "G": green, "B": blue},
        }
        nodes[hsv_id] = {
            "class_type": "LayerColor: HSV",
            "inputs": {"image": [rgb_id, 0], "H": hue, "S": hsv_saturation, "V": value},
        }
        nodes[gamma_id] = {
            "class_type": "LayerColor: Gamma",
            "inputs": {"image": [hsv_id, 0], "gamma": gamma},
        }
        nodes[levels_id] = {
            "class_type": "LayerColor: Levels",
            "inputs": {"image": [gamma_id, 0], "channel": "RGB", "black_point": black_point,
                       "white_point": white_point, "gray_point": gray_point,
                       "output_black_point": 0, "output_white_point": 255},
        }
        image_ref = [levels_id, 0]

    save_id = alloc()
    nodes[save_id] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "EasyPanel", "images": image_ref}}
    return {"prompt": nodes, "client_id": "easy-panel"}


_ANIMA_TRANSLATION_PROMPT = """\
You are an Anima prompt adapter. Convert the user's Chinese image description into one precise English positive prompt for Anima.

Rules:
1. Preserve every explicitly stated subject, appearance, garment, pose, action, expression, camera angle, setting, lighting, color, and medium. Never invent or remove elements.
2. The message contains application fields (ANIMA_PREFIX, SAFETY_TAG) followed by CHINESE_DESCRIPTION:. Insert their values where told, ignore empty ones, and never output field names.
3. Place LoRA triggers, <lora:...>, embeddings, wildcards, and weights like (concept:1.5) verbatim at the very start, in original order. Character, series, and artist tags are preserved but placed in their section below.
4. After triggers, order: quality/meta, safety, subject count, character, series, artist, appearance, clothing, pose/action, expression/gaze, composition/camera, setting, lighting/color/style, then natural-language sentence if any.
5. Lowercase normal tags; underscores to spaces (keep only in score_*); prefer canonical Gelbooru terms; comma-separated; concise. Merge duplicates, synonyms, and hierarchies (e.g. "very long hair" not "long hair, very long hair").
6. Artist: output "@artist name" only when given; never invent one.
7. Use 1-2 concise English sentences only when needed (multiple subjects, complex poses, hand placement, spatial relations); clearly attribute each action to the right subject.
8. Keep about 10-45 meaningful tags; never add filler quality spam unless requested.
9. Put ANIMA_PREFIX after any triggers; use SAFETY_TAG as the rating; add no other quality or score_* tags.
10. Output only the final positive prompt, one line, no headings, explanations, quotation marks, Markdown, JSON, negative prompt, or alternatives.
"""

_ILLUSTRIOUS_TRANSLATION_PROMPT = """\
You are an Illustrious XL prompt adapter. Convert the user's Chinese description into one compact English positive prompt using canonical Danbooru tags (natural language only for actions tags cannot express).

Rules:
1. Keep every stated subject/count, character and series name, physical appearance, hairstyle, clothing, pose/action, interaction, expression, gaze, camera distance and angle, foreground/background, lighting/color, style/medium. Never invent details, identity, franchise, or story elements.
2. The message contains ILLUSTRIOUS_PREFIX followed by CHINESE_DESCRIPTION:. Insert its value, ignore empty ones, and never output field names.
3. Place LoRA triggers, <lora:...>, embeddings, wildcards, escaped character tags, and existing weights verbatim at the start; never translate them.
4. Order: triggers, quality prefix, subject count, character/series, major appearance, hair/face, clothing/accessories, pose, action/interaction, expression/gaze, framing/camera, background/environment, lighting/color, style/medium.
5. Lowercase ordinary tags with spaces, not underscores (keep underscores only inside protected, parenthetical, or tag-database tokens); comma-separated; prefer Danbooru terms. Deduplicate and merge synonyms/hierarchies (e.g. "white collared shirt" not "shirt, white shirt, collared shirt").
6. Use an established character/series tag only when present in the input or the application tag database; otherwise keep the readable name.
7. Simple scenes: tags only. Complex relationships: add one short clause identifying each subject; never write the whole output as prose.
8. Use ILLUSTRIOUS_PREFIX as the quality prefix; add no score_* or "very awa" tags, model magic words, or conflicting quality tiers.
9. Keep the smallest tag set that fully preserves the request (about 12-50 typical).
10. Output only the final positive prompt, one line, no explanations, headings, categories, bullet points, Markdown, JSON, negative prompt, comments, or alternatives.
"""

_KREA_TRANSLATION_PROMPT = """\
You are a Krea 2 prompt editor. Convert the user's Chinese description into one clear, visually grounded English prompt that reads as a coherent image description (not a tag list).

Rules:
1. Keep every stated subject, appearance, hairstyle, clothing/accessory, pose/action, interaction, expression, gaze, camera view, environment, lighting, color palette, medium, and style. Never invent elements, visible text, or story events.
2. The message contains KREA_EXPANSION_MODE and CHINESE_DESCRIPTION:. Insert their values, ignore empty ones, and never output field names.
3. Place LoRA or style trigger words verbatim at the very start, followed by a comma; keep character/series names and requested quoted text exactly.
4. Describe in natural order: subject, defining appearance, clothing/accessories, pose/action, interaction and spatial relations, expression/gaze, composition and framing, setting/background, lighting/color/texture/atmosphere. Flow naturally, not template-like.
5. For multiple characters, associate each with their own appearance, clothing, position, action, and gaze using explicit spatial wording (left/right/foreground/behind/facing); avoid ambiguous pronouns.
6. KREA_EXPANSION_MODE: strict = add no unspecified lighting, framing, style, medium, color, atmosphere, or scene detail; balanced = may add one restrained framing/lighting/medium when unspecified. In both, never add subjects, objects, clothing, colors, locations, identities, or story.
7. Describe poses physically: body orientation, head/torso direction, visible hands, contact, camera-relative direction, standing/sitting/kneeling/reclining/moving. No unrequested poses.
8. Use concrete visual language (e.g. "soft directional lighting", "low-angle medium shot"); avoid promotional fluff ("breathtaking", "perfect", "viral artwork").
9. Reproduce requested in-image text exactly inside English quotation marks.
10. Length proportional to input (about 15-50 words simple, 50-140 detailed); no filler.
11. Output only the final prompt as one cohesive paragraph; no reasoning, explanations, headings, bullet points, Markdown, JSON, negatives, alternatives, or surrounding quotes.
"""


def ai_prompt_system(family: str) -> str:
    """Return the model-family-specific translation system prompt (production spec)."""
    family = str(family or "").strip().lower()
    if family == "krea2":
        return _KREA_TRANSLATION_PROMPT
    if family == "anima":
        return _ANIMA_TRANSLATION_PROMPT
    return _ILLUSTRIOUS_TRANSLATION_PROMPT


def validated_ai_endpoint(raw_endpoint: str, protocol: str, model: str) -> str:
    defaults = {
        "openai": DEFAULT_AI_CHAT,
        "anthropic": DEFAULT_ANTHROPIC_MESSAGES,
        "gemini": DEFAULT_GEMINI_GENERATE,
    }
    endpoint = str(raw_endpoint or defaults[protocol]).strip()
    if protocol == "gemini":
        endpoint = endpoint.replace("{model}", urllib.parse.quote(model, safe="-._"))
    if len(endpoint) > 1000:
        raise ValueError("AI 接口地址过长。")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("AI 接口地址必须是完整的 HTTP 或 HTTPS URL。")
    if parsed.username or parsed.password:
        raise ValueError("请勿把 API Key 写进接口 URL；请使用密钥输入框。")
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme == "http" and parsed.hostname.lower() not in local_hosts:
        raise ValueError("远程 AI 接口必须使用 HTTPS；HTTP 仅允许本机 Ollama 等服务。")
    return endpoint


def ai_auth_headers(api_key: str, auth_type: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if not api_key or auth_type == "none":
        return headers
    if auth_type == "bearer":
        headers["Authorization"] = "Bearer " + api_key
    elif auth_type == "x-api-key":
        headers["x-api-key"] = api_key
    elif auth_type == "api-key":
        headers["api-key"] = api_key
    elif auth_type == "x-goog-api-key":
        headers["x-goog-api-key"] = api_key
    else:
        raise ValueError("不支持的 API 鉴权方式。")
    return headers


def _openai_style_text(payload: dict) -> str:
    """Extract text from OpenAI-compatible responses across common shapes."""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                text = "\n".join(str(part.get("text", "")).strip() for part in content
                                 if isinstance(part, dict) and part.get("text")).strip()
                if text:
                    return text
            if content:
                return str(content).strip()
            # DeepSeek reasoner keeps the final answer in content; reasoning_content
            # is not a usable image prompt, so it is intentionally ignored.
        if first.get("text"):
            return str(first["text"]).strip()
    message = payload.get("message")
    if isinstance(message, dict) and message.get("content"):
        return str(message["content"]).strip()
    for key in ("response", "output_text", "content", "result", "output"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def ai_response_text(payload: dict, protocol: str) -> str:
    """Extract the assistant text from an AI response across common shapes.

    Returns "" when no text is found so callers can report a precise error.
    Raises ValueError when the service returned a business error with HTTP 200.
    """
    if not isinstance(payload, dict):
        return ""
    # Some compatible servers return {"error": {...}} while still replying HTTP 200.
    err = payload.get("error")
    if isinstance(err, dict):
        detail = err.get("message") or err.get("error") or err.get("type") or json.dumps(err, ensure_ascii=False)
        raise ValueError("AI 服务返回错误：%s" % str(detail)[:500])
    if isinstance(err, str) and err:
        raise ValueError("AI 服务返回错误：%s" % err[:500])

    if protocol == "anthropic":
        blocks = payload.get("content", [])
        text = "\n".join(str(block.get("text", "")).strip() for block in blocks
                         if isinstance(block, dict) and block.get("type") == "text").strip()
        if text:
            return text
        # Anthropic-compatible servers that reply OpenAI-style.
        return _openai_style_text(payload)

    if protocol == "gemini":
        candidates = payload.get("candidates", [])
        if isinstance(candidates, list) and candidates:
            first = candidates[0] if isinstance(candidates[0], dict) else {}
            content = first.get("content")
            if isinstance(content, dict):
                parts = content.get("parts", [])
                text = "\n".join(str(part.get("text", "")).strip() for part in parts
                                 if isinstance(part, dict) and part.get("text")).strip()
                if text:
                    return text
            for key in ("output", "text"):
                if first.get(key):
                    return str(first[key]).strip()
        if payload.get("output_text"):
            return str(payload["output_text"]).strip()
        return ""

    return _openai_style_text(payload)


def parse_ai_json(content: str) -> dict:
    cleaned = str(content or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start >= 0:
            try:
                value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                pass
    return {"sections": {"manual": cleaned}, "negative": ""}


# --- Flat English prompt -> panel section classifier (AI translation application) ---

_SECTION_ORDER = ("subject", "appearance", "clothing", "pose", "composition",
                  "scene", "lighting", "style", "manual")

_SUBJECT_TERMS = ("1girl", "2girls", "3girls", "1boy", "2boys", "woman", "man", "girl",
                  "boy", "solo", "character", "characters", "multiple girls",
                  "multiple characters", "group", "couple", "female", "male", "teenager",
                  "adult", "young woman", "young man", "loli", "shota", "milf", "person")

_APPEARANCE_TERMS = ("hair", "eyes", "pupils", "eyelashes", "eyebrows", "bangs", "sidelocks",
                     "braid", "ponytail", "twintails", "ahoge", "drill hair", "streaked hair",
                     "gradient hair", "hair between eyes", "hair ornament", "hairpin",
                     "hairclip", "hairband", "headband", "skin", "blush", "freckles", "mole",
                     "breasts", "cleavage", "body", "figure", "waist", "thighs", "legs",
                     "collarbone", "shoulders", "heterochromia", "navel", "midriff", "stomach",
                     "arms", "hands", "fingers", "toenails", "neck", "face", "expression",
                     "fang", "scar", "tattoo", "wings", "tail", "ears", "horns", "halo",
                     "slim", "curvy", "athletic", "large breasts", "small breasts",
                     "medium breasts", "covered breasts", "underboob", "sideboob",
                     "body markings", "skin fangs", "smile", "frown", "eyebrow", "fingernails",
                     "nails", "feet", "barefoot", "cleavage cutout", "collarbone")

_CLOTHING_TERMS = ("dress", "shirt", "blouse", "skirt", "pants", "shorts", "uniform", "coat",
                   "jacket", "sweater", "hoodie", "kimono", "robe", "cape", "cloak", "scarf",
                   "tie", "necktie", "ribbon", "bow", "belt", "sash", "gloves", "mittens",
                   "sleeves", "collar", "choker", "necklace", "pendant", "earrings", "ring",
                   "bracelet", "watch", "hat", "headwear", "cap", "beret", "veil", "crown",
                   "tiara", "pantyhose", "tights", "stockings", "thighhighs", "socks",
                   "leggings", "footwear", "shoes", "boots", "heels", "sandals", "mary janes",
                   "bikini", "swimsuit", "leotard", "bodysuit", "lingerie", "underwear",
                   "panties", "bra", "garter", "bodystocking", "apron", "corset", "camisole",
                   "jumpsuit", "overalls", "cardigan", "blazer", "hood", "vest", "waistcoat",
                   "poncho", "fabric", "lace", "frills", "fur", "leather", "denim", "pocket",
                   "buttons", "zipper", "armor", "breastplate", "gauntlets", "armlet",
                   "wristband", "cuffs", "sleeves past wrists", "showgirl skirt",
                   "pleated skirt", "sailor", "serafuku", "school uniform", "military uniform",
                   "gym uniform", "maid", "nun", "china dress", "pantsuit", "suit", "tuxedo",
                   "tank top", "crop top", "tube top", "halter", "bodice", "pelvic curtain",
                   "breast curtain", "thong", "swimwear", "wetsuit", "armor", "gauntlet",
                   "kneehighs", "anklet", "chaps", "capelet", "poncho", "overalls",
                   "playboy bunny", "bunnysuit", "bunny suit")

_POSE_TERMS = ("standing", "sitting", "lying", "kneeling", "crouching", "leaning", "walking",
               "running", "jumping", "dancing", "raising", "holding", "carrying", "hugging",
               "embracing", "kissing", "touching", "pointing", "looking at viewer",
               "looking back", "looking away", "looking to the side", "looking down",
               "looking up", "pose", "gesture", "hand on hip", "crossed legs", "spread legs",
               "arms up", "arms behind head", "arms crossed", "squatting", "crawling",
               "riding", "bent over", "prone", "supine", "spread", "groping", "caressing",
               "grabbing", "waving", "stretching", "bending", "turning", "reaching", "lifting",
               "hand in own panties", "masturbation", "thigh straddle", "ass up",
               "doggy style", "missionary", "cowgirl position", "standing on one leg",
               "sitting on", "kneeling on", "lying on", "leaning on", "leaning against",
               "back-to-back", "piggyback", "bridal carry", "hand on", "arm around",
               "headpat", "handholding", "hand-holding", "crossdressing", "pose")

_COMPOSITION_TERMS = ("full body", "upper body", "waist up", "bust", "portrait", "close-up",
                      "close up", "headshot", "medium shot", "wide shot", "long shot",
                      "low angle", "high angle", "bird's eye view", "first-person view",
                      "view", "perspective", "framing", "composition", "cropped",
                      "from behind", "from side", "from front", "depth of field", "focus",
                      "centered", "off-center", "rule of thirds", "head tilted", "cut-in",
                      "cowboy shot", "full shot", "closeup", "faraway", "distant",
                      "extreme close-up", "over-the-shoulder", "pov", "selfie")

_SCENE_TERMS = ("background", "indoors", "outdoor", "classroom", "corridor", "city", "street",
                "building", "room", "bedroom", "kitchen", "bathroom", "beach", "seaside",
                "ocean", "sea", "pool", "mountain", "forest", "park", "garden",
                "cherry blossoms", "snow", "rain", "night", "sky", "window", "door", "chair",
                "bed", "desk", "stage", "temple", "shrine", "castle", "palace", "throne",
                "rooftop", "balcony", "train", "car", "library", "cafe", "restaurant",
                "market", "alley", "bridge", "river", "lake", "water", "grass", "flowers",
                "tree", "clouds", "moon", "sun", "stars", "sign", "fence", "wall", "floor",
                "ceiling", "couch", "sofa", "table", "bath", "shower", "office", "school",
                "dormitory", "ship", "battlefield", "ruins", "space", "city lights", "bokeh",
                "winter", "autumn", "spring", "summer", "sunny", "meadow", "hill", "cliff",
                "cave", "desert", "waterfall", "pond", "boat", "airplane", "helicopter",
                "station", "platform", "elevator", "stairs", "sidewalk", "crosswalk",
                "neon city", "skyline", "horizon", "cloudy", "overcast", "indoors",
                "outdoors", "outside", "inside", "hospital", "laboratory", "garage",
                "workshop", "factory", "warehouse", "church", "cathedral", "graveyard",
                "cemetery", "dungeon", "cave")

_LIGHTING_TERMS = ("lighting", "light", "shadow", "sunlight", "daylight", "moonlight", "lamp",
                   "neon", "glow", "rim light", "backlight", "soft light", "hard light",
                   "sunset", "golden hour", "color grading", "palette", "colored",
                   "overexposed", "underexposed", "silhouette", "backlit", "candlelight",
                   "starlight", "spotlight", "fluorescent", "volumetric", "light rays",
                   "god rays", "twilight", "dusk", "dawn", "glowing", "luminous", "shade",
                   "highlight", "contrast", "bright", "dim", "dark", "moody", "warm light",
                   "cool light", "bokeh lights", "streetlight", "neon light")

_STYLE_TERMS = ("anime", "illustration", "painting", "lineart", "line art", "sketch",
                "watercolor", "cel shading", "cell shading", "3d", "3d render", "render",
                "photorealistic", "realistic", "artstyle", "art style", "aesthetic",
                "monochrome", "grayscale", "pastel", "oil painting", "acrylic",
                "digital painting", "concept art", "anime coloring", "flat color", "detailed",
                "intricate", "clean lineart", "semi-realistic", "pixel art", "chibi",
                "minimalist", "impressionist", "surreal", "fantasy art", "8k", "hd", "sharp",
                "vibrant", "muted", "saturated", "official art", "promotional art", "art",
                "traditional media", "film grain", "drawing", "painterly", "soft shading",
                "flat shading", "masterpiece", "best quality", "style", "colorful",
                "storybook", "comic", "manga", "cartoon", "graphic novel", "ukiyo-e",
                "abstract", "minimal", "glossy", "matte", "smooth")

# Compiler-managed control tokens: dropped from the sections so they are not duplicated
# or left stale when the user switches checkpoints. The compiler re-injects them.
_TRANSLATE_FILTER_PREFIX = ("score_",)
_TRANSLATE_FILTER_EXACT = frozenset((
    "masterpiece", "best quality", "amazing quality", "very awa", "highres", "absurdres",
    "newest", "ultra-detailed", "safe", "nsfw", "explicit", "sensitive", "lowres",
    "bad quality", "worst quality", "bad anatomy", "bad hands", "jpeg artifacts",
))

_NL_MARKERS = (" is ", " are ", " was ", " were ", " has ", " have ", " wearing ",
               " behind ", " beside ", " next to ", " in front of ", " on the ",
               " in the ", " at the ", " with the ", " facing ", " viewed from ",
               " between ", " from behind ", " to the left ", " to the right ",
               " in her ", " in his ", " her hand ", " his hand ", " one hand ",
               " both hands ", " she is ", " he is ", " they are ", " the other ",
               " while ")


def _is_natural_language(term: str) -> bool:
    words = [word for word in str(term).split() if word]
    if len(words) < 4:
        return False
    low = " " + str(term).lower() + " "
    return any(marker in low for marker in _NL_MARKERS)


_WEIGHT_BRACKET_RE = re.compile(r"\([^()]*:\s*(?:0(?:\.\d+)?|1(?:\.\d+)?|2(?:\.0+)?)\)")


def _is_trigger_like(term: str) -> bool:
    """Character/series/trigger tokens: parenthesised, camelCase, numbered, underscored.

    Prompt-weight syntax like (holding hands:1.2) is emphasis, not a trigger word,
    so it is stripped before the trigger-feature test.
    """
    stripped = _WEIGHT_BRACKET_RE.sub("", term)
    if stripped != term:
        if not stripped.strip():
            return False
        term = stripped
    return bool(re.search(r"\([^()]*\)|[a-z][A-Z]|[A-Za-z]{2,}\d|\w_\w", term))


def _matches_terms(low: str, terms: tuple) -> bool:
    """Whole-word match for single words, substring match for multi-word phrases.

    This keeps 'scarf' from matching the 'scar' appearance keyword while still
    matching phrases like 'looking at viewer' or 'long hair'.
    """
    words = set(low.split())
    for term in terms:
        if " " in term:
            if term in low:
                return True
        elif term in words:
            return True
    return False


def _split_sentence_tail(term: str) -> tuple:
    """Split 'anime style. She is sitting ...' into ('anime style', 'She is sitting ...').

    Tag-style output (Anima / Illustrious) can glue a trailing sentence to the last
    tag with '. '; return the tag head for classification and the sentence for the
    naturalLanguage section.
    """
    parts = re.split(r"(?<=[.!?])\s+", str(term or "").strip())
    if len(parts) <= 1:
        return str(term or "").strip(), ""
    sentence = parts[-1].strip()
    head = ", ".join(part.strip().rstrip(".!?") for part in parts[:-1] if part.strip())
    return head, sentence


def classify_english_prompt(text: str, family: str = "illustrious") -> dict:
    """Split a flat English positive prompt into panel sections.

    Krea 2 output is one natural-language paragraph and is kept whole in the
    naturalLanguage section. Tag-style output (Anima / Illustrious) is classified
    term by term; application-injected quality/safety tokens are dropped because
    the compiler re-injects them from the model profile.
    """
    sections: dict[str, list[str]] = {key: [] for key in _SECTION_ORDER}
    sections["naturalLanguage"] = []
    for term in split_prompt_terms(text, limit=240):
        head, sentence = _split_sentence_tail(term)
        if sentence:
            sections["naturalLanguage"].append(sentence)
        term = head
        low = str(term).strip().lower()
        if not low:
            continue
        if _is_natural_language(term):
            sections["naturalLanguage"].append(term)
            continue
        if low.startswith("@"):
            sections["style"].append(term)  # artist tag
            continue
        if low.startswith(_TRANSLATE_FILTER_PREFIX) or low in _TRANSLATE_FILTER_EXACT:
            continue
        match = _WEIGHT_BRACKET_RE.sub("", low).strip()
        if not match:
            inner = re.search(r"\(([^()]*):", low)
            match = inner.group(1).strip() if inner else low
        if _is_trigger_like(term) or _matches_terms(match, _SUBJECT_TERMS):
            sections["subject"].append(term)
        elif _matches_terms(match, _COMPOSITION_TERMS):
            sections["composition"].append(term)
        elif _matches_terms(match, _POSE_TERMS):
            sections["pose"].append(term)
        elif _matches_terms(match, _APPEARANCE_TERMS):
            sections["appearance"].append(term)
        elif _matches_terms(match, _CLOTHING_TERMS):
            sections["clothing"].append(term)
        elif _matches_terms(match, _SCENE_TERMS):
            sections["scene"].append(term)
        elif _matches_terms(match, _LIGHTING_TERMS):
            sections["lighting"].append(term)
        elif _matches_terms(match, _STYLE_TERMS):
            sections["style"].append(term)
        else:
            sections["manual"].append(term)
    if family == "krea2":
        # Natural-language family: keep the whole paragraph in one place.
        return {"naturalLanguage": str(text or "").strip()}
    return {key: ", ".join(values) for key, values in sections.items() if values}


TRANSLATION_MAX_TOKENS = {"anima": 260, "illustrious": 220, "krea2": 320}


def illustrious_quality_prefix(model_name: str) -> list[str]:
    """Checkpoint-aware Illustrious quality prefix; the translator and compiler share it."""
    name = Path(str(model_name or "")).name.lower()
    if "noobai" in name:
        return ["very awa", "masterpiece", "best quality", "newest", "highres", "absurdres"]
    if name.startswith("wai"):
        return ["masterpiece", "best quality", "amazing quality"]
    return ["masterpiece", "best quality"]


def translation_prefix(family: str, model: str, safety: str) -> str:
    """The quality prefix injected into the translator's user message, from model config."""
    if family == "anima":
        name = Path(str(model or "")).name.lower()
        return "masterpiece, best quality" if "aesthetic" in name else "masterpiece, best quality, score_7"
    if family == "krea2":
        return ""
    if family == "illustrious":
        return ", ".join(illustrious_quality_prefix(model))
    return "masterpiece, best quality, highres"


def build_translation_user_message(family: str, prefix: str, safety: str, text: str) -> str:
    """Assemble the translator user message: application fields then the Chinese description."""
    lines: list[str] = []
    if family == "anima":
        if prefix:
            lines.append("ANIMA_PREFIX: " + prefix)
        lines.append("SAFETY_TAG: " + safety)
    elif family == "illustrious":
        if prefix:
            lines.append("ILLUSTRIOUS_PREFIX: " + prefix)
    elif family == "krea2":
        lines.append("KREA_EXPANSION_MODE: balanced")
    lines.append("CHINESE_DESCRIPTION: " + str(text or "").strip())
    return "\n".join(lines)


def _is_param_rejected(detail: str) -> bool:
    """True when an OpenAI-compatible gateway rejected our extra sampling params."""
    low = (detail or "").lower()
    words = ("max_tokens", "top_p", "unsupported parameter", "unknown parameter",
             "not supported", "invalid parameter", "extra inputs", "unexpected parameter",
             "additional properties")
    return any(word in low for word in words)


def _is_reasoning_model(model: str) -> bool:
    """True for reasoning models whose output budget is split with reasoning_content."""
    name = str(model or "").lower().replace("_", "-")
    marks = ("reasoner", "thinking", "-r1", "-o1", "-o3", "-o4",
             "deepseek-v3.1", "deepseek-v4", "deepseek-r1", "v4-flash")
    return any(mark in name for mark in marks)


def _response_has_reasoning(payload: dict) -> bool:
    """True when the response carries reasoning_content (reasoning models)."""
    if not isinstance(payload, dict):
        return False
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and message.get("reasoning_content") is not None:
            return True
    return "reasoning_content" in payload or "reasoning" in payload


def _finish_reason_length(payload: dict) -> bool:
    """True when the response was cut off by the token budget (finish_reason=length)."""
    if not isinstance(payload, dict):
        return False
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0].get("finish_reason") == "length"
    return False


# Reasoning models spend output tokens on reasoning_content; the initial budget is
# already generous, and the retry ladder grows it further until an answer fits.
REASONING_MAX_TOKENS = 16384
REASONING_RETRY_BUDGETS = (16384, 32768)


def ai_translate(data: dict) -> dict:
    """Convert Chinese to a family-specific final English positive prompt.

    The system prompt is per model family (Anima / Illustrious / Krea 2) and the
    quality prefix, safety tag and expansion mode are injected as application fields
    so the translator never guesses model magic words.
    """
    api_key = str(data.get("apiKey", "")).strip()
    text = str(data.get("text", "")).strip()
    protocol = str(data.get("protocol", "openai")).strip().lower()
    auth_type = str(data.get("authType", "bearer")).strip().lower()
    model = str(data.get("model", "")).strip()
    checkpoint = str(data.get("checkpoint", "") or "")
    family = str(data.get("family", "illustrious")).strip().lower()
    if family not in {"anima", "illustrious", "krea2"}:
        family = "krea2" if family == "krea" else "illustrious"
    if protocol not in {"openai", "anthropic", "gemini"}:
        raise ValueError("接口协议仅支持 OpenAI 兼容、Anthropic 或 Gemini。")
    if protocol in {"anthropic", "gemini"} and not model:
        raise ValueError("该接口协议必须填写模型名称。")
    endpoint = validated_ai_endpoint(str(data.get("endpoint", "")), protocol, model)
    parsed = urllib.parse.urlparse(endpoint)
    is_local = (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
    if not api_key and auth_type != "none" and not is_local:
        raise ValueError("请填写 API Key，或把鉴权方式设为“无需密钥”。")
    if not text:
        raise ValueError("请先填写中文描述。")
    if len(text) > 6000:
        raise ValueError("中文描述过长，请控制在 6000 个字符以内。")
    if len(model) > 300:
        raise ValueError("模型名称过长。")

    system = ai_prompt_system(family)
    safety = normalized_safety_level(data)
    prefix = translation_prefix(family, checkpoint, safety)
    user_message = build_translation_user_message(family, prefix, safety, text)
    max_tokens = TRANSLATION_MAX_TOKENS.get(family, 220)
    if _is_reasoning_model(model):
        # Reasoning models spend output tokens on reasoning_content; give them headroom
        # so the final answer is not truncated to empty.
        max_tokens = REASONING_MAX_TOKENS

    def _make_body(max_tok: int) -> dict:
        if protocol == "anthropic":
            return {"model": model, "max_tokens": max_tok, "temperature": 0.2,
                    "system": system, "messages": [{"role": "user", "content": user_message}]}
        if protocol == "gemini":
            return {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                "generationConfig": {"temperature": 0.2, "topP": 0.9, "maxOutputTokens": max_tok},
            }
        body = {"messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user_message}],
                "temperature": 0.2, "top_p": 0.9, "max_tokens": max_tok}
        if model:
            body["model"] = model
        return body

    request_body = _make_body(max_tokens)

    headers = ai_auth_headers(api_key, auth_type)
    if protocol == "anthropic":
        headers["anthropic-version"] = "2023-06-01"

    def _post(body: dict):
        request = urllib.request.Request(endpoint, data=json.dumps(body).encode("utf-8"),
                                         method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8")), None
        except urllib.error.HTTPError as exc:
            return None, (exc.code, exc.read().decode("utf-8", "replace"))

    payload, http_err = _post(request_body)
    if http_err and protocol == "openai" and _is_param_rejected(http_err[1]):
        # Some OpenAI-compatible gateways reject max_tokens / top_p / temperature.
        slim = {"messages": request_body["messages"]}
        if request_body.get("model"):
            slim["model"] = request_body["model"]
        payload, http_err = _post(slim)
    if http_err:
        raise ValueError("AI 请求失败（HTTP %s）：%s" % (http_err[0], http_err[1][:700]))
    content = ai_response_text(payload, protocol)
    if not content and (_response_has_reasoning(payload) or _finish_reason_length(payload)):
        # Reasoning content (or a plain truncation) burned the output budget, leaving
        # the final answer empty. Retry with progressively larger budgets.
        for budget in REASONING_RETRY_BUDGETS:
            if budget <= max_tokens:
                continue
            payload, http_err = _post(_make_body(budget))
            if http_err:
                break
            max_tokens = budget
            content = ai_response_text(payload, protocol)
            if content:
                break
            if not _response_has_reasoning(payload) and not _finish_reason_length(payload):
                break
    if not content:
        snippet = json.dumps(payload, ensure_ascii=False)[:400]
        reason = "该模型把输出预算全用于思维链推理，多次提高预算后仍未返回正文。" if _response_has_reasoning(payload) else "输出可能被截断。"
        raise ValueError(
            "AI 接口返回成功，但没有找到文本内容；%s"
            "服务端返回：%s" % (reason, snippet)
        )

    positive = str(content or "").strip()
    negative = ""
    prompt_mode = "flat"
    sections: dict = {}
    # Robust fallback: if a model returns JSON sections anyway, convert them.
    if positive.startswith("{") and ("sections" in positive or "negative" in positive):
        parsed_result = parse_ai_json(positive)
        raw_sections = parsed_result.get("sections", {}) if isinstance(parsed_result, dict) else {}
        if isinstance(raw_sections, dict) and any(raw_sections.values()):
            sections = {}
            for key in (*PROMPT_SECTION_KEYS, "naturalLanguage"):
                value = raw_sections.get(key, "")
                if isinstance(value, list):
                    value = ", ".join(str(item) for item in value if str(item).strip())
                sections[key] = str(value or "").strip()
            positive = unique_prompt_terms(*(sections[key] for key in PROMPT_SECTION_KEYS))
            if sections["naturalLanguage"]:
                positive = positive.rstrip(" .") + ". " + sections["naturalLanguage"]
            negative = str(parsed_result.get("negative", "") if isinstance(parsed_result, dict) else "").strip()
            prompt_mode = "sections"
    if not sections:
        sections = classify_english_prompt(positive, family)
    return {"positive": positive, "negative": negative, "protocol": protocol,
            "family": family, "promptMode": prompt_mode, "prefix": prefix,
            "sections": sections}


def google_translate(data: dict) -> dict:
    """Official Google Cloud Translation Basic v2 request."""
    api_key = str(data.get("apiKey", "")).strip()
    text = str(data.get("text", "")).strip()
    if not api_key:
        raise ValueError("请先在面板中填写 Google Cloud Translation API Key。")
    if not text:
        raise ValueError("请先填写中文描述。")
    if len(text) > 6000:
        raise ValueError("中文描述过长，请控制在 6000 个字符以内。")
    encoded = json.dumps({"q": text, "source": "zh-CN", "target": "en", "format": "text"}).encode("utf-8")
    endpoint = GOOGLE_TRANSLATE + "?" + urllib.parse.urlencode({"key": api_key})
    request = urllib.request.Request(endpoint, data=encoded, method="POST", headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise ValueError("Google 翻译请求失败（HTTP %s）：%s" % (exc.code, detail[:500])) from exc
    translated = payload.get("data", {}).get("translations", [{}])[0].get("translatedText", "")
    positive = html.unescape(str(translated)).strip()
    return {"positive": positive, "negative": "",
            "sections": {"naturalLanguage": positive}}


CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)
MAX_BATCH_TASKS = 50
MAX_BATCH_IMAGES = 200


def expand_generation_jobs(jobs) -> list[dict]:
    """Expand logical panel tasks into independent ComfyUI prompt jobs."""
    if not isinstance(jobs, list) or not jobs or len(jobs) > MAX_BATCH_TASKS:
        raise ValueError(f"任务队列必须包含 1-{MAX_BATCH_TASKS} 个逻辑任务。")
    expanded: list[dict] = []
    for task_index, job in enumerate(jobs):
        if not isinstance(job, dict):
            raise ValueError("第 %d 个任务格式不正确。" % (task_index + 1))
        raw_count = job.get("batchCount", 1)
        try:
            image_count = int(raw_count)
        except (TypeError, ValueError):
            raise ValueError("第 %d 个任务的生成数量无效。" % (task_index + 1)) from None
        if not 1 <= image_count <= 16:
            raise ValueError("第 %d 个任务的生成数量必须为 1-16。" % (task_index + 1))
        for image_index in range(image_count):
            item = dict(job)
            item.pop("batchCount", None)
            seed_text = str(item.get("seed", "") or "").strip()
            if re.fullmatch(r"\d+", seed_text):
                # Match the immediate-generation path: a fixed seed increments
                # once per image, while -1/random is independently randomized.
                item["seed"] = str((int(seed_text) + image_index) % (2**63 - 1))
            expanded.append({"task_index": task_index, "image_index": image_index,
                             "image_count": image_count, "payload": item})
    if len(expanded) > MAX_BATCH_IMAGES:
        raise ValueError(f"任务队列展开后共 {len(expanded)} 张，超过 {MAX_BATCH_IMAGES} 张上限；"
                         "请拆成两次发送。")
    return expanded


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, body: dict, status=HTTPStatus.OK):
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return True
        except CLIENT_DISCONNECT_ERRORS:
            # Reloading the panel or cancelling fetch() closes the browser socket.
            # This is normal and must not be converted into a second error response.
            return False

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/":
                content = (ROOT / "index.html").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif parsed.path == "/pose-editor-workflow.json":
                content = (ROOT / "pose_editor_workflow.json").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=OpenPose_Skeleton_Editor.json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif parsed.path == "/api/models":
                info = comfy_json("/object_info")
                all_checkpoints = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
                checkpoints, unavailable_checkpoints = [], []
                for checkpoint in all_checkpoints:
                    issue = checkpoint_issue(checkpoint)
                    if issue:
                        unavailable_checkpoints.append({"name": checkpoint, "reason": issue})
                    else:
                        checkpoints.append(checkpoint)
                loras = info["LoraLoader"]["input"]["required"]["lora_name"][0]
                controlnets = info.get("ControlNetLoader", {}).get("input", {}).get("required", {}).get("control_net_name", [[]])[0]
                diffusion_models = info.get("UNETLoader", {}).get("input", {}).get("required", {}).get("unet_name", [[]])[0]
                anima_models = [name for name in diffusion_models if is_anima_model(name)]
                krea2_models = [name for name in diffusion_models if is_krea2_model(name)]
                text_encoders = info.get("CLIPLoader", {}).get("input", {}).get("required", {}).get("clip_name", [[]])[0]
                vaes = info.get("VAELoader", {}).get("input", {}).get("required", {}).get("vae_name", [[]])[0]
                anima_ready = ANIMA_TEXT_ENCODER in text_encoders and ANIMA_VAE in vaes
                krea2_ready = KREA2_TEXT_ENCODER in text_encoders and KREA2_VAE in vaes
                sampling_profiles = {name: model_sampling_profile(name)
                                     for name in checkpoints + anima_models + krea2_models}
                self.send_json({"checkpoints": checkpoints, "unavailable_checkpoints": unavailable_checkpoints,
                                "anima_models": anima_models, "anima_ready": anima_ready,
                                "krea2_models": krea2_models, "krea2_ready": krea2_ready,
                                "anima_tag_count": len(ANIMA_TAG_INDEX), "loras": loras,
                                "loraMeta": lora_meta_map(loras), "controlnets": controlnets,
                                "samplingProfiles": sampling_profiles})
            elif parsed.path == "/api/status":
                queue = comfy_json("/queue")
                self.send_json({"running": len(queue.get("queue_running", [])), "pending": len(queue.get("queue_pending", []))})
            elif parsed.path == "/api/tags":
                query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
                self.send_json({"tags": search_tags(query[:100]), "total": len(TAG_INDEX)})
            elif parsed.path == "/api/lora-notes":
                self.send_json({"notes": load_lora_notes()})
            elif parsed.path == "/api/lora-sidecars":
                self.send_json({"entries": load_lora_sidecars()})
            elif parsed.path == "/api/output-images":
                self.send_json({"entries": list_output_images()})
            elif parsed.path == "/api/history":
                job = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
                if not re.fullmatch(r"[0-9a-f-]{36}", job):
                    raise ValueError("无效任务编号。")
                self.send_json(comfy_json("/history/" + job))
            elif parsed.path == "/output":
                name = urllib.parse.parse_qs(parsed.query).get("name", [""])[0]
                safe_name = Path(name).name
                file = OUTPUT / safe_name
                if safe_name != name or not file.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                content = file.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except CLIENT_DISCONNECT_ERRORS:
            return
        except (urllib.error.URLError, TimeoutError) as exc:
            self.send_json({"error": "无法连接 ComfyUI：" + str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self):
        if self.path not in {"/api/generate", "/api/generate-batch", "/api/preview-pose", "/api/translate", "/api/google-translate", "/api/lora-notes", "/api/lora-import-sidecar", "/api/upload-pose", "/api/anima-tags", "/api/anima-preflight", "/api/illustrious-preflight", "/api/prompt-compile", "/api/read-image", "/api/read-output", "/api/upload-inpaint", "/api/krea2-preflight", "/api/preview-color"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            if self.path in {"/api/upload-pose", "/api/read-image", "/api/upload-inpaint"}:
                size = bounded(self.headers.get("Content-Length"), 0, 0, 30_000_000)
                if not size:
                    raise ValueError("图片上传为空。")
                body = self.rfile.read(size)
                if self.path == "/api/upload-pose":
                    self.send_json({"name": save_pose_upload(self.headers.get("Content-Type", ""), body)})
                elif self.path == "/api/upload-inpaint":
                    self.send_json(save_inpaint_upload(self.headers.get("Content-Type", ""), body))
                else:
                    content = extract_image_upload(self.headers.get("Content-Type", ""), body)
                    self.send_json(parse_generation_info(content))
                return
            size = bounded(self.headers.get("Content-Length"), 0, 0, 50_000_000)
            data = json.loads(self.rfile.read(size).decode("utf-8"))
            if self.path == "/api/read-output":
                name = str(data.get("name", "") or "").strip()
                safe_name = Path(name).name
                file = OUTPUT / safe_name
                if safe_name != name or not file.is_file():
                    raise ValueError("找不到该输出图片。")
                self.send_json(parse_generation_info(file.read_bytes()))
            if self.path == "/api/preview-color":
                name = str(data.get("name", "") or "").strip()
                safe_name = Path(name).name
                file = OUTPUT / safe_name
                if safe_name != name or not file.is_file():
                    raise ValueError("找不到该输出图片。")
                rendered = apply_color_correction(file.read_bytes(), data.get("params") or {})
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Content-Length", str(len(rendered)))
                self.end_headers()
                self.wfile.write(rendered)
                return
            if self.path == "/api/translate":
                self.send_json(ai_translate(data))
            elif self.path == "/api/google-translate":
                self.send_json(google_translate(data))
            elif self.path == "/api/anima-tags":
                self.send_json(validate_anima_tags(data))
            elif self.path == "/api/anima-preflight":
                self.send_json(anima_preflight(data))
            elif self.path == "/api/krea2-preflight":
                self.send_json(krea2_preflight(data))
            elif self.path == "/api/illustrious-preflight":
                self.send_json(illustrious_preflight(data))
            elif self.path == "/api/prompt-compile":
                self.send_json(compile_prompt(data))
            elif self.path == "/api/preview-pose":
                self.send_json(comfy_json("/prompt", "POST", build_pose_preview_workflow(data)))
            elif self.path == "/api/lora-notes":
                save_lora_notes(data.get("notes", {}))
                self.send_json({"ok": True})
            elif self.path == "/api/lora-import-sidecar":
                self.send_json(import_lora_sidecar(str(data.get("name", ""))))
            elif self.path == "/api/generate-batch":
                jobs = data.get("jobs")
                expanded = expand_generation_jobs(jobs)
                # Build every workflow before submitting the first one. This
                # prevents a malformed late task from leaving a partially sent
                # queue that the panel can no longer account for.
                prepared = [{**item, "workflow": build_workflow(item["payload"])}
                            for item in expanded]
                submitted = []
                for index, item in enumerate(prepared):
                    submitted.append({"index": index, "task_index": item["task_index"],
                                      "image_index": item["image_index"],
                                      "image_count": item["image_count"],
                                      "prompt_id": comfy_json("/prompt", "POST", item["workflow"]).get("prompt_id")})
                self.send_json({"jobs": submitted, "logical_tasks": len(jobs),
                                "total_images": len(submitted)})
            else:
                self.send_json(comfy_json("/prompt", "POST", build_workflow(data)))
        except CLIENT_DISCONNECT_ERRORS:
            return
        except urllib.error.HTTPError as exc:
            self.send_json({"error": exc.read().decode("utf-8", "replace")}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


if __name__ == "__main__":
    print(f"Easy Panel: http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
