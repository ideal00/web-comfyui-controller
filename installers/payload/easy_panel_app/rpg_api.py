"""RPGBox-facing visual API helpers.

This module deliberately contains no HTTP-server or ComfyUI imports.  It turns a
small, stable RPG scene description into the existing Easy Panel generation
payload, so the mobile client does not need to know ComfyUI node ids or model-
specific prompt rules.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

from easy_panel_app.config import ROOT
from easy_panel_app.prompt_utils import unique_prompt_terms

RPG_API_VERSION = 2
RPG_PROFILE_FILE = ROOT / "rpg_visual_profiles.json"
RPG_JOB_FILE = ROOT / "rpg_jobs.json"
# Easy Panel writes the hi-res first pass as "<prefix>_base_00001_.png" so the
# desktop panel can pair 首采 / 二采; mobile results list only finished images.
HIRES_BASE_MARKER = "_base_"
_RPG_LOCK = threading.RLock()

# One server-owned quality contract for the phase-one client.  The browser
# may use a compatibility fallback, but /api/rpg/models is the authoritative
# source whenever the RPG bridge is available.
RPG_QUALITY_PROFILES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "fast": {
        "Illustrious": {"steps": 20, "cfg": 5.0, "sampler": "euler_ancestral", "scheduler": "normal"},
        "Anima": {"steps": 30, "cfg": 4.5, "sampler": "euler", "scheduler": "simple"},
    },
    "balanced": {
        "Illustrious": {"steps": 24, "cfg": 6.0, "sampler": "euler_ancestral", "scheduler": "normal"},
        "Anima": {"steps": 34, "cfg": 4.8, "sampler": "er_sde", "scheduler": "simple"},
    },
    "detailed": {
        "Illustrious": {"steps": 28, "cfg": 6.5, "sampler": "euler_ancestral", "scheduler": "normal"},
        "Anima": {"steps": 42, "cfg": 5.0, "sampler": "er_sde", "scheduler": "simple"},
    },
}

DEFAULT_PROFILE_DOCUMENT: Dict[str, Any] = {
    "version": RPG_API_VERSION,
    "defaults": {
        "model": "",
        "width": 832,
        "height": 1216,
        "safetyLevel": "safe",
        "style": "",
        "negative": "",
        "regional": False,
        "pollIntervalMs": 1800,
    },
    "characters": {},
}


def _deep_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def load_rpg_profiles() -> Dict[str, Any]:
    """Return normalized mobile visual profiles, creating the file if missing."""

    with _RPG_LOCK:
        if not RPG_PROFILE_FILE.exists():
            _atomic_json_write(RPG_PROFILE_FILE, DEFAULT_PROFILE_DOCUMENT)
        try:
            raw = json.loads(RPG_PROFILE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
        characters = raw.get("characters") if isinstance(raw.get("characters"), dict) else {}
        merged_defaults = dict(DEFAULT_PROFILE_DOCUMENT["defaults"])
        merged_defaults.update(defaults)
        return {
            "version": RPG_API_VERSION,
            "defaults": merged_defaults,
            "characters": characters,
        }


def save_rpg_profiles(document: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(document, Mapping):
        raise ValueError("RPG 视觉配置必须是 JSON 对象。")
    defaults = document.get("defaults") if isinstance(document.get("defaults"), Mapping) else {}
    characters = document.get("characters") if isinstance(document.get("characters"), Mapping) else {}
    if len(characters) > 500:
        raise ValueError("角色视觉配置不能超过 500 个。")
    normalized = {
        "version": RPG_API_VERSION,
        "defaults": {**DEFAULT_PROFILE_DOCUMENT["defaults"], **dict(defaults)},
        "characters": dict(characters),
    }
    with _RPG_LOCK:
        _atomic_json_write(RPG_PROFILE_FILE, normalized)
    return normalized


def token_required() -> bool:
    return bool(os.environ.get("EASY_PANEL_RPG_TOKEN", "").strip())


def check_rpg_token(provided: str) -> bool:
    expected = os.environ.get("EASY_PANEL_RPG_TOKEN", "").strip()
    if not expected:
        return True
    return str(provided or "").strip() == expected


def _text(value: Any, limit: int = 1000) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise ValueError("RPG 视觉字段过长，请缩短场景描述。")
    return text


def _number(value: Any, fallback: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(maximum, max(minimum, number))


def _integer(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(maximum, max(minimum, number))


def _safe_id(value: Any, fallback: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_-]+", "_", str(value or "").strip()).strip("_")
    return (text[:48] or fallback)


def safe_rpg_prefix(game_id: Any = "", scene_id: Any = "") -> str:
    game = _safe_id(game_id, "game")
    scene = _safe_id(scene_id, str(int(time.time())))
    return "RPGBox_%s_%s" % (game, scene)


def _normalize_loras(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    result: List[Dict[str, Any]] = []
    seen = set()
    for item in items[:24]:
        if isinstance(item, str):
            name, weight = item.strip(), 0.8
        elif isinstance(item, Mapping):
            name = _text(item.get("name"), 300)
            weight = _number(item.get("weight"), 0.8, 0.0, 1.5)
        else:
            continue
        if not name:
            continue
        key = name.replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        result.append({"name": name, "weight": weight})
    return result


def _merge_loras(*collections: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for collection in collections:
        for item in collection:
            name = _text(item.get("name"), 300)
            if not name:
                continue
            key = name.replace("\\", "/").lower()
            if key not in merged:
                order.append(key)
            merged[key] = {"name": name, "weight": _number(item.get("weight"), 0.8, 0.0, 1.5)}
    return [merged[key] for key in order]


def _normalize_style_loras(items: Any, model_family: str = "") -> List[Dict[str, Any]]:
    """Normalize the optional chat-scoped style layer without changing person LoRAs."""

    rows = _normalize_loras(items)
    if not rows:
        return []
    requested_family = str(model_family or "").strip().lower()
    if requested_family and requested_family not in {"illustrious", "anima"}:
        raise ValueError("画风 LoRA 的底模族未确认，已阻止提交。")
    return rows


def rpg_quality_profiles() -> Dict[str, Dict[str, Dict[str, Any]]]:
    return _deep_copy(RPG_QUALITY_PROFILES)


def _model_candidates(model_catalog: Mapping[str, Any]) -> List[str]:
    values: List[str] = []
    for key in ("checkpoints", "anima_models", "krea2_models"):
        raw = model_catalog.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item).strip())
    return values


def choose_rpg_model(requested: Any, defaults: Mapping[str, Any], model_catalog: Mapping[str, Any]) -> str:
    requested_name = _text(requested or defaults.get("model"), 500)
    candidates = _model_candidates(model_catalog)
    if requested_name:
        if not candidates or requested_name in candidates:
            return requested_name
        requested_base = requested_name.replace("\\", "/").split("/")[-1].lower()
        for candidate in candidates:
            if candidate.replace("\\", "/").split("/")[-1].lower() == requested_base:
                return candidate
        raise ValueError("RPG 请求的基础模型当前不可用：%s" % requested_name)
    preferences = ("waiillustrious", "spectacular", "illustrious", "ilxl", "milmu")
    lowered = [(candidate, candidate.replace("\\", "/").lower()) for candidate in candidates]
    for needle in preferences:
        for candidate, name in lowered:
            if needle in name:
                return candidate
    if candidates:
        return candidates[0]
    raise ValueError("没有检测到可用于 RPG 生图的基础模型。")


def _character_profile(characters: Mapping[str, Any], character: Mapping[str, Any]) -> Mapping[str, Any]:
    key = _text(character.get("id") or character.get("name"), 120)
    direct = characters.get(key)
    if isinstance(direct, Mapping):
        return direct
    key_lower = key.lower()
    for profile_key, value in characters.items():
        if str(profile_key).lower() == key_lower and isinstance(value, Mapping):
            return value
        if isinstance(value, Mapping) and str(value.get("name", "")).lower() == key_lower:
            return value
    return {}


def _without_prompt_terms(base: Any, remove: Any) -> str:
    blocked = {part.strip().casefold() for part in str(remove or "").split(",") if part.strip()}
    return ", ".join(part.strip() for part in str(base or "").split(",")
                       if part.strip() and part.strip().casefold() not in blocked)


def _character_prompt(character: Mapping[str, Any], profile: Mapping[str, Any]) -> Dict[str, Any]:
    char_id = _text(character.get("id") or character.get("name"), 120)
    display_name = _text(character.get("name") or profile.get("name") or char_id, 120)
    mode = _text(profile.get("mode"), 40).lower() or "lora"
    if mode == "plain":
        # Plain-role profiles are an explicit user choice.  They must never
        # turn the character id/name into a synthetic LoRA trigger.
        trigger = ""
        base_appearance = _text(profile.get("plainAppearancePrompt")
                                or profile.get("plain_appearance_prompt")
                                or profile.get("baseAppearance")
                                or profile.get("base_appearance")
                                or profile.get("appearance"), 1200)
    else:
        trigger = _text(character.get("trigger") or profile.get("trigger") or char_id, 300)
        base_appearance = _text(profile.get("baseAppearance") or profile.get("base_appearance")
                                or profile.get("appearance"), 1200)
    expression = _text(character.get("expression"), 300)
    pose = _text(character.get("pose"), 500)
    action = _text(character.get("action"), 500)
    held_items = _text(character.get("heldItems") or character.get("held_items"), 800)
    extra = _text(character.get("prompt") or character.get("extraPrompt"), 1000)
    outfit_id = _text(character.get("outfit") or profile.get("default_outfit") or "default", 120)
    outfits = profile.get("outfits") if isinstance(profile.get("outfits"), Mapping) else {}
    variants = profile.get("appearance_variants") if isinstance(profile.get("appearance_variants"), Mapping) else {}
    variant = variants.get(outfit_id) if isinstance(variants.get(outfit_id), Mapping) else {}
    variant_appearance = _text(variant.get("appearancePresetPrompt") or variant.get("appearance_preset_prompt"), 1200)
    appearance = unique_prompt_terms(
        _without_prompt_terms(variant_appearance or base_appearance, variant.get("appearanceRemove")
                              or variant.get("appearance_remove")),
        _text(variant.get("appearanceAdd") or variant.get("appearance_add"), 800),
        "" if mode == "plain" else _text(character.get("appearance"), 1200),
    )
    outfit = _text(character.get("outfitPrompt"), 1200)
    if not outfit and variant:
        outfit = _text(variant.get("clothingPrompt") or variant.get("clothing_prompt"), 1200)
    if not outfit and outfit_id and outfit_id in outfits:
        outfit = _text(outfits.get(outfit_id), 1200)
    subject = unique_prompt_terms(trigger, appearance, outfit, expression, pose, action, held_items, extra)
    profile_loras = [] if mode == "plain" else _normalize_loras(profile.get("loras"))
    inline_loras = _normalize_loras(character.get("loras"))
    if mode == "plain":
        inline_loras = []
    return {
        "id": char_id or display_name,
        "name": display_name or char_id,
        "gender": _text(character.get("gender") or profile.get("gender"), 40).lower(),
        "trigger": trigger,
        "appearance": appearance,
        "outfit": outfit,
        "appearance_variant_id": outfit_id,
        "appearance_preset_id": _text(variant.get("appearancePresetId") or variant.get("appearance_preset_id"), 120),
        "held_items": held_items,
        "expression": expression,
        "pose": pose,
        "action": action,
        "prompt": subject,
        "mode": mode,
        "loras": _merge_loras(profile_loras, inline_loras),
        "style": unique_prompt_terms(_text(profile.get("style"), 800), _text(character.get("style"), 800)),
    }


def _subject_count_prompt(characters: List[Dict[str, Any]]) -> str:
    if not characters:
        return ""
    if len(characters) == 1:
        gender = characters[0].get("gender")
        if gender in {"male", "man", "boy"}:
            return "1boy, solo"
        return "1girl, solo"
    female = sum(item.get("gender") not in {"male", "man", "boy"} for item in characters)
    male = len(characters) - female
    parts: List[str] = []
    if female:
        parts.append("%dgirls" % female if female > 1 else "1girl")
    if male:
        parts.append("%dboys" % male if male > 1 else "1boy")
    return ", ".join(parts)


def _auto_regions(characters: List[Dict[str, Any]], enabled: bool) -> List[Dict[str, Any]]:
    """Create the panel's existing two-person Regional Prompting layout."""

    if not enabled or len(characters) != 2:
        return []
    positions = ((0.0, 0.54, "character on the left"), (0.46, 0.54, "character on the right"))
    result = []
    for character, (x, width, position) in zip(characters, positions):
        lora = character["loras"][0]["name"] if character.get("loras") else ""
        result.append({
            "name": character.get("name") or character.get("id") or "Character",
            "subject": "1boy" if character.get("gender") in {"male", "man", "boy"} else "1girl",
            "lora": lora,
            "prompt": unique_prompt_terms(position, character.get("prompt", "")),
            "x": x,
            "y": 0.0,
            "width": width,
            "height": 1.0,
            "strength": 1.0,
        })
    return result


def build_rpg_payload(request: Mapping[str, Any], model_catalog: Optional[Mapping[str, Any]] = None,
                      profile_document: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Compile a stable RPGBox scene description into an Easy Panel payload."""

    if not isinstance(request, Mapping):
        raise ValueError("RPG 生图请求必须是 JSON 对象。")
    visual = request.get("visual") if isinstance(request.get("visual"), Mapping) else request
    generation = request.get("generation") if isinstance(request.get("generation"), Mapping) else {}
    client = request.get("client") if isinstance(request.get("client"), Mapping) else {}
    profiles = dict(profile_document or load_rpg_profiles())
    defaults = profiles.get("defaults") if isinstance(profiles.get("defaults"), Mapping) else {}
    profile_characters = profiles.get("characters") if isinstance(profiles.get("characters"), Mapping) else {}
    model_catalog = model_catalog or {}

    raw_characters = visual.get("characters")
    if not isinstance(raw_characters, list):
        ids = visual.get("characterIds") if isinstance(visual.get("characterIds"), list) else []
        raw_characters = [{"id": item} for item in ids]
    if len(raw_characters) > 6:
        raise ValueError("单张 RPG 场景最多支持 6 个角色。")
    characters = []
    for raw in raw_characters:
        if isinstance(raw, str):
            raw = {"id": raw}
        if not isinstance(raw, Mapping):
            continue
        characters.append(_character_prompt(raw, _character_profile(profile_characters, raw)))

    model = choose_rpg_model(generation.get("model"), defaults, model_catalog)
    model_key = model.replace("\\", "/").lower()
    family = "anima" if "anima" in model_key else "illustrious"
    quality_id = str(generation.get("quality") or "balanced").strip().lower()
    if quality_id not in RPG_QUALITY_PROFILES:
        quality_id = "balanced"
    quality = RPG_QUALITY_PROFILES[quality_id]["Anima" if family == "anima" else "Illustrious"]
    width = _integer(generation.get("width", defaults.get("width")), 832, 512, 1920)
    height = _integer(generation.get("height", defaults.get("height")), 1216, 512, 1920)
    subject_count = _subject_count_prompt(characters)
    triggers = ", ".join(item.get("trigger", "") for item in characters if item.get("trigger"))
    appearances = ", ".join(item.get("appearance", "") for item in characters if item.get("appearance"))
    outfits = ", ".join(item.get("outfit", "") for item in characters if item.get("outfit"))
    poses = ", ".join(unique_prompt_terms(item.get("expression", ""), item.get("pose", ""), item.get("action", ""), item.get("held_items", ""))
                      for item in characters)
    styles = ", ".join(item.get("style", "") for item in characters if item.get("style"))

    location = _text(visual.get("location"), 800)
    time_of_day = _text(visual.get("time"), 300)
    scene = _text(visual.get("scene") or visual.get("environment"), 1200)
    weather = _text(visual.get("weather"), 300)
    lighting = unique_prompt_terms(_text(visual.get("lighting"), 800), _text(time_of_day, 300))
    shot = _text(visual.get("shot") or visual.get("framing"), 300)
    camera = _text(visual.get("cameraAngle") or visual.get("camera"), 300)
    composition = unique_prompt_terms(shot, camera, _text(visual.get("composition"), 500))
    mood = _text(visual.get("mood"), 500)
    relation = _text(visual.get("relation") or visual.get("naturalLanguage"), 1200)
    held_items = ", ".join(item.get("held_items", "") for item in characters if item.get("held_items"))
    global_style = unique_prompt_terms(_text(defaults.get("style"), 1000), styles,
                                       _text(visual.get("style"), 1000), _text(generation.get("style"), 1000))

    model_family = "anima" if family == "anima" else "illustrious"
    raw_style_loras = generation.get("styleLoras")
    if raw_style_loras is None:
        raw_style_loras = visual.get("styleLoras")
    style_loras = _normalize_style_loras(raw_style_loras, generation.get("styleFamily"))
    requested_style_family = _text(generation.get("styleFamily") or visual.get("styleFamily"), 32).lower()
    if requested_style_family and requested_style_family != model_family:
        raise ValueError("画风 LoRA 与当前基础模型底模族不兼容；请切换同族画风或关闭画风。")

    prompt_sections = {
        "subject": unique_prompt_terms(subject_count, triggers),
        "appearance": appearances,
        "clothing": outfits,
        "pose": poses,
        "composition": composition,
        "scene": unique_prompt_terms(location, scene, weather),
        "lighting": lighting,
        "style": global_style,
        "naturalLanguage": unique_prompt_terms(relation, mood, held_items),
        "manual": _text(visual.get("extraPrompt"), 1200),
    }

    all_character_loras: List[Dict[str, Any]] = []
    for character in characters:
        all_character_loras.extend(character.get("loras") or [])
    generation_loras = _normalize_loras(generation.get("loras"))
    loras = _merge_loras(all_character_loras, style_loras, generation_loras)
    regional = bool(generation.get("regional", defaults.get("regional", False)))
    regions = _auto_regions(characters, regional)

    safety = _text(generation.get("safetyLevel", defaults.get("safetyLevel", "safe")), 40) or "safe"
    payload: Dict[str, Any] = {
        "model": model,
        "quality": quality_id,
        "qualityProfile": _deep_copy(quality),
        "loras": loras,
        "characterLoras": _deep_copy(all_character_loras),
        "styleLoras": _deep_copy(style_loras),
        "styleFamily": requested_style_family or (model_family if style_loras else ""),
        "prompt": "",
        "negative": unique_prompt_terms(_text(defaults.get("negative"), 1600), _text(generation.get("negative"), 1600)),
        "promptSections": prompt_sections,
        "promptMode": _text(generation.get("promptMode"), 40) or "style_test",
        "safetyLevel": safety,
        "mature": bool(generation.get("mature", False)),
        "width": width,
        "height": height,
        "seed": generation.get("seed", -1),
        "regions": regions,
        "regionGlobalPrompt": unique_prompt_terms(_text(visual.get("groupAction"), 600), relation),
        "promptAutomation": generation.get("promptAutomation") if isinstance(generation.get("promptAutomation"), Mapping) else {},
        "guidance": generation.get("guidance") if isinstance(generation.get("guidance"), Mapping) else {"mode": "off"},
        "illustriousMode": _text(generation.get("illustriousMode"), 40) or "precision",
        "filenamePrefix": safe_rpg_prefix(client.get("gameId") or request.get("gameId"),
                                           client.get("sceneId") or request.get("sceneId")),
    }
    for key in ("steps", "cfg", "sampler", "scheduler", "hiresScale", "hiresDenoise",
                "hiresSteps", "hiresCfg", "hiresSampler", "hiresScheduler",
                "hiresPromptMode", "hiresPositive", "hiresNegative", "hiresCompositionLock"):
        if key in generation and generation.get(key) not in (None, ""):
            payload[key] = generation.get(key)
    for key in ("steps", "cfg", "sampler", "scheduler"):
        if key not in payload:
            payload[key] = quality[key]
    for key in ("vae", "modelEnhancement", "transparentBackground", "colorCorrection", "outputEnhancement"):
        value = generation.get(key)
        if isinstance(value, Mapping):
            payload[key] = dict(value)
    return payload


def record_rpg_job(prompt_id: str, request: Mapping[str, Any], payload: Mapping[str, Any],
                   snapshot_id: str = "") -> Dict[str, Any]:
    client = dict(request.get("client") or {}) if isinstance(request.get("client"), Mapping) else {}
    request_id = _safe_id(client.get("requestId") or request.get("requestId"), "")
    entry = {
        "prompt_id": prompt_id,
        "snapshot_id": snapshot_id,
        "request_id": request_id,
        "created_at": int(time.time() * 1000),
        "client": client,
        "filename_prefix": payload.get("filenamePrefix", "RPGBox"),
        "model": payload.get("model", ""),
        "character_loras": _deep_copy(payload.get("characterLoras") or []),
        "style_loras": _deep_copy(payload.get("styleLoras") or []),
    }
    with _RPG_LOCK:
        rows = _load_rpg_jobs_unlocked()
        rows = [row for row in rows if row.get("prompt_id") != prompt_id]
        rows.append(entry)
        if len(rows) > 1000:
            rows = rows[-1000:]
        _atomic_json_write(RPG_JOB_FILE, rows)
    return entry


def _load_rpg_jobs_unlocked() -> List[Dict[str, Any]]:
    if not RPG_JOB_FILE.exists():
        return []
    try:
        data = json.loads(RPG_JOB_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def find_rpg_job(prompt_id: str) -> Dict[str, Any]:
    with _RPG_LOCK:
        for row in reversed(_load_rpg_jobs_unlocked()):
            if row.get("prompt_id") == prompt_id:
                return dict(row)
    return {}


def find_rpg_job_by_request_id(request_id: str) -> Dict[str, Any]:
    """Find the newest job submitted with a stable mobile request id."""

    safe = _safe_id(request_id, "")
    if not safe:
        return {}
    with _RPG_LOCK:
        for row in reversed(_load_rpg_jobs_unlocked()):
            if row.get("request_id") == safe:
                return dict(row)
    return {}


def image_url(filename: str, subfolder: str = "", image_type: str = "output") -> str:
    from urllib.parse import urlencode

    query = {"name": Path(str(filename or "")).name, "type": str(image_type or "output")}
    clean_subfolder = str(subfolder or "").replace("\\", "/").strip("/")
    if clean_subfolder:
        query["subfolder"] = clean_subfolder
    return "/api/rpg/image?" + urlencode(query)


def history_to_rpg_status(prompt_id: str, history: Mapping[str, Any]) -> Dict[str, Any]:
    job = history.get(prompt_id) if isinstance(history, Mapping) else None
    metadata = find_rpg_job(prompt_id)
    result: Dict[str, Any] = {
        "api_version": RPG_API_VERSION,
        "job_id": prompt_id,
        "prompt_id": prompt_id,
        "status": "queued",
        "images": [],
        "meta": metadata,
    }
    if not isinstance(job, Mapping):
        return result
    status = job.get("status") if isinstance(job.get("status"), Mapping) else {}
    if str(status.get("status_str", "")).lower() == "error":
        result["status"] = "error"
        messages = status.get("messages")
        result["error"] = messages if isinstance(messages, list) else "ComfyUI 执行失败。"
        return result
    outputs = job.get("outputs") if isinstance(job.get("outputs"), Mapping) else {}
    images: List[Dict[str, Any]] = []
    hi_res_base: List[Dict[str, Any]] = []
    for output in outputs.values():
        if not isinstance(output, Mapping):
            continue
        for image in output.get("images") or []:
            if not isinstance(image, Mapping):
                continue
            name = Path(str(image.get("filename", ""))).name
            if not name:
                continue
            entry = {
                "filename": name,
                "subfolder": str(image.get("subfolder", "")),
                "type": str(image.get("type", "output")),
                "url": image_url(name, str(image.get("subfolder", "")), str(image.get("type", "output"))),
            }
            # The hi-res first pass is written for the desktop 首采 / 二采
            # comparison; the mobile result list only shows finished images.
            if HIRES_BASE_MARKER in name:
                hi_res_base.append(entry)
            else:
                images.append(entry)
    images = images or hi_res_base
    if images:
        result["status"] = "completed"
        result["images"] = images
    else:
        result["status"] = "running"
    return result


__all__ = [
    "RPG_API_VERSION",
    "RPG_QUALITY_PROFILES",
    "RPG_PROFILE_FILE",
    "build_rpg_payload",
    "check_rpg_token",
    "choose_rpg_model",
    "find_rpg_job",
    "find_rpg_job_by_request_id",
    "history_to_rpg_status",
    "image_url",
    "load_rpg_profiles",
    "record_rpg_job",
    "rpg_quality_profiles",
    "safe_rpg_prefix",
    "save_rpg_profiles",
    "token_required",
]
