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
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    # importlib-based callers do not always add the loaded file's directory.
    # Keep the legacy single-file import contract while implementation modules
    # move into ``easy_panel_app``.
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.config import (
    ANIMA_TAG_DATA,
    CHECKPOINT_DIR,
    COMFY,
    COMFY_INPUT,
    COMFY_MODELS,
    HOST,
    LORA_DIR,
    LORA_NOTES,
    OUTPUT,
    PORT,
    ROOT,
    SETTINGS,
    TAG_DATA,
)
from easy_panel_app.integrations.ai import (
    ai_auth_headers,
    ai_prompt_system,
    ai_response_text,
    ai_translate,
    build_translation_user_message,
    classify_english_prompt,
    google_translate,
    illustrious_quality_prefix,
    parse_ai_json,
    translation_prefix,
    validated_ai_endpoint,
)
from easy_panel_app.integrations.comfy_client import comfy_json
from easy_panel_app.image_ops import apply_color_correction
from easy_panel_app.lora_sidecars import atomic_write_notes, merge_note, parse_lora_sidecar, read_text_smart
from easy_panel_app.media_storage import (
    extract_image_upload,
    list_output_images,
    prepare_generation_image,
    save_inpaint_upload,
    save_pose_upload,
    validate_input_image,
)
from easy_panel_app.metadata import (
    parse_a1111_parameters,
    parse_comfyui_prompt,
    parse_comfyui_ui_workflow,
    parse_generation_info,
    parse_novelai_comment,
)
from easy_panel_app.numeric import bounded
from easy_panel_app.prompt_utils import (
    normalize_prompt_key,
    normalized_safety_level,
    split_prompt_terms,
    unique_prompt_terms,
)
from easy_panel_app.validation import checkpoint_issue
from easy_panel_app.queueing import (
    MAX_BATCH_IMAGES,
    MAX_BATCH_TASKS,
    expand_generation_jobs,
)

TAG_CATEGORIES = {0: "通用", 1: "画师", 3: "作品", 4: "角色", 5: "元数据"}
ANIMA_TEXT_ENCODER = "qwen_3_06b_base.safetensors"
ANIMA_VAE = "qwen_image_vae.safetensors"


KREA2_TEXT_ENCODER = "qwen3VL4BAbliteratedComfyui_v10.safetensors"
KREA2_VAE = ANIMA_VAE


# Compatibility exports now resolve through the data-driven model catalog.
# Keeping these names in the top-level module avoids breaking tests and scripts
# that imported the original single-file implementation.
from easy_panel_app.model_profiles import (  # noqa: E402
    anima_sampling_settings,
    illustrious_sampling_settings,
    is_anima_model,
    is_illustrious_model,
    is_krea2_model,
    krea2_sampling_settings,
    model_sampling_profile,
)


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


PROMPT_SECTION_KEYS = ("subject", "appearance", "clothing", "pose", "composition",
                       "scene", "lighting", "style", "manual")
PROMPT_SECTION_LABELS = {
    "subject": "人物与角色", "appearance": "外貌", "clothing": "服装与材质",
    "pose": "姿势", "composition": "构图", "scene": "场景",
    "lighting": "光线", "style": "画风与上色", "manual": "其他补充",
}
MATURE_NEGATIVE_TERMS = ("nsfw", "nude", "nudity", "explicit", "sex", "sexual",
                         "porn", "hentai", "uncensored")


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
    atomic_write_notes(LORA_NOTES, notes)


def load_lora_sidecars() -> dict:
    """Return same-name LoRA .txt files, keyed like ComfyUI's relative LoRA names."""
    if not LORA_DIR.is_dir():
        return {}
    entries: dict[str, dict] = {}
    for text_file in LORA_DIR.rglob("*.txt"):
        if not text_file.with_suffix(".safetensors").is_file():
            continue
        try:
            content = read_text_smart(text_file)
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


def import_lora_sidecar(lora_filename: str) -> dict:
    """Parse the same-name .txt for a LoRA and merge presets into lora_notes.json."""
    requested = str(lora_filename or "").replace("\\", "/").lstrip("/").strip()
    target = Path(requested).name
    if Path(target).suffix.casefold() not in {".safetensors", ".pt", ".ckpt"}:
        raise ValueError("请选择有效的 LoRA 文件。")
    root = LORA_DIR.resolve()
    model_file: Path | None = None
    if requested:
        candidate = (root / Path(requested)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ValueError("LoRA 路径超出 models\\loras。")
        if candidate.is_file() and candidate.suffix.casefold() in {".safetensors", ".pt", ".ckpt"}:
            model_file = candidate
    matches: list[Path] = []
    if model_file is None and LORA_DIR.is_dir():
        matches = [path for path in LORA_DIR.rglob("*")
                   if path.is_file() and path.name.casefold() == target.casefold()
                   and path.suffix.casefold() in {".safetensors", ".pt", ".ckpt"}]
        if len(matches) > 1:
            raise ValueError(f"发现多个同名 LoRA：{target}；请使用包含子目录的完整 LoRA 名称。")
        model_file = matches[0] if matches else None
    if model_file is None:
        raise ValueError(f"未找到 LoRA：{target}")
    txt_file: Path | None = None
    exact_txt = model_file.with_suffix(".txt")
    if exact_txt.is_file():
        txt_file = exact_txt
    if txt_file is None:
        raise ValueError(f"未找到 {target} 的同名 TXT；请把 TXT 放在 models\\loras 下与 LoRA 同名。")
    content = read_text_smart(txt_file)
    parsed = parse_lora_sidecar(content, txt_file.relative_to(LORA_DIR).as_posix())
    notes = load_lora_notes()
    relative_model = model_file.relative_to(LORA_DIR).as_posix()
    duplicate_count = sum(1 for path in LORA_DIR.rglob(target)
                          if path.is_file() and path.name.casefold() == target.casefold())
    note_key = relative_model if "/" in requested or duplicate_count > 1 else target
    existing_note = notes.get(note_key)
    if not isinstance(existing_note, dict):
        existing_note = notes.get(target, {})
    note, _ = merge_note(existing_note if isinstance(existing_note, dict) else {}, parsed)
    notes[note_key] = note
    atomic_write_notes(LORA_NOTES, notes)
    added = [str(item.get("name", "")).strip() for item in parsed.get("outfits", [])
             if str(item.get("name", "")).strip()]
    return {
        "noteKey": note_key,
        "meta": {k: note.get(k, "") for k in ("base_model", "weight", "trigger")},
        "added": added,
        "total": len(note.get("outfits", [])),
    }


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

    vae_options = data.get("vae") or {}
    if not isinstance(vae_options, dict):
        raise ValueError("VAE 设置格式无效。")
    vae_mode = str(vae_options.get("mode", "standard") or "standard")
    if vae_mode not in {"standard", "tiled"}:
        raise ValueError("未知的 VAE 模式。")
    vae_tile_size = bounded(vae_options.get("tileSize"), 512, 256, 1024)
    vae_overlap = bounded(vae_options.get("overlap"), 64, 0, 256)
    if vae_overlap * 4 > vae_tile_size:
        vae_overlap = vae_tile_size // 4

    resolution = sampling_profile.get("resolution") or {}
    minimum_size = int(resolution.get("min", 512))
    maximum_size = int(resolution.get("max", 1920))
    alignment = max(8, int(resolution.get("alignment", 8)))
    width = bounded(data.get("width"), 832, minimum_size, maximum_size)
    height = bounded(data.get("height"), 1216, minimum_size, maximum_size)
    width -= width % alignment
    height -= height % alignment
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

    enhancement = data.get("modelEnhancement") or {}
    if not isinstance(enhancement, dict):
        raise ValueError("模型增强设置格式无效。")
    enhancement_mode = str(enhancement.get("mode", "off") or "off")
    if enhancement_mode not in {"off", "freeu_v2", "cfg_rescale"}:
        raise ValueError("未知的模型增强模式。")
    capabilities = sampling_profile.get("capabilities") or {}
    if enhancement_mode == "freeu_v2":
        if not capabilities.get("freeu_v2"):
            raise ValueError(f"{sampling_profile['label']} 不支持 FreeU V2。")
        enhance_id = alloc()
        nodes[enhance_id] = {
            "class_type": "FreeU_V2",
            "inputs": {
                "model": model_ref,
                "b1": bounded(enhancement.get("b1"), 1.3, 0.0, 10.0, integer=False),
                "b2": bounded(enhancement.get("b2"), 1.4, 0.0, 10.0, integer=False),
                "s1": bounded(enhancement.get("s1"), 0.9, 0.0, 10.0, integer=False),
                "s2": bounded(enhancement.get("s2"), 0.2, 0.0, 10.0, integer=False),
            },
        }
        model_ref = [enhance_id, 0]
    elif enhancement_mode == "cfg_rescale":
        if not capabilities.get("cfg_rescale"):
            raise ValueError("CFG Rescale 仅对当前识别到的 v-pred 模型开放。")
        enhance_id = alloc()
        nodes[enhance_id] = {
            "class_type": "RescaleCFG",
            "inputs": {
                "model": model_ref,
                "multiplier": bounded(enhancement.get("multiplier"), 0.7, 0.0, 1.0,
                                      integer=False),
            },
        }
        model_ref = [enhance_id, 0]

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
        if vae_mode == "tiled":
            nodes[encode_id] = {"class_type": "VAEEncodeTiled", "inputs": {
                "pixels": [load_id, 0], "vae": vae_ref,
                "tile_size": vae_tile_size, "overlap": vae_overlap,
                "temporal_size": 64, "temporal_overlap": 8,
            }}
        else:
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
    if vae_mode == "tiled":
        nodes[decode_id] = {"class_type": "VAEDecodeTiled", "inputs": {
            "samples": sample_ref, "vae": vae_ref,
            "tile_size": vae_tile_size, "overlap": vae_overlap,
            "temporal_size": 64, "temporal_overlap": 8,
        }}
    else:
        nodes[decode_id] = {"class_type": "VAEDecode",
                            "inputs": {"samples": sample_ref, "vae": vae_ref}}

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


CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)


def comfy_websocket_url() -> str:
    comfy_address = urllib.parse.urlparse(COMFY)
    websocket_scheme = "wss" if comfy_address.scheme == "https" else "ws"
    websocket_path = comfy_address.path.rstrip("/") + "/ws"
    return urllib.parse.urlunparse((
        websocket_scheme,
        comfy_address.netloc,
        websocket_path,
        "",
        "",
        "",
    ))


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

    def stream_comfy_progress(self):
        """Relay ComfyUI WebSocket JSON as same-origin server-sent events."""
        try:
            import asyncio
            import aiohttp
        except ImportError:
            self.send_json({"error": "当前 Python 缺少 aiohttp，无法读取实时采样进度。"},
                           HTTPStatus.SERVICE_UNAVAILABLE)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        async def relay():
            # build_workflow() submits prompts with this client_id. ComfyUI
            # routes execution/progress events only to the matching socket.
            client_id = "easy-panel"
            separator = "&" if "?" in comfy_websocket_url() else "?"
            target = comfy_websocket_url() + separator + urllib.parse.urlencode({"clientId": client_id})
            timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=None)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(target, heartbeat=30) as websocket:
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    async for message in websocket:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            encoded = ("data: " + message.data.replace("\n", "") + "\n\n").encode("utf-8")
                            self.wfile.write(encoded)
                            self.wfile.flush()
                        elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break

        try:
            asyncio.run(relay())
        except CLIENT_DISCONNECT_ERRORS:
            return
        except Exception:
            # EventSource reconnects automatically. Avoid writing a second HTTP
            # response after the stream headers have already been sent.
            return

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
            elif parsed.path.startswith("/assets/"):
                asset_root = (ROOT / "web" / "assets").resolve()
                relative = Path(parsed.path.removeprefix("/assets/").replace("/", os.sep))
                asset = (asset_root / relative).resolve()
                if not asset.is_relative_to(asset_root) or not asset.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                content = asset.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
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
            elif parsed.path == "/api/progress-stream":
                self.stream_comfy_progress()
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
                self.send_json({
                    "running": len(queue.get("queue_running", [])),
                    "pending": len(queue.get("queue_pending", [])),
                    "progress_stream": "/api/progress-stream",
                })
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
