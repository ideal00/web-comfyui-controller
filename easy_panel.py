"""A small local-only UI that submits SDXL/Illustrious jobs to ComfyUI."""
from __future__ import annotations

import json
import html
import csv
import bisect
import base64
import hashlib
import hmac
import ipaddress
import io
import mimetypes
import os
import random
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from functools import lru_cache
from http import HTTPStatus
from http.cookies import SimpleCookie
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
    CREATIVE_INDEX_FILE,
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
from easy_panel_app.lora_sidecars import atomic_write_notes, classify_lora_note_outfits, merge_note, parse_lora_sidecar, read_text_smart
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
    merge_hires_prompt,
    normalize_prompt_key,
    normalized_safety_level,
    split_prompt_terms,
    unique_prompt_terms,
)
from easy_panel_app.validation import checkpoint_issue
from easy_panel_app.creative_index import (
    CreativeIndex,
    KNOWN_STATUSES as CREATIVE_INDEX_STATUSES,
    SCHEMA_VERSION as CREATIVE_INDEX_SCHEMA_VERSION,
    SUPPORTED_OPERATIONS as CREATIVE_INDEX_OPERATIONS,
    normalize_operation as normalize_creative_operation,
)
from easy_panel_app.queueing import (
    MAX_BATCH_IMAGES,
    MAX_BATCH_TASKS,
    expand_generation_jobs,
)
from easy_panel_app.rpg_api import (
    RPG_API_VERSION,
    RPG_JOB_FILE,
    build_rpg_payload,
    check_rpg_token,
    choose_rpg_model,
    find_rpg_job,
    find_rpg_job_by_request_id,
    history_to_rpg_status,
    image_url,
    load_rpg_profiles,
    record_rpg_job,
    rpg_quality_profiles,
    save_rpg_profiles,
    token_required,
)
from easy_panel_app.shared_state import (
    MAX_REQUEST_BYTES as SHARED_STATE_MAX_REQUEST_BYTES,
    SHARED_STATE_FILENAME,
    SharedStateStore,
)

TAG_CATEGORIES = {0: "通用", 1: "画师", 3: "作品", 4: "角色", 5: "元数据"}
ANIMA_TEXT_ENCODER = "qwen_3_06b_base.safetensors"
ANIMA_VAE = "qwen_image_vae.safetensors"


KREA2_TEXT_ENCODER = "qwen3VL4BAbliteratedComfyui_v10.safetensors"
KREA2_VAE = ANIMA_VAE
HIRES_UPSCALE_MODEL = "RealESRGAN_x4plus_anime_6B.pth"
HIRES_PROMPT_MODES = ("inherit", "append", "replace")
SEEDVR2_MODEL = "seedvr2_3b_int8_convrot.safetensors"
SEEDVR2_VAE = "seedvr2_ema_vae_fp16.safetensors"
FACE_DETECTOR_MODEL = "bbox/face_yolov8m.pt"
HAND_DETECTOR_MODEL = "bbox/hand_yolov8s.pt"
FOOT_DETECTOR_MODEL = "bbox/foot_yolov8x.pt"
EMBEDDING_EXTENSIONS = {".safetensors", ".pt", ".bin"}
EMBEDDING_NOTES_FILE = PROJECT_DIR / "embedding_notes.json"
SHARED_STATE_FILE = PROJECT_DIR / SHARED_STATE_FILENAME
SHARED_STATE_STORE = SharedStateStore(SHARED_STATE_FILE)
ROUTE1_MAX_WORKING_PIXELS = 2_200_000


def route1_working_dimensions(width: int, height: int,
                              max_pixels: int = ROUTE1_MAX_WORKING_PIXELS) -> tuple[int, int]:
    """Return an aspect-preserving, model-aligned route-1 working size."""
    width, height = int(width), int(height)
    if width <= 0 or height <= 0 or width * height <= max_pixels:
        return width, height
    scale = (max_pixels / (width * height)) ** 0.5
    target_width = max(8, int(width * scale) // 8 * 8)
    target_height = max(8, int(height * scale) // 8 * 8)
    while target_width * target_height > max_pixels:
        if target_width >= target_height:
            target_width = max(8, target_width - 8)
        else:
            target_height = max(8, target_height - 8)
    return target_width, target_height


def prepare_route1_working_assets(image_name: str, mask_name: str,
                                  max_pixels: int = ROUTE1_MAX_WORKING_PIXELS
                                  ) -> tuple[str, str, tuple[int, int], tuple[int, int], bool]:
    """Create aligned background/mask copies for route 1 without touching uploads."""
    try:
        from PIL import Image as _PILImage, ImageOps as _PILImageOps

        image_path, mask_path = COMFY_INPUT / image_name, COMFY_INPUT / mask_name
        with _PILImage.open(image_path) as source:
            source = _PILImageOps.exif_transpose(source)
            original_size = source.size
            working_size = route1_working_dimensions(*original_size, max_pixels=max_pixels)
            if working_size == original_size:
                return image_name, mask_name, original_size, working_size, False
            background = source.convert("RGB").resize(working_size, _PILImage.Resampling.LANCZOS)
        with _PILImage.open(mask_path) as source_mask:
            mask = source_mask.convert("L").resize(working_size, _PILImage.Resampling.LANCZOS)

        working_dir = COMFY_INPUT / "easy_panel"
        working_dir.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        working_image_name = f"easy_panel/route1_work_{token}.png"
        working_mask_name = f"easy_panel/route1_mask_{token}.png"
        background.save(COMFY_INPUT / working_image_name, format="PNG")
        mask.save(COMFY_INPUT / working_mask_name, format="PNG")
        return working_image_name, working_mask_name, original_size, working_size, True
    except Exception as exc:
        raise ValueError("路线1无法自动缩小背景图与蒙版：" + str(exc)) from exc


def prepare_route1_generation_mask(mask_name: str,
                                   working_size: tuple[int, int]) -> tuple[str, int, int]:
    """Add a safety halo around only the head area of a rough character mask."""
    try:
        import cv2
        import numpy as np
        from PIL import Image as _PILImage, ImageChops as _PILImageChops

        with _PILImage.open(COMFY_INPUT / mask_name) as source_mask:
            mask = source_mask.convert("L")
        if mask.size != tuple(working_size):
            mask = mask.resize(tuple(working_size), _PILImage.Resampling.LANCZOS)
        longest_side = max(int(working_size[0]), int(working_size[1]))
        headroom = max(20, min(36, round(longest_side / 64)))
        side_margin = max(24, min(40, round(longest_side / 56)))
        shifted_left = _PILImage.new("L", mask.size, 0)
        shifted_right = _PILImage.new("L", mask.size, 0)
        shifted_left.paste(mask, (-side_margin, 0))
        shifted_right.paste(mask, (side_margin, 0))
        lateral_mask = _PILImageChops.lighter(
            mask, _PILImageChops.lighter(shifted_left, shifted_right)
        )
        bbox = mask.getbbox()
        head_region = _PILImage.new("L", mask.size, 0)
        if bbox:
            left, top, right, bottom = bbox
            mask_height, mask_width = bottom - top, right - left
            head_band_height = max(48, round(min(mask_height * 0.30, mask_width * 0.55)))
            head_band_bottom = min(bottom, top + head_band_height)
            head_region.paste(mask.crop((0, top, mask.width, head_band_bottom)),
                              (0, top))
        kernel_size = headroom * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                           (kernel_size, kernel_size))
        expanded_head = _PILImage.fromarray(
            cv2.dilate(np.asarray(head_region, dtype=np.uint8), kernel), mode="L"
        )
        generation_mask = _PILImageChops.lighter(lateral_mask, expanded_head)

        working_dir = COMFY_INPUT / "easy_panel"
        working_dir.mkdir(parents=True, exist_ok=True)
        generation_name = f"easy_panel/route1_generation_mask_{uuid.uuid4().hex}.png"
        generation_mask.save(COMFY_INPUT / generation_name, format="PNG")
        return generation_name, headroom, side_margin
    except Exception as exc:
        raise ValueError("路线1无法为人物头顶预留生成空间：" + str(exc)) from exc


def prepare_route1_environment_light(image_name: str, mask_name: str) -> tuple[str, dict]:
    """Measure robust local lighting and create an aligned low-frequency light field."""
    try:
        import cv2
        import numpy as np
        from PIL import Image as _PILImage, ImageFilter as _PILImageFilter

        with _PILImage.open(COMFY_INPUT / image_name) as source:
            image = source.convert("RGB")
        with _PILImage.open(COMFY_INPUT / mask_name) as source_mask:
            mask_image = source_mask.convert("L")
        if mask_image.size != image.size:
            mask_image = mask_image.resize(image.size, _PILImage.Resampling.LANCZOS)

        rgb = np.asarray(image, dtype=np.float32) / 255.0
        mask = np.asarray(mask_image, dtype=np.float32) / 255.0
        height, width = mask.shape
        longest = max(width, height)
        near_radius = max(24, min(100, round(longest * 0.045)))
        middle_radius = max(near_radius + 24, min(300, round(longest * 0.14)))
        outside = (mask < 0.08).astype(np.uint8)
        distance = cv2.distanceTransform(outside, cv2.DIST_L2, 5)
        near_selection = (distance > 1) & (distance <= near_radius)
        middle_selection = (distance > near_radius) & (distance <= middle_radius)
        if int(near_selection.sum()) < 128:
            near_selection = outside.astype(bool)
        if int(middle_selection.sum()) < 128:
            middle_selection = outside.astype(bool)

        def robust_pixels(selection):
            pixels = rgb[selection]
            luminance = pixels @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
            saturation = pixels.max(axis=1) - pixels.min(axis=1)
            low, high = np.percentile(luminance, [5, 95])
            keep = (luminance >= low) & (luminance <= high) & (saturation < 0.90)
            if int(keep.sum()) >= 64:
                pixels, luminance = pixels[keep], luminance[keep]
            return pixels, luminance

        near_pixels, near_luminance = robust_pixels(near_selection)
        middle_pixels, middle_luminance = robust_pixels(middle_selection)
        shadow_cut, highlight_cut = np.percentile(middle_luminance, [25, 75])
        shadow_pixels = middle_pixels[middle_luminance <= shadow_cut]
        highlight_pixels = middle_pixels[middle_luminance >= highlight_cut]
        near_rgb = np.median(near_pixels, axis=0)
        middle_rgb = np.median(middle_pixels, axis=0)
        shadow_rgb = np.median(shadow_pixels, axis=0)
        highlight_rgb = np.median(highlight_pixels, axis=0)
        contrast = float(np.percentile(middle_luminance, 90) -
                         np.percentile(middle_luminance, 10))

        fit_selection = near_selection | middle_selection
        ys, xs = np.nonzero(fit_selection)
        values = rgb[ys, xs] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        low, high = np.percentile(values, [5, 95])
        keep = (values >= low) & (values <= high)
        xs, ys, values = xs[keep], ys[keep], values[keep]
        if values.size > 60000:
            stride = max(1, values.size // 60000)
            xs, ys, values = xs[::stride], ys[::stride], values[::stride]
        design = np.column_stack((
            (xs / max(1, width - 1)) * 2 - 1,
            (ys / max(1, height - 1)) * 2 - 1,
            np.ones_like(values),
        ))
        coefficient, *_ = np.linalg.lstsq(design, values, rcond=None)
        gradient_x, gradient_y, base_luminance = (float(value) for value in coefficient)
        gradient_angle = float(np.degrees(np.arctan2(gradient_y, gradient_x)))

        near_blur = image.filter(_PILImageFilter.GaussianBlur(radius=max(12, near_radius * 0.65)))
        middle_blur = image.filter(
            _PILImageFilter.GaussianBlur(radius=max(24, middle_radius * 0.55)))
        blurred_field = _PILImage.blend(near_blur, middle_blur, 0.42)
        # Soft-light treats 50% gray as neutral. Feeding it the background's
        # absolute RGB projects large sky/wall colour blocks onto the character
        # and can bleach hair or darken skin. Convert the blurred background to
        # a restrained modulation field: spatial variation controls luminance,
        # while only the robust global environment tint is retained.
        field_rgb = np.asarray(blurred_field, dtype=np.float32) / 255.0
        luma_weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        field_luma = field_rgb @ luma_weights
        neutral_luma = float(np.median(field_luma))
        luminance_delta = np.clip(field_luma - neutral_luma, -0.30, 0.30)
        middle_luma = float(middle_rgb @ luma_weights)
        global_tint = np.clip(middle_rgb - middle_luma, -0.12, 0.12)
        modulation = (
            0.5 + luminance_delta[..., None] * 0.28 + global_tint[None, None, :] * 0.12
        )
        modulation = np.clip(modulation, 0.40, 0.60)
        light_field = _PILImage.fromarray(
            np.rint(modulation * 255.0).astype(np.uint8), mode="RGB"
        )
        working_dir = COMFY_INPUT / "easy_panel"
        working_dir.mkdir(parents=True, exist_ok=True)
        light_name = f"easy_panel/route1_light_{uuid.uuid4().hex}.png"
        light_field.save(COMFY_INPUT / light_name, format="PNG")

        def rgb255(values):
            return tuple(int(round(float(value) * 255)) for value in values)

        analysis = {
            "nearRadius": near_radius,
            "middleRadius": middle_radius,
            "baseLuminance": round(base_luminance, 4),
            "gradientX": round(gradient_x, 4),
            "gradientY": round(gradient_y, 4),
            "gradientAngle": round(gradient_angle, 2),
            "contrast": round(contrast, 4),
            "nearRgb": rgb255(near_rgb),
            "middleRgb": rgb255(middle_rgb),
            "highlightRgb": rgb255(highlight_rgb),
            "shadowRgb": rgb255(shadow_rgb),
        }
        analysis["prompt"] = (
            "continuous background-derived illumination field, "
            f"measured luminance gradient vector ({gradient_x:.3f}, {gradient_y:.3f}), "
            f"local contrast {contrast:.3f}, near reflected light RGB {rgb255(near_rgb)}, "
            f"highlight tint RGB {rgb255(highlight_rgb)}, shadow tint RGB {rgb255(shadow_rgb)}"
        )
        return light_name, analysis
    except Exception as exc:
        raise ValueError("路线1无法分析人物位置周围的环境光：" + str(exc)) from exc


def object_info_choices(info: dict, class_type: str, input_name: str) -> list[str]:
    """Read old list combos and ComfyUI's newer dynamic COMBO schemas."""
    spec = (info.get(class_type, {}).get("input", {}).get("required", {})
            .get(input_name, []))
    if not isinstance(spec, list) or not spec:
        return []
    if len(spec) > 1 and isinstance(spec[1], dict):
        options = spec[1].get("options")
        if isinstance(options, list):
            return [str(item.get("key") if isinstance(item, dict) else item)
                    for item in options
                    if (item.get("key") if isinstance(item, dict) else item) is not None]
    if isinstance(spec[0], list):
        return [str(item) for item in spec[0]]
    # Some loader inputs expose the choices directly without an option metadata dict.
    if all(isinstance(item, str) for item in spec) and spec[0] not in {
        "COMBO", "COMFY_DYNAMICCOMBO_V3",
    }:
        return list(spec)
    return []


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
PANEL_VERSION = "2.2.2"
SNAPSHOT_FILE = PROJECT_DIR / "generation_snapshots.json"
SNAPSHOT_SCHEMA_VERSION = 2
SNAPSHOT_SOURCE_SECTION_KEYS = (
    "subject", "appearance", "clothing", "pose", "composition", "scene",
    "lighting", "styleColoring", "naturalLanguage", "manual",
)
SNAPSHOT_SECRET_KEY_MARKERS = (
    "token", "password", "passwd", "secret", "authorization", "cookie",
    "api_key", "apikey", "access_key",
)
RPG_SESSION_COOKIE = "easy_panel_rpg_session"
RPG_SESSION_MAX_AGE = 12 * 60 * 60
_FILE_SIGNATURE_CACHE: dict[tuple[str, int, int], dict] = {}
_CREATIVE_INDEX_SOURCE_SIGNATURE: tuple | None = None
_CREATIVE_INDEX_IMPORT_LOCK = threading.Lock()
CREATIVE_INDEX_RECONCILE_LIMIT = 1000
CREATIVE_RECONCILE_IMAGE_EXTENSIONS = frozenset({
    ".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp",
})
CREATIVE_RECONCILE_ORPHAN_GRACE_SECONDS = 300


def get_creative_index() -> CreativeIndex:
    """Return a lazy SQLite index handle without touching legacy JSON files."""

    return CreativeIndex(CREATIVE_INDEX_FILE)


_CREATIVE_PRUNE_LOCK = threading.Lock()
_CREATIVE_PRUNE_INTERVAL_SECONDS = 15.0
_LAST_CREATIVE_PRUNE_TS = 0.0


def prune_creative_missing_outputs() -> dict:
    """Throttled cleanup: drop library records whose output image files are gone.

    Runs at most once every ``_CREATIVE_PRUNE_INTERVAL_SECONDS`` and is called
    before library reads so both the desktop and mobile galleries stop showing
    records whose images were already deleted from disk.  Never raises: a
    cleanup failure must not break an otherwise read-only library request.
    """

    global _LAST_CREATIVE_PRUNE_TS
    now = time.time()
    if now - _LAST_CREATIVE_PRUNE_TS < _CREATIVE_PRUNE_INTERVAL_SECONDS:
        return {"throttled": True}
    with _CREATIVE_PRUNE_LOCK:
        if now - _LAST_CREATIVE_PRUNE_TS < _CREATIVE_PRUNE_INTERVAL_SECONDS:
            return {"throttled": True}
        _LAST_CREATIVE_PRUNE_TS = now
    try:
        return get_creative_index().prune_missing_outputs(OUTPUT)
    except Exception:
        return {"error": True}


def ensure_creative_index_from_legacy_best_effort(index: CreativeIndex | None = None) -> dict:
    """Import legacy JSON once per source-file revision before Library reads."""

    global _CREATIVE_INDEX_SOURCE_SIGNATURE
    target = index or get_creative_index()
    snapshot_source = SNAPSHOT_FILE if SNAPSHOT_FILE.is_file() else None
    jobs_source = RPG_JOB_FILE if RPG_JOB_FILE.is_file() else None

    def signature(path: Path | None) -> tuple:
        if path is None:
            return ("", 0, 0)
        try:
            stat = path.stat()
            return (str(path.resolve()), int(stat.st_size), int(stat.st_mtime_ns))
        except OSError:
            return (str(path), 0, 0)

    source_signature = (
        str(target.path.resolve()),
        signature(snapshot_source),
        signature(jobs_source),
        str(OUTPUT.resolve()),
    )
    with _CREATIVE_INDEX_IMPORT_LOCK:
        if _CREATIVE_INDEX_SOURCE_SIGNATURE == source_signature:
            return {}
        report = target.import_legacy_files(snapshot_source, jobs_source, output_root=OUTPUT)
        if not report.get("errors"):
            _CREATIVE_INDEX_SOURCE_SIGNATURE = source_signature
        return report


def infer_creative_operation(data: dict | None) -> str:
    """Map existing request flags to the Library operation vocabulary."""

    payload = data if isinstance(data, dict) else {}
    generation_payload = payload.get("generation") if isinstance(payload.get("generation"), dict) else {}
    visual_payload = payload.get("visual") if isinstance(payload.get("visual"), dict) else {}
    explicit = str(
        payload.get("operation")
        or generation_payload.get("operation")
        or visual_payload.get("operation")
        or ""
    ).strip()
    normalized = normalize_creative_operation(explicit)
    if normalized != "unknown":
        return normalized
    if explicit.casefold() in {"panel.generate", "rpg.generate"}:
        return "txt2img"
    if explicit:
        return "unknown"
    generation = payload.get("generation") if isinstance(payload.get("generation"), dict) else payload
    output_enhancement = generation.get("outputEnhancement") if isinstance(generation.get("outputEnhancement"), dict) else {}
    if output_enhancement.get("mode") not in (None, "", "off"):
        return "upscale"
    repair = generation.get("repair") if isinstance(generation.get("repair"), dict) else {}
    if repair.get("enabled"):
        mode = str(repair.get("mode", "") or "").casefold()
        if "hand" in mode:
            return "hand_fix"
        if "face" in mode:
            return "face_fix"
        return "inpaint"
    img2img = generation.get("img2img") if isinstance(generation.get("img2img"), dict) else {}
    if img2img.get("enabled"):
        return "img2img"
    return "txt2img"


def creative_request_id(data: dict | None) -> str:
    payload = data if isinstance(data, dict) else {}
    client = payload.get("client") if isinstance(payload.get("client"), dict) else {}
    return str(client.get("requestId") or payload.get("requestId") or "").strip()


def index_snapshot_best_effort(snapshot: dict, source_request: dict | None = None,
                               *, operation: str = "", status: str = "queued",
                               prompt_id: str = "", request_id: str = "") -> dict:
    """Index a snapshot without making SQLite availability part of generation success."""

    try:
        return get_creative_index().upsert_snapshot(
            snapshot,
            operation=operation or infer_creative_operation(source_request or snapshot.get("payload")),
            status=status,
            prompt_id=prompt_id or str(snapshot.get("promptId") or ""),
            request_id=request_id or creative_request_id(source_request),
            output_root=OUTPUT,
            parent_generation_id=(source_request or {}).get("parentGenerationId", "")
            if isinstance(source_request, dict) else "",
            parent_artifact_id=(source_request or {}).get("parentArtifactId", "")
            if isinstance(source_request, dict) else "",
        )
    except Exception:
        # The native JSON snapshot is deliberately authoritative.  An index
        # problem must never turn a submitted ComfyUI job into a false failure.
        return {}


def update_creative_index_status_best_effort(snapshot_id: str, status: dict) -> dict:
    """Reflect RPG job progress in SQLite while keeping the existing status API."""

    try:
        return get_creative_index().update_snapshot_status(
            snapshot_id,
            status=status.get("status", "unknown"),
            images=status.get("images") if isinstance(status.get("images"), list) else (),
            output_root=OUTPUT,
        ) or {}
    except Exception:
        return {}


def update_creative_index_job_status_best_effort(job: dict, status: dict) -> dict:
    """Reflect a ComfyUI status using the prompt id as the stable fallback key."""

    if not isinstance(job, dict) or not isinstance(status, dict):
        return {}
    try:
        return get_creative_index().update_job(
            prompt_id=str(job.get("prompt_id") or ""),
            request_id=str(job.get("request_id") or ""),
            snapshot_id=str(job.get("snapshot_id") or ""),
            status=status.get("status", "unknown"),
            images=status.get("images") if isinstance(status.get("images"), list) else (),
            output_root=OUTPUT,
        ) or {}
    except Exception:
        return {}


def _rpg_output_prefix_for_job(job: dict) -> str:
    """Return the unique RPGBox output prefix saved with a submitted job."""

    if not isinstance(job, dict):
        return ""
    prompt_id = str(job.get("prompt_id") or job.get("promptId") or "").strip()
    metadata = {}
    if prompt_id:
        try:
            metadata = find_rpg_job(prompt_id)
        except Exception:
            metadata = {}
    snapshot_id = str(
        job.get("snapshot_id") or job.get("snapshotId") or metadata.get("snapshot_id") or ""
    ).strip()
    prefix = str(metadata.get("filename_prefix") or "").strip()
    if not prefix and snapshot_id:
        try:
            snapshot = find_generation_snapshot(snapshot_id)
        except Exception:
            snapshot = None
        payload = snapshot.get("payload") if isinstance(snapshot, dict) else {}
        prefix = str(payload.get("filenamePrefix") or "").strip()
    if not prefix:
        return ""
    # RPGBox prefixes are generated by safe_rpg_prefix and are intentionally
    # flat.  Do not scan generic EasyPanel output names: those are shared by
    # unrelated desktop jobs and cannot be mapped to one prompt safely.
    prefix = re.sub(r"[^0-9A-Za-z_-]+", "_", prefix).strip("_")[:128]
    return prefix if prefix.casefold().startswith("rpgbox_") else ""


def find_rpg_output_images(job: dict, output_root: str | Path | None = None) -> list[dict]:
    """Recover RPG outputs from disk after ComfyUI evicts their history rows."""

    prefix = _rpg_output_prefix_for_job(job)
    if not prefix:
        return []
    root = Path(output_root if output_root is not None else OUTPUT).expanduser().resolve()
    if not root.is_dir():
        return []
    wanted_prefix = prefix.casefold()
    matches: list[tuple[int, str, Path]] = []
    try:
        candidates = root.rglob("*")
    except OSError:
        return []
    for candidate in candidates:
        try:
            if not candidate.is_file() or candidate.suffix.casefold() not in CREATIVE_RECONCILE_IMAGE_EXTENSIONS:
                continue
            if not candidate.name.casefold().startswith(wanted_prefix):
                continue
            relative = candidate.relative_to(root)
            matches.append((candidate.stat().st_mtime_ns, relative.as_posix(), candidate))
        except (OSError, ValueError):
            continue
    matches.sort(key=lambda item: (item[0], item[1]))
    images: list[dict] = []
    for _modified_ns, relative_name, candidate in matches[:16]:
        relative = Path(relative_name)
        subfolder = "" if str(relative.parent) == "." else relative.parent.as_posix()
        images.append({
            "filename": candidate.name,
            "subfolder": subfolder,
            "type": "output",
            "url": image_url(candidate.name, subfolder, "output"),
        })
    return images


def rpg_status_with_output_recovery(prompt_id: str, history: dict, job: dict | None = None) -> dict:
    """Add a filesystem fallback for completed RPG jobs missing from history."""

    status = history_to_rpg_status(prompt_id, history)
    if not isinstance(status, dict) or status.get("status") not in {"queued", "running"}:
        return status
    context = dict(job) if isinstance(job, dict) else {"prompt_id": prompt_id}
    if not context.get("snapshot_id"):
        metadata = status.get("meta") if isinstance(status.get("meta"), dict) else {}
        context["snapshot_id"] = metadata.get("snapshot_id") or metadata.get("snapshotId") or ""
    recovered = find_rpg_output_images(context)
    if not recovered:
        return status
    return {**status, "status": "completed", "images": recovered}


def _comfy_queue_prompt_ids(queue: dict, key: str) -> set[str]:
    """Extract prompt ids from ComfyUI's queue_running/queue_pending rows."""

    if not isinstance(queue, dict):
        return set()
    result: set[str] = set()
    rows = queue.get(key)
    if not isinstance(rows, list):
        return result
    for row in rows:
        prompt_id = ""
        if isinstance(row, (list, tuple)) and len(row) > 1:
            prompt_id = str(row[1] or "").strip()
        elif isinstance(row, dict):
            prompt_id = str(row.get("prompt_id") or row.get("promptId") or "").strip()
        if prompt_id:
            result.add(prompt_id)
    return result


def _creative_job_is_orphaned(job: dict) -> bool:
    """Give a missing-history job a short grace period before retiring it."""

    try:
        created_at = int(job.get("created_at") or job.get("updated_at") or 0)
    except (TypeError, ValueError):
        return False
    if created_at <= 0:
        return False
    return (time.time() * 1000 - created_at) > CREATIVE_RECONCILE_ORPHAN_GRACE_SECONDS * 1000


def sync_rpg_status_to_creative_index(status: dict) -> dict:
    """Mirror an existing RPG status response into the read-only index."""

    if not isinstance(status, dict):
        return status
    metadata = status.get("meta") if isinstance(status.get("meta"), dict) else {}
    snapshot_id = str(metadata.get("snapshot_id") or metadata.get("snapshotId") or "").strip()
    if snapshot_id:
        update_creative_index_status_best_effort(snapshot_id, status)
    else:
        prompt_id = str(status.get("prompt_id") or status.get("job_id") or "").strip()
        if prompt_id:
            update_creative_index_job_status_best_effort({"prompt_id": prompt_id}, status)
    return status


def reconcile_creative_index_jobs(limit: int = CREATIVE_INDEX_RECONCILE_LIMIT) -> int:
    """Reconcile finished ComfyUI jobs even when no client is polling them.

    Both the desktop page and the mobile app historically wrote ``queued`` to
    the SQLite projection and relied on their own polling loop to write the
    terminal state.  The ComfyUI history is process-owned, so a short-lived
    client must not be the only component responsible for this transition.
    """

    try:
        ensure_creative_index_from_legacy_best_effort()
        jobs = get_creative_index().list_unfinished_jobs(limit=limit)
    except Exception:
        return 0
    if not jobs:
        return 0

    try:
        history = comfy_json("/history?max_items=%d" % CREATIVE_INDEX_RECONCILE_LIMIT)
    except Exception:
        return 0
    if not isinstance(history, dict):
        return 0
    try:
        queue = comfy_json("/queue")
    except Exception:
        queue = None
    queue_known = isinstance(queue, dict) and all(
        key in queue for key in ("queue_running", "queue_pending")
    )
    running_prompt_ids = _comfy_queue_prompt_ids(queue, "queue_running") if queue_known else set()
    pending_prompt_ids = _comfy_queue_prompt_ids(queue, "queue_pending") if queue_known else set()

    reconciled = 0
    for job in jobs:
        prompt_id = str(job.get("prompt_id") or "").strip()
        if not prompt_id:
            continue
        has_history = isinstance(history.get(prompt_id), dict)
        status = rpg_status_with_output_recovery(prompt_id, history, job)
        if not has_history and status.get("status") != "completed":
            if prompt_id in pending_prompt_ids:
                continue
            if prompt_id in running_prompt_ids:
                status = {"status": "running", "images": []}
            elif queue_known and _creative_job_is_orphaned(job):
                status = {
                    "status": "error",
                    "images": [],
                    "error": "ComfyUI 已不再保留该任务，且未找到输出文件。",
                }
            else:
                # ComfyUI omits still-queued jobs from /history.  Leave them
                # alone until a later pass sees their completed record/output,
                # or until the queue confirms that the record is orphaned.
                continue
        if not isinstance(status, dict):
            continue
        if update_creative_index_job_status_best_effort(job, status):
            reconciled += 1

        # Keep the replay-oriented JSON snapshot aligned with the query index
        # when a completed job was never observed by a client.
        if status.get("status") == "completed":
            snapshot_id = str(job.get("snapshot_id") or "").strip()
            image_names = [
                str(image.get("filename") or "").strip()
                for image in status.get("images") or []
                if isinstance(image, dict) and str(image.get("filename") or "").strip()
            ]
            if snapshot_id and image_names:
                try:
                    attach_snapshot_outputs(snapshot_id, image_names)
                except Exception:
                    pass
    return reconciled


def _creative_reconcile_interval_seconds() -> float:
    raw = os.environ.get("EASY_PANEL_RECONCILE_INTERVAL_SECONDS", "5").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 5.0
    return min(60.0, max(2.0, value))


def start_creative_index_reconciler() -> threading.Event:
    """Start the daemon that reconciles client-independent job state."""

    stop_event = threading.Event()
    interval = _creative_reconcile_interval_seconds()

    def run() -> None:
        while not stop_event.wait(interval):
            try:
                reconcile_creative_index_jobs()
            except Exception:
                # Reconciliation is best effort and must never affect the API
                # server or the ComfyUI worker.
                continue

    thread = threading.Thread(
        target=run,
        name="easy-panel-creative-index-reconciler",
        daemon=True,
    )
    thread.start()
    return stop_event


def _rpg_expected_token() -> str:
    return os.environ.get("EASY_PANEL_RPG_TOKEN", "").strip()


def _rpg_session_signature(value: str) -> str:
    return hmac.new(
        _rpg_expected_token().encode("utf-8"),
        value.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _new_rpg_session_cookie_value() -> str:
    body = f"{int(time.time())}.{secrets.token_urlsafe(18)}"
    return f"{body}.{_rpg_session_signature(body)}"


def _valid_rpg_session_cookie(value: str) -> bool:
    if not _rpg_expected_token():
        return False
    parts = str(value or "").split(".", 2)
    if len(parts) != 3:
        return False
    issued, nonce, signature = parts
    if (not nonce or not re.fullmatch(r"[0-9]+", issued)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", nonce)):
        return False
    try:
        issued_at = int(issued)
    except ValueError:
        return False
    now = int(time.time())
    if issued_at > now + 60 or now - issued_at > RPG_SESSION_MAX_AGE:
        return False
    body = f"{issued}.{nonce}"
    return hmac.compare_digest(signature, _rpg_session_signature(body))


def prompt_automation(data: dict) -> dict[str, bool]:
    """Return explicit switches for every prompt fragment inserted by the panel."""
    supplied = data.get("promptAutomation")
    defaults = {
        "quality": True,
        "loraTriggers": True,
        "baseNegative": True,
        "safetyNegative": True,
        "dynamicNegative": True,
        "sceneFallback": True,
        "detailerNegative": True,
    }
    if isinstance(supplied, dict):
        for key in defaults:
            if key in supplied:
                defaults[key] = bool(supplied[key])
    return defaults


def safety_negative_terms(level: str) -> list[str]:
    if level == "safe":
        return list(MATURE_NEGATIVE_TERMS)
    if level == "sensitive":
        return ["nude", "nudity", "explicit", "sex", "sexual", "porn", "hentai"]
    return []


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


PROMPT_FAMILY_LABELS = {
    "anima": "Anima 硬标签+质感+关系句",
    "illustrious": "Illustrious 标签为主",
    "sdxl": "SDXL 标签为主",
    "krea2": "Krea 2 自然语言优先",
}
PROMPT_FAMILY_RULES = {
    "anima": "以 Danbooru 英文硬标签为主，补充简短英文关系句；不要凭空添加角色、服装或动作；不要添加与模型 LoRA 冲突的质量前缀。",
    "illustrious": "以逗号分隔的 Danbooru 英文标签为主，主体、外貌、服装、动作、构图、场景、光影顺序清楚。",
    "sdxl": "使用清晰、简洁的英文图像提示词，标签为主，必要时用短句消除动作或空间歧义。",
    "krea2": "使用自然流畅的英文视觉描述，明确主体、动作、镜头、场景、光影和材质，避免标签堆砌。",
}
PROMPT_INSTRUCTION_SAFETY_LEVELS = {"safe", "sensitive", "nsfw", "explicit"}


def resolve_prompt_instruction_model(requested: str = "") -> str:
    """Resolve the same effective checkpoint used by the RPG submit path."""

    model = str(requested or "").strip()
    if model:
        return model
    profiles = load_rpg_profiles()
    defaults = profiles.get("defaults") if isinstance(profiles.get("defaults"), dict) else {}
    return choose_rpg_model("", defaults, rpg_model_catalog())


def build_prompt_instruction(text: str, model: str = "", safety_level: str = "safe") -> dict:
    """Build the model-aware DeepSeek instruction shared by desktop and mobile."""

    source = str(text or "").strip()
    if not source:
        raise ValueError("请先输入中文描述。")
    if len(source) > 4000:
        raise ValueError("中文描述不能超过 4000 个字符。")
    resolved_model = resolve_prompt_instruction_model(model)
    family = prompt_family(resolved_model)
    safety = str(safety_level or "safe").strip().lower()
    if safety not in PROMPT_INSTRUCTION_SAFETY_LEVELS:
        safety = "safe"
    label = PROMPT_FAMILY_LABELS.get(family, PROMPT_FAMILY_LABELS["sdxl"])
    rule = PROMPT_FAMILY_RULES.get(family, PROMPT_FAMILY_RULES["sdxl"])
    instruction = (
        "你是 ComfyUI 提示词转换助手。请把下面的中文构想转换成适合当前模型的英文提示词。\n"
        f"当前模型族：{label}\n"
        f"当前检查点：{resolved_model}\n"
        f"安全级别：{safety}\n"
        f"规则：{rule}\n"
        "保留用户明确要求，不扩写敏感程度，不解释思路，不使用 Markdown 代码块。"
        "只按以下两行格式回答：\n"
        "POSITIVE: 英文正向提示词\n"
        "NEGATIVE: 仅列出针对本画面需要额外避免的问题；没有则留空\n\n"
        "用户中文构想：\n"
        f"{source}"
    )
    return {
        "api_version": RPG_API_VERSION,
        "model": resolved_model,
        "family": family,
        "family_label": label,
        "safety_level": safety,
        "instruction": instruction,
    }


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


def load_embedding_notes() -> dict:
    """Read display metadata separately from the real embedding filenames."""
    if not EMBEDDING_NOTES_FILE.is_file():
        return {}
    try:
        with EMBEDDING_NOTES_FILE.open("r", encoding="utf-8-sig") as handle:
            notes = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return notes if isinstance(notes, dict) else {}


def embedding_catalog() -> tuple[list[str], dict]:
    """List local textual inversions with panel-friendly labels and target fields."""
    root = COMFY_MODELS / "embeddings"
    if not root.is_dir():
        return [], {}
    notes = load_embedding_notes()
    names: list[str] = []
    meta: dict[str, dict] = {}
    section_tokens = (
        ("02_负面", "negative"),
        ("03_外貌", "appearance"),
        ("04_nsfw姿势", "pose"),
        ("05_性感动作", "pose"),
        ("06_构图", "composition"),
        ("07_场景", "scene"),
        ("08_动作表情", "pose"),
    )
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.suffix.casefold() not in EMBEDDING_EXTENSIONS:
            continue
        relative = path.relative_to(root).as_posix()
        physical_folder = path.relative_to(root).parent.as_posix()
        normalized_folder = physical_folder.casefold()
        section = next((target for token, target in section_tokens if token in normalized_folder), "manual")
        if "__" in path.stem:
            chinese, original = path.stem.split("__", 1)
            label = f"{chinese}（{original}）"
        else:
            label = path.stem
        family = "illustrious" if "illustrious" in normalized_folder or "光辉" in physical_folder else "general"
        note = notes.get(relative) or notes.get(path.name)
        if isinstance(note, dict):
            folder = str(note.get("folder", "")).strip() or physical_folder or "未分类"
            label = str(note.get("label", "")).strip() or label
            section = str(note.get("section", "")).strip() or section
            family = str(note.get("family", "")).strip() or family
        else:
            note = {}
            folder = physical_folder or "未分类"
        names.append(relative)
        meta[relative] = {
            "folder": folder,
            "label": label,
            "section": section,
            "family": family,
            "trigger": str(note.get("trigger", "")).strip() or path.stem,
            "prompt": str(note.get("prompt", "")).strip() or f"embedding:{path.stem}",
            "source": str(note.get("source", "")).strip() or path.name,
            "versionId": note.get("version_id"),
        }
    return names, meta


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


def prompt_term_info(term: str) -> dict:
    """Parse common ComfyUI emphasis syntax without changing the submitted text."""
    raw = str(term or "").strip()
    weight = 1.0
    match = re.fullmatch(r"\((.*):\s*(-?(?:\d+(?:\.\d*)?|\.\d+))\)", raw)
    if match:
        raw = match.group(1).strip()
        try:
            weight = float(match.group(2))
        except ValueError:
            weight = 1.0
    return {"text": str(term or "").strip(), "key": normalize_prompt_key(raw), "weight": weight}


PROMPT_CONFLICT_GROUPS = (
    ("画面范围", ("full body", "upper body", "cowboy shot", "portrait", "close-up")),
    ("基础姿势", ("standing", "sitting", "lying")),
    ("人物朝向", ("front view", "from behind", "side view")),
    ("场景", ("indoors", "outdoors")),
    ("发型", ("high ponytail", "ponytail", "twintails", "side ponytail", "low ponytail",
              "hair down", "loose hair", "short hair", "bob cut", "single braid", "braided hair")),
)


def diagnose_prompt_conflicts(terms: list[str], negative_terms: list[str] | None,
                              natural_language: str, safety_level: str) -> list[dict]:
    positive = [prompt_term_info(term) for term in terms]
    negative = [prompt_term_info(term) for term in (negative_terms or [])]
    keys = {item["key"] for item in positive}
    negative_keys = {item["key"] for item in negative}
    issues: list[dict] = []

    def add(code: str, severity: str, title: str, message: str, related: list[str]) -> None:
        issues.append({"code": code, "severity": severity, "title": title,
                       "message": message, "terms": related})

    def report(label: str, options: tuple[str, ...]) -> None:
        present = [option for option in options if normalize_prompt_key(option) in keys]
        if len(present) > 1:
            add("positive-conflict", "warning", label + "冲突",
                f"{label}可能冲突：" + "、".join(present), present)

    for label, options in PROMPT_CONFLICT_GROUPS:
        report(label, options)
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
        add("subject-count", "warning", "人数冲突", "人数可能冲突：solo 与多人标签同时存在。",
            ["solo"])
    mature_positive = keys.intersection(MATURE_NEGATIVE_TERMS)
    if safety_level == "safe" and mature_positive:
        add("safety", "warning", "安全等级冲突",
            "安全等级为 SFW，但正向提示词含有：" + "、".join(sorted(mature_positive)),
            sorted(mature_positive))
    if natural_language and len(natural_language) < 24:
        add("short-natural-language", "info", "自然语言过短",
            "自然语言描述较短；Anima 纯自然语言模式建议至少写两个具体句子。", [])
    cross = sorted(keys.intersection(negative_keys))
    for key in cross[:12]:
        add("positive-negative", "warning", "正负向相互对抗",
            f"“{key}”同时出现在正向和负向，可能改变构图或使生成不稳定。", [key])
    for item in positive:
        if item["weight"] > 1.25:
            add("high-weight", "warning", "提示词权重过高",
                f"“{item['text']}”权重为 {item['weight']:g}；叠加多个 LoRA 时建议先降到 1.05–1.15。",
                [item["text"]])
    hairstyle_sets = (
        ({"high ponytail", "ponytail", "side ponytail", "low ponytail", "twintails"},
         {"hair down", "loose hair"}),
    )
    for tied, loose in hairstyle_sets:
        pos_tied = sorted(keys.intersection(tied))
        pos_loose = sorted(keys.intersection(loose))
        neg_tied = sorted(negative_keys.intersection(tied))
        neg_loose = sorted(negative_keys.intersection(loose))
        if pos_tied and (pos_loose or neg_loose):
            related = pos_tied + pos_loose + neg_loose
            add("hairstyle-pull", "warning", "发型注意力拉扯",
                "束发/马尾与散发约束同时作用；这类正负向拉扯会在 LoRA 叠加时改变整体去噪轨迹。",
                related)
        elif pos_loose and neg_tied:
            add("hairstyle-pull", "warning", "发型注意力拉扯",
                "散发与负向束发约束同时作用，建议只保留正向目标发型。", pos_loose + neg_tied)
    return issues


def prompt_conflicts(terms: list[str], natural_language: str, safety_level: str,
                     negative_terms: list[str] | None = None) -> list[str]:
    return [item["message"] for item in diagnose_prompt_conflicts(
        terms, negative_terms, natural_language, safety_level
    )]


def dynamic_negative_terms(positive: str) -> list[str]:
    normalized = positive.lower().replace("_", " ")
    additions: list[str] = []
    if any(token in normalized for token in ("hand", "holding", "touching", "grasping", "fingers")):
        additions += ["bad hands", "extra digits", "missing fingers", "fused fingers"]
    if any(token in normalized for token in ("full body", "thigh", "leg", "feet", "foot", "pantyhose", "thighhigh")):
        additions += ["bad feet", "extra legs", "missing legs", "malformed limbs"]
    if any(token in normalized for token in ("2girls", "2boys", "multiple girls", "multiple people", "group", "crowd")):
        additions += ["duplicate person", "fused bodies", "merged limbs", "extra arms"]
    if "solo" in normalized:
        # Strong character/action LoRAs can paint hand-like training fragments or
        # partial people into an otherwise unspecified background.  A solo prompt
        # should explicitly reject those artifacts instead of relying on "solo"
        # alone, which many anime checkpoints treat as a weak subject-count hint.
        additions += ["multiple people", "background characters", "extra person",
                      "duplicate person", "disembodied limbs", "floating limbs"]
    if any(token in normalized for token in ("low angle", "from above", "foreshortening", "dynamic pose", "dutch angle")):
        additions += ["bad perspective", "warped background", "distorted body"]
    return exact_unique_terms(", ".join(additions))


def compile_prompt(data: dict) -> dict:
    model = str(data.get("model", ""))
    safety = normalized_safety_level(data)
    profile = model_prompt_profile(model, safety)
    automation = prompt_automation(data)
    sections = prompt_sections(data)
    sources: list[dict] = []

    def source(key: str, label: str, kind: str, enabled: bool, terms) -> None:
        if isinstance(terms, str):
            values = split_prompt_terms(terms, limit=720)
        else:
            values = [str(item) for item in (terms or []) if str(item).strip()]
        sources.append({"key": key, "label": label, "kind": kind,
                        "enabled": bool(enabled), "terms": values})

    depth_settings = data.get("depth") or {}
    depth_enabled = bool(isinstance(depth_settings, dict) and depth_settings.get("enabled"))
    scene_fallback = bool(isinstance(data.get("promptSections"), dict)
                          and not sections["scene"] and automation["sceneFallback"]
                          and not depth_enabled)
    if scene_fallback:
        # The structured panel owns the scene field, so an empty scene means
        # "use a safe neutral fallback".  This prevents stacked LoRAs from
        # inventing dense background props and figures.  Callers that want a
        # detailed setting can still provide one explicitly.
        sections["scene"] = "simple background, uncluttered background, subject focus"
    all_trigger_terms = exact_unique_terms(", ".join(selected_lora_triggers(data)))
    trigger_terms = all_trigger_terms if automation["loraTriggers"] else []
    ordered: list[str] = []
    seen: set[str] = set()
    positive_candidates = 0
    positive_removed_count = 0
    positive_removed_terms: list[str] = []

    def extend(chunk) -> None:
        nonlocal positive_candidates, positive_removed_count
        source = ", ".join(chunk) if isinstance(chunk, (list, tuple)) else str(chunk or "")
        for term in split_prompt_terms(source, limit=360):
            positive_candidates += 1
            key = normalize_prompt_key(term)
            if key and key not in seen:
                seen.add(key)
                ordered.append(term)
            elif key:
                positive_removed_count += 1
                if len(positive_removed_terms) < 128:
                    positive_removed_terms.append(term)

    source("loraTriggers", "LoRA 自动触发词", "positive", automation["loraTriggers"],
           all_trigger_terms)
    source("quality", "模型质量词", "positive", automation["quality"], profile["quality"])
    if automation["loraTriggers"]:
        extend(trigger_terms)
    if automation["quality"]:
        extend(profile["quality"])
    for key in PROMPT_SECTION_KEYS:
        value = sections[key]
        if profile["family"] == "anima" and key == "manual":
            value = canonical_anima_hard_tags(value)
        extend(value)
    user_positive_terms = []
    original_sections = prompt_sections(data)
    for key in PROMPT_SECTION_KEYS:
        user_positive_terms.extend(split_prompt_terms(original_sections[key], limit=360))
    source("userPositive", "用户正向分区", "positive", True, user_positive_terms)
    source("sceneFallback", "空场景兜底", "positive", automation["sceneFallback"],
           ["simple background", "uncluttered background", "subject focus"] if scene_fallback else [])
    natural_language = sections["naturalLanguage"].strip()
    if natural_language:
        source("naturalLanguage", "自然语言关系", "positive", True, [natural_language])
    positive = ", ".join(ordered)
    if natural_language:
        positive = positive.rstrip(" .") + ". " + natural_language

    manual_negative = str(data.get("negative", "") or "").strip()
    base_negative = list(profile["negative"])
    safety_negative = safety_negative_terms(safety)
    dynamic_negative = dynamic_negative_terms(positive)
    negative_terms: list[str] = []
    if automation["baseNegative"]:
        negative_terms = exact_unique_terms(", ".join(negative_terms), ", ".join(base_negative))
    if automation["safetyNegative"]:
        negative_terms = exact_unique_terms(", ".join(negative_terms), ", ".join(safety_negative))
    negative_terms = exact_unique_terms(", ".join(negative_terms), manual_negative)
    if automation["dynamicNegative"]:
        negative_terms = exact_unique_terms(", ".join(negative_terms), ", ".join(dynamic_negative))
    fallback_negative = []
    if scene_fallback:
        fallback_negative = ["busy background", "cluttered background"]
        negative_terms = exact_unique_terms(
            ", ".join(negative_terms), "busy background, cluttered background")
    depth_options = data.get("depth") or {}
    depth_negative: list[str] = []
    if (isinstance(depth_options, dict) and depth_options.get("enabled")
            and depth_options.get("suppressSimple", True)):
        depth_negative = ["simple background", "plain background", "empty background",
                          "minimal background", "flat background", "low detail background"]
        negative_terms = exact_unique_terms(
            ", ".join(negative_terms), ", ".join(depth_negative))
    # The hand/foot detailer may be enabled even when the visible prompt does not
    # literally mention limbs (for example a generic "1girl, standing" prompt).
    # Seed the base sampler with matching failure prevention so the local pass is
    # correcting a mostly sound structure instead of rebuilding it from scratch.
    enhancement = data.get("outputEnhancement") or {}
    limb_detailer = (enhancement.get("limbDetailer") or {}) if isinstance(enhancement, dict) else {}
    detailer_negative: list[str] = []
    if isinstance(limb_detailer, dict) and automation["detailerNegative"]:
        if limb_detailer.get("hands"):
            detailer_negative += ["bad hands", "malformed hands", "extra fingers", "missing fingers",
                                  "fused fingers", "blurry hands"]
            negative_terms = exact_unique_terms(
                ", ".join(negative_terms),
                "bad hands, malformed hands, extra fingers, missing fingers, fused fingers, blurry hands",
            )
        if limb_detailer.get("feet"):
            detailer_negative += ["bad feet", "malformed feet", "extra toes", "missing toes",
                                  "fused toes", "blurry feet"]
            negative_terms = exact_unique_terms(
                ", ".join(negative_terms),
                "bad feet, malformed feet, extra toes, missing toes, fused toes, blurry feet",
            )
    source("baseNegative", "模型基础负面词", "negative", automation["baseNegative"], base_negative)
    source("safetyNegative", "安全等级负面词", "negative", automation["safetyNegative"], safety_negative)
    source("userNegative", "用户额外负面词", "negative", True, manual_negative)
    source("dynamicNegative", "动态结构保护词", "negative", automation["dynamicNegative"], dynamic_negative)
    source("sceneFallbackNegative", "空场景负面兜底", "negative", automation["sceneFallback"],
           fallback_negative)
    source("depthBackgroundNegative", "Depth 简陋背景抑制", "negative",
           bool(depth_negative), depth_negative)
    source("detailerNegative", "局部修复保护词", "negative", automation["detailerNegative"],
           detailer_negative)
    diagnostics = diagnose_prompt_conflicts(ordered, negative_terms, natural_language, safety)
    warnings = [item["message"] for item in diagnostics]
    warnings.extend(lora_compatibility_warnings(data, profile["family"]))
    style_count = len(split_prompt_terms(sections["style"], limit=180))
    if str(data.get("promptMode", "style_test")) == "style_test" and style_count:
        warnings.append("当前为画风测试模式，但“画风与上色”分区不为空；这些词可能掩盖 LoRA 自身表现。")
    errors: list[str] = []
    user_term_count = sum(len(split_prompt_terms(sections[key], limit=360)) for key in PROMPT_SECTION_KEYS)
    region_term_count = sum(len(split_prompt_terms(item.get("prompt", ""), limit=180))
                            for item in (data.get("regions") or []) if isinstance(item, dict))
    override = data.get("promptOverride") or {}
    overridden = bool(isinstance(override, dict) and override.get("enabled"))
    if overridden:
        # Manual final-prompt mode is deliberately exact: do not reinsert model
        # quality tags, LoRA triggers, safety negatives, scene fallbacks or
        # dynamic anatomy terms after the user has edited the final text.
        positive = str(override.get("positive", "") or "").strip()
        negative = str(override.get("negative", "") or "").strip()
        if len(positive) > 32_000 or len(negative) > 32_000:
            errors.append("最终提示词单项不能超过 32000 个字符。")
        ordered = split_prompt_terms(positive, limit=720)
        negative_terms = split_prompt_terms(negative, limit=720)
        diagnostics = diagnose_prompt_conflicts(ordered, negative_terms, "", safety)
        warnings = [item["message"] for item in diagnostics]
        warnings.extend(lora_compatibility_warnings(data, profile["family"]))
        sources = [{"key": "manualOverride", "label": "手动最终文本", "kind": "both",
                    "enabled": True, "terms": ordered + negative_terms}]
        deduplication = {
            "positiveCandidates": len(ordered),
            "positiveFinal": len(ordered),
            "positiveRemoved": 0,
            "positiveRemovedTerms": [],
        }
    elif not user_term_count and not trigger_terms and not natural_language and not region_term_count:
        errors.append("请至少填写人物、场景、姿势、其他标签或自然语言描述中的一项。")
        deduplication = {
            "positiveCandidates": positive_candidates,
            "positiveFinal": len(ordered),
            "positiveRemoved": positive_removed_count,
            "positiveRemovedTerms": positive_removed_terms,
        }
    else:
        deduplication = {
            "positiveCandidates": positive_candidates,
            "positiveFinal": len(ordered),
            "positiveRemoved": positive_removed_count,
            "positiveRemovedTerms": positive_removed_terms,
        }
    return {"positive": positive,
            "negative": negative if overridden else ", ".join(negative_terms),
            "errors": errors, "warnings": warnings, "sections": sections,
            "triggers": trigger_terms, "profile": profile,
            "sources": sources, "diagnostics": diagnostics, "automation": automation,
            "overridden": overridden,
            "deduplication": deduplication,
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
    width = bounded(data.get("width"), 832, 512, 1536)
    height = bounded(data.get("height"), 1216, 512, 1536)
    if width * height > 1_250_000:
        warnings.append(f"Anima 当前尺寸为 {width}×{height}；8GB 显存压力较大，显存不足时请改用 864×1152 或 1024×1024。")
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
    width = bounded(data.get("width"), 832, 512, 2560)
    height = bounded(data.get("height"), 1216, 512, 2560)
    if width * height > 1_250_000:
        warnings.append(
            f"Krea 2 当前尺寸 {width}×{height}（{width * height / 1e6:.2f} MP）；8GB 显存建议用 "
            f"864×1152 或 1024×1024 以内，超出时会走 CPU 卸载（明显变慢）。"
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
    scale = bounded(data.get("hiresScale"), 1.25, 1.0, 8.0, integer=False)
    width = bounded(data.get("width"), 832, 512, 2560)
    height = bounded(data.get("height"), 1216, 512, 2560)
    projected_pixels = width * height * (scale ** 2 if mode == "hires" else 1)
    if mode == "hires" and scale > 1.3:
        warnings.append("高清倍率高于 1.30×，8GB 显存更容易溢出；建议先用 1.25×。")
    if mode == "hires" and projected_pixels > 1_900_000:
        out_width = round(width * scale / 8) * 8
        out_height = round(height * scale / 8) * 8
        warnings.append(f"预计高清成图为 {out_width}×{out_height}；8GB 显存风险较高，建议改用精准模式或 1.10–1.15×。")
    hires_mode = normalized_hires_prompt_mode(data)
    hires_positive = str(data.get("hiresPositive", "") or "").strip()
    hires_negative = str(data.get("hiresNegative", "") or "").strip()
    if str(data.get("hiresPromptMode", "") or "").strip().lower() not in HIRES_PROMPT_MODES:
        if str(data.get("hiresPromptMode", "") or "").strip():
            warnings.append("二采提示词模式无效，已按“继承首采”处理；可选 inherit / append / replace。")
    if (hires_positive or hires_negative) and mode != "hires":
        warnings.append("二采提示词只在高清模式（二次采样）下生效；当前生成模式不是高清模式。")
    if mode == "hires" and hires_mode != "inherit" and (hires_positive or hires_negative):
        if len(split_prompt_terms(hires_positive, limit=360)) > 40:
            warnings.append("二采补充提示词条目偏多；高清阶段建议只保留 10–20 项细节词，避免二采重新抢构图。")
        if normalized_regions(data):
            warnings.append("多人区域提示词期间，二采提示词会按“继承首采”处理；如需独立二采提示词请先关闭多人分区。")
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
    return classify_lora_note_outfits(content) if isinstance(content, dict) else {}


def load_lora_rename_aliases() -> dict[str, str]:
    """Return old-to-new LoRA names used to migrate browser-persisted state."""
    sources = []
    packaged = PROJECT_DIR / "lora_rename_aliases.json"
    if packaged.is_file():
        sources.append(packaged)
    imports = PROJECT_DIR / "lora_imports"
    if imports.is_dir():
        sources.extend(sorted(imports.glob("*_illustrious_chinese_filenames.json")))
    if not sources:
        return {}
    aliases: dict[str, str] = {}
    prefix = "Illustrious_Hosiery_Test/"
    for source in sources:
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        for old, new in raw.items():
            old_name = str(old).replace("\\", "/").lstrip("./")
            new_name = str(new).replace("\\", "/").lstrip("./")
            if not old_name or not new_name:
                continue
            aliases[prefix + old_name] = prefix + new_name
            aliases[Path(old_name).name] = Path(new_name).name
    return aliases


def normalized_lora_name(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().casefold()


def comfy_lora_name(value: str) -> str:
    """Return a relative LoRA name in the separator format ComfyUI expects.

    The RPG bridge and the SillyTavern catalog use forward slashes so the same
    profile works across platforms.  ComfyUI's Windows object-info choices use
    backslashes, however, and reject an otherwise valid catalog path.  Resolve
    an existing file below the configured LoRA root and emit the exact relative
    Windows form without allowing traversal outside that root.
    """

    raw = str(value or "").replace("\\", "/").lstrip("/")
    if not raw:
        return ""
    root = LORA_DIR.resolve()
    candidate = (root / Path(raw)).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return raw.replace("/", "\\")
    if candidate.is_file():
        return relative.as_posix().replace("/", "\\")
    return raw.replace("/", "\\")


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


def normalized_hires_prompt_mode(data: dict) -> str:
    """Return the hi-res prompt mode, defaulting to inherit for old payloads."""
    mode = str(data.get("hiresPromptMode", "") or "").strip().lower()
    return mode if mode in HIRES_PROMPT_MODES else "inherit"


def regional_global_prompt(data: dict, compiled: dict, bound_loras: set[str]) -> str:
    """Build a character-free scene/style prompt shared by every region."""
    sections = compiled["sections"]
    explicit = str(data.get("regionGlobalPrompt", "") or "").strip()
    if compiled.get("overridden"):
        return unique_prompt_terms(compiled["positive"], explicit)
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
    if compiled.get("overridden"):
        # Region fields remain editable, but no hidden quality/trigger terms are
        # reintroduced while the final-prompt override is active.
        return unique_prompt_terms(
            compiled["positive"], region["subject"],
            regional_position_prompt(region), region["prompt"],
        )
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
    atomic_write_notes(LORA_NOTES, classify_lora_note_outfits(notes))


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


def safe_generation_filename_prefix(data: dict, default: str = "EasyPanel") -> str:
    """Return a flat, traversal-safe ComfyUI SaveImage prefix."""
    raw = str(data.get("filenamePrefix", "") or "").strip()
    if not raw:
        return default
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "_", raw).strip("_")
    return cleaned[:96] or default


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
    if regional_mode and not compiled.get("overridden"):
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
            "inputs": {"model": model_ref, "sampling": "v_prediction",
                       "zsnr": bool(sampling_profile.get("zsnr", False))},
        }
        model_ref = [sampling_id, 0]

    for lora in data.get("loras", []):
        name = str(lora.get("name", ""))
        if not name:
            continue
        comfy_name = comfy_lora_name(name)
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
                "model": model_ref, "lora_name": comfy_name, "strength_model": weight,
            }}
            model_ref = [node_id, 0]
        else:
            nodes[node_id] = {
                "class_type": "LoraLoader",
                "inputs": {"model": model_ref, "clip": clip_ref, "lora_name": comfy_name,
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
        freeu_defaults = sampling_profile.get("freeu") or {}
        enhance_id = alloc()
        nodes[enhance_id] = {
            "class_type": "FreeU_V2",
            "inputs": {
                "model": model_ref,
                "b1": bounded(enhancement.get("b1"), freeu_defaults.get("b1", 1.3), 0.0, 10.0, integer=False),
                "b2": bounded(enhancement.get("b2"), freeu_defaults.get("b2", 1.4), 0.0, 10.0, integer=False),
                "s1": bounded(enhancement.get("s1"), freeu_defaults.get("s1", 0.9), 0.0, 10.0, integer=False),
                "s2": bounded(enhancement.get("s2"), freeu_defaults.get("s2", 0.2), 0.0, 10.0, integer=False),
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
                    "lora_name": comfy_lora_name(r["lora"]),
                    "strength_model": weight, "strength_clip": weight,
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

    # Route 1: composite an anime character into a real background.  This is an
    # isolated two-pass inpaint graph: OpenPose controls the character pose,
    # background depth preserves scene geometry, and a low-denoise second pass
    # removes the cut-out edge while leaving the unmasked background intact.
    route1 = data.get("route1") or {}
    if isinstance(route1, dict) and route1.get("enabled"):
        if anima or krea2:
            raise ValueError("路线1的 Xinsir OpenPose / Depth ControlNet 仅支持 SDXL / Illustrious 模型。")
        if regional_mode:
            raise ValueError("路线1暂不与多人区域提示词同时使用，请先关闭多人分区。")
        image_name = validate_input_image(str(route1.get("image", "") or ""))
        mask_name = validate_input_image(str(route1.get("mask", "") or ""))
        pose_mode = str(route1.get("poseMode", "extract") or "extract")
        if pose_mode not in {"prompt", "extract", "skeleton"}:
            raise ValueError("路线1姿势模式无效。")
        pose_name = ""
        openpose_controlnet = str(route1.get("openposeControlnet", "") or "").strip()
        depth_controlnet = str(route1.get("depthControlnet", "") or "").strip()
        if pose_mode != "prompt":
            pose_name = validate_input_image(str(route1.get("poseImage", "") or ""))
            if not openpose_controlnet:
                raise ValueError("请选择路线1的 OpenPose ControlNet。")
        if not depth_controlnet:
            raise ValueError("请选择路线1的 Depth ControlNet。")

        image_name, mask_name, _original_size, working_size, _was_resized = (
            prepare_route1_working_assets(image_name, mask_name)
        )
        generation_mask_name, _headroom, _side_margin = prepare_route1_generation_mask(
            mask_name, working_size
        )
        smart_fusion = bool(route1.get("smartFusion", True))
        light_map_name, light_analysis = "", {}
        if smart_fusion:
            light_map_name, light_analysis = prepare_route1_environment_light(
                image_name, mask_name
            )

        light_direction = str(route1.get("lightDirection", "auto") or "auto").strip()
        light_prompts = {
            "upper_right": "strong directional sunlight from the upper right, warm highlights on the upper-right edges, cooler shadow on the lower-left side",
            "upper_left": "strong directional sunlight from the upper left, warm highlights on the upper-left edges, cooler shadow on the lower-right side",
            "right": "directional light from the right, bright right rim and softly shaded left side",
            "left": "directional light from the left, bright left rim and softly shaded right side",
            "backlight": "environment-matched backlight, restrained rim light and readable facial shadows",
        }
        light_prompt = str(light_analysis.get("prompt", "") or
                           "lighting direction inferred from the surrounding environment")
        if light_direction != "auto" and light_direction in light_prompts:
            light_prompt = ", ".join((
                light_prompt, "manual direction override", light_prompts[light_direction],
            ))
        blend_prompt = str(route1.get("blendPrompt", "") or "").strip()
        blend_prompt = ", ".join(part for part in (
            blend_prompt, light_prompt,
            "(exactly one character:1.3), (single centered subject:1.25), "
            "character centered inside the marked area, no foreground silhouette",
            "subtle environmental reflected light, natural ambient occlusion at character boundaries",
        ) if part)
        route_negative = str(route1.get("negativePrompt", "") or "").strip()
        route_negative = ", ".join(part for part in (
            route_negative,
            "second character, second person, foreground person, dark silhouette, "
            "giant silhouette, foreground figure, duplicate subject",
        ) if part)
        if blend_prompt:
            route_positive_id = alloc()
            nodes[route_positive_id] = {"class_type": "CLIPTextEncode", "inputs": {
                "text": ", ".join(part for part in (prompt, blend_prompt) if part), "clip": clip_ref,
            }}
            positive_ref = [route_positive_id, 0]
        if route_negative:
            route_negative_id = alloc()
            nodes[route_negative_id] = {"class_type": "CLIPTextEncode", "inputs": {
                "text": ", ".join(part for part in (negative, route_negative) if part), "clip": clip_ref,
            }}
            negative_ref = [route_negative_id, 0]

        load_image_id, load_mask_id, load_generation_mask_id = alloc(), alloc(), alloc()
        grow_mask_id, feather_mask_id = alloc(), alloc()
        nodes[load_image_id] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
        nodes[load_mask_id] = {"class_type": "LoadImageMask", "inputs": {
            "image": mask_name, "channel": "red",
        }}
        nodes[load_generation_mask_id] = {"class_type": "LoadImageMask", "inputs": {
            "image": generation_mask_name, "channel": "red",
        }}
        grow = bounded(route1.get("grow"), 8, 0, 64)
        feather = bounded(route1.get("feather"), 12, 0, 64)
        nodes[grow_mask_id] = {"class_type": "GrowMask", "inputs": {
            "mask": [load_generation_mask_id, 0], "expand": grow, "tapered_corners": True,
        }}
        nodes[feather_mask_id] = {"class_type": "FeatherMask", "inputs": {
            "mask": [grow_mask_id, 0], "left": feather, "top": feather,
            "right": feather, "bottom": feather,
        }}
        mask_ref = [feather_mask_id, 0]

        controlled_positive, controlled_negative = positive_ref, negative_ref
        if pose_mode != "prompt":
            pose_load_id = alloc()
            nodes[pose_load_id] = {"class_type": "LoadImage", "inputs": {"image": pose_name}}
            pose_image_ref = [pose_load_id, 0]
            if pose_mode == "extract":
                pose_pre_id = alloc()
                nodes[pose_pre_id] = {"class_type": "DWPreprocessor", "inputs": {
                    "image": pose_image_ref, "bbox_detector": "None",
                    "pose_estimator": "dw-ll_ucoco_384.onnx", "resolution": 1024,
                    "scale_stick_for_xinsr_cn": "enable",
                }}
                pose_image_ref = [pose_pre_id, 0]

            openpose_loader_id, openpose_apply_id = alloc(), alloc()
            nodes[openpose_loader_id] = {"class_type": "ControlNetLoader", "inputs": {
                "control_net_name": openpose_controlnet,
            }}
            pose_strength = bounded(route1.get("poseStrength"), 0.75, 0, 2, integer=False)
            pose_end = bounded(route1.get("poseEnd"), 0.85, 0, 1, integer=False)
            nodes[openpose_apply_id] = {"class_type": "ControlNetApplyAdvanced", "inputs": {
                "positive": positive_ref, "negative": negative_ref,
                "control_net": [openpose_loader_id, 0], "image": pose_image_ref,
                "strength": pose_strength, "start_percent": 0.0, "end_percent": pose_end,
            }}
            controlled_positive, controlled_negative = [openpose_apply_id, 0], [openpose_apply_id, 1]

        # Remove the original scene geometry from the character opening before
        # depth extraction. Otherwise a doorpost/tree inside the paint mask
        # competes with the requested body and can suppress it completely.
        depth_blank_id, depth_source_id = alloc(), alloc()
        working_width = working_size[0] if working_size[0] > 0 else width
        working_height = working_size[1] if working_size[1] > 0 else height
        nodes[depth_blank_id] = {"class_type": "EmptyImage", "inputs": {
            "width": working_width, "height": working_height,
            "batch_size": 1, "color": 0x7F7F7F,
        }}
        nodes[depth_source_id] = {"class_type": "ImageCompositeMasked", "inputs": {
            "destination": [load_image_id, 0], "source": [depth_blank_id, 0],
            "x": 0, "y": 0, "resize_source": False, "mask": mask_ref,
        }}

        depth_pre_id, depth_loader_id, depth_apply_id = alloc(), alloc(), alloc()
        nodes[depth_pre_id] = {"class_type": "DepthAnythingV2Preprocessor", "inputs": {
            "image": [depth_source_id, 0], "ckpt_name": "depth_anything_v2_vits.pth", "resolution": 1024,
        }}
        nodes[depth_loader_id] = {"class_type": "ControlNetLoader", "inputs": {
            "control_net_name": depth_controlnet,
        }}
        depth_strength = bounded(route1.get("depthStrength"), 0.45, 0, 2, integer=False)
        depth_end = bounded(route1.get("depthEnd"), 0.70, 0, 1, integer=False)
        nodes[depth_apply_id] = {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": controlled_positive, "negative": controlled_negative,
            "control_net": [depth_loader_id, 0], "image": [depth_pre_id, 0],
            "strength": depth_strength, "start_percent": 0.0, "end_percent": depth_end,
        }}

        pass1_condition_id, pass1_sampler_id, pass1_decode_id = alloc(), alloc(), alloc()
        nodes[pass1_condition_id] = {"class_type": "InpaintModelConditioning", "inputs": {
            "positive": [depth_apply_id, 0], "negative": [depth_apply_id, 1], "vae": vae_ref,
            "pixels": [load_image_id, 0], "mask": mask_ref, "noise_mask": True,
        }}
        nodes[pass1_sampler_id] = {"class_type": "KSampler", "inputs": {
            "seed": seed,
            "steps": bounded(route1.get("pass1Steps"), 28, 8, 60),
            "cfg": bounded(route1.get("pass1Cfg"), 6.5, 1, 15, integer=False),
            "sampler_name": "euler", "scheduler": "karras",
            "denoise": bounded(route1.get("pass1Denoise"), 0.85, 0.1, 1, integer=False),
            "model": model_ref, "positive": [pass1_condition_id, 0],
            "negative": [pass1_condition_id, 1], "latent_image": [pass1_condition_id, 2],
        }}
        nodes[pass1_decode_id] = {"class_type": "VAEDecode", "inputs": {
            "samples": [pass1_sampler_id, 0], "vae": vae_ref,
        }}

        pass2_condition_id, pass2_sampler_id, pass2_decode_id = alloc(), alloc(), alloc()
        nodes[pass2_condition_id] = {"class_type": "InpaintModelConditioning", "inputs": {
            "positive": positive_ref, "negative": negative_ref, "vae": vae_ref,
            "pixels": [pass1_decode_id, 0], "mask": mask_ref, "noise_mask": True,
        }}
        nodes[pass2_sampler_id] = {"class_type": "KSampler", "inputs": {
            "seed": min(seed + 1, 2**63 - 1),
            "steps": bounded(route1.get("pass2Steps"), 20, 8, 40),
            "cfg": bounded(route1.get("pass2Cfg"), 5.5, 1, 15, integer=False),
            "sampler_name": "dpmpp_2m", "scheduler": "karras",
            "denoise": bounded(route1.get("pass2Denoise"), 0.25, 0.05, 0.6, integer=False),
            "model": model_ref, "positive": [pass2_condition_id, 0],
            "negative": [pass2_condition_id, 1], "latent_image": [pass2_condition_id, 2],
        }}
        nodes[pass2_decode_id] = {"class_type": "VAEDecode", "inputs": {
            "samples": [pass2_sampler_id, 0], "vae": vae_ref,
        }}
        if smart_fusion:
            # RMBG supplies a soft alpha matte (including hair and translucent
            # detail). The user's rough mask is expanded and feathered before
            # multiplication, so it limits the search area without acting as a
            # hard cookie cutter. This is the practical trimap: foreground from
            # RMBG confidence, an uncertain soft boundary, and definite outside.
            # The rough mask only locates the search area. RMBG owns the final
            # silhouette; do not multiply it by the rough mask again, because a
            # character leaning outside that mask would be cut in half. Keep a
            # generous asymmetric crop around the area instead.
            crop_top = min(72, _headroom + grow + feather)
            crop_bottom = min(48, grow + feather)
            crop_side = min(112, _side_margin + grow + feather)
            crop_id, rmbg_id, restore_mask_id = alloc(), alloc(), alloc()
            nodes[crop_id] = {"class_type": "LayerUtility: CropByMask", "inputs": {
                "image": [pass2_decode_id, 0], "mask_for_crop": [load_mask_id, 0],
                "invert_mask": False, "detect": "min_bounding_rect",
                "top_reserve": crop_top, "bottom_reserve": crop_bottom,
                "left_reserve": crop_side, "right_reserve": crop_side,
            }}
            nodes[rmbg_id] = {"class_type": "LayerMask: RmBgUltra V2", "inputs": {
                "image": [crop_id, 0], "detail_method": "GuidedFilter",
                "detail_erode": 6, "detail_dilate": 8,
                "black_point": 0.02, "white_point": 0.98,
                "process_detail": True, "device": "cpu", "max_megapixels": 2.2,
            }}
            nodes[restore_mask_id] = {"class_type": "LayerUtility: RestoreCropBox", "inputs": {
                "background_image": [load_image_id, 0], "croped_image": [rmbg_id, 0],
                "invert_mask": False, "crop_box": [crop_id, 2],
                "croped_mask": [rmbg_id, 1],
            }}
            precise_mask_ref = [restore_mask_id, 1]

            # Analyze only the character's local crop. Whole-frame color transfer
            # is dominated by the already-identical background and barely affects
            # the subject. The aligned blurred light crop supplies a continuous
            # low-frequency illumination field instead of a classified light type.
            color_strength = bounded(route1.get("colorMatchStrength"), 0.28, 0, 0.8,
                                     integer=False)
            reference_crop_id, light_load_id, light_crop_id = alloc(), alloc(), alloc()
            nodes[reference_crop_id] = {"class_type": "LayerUtility: CropByMask", "inputs": {
                "image": [load_image_id, 0], "mask_for_crop": [load_mask_id, 0],
                "invert_mask": False, "detect": "min_bounding_rect",
                "top_reserve": crop_top, "bottom_reserve": crop_bottom,
                "left_reserve": crop_side, "right_reserve": crop_side,
            }}
            nodes[light_load_id] = {"class_type": "LoadImage", "inputs": {
                "image": light_map_name,
            }}
            nodes[light_crop_id] = {"class_type": "LayerUtility: CropByMask", "inputs": {
                "image": [light_load_id, 0], "mask_for_crop": [load_mask_id, 0],
                "invert_mask": False, "detect": "min_bounding_rect",
                "top_reserve": crop_top, "bottom_reserve": crop_bottom,
                "left_reserve": crop_side, "right_reserve": crop_side,
            }}
            color_match_id, light_blend_id, grain_id = alloc(), alloc(), alloc()
            nodes[color_match_id] = {"class_type": "ColorTransfer", "inputs": {
                "image_target": [crop_id, 0], "image_ref": [reference_crop_id, 0],
                "method": "reinhard_lab", "source_stats": "per_frame",
                "strength": color_strength,
            }}
            light_strength = bounded(route1.get("environmentLightStrength"), 0.22, 0, 0.6,
                                     integer=False)
            nodes[light_blend_id] = {"class_type": "ImageBlend", "inputs": {
                "image1": [color_match_id, 0], "image2": [light_crop_id, 0],
                "blend_factor": light_strength, "blend_mode": "soft_light",
            }}
            grain_strength = bounded(route1.get("grainStrength"), 0.035, 0, 0.12,
                                     integer=False)
            nodes[grain_id] = {"class_type": "LayerFilter: AddGrain", "inputs": {
                "image": [light_blend_id, 0], "grain_power": grain_strength,
                "grain_scale": 1.0, "grain_sat": 0.2,
            }}
            sharpen_strength = bounded(route1.get("sharpenStrength"), 0.10, 0, 0.15,
                                       integer=False)
            sharpen_id, edge_id, edge_mask_id = alloc(), alloc(), alloc()
            edge_grow_id, edge_feather_id, edge_limit_id = alloc(), alloc(), alloc()
            nodes[sharpen_id] = {"class_type": "ImageSharpen", "inputs": {
                "image": [grain_id, 0], "sharpen_radius": 1,
                "sigma": 0.8, "alpha": sharpen_strength,
            }}
            nodes[edge_id] = {"class_type": "Canny", "inputs": {
                "image": [grain_id, 0], "low_threshold": 0.25, "high_threshold": 0.65,
            }}
            nodes[edge_mask_id] = {"class_type": "ImageToMask", "inputs": {
                "image": [edge_id, 0], "channel": "red",
            }}
            nodes[edge_grow_id] = {"class_type": "GrowMask", "inputs": {
                "mask": [edge_mask_id, 0], "expand": 1, "tapered_corners": True,
            }}
            nodes[edge_feather_id] = {"class_type": "FeatherMask", "inputs": {
                "mask": [edge_grow_id, 0], "left": 2, "top": 2,
                "right": 2, "bottom": 2,
            }}
            nodes[edge_limit_id] = {"class_type": "MaskComposite", "inputs": {
                "destination": [edge_feather_id, 0], "source": [rmbg_id, 1],
                "x": 0, "y": 0, "operation": "multiply",
            }}
            sharpen_composite_id = alloc()
            nodes[sharpen_composite_id] = {"class_type": "ImageCompositeMasked", "inputs": {
                "destination": [grain_id, 0], "source": [sharpen_id, 0],
                "x": 0, "y": 0, "resize_source": False, "mask": [edge_limit_id, 0],
            }}
            processed_restore_id, base_composite_id = alloc(), alloc()
            nodes[processed_restore_id] = {
                "class_type": "LayerUtility: RestoreCropBox", "inputs": {
                    "background_image": [pass2_decode_id, 0],
                    "croped_image": [sharpen_composite_id, 0], "invert_mask": False,
                    "crop_box": [crop_id, 2], "croped_mask": [rmbg_id, 1],
                },
            }
            nodes[base_composite_id] = {"class_type": "ImageCompositeMasked", "inputs": {
                "destination": [load_image_id, 0], "source": [processed_restore_id, 0],
                "x": 0, "y": 0, "resize_source": False, "mask": precise_mask_ref,
            }}

            # Only redraw a resolution-adaptive band around the alpha boundary.
            # The shrunken inner mask protects the face and character core.
            ring_radius = max(12, min(32, round(max(working_width, working_height) / 64)))
            inner_radius = max(6, ring_radius // 2)
            ring_feather = max(4, min(12, round(ring_radius / 3)))
            outer_id, outer_feather_id, inner_id, ring_id = alloc(), alloc(), alloc(), alloc()
            nodes[outer_id] = {"class_type": "GrowMask", "inputs": {
                "mask": precise_mask_ref, "expand": ring_radius, "tapered_corners": True,
            }}
            nodes[outer_feather_id] = {"class_type": "FeatherMask", "inputs": {
                "mask": [outer_id, 0], "left": ring_feather, "top": ring_feather,
                "right": ring_feather, "bottom": ring_feather,
            }}
            nodes[inner_id] = {"class_type": "GrowMask", "inputs": {
                "mask": precise_mask_ref, "expand": -inner_radius,
                "tapered_corners": True,
            }}
            nodes[ring_id] = {"class_type": "MaskComposite", "inputs": {
                "destination": [outer_feather_id, 0], "source": [inner_id, 0],
                "x": 0, "y": 0, "operation": "subtract",
            }}

            fusion_condition_id, fusion_sampler_id, fusion_decode_id = alloc(), alloc(), alloc()
            nodes[fusion_condition_id] = {"class_type": "InpaintModelConditioning", "inputs": {
                "positive": positive_ref, "negative": negative_ref, "vae": vae_ref,
                "pixels": [base_composite_id, 0], "mask": [ring_id, 0], "noise_mask": True,
            }}
            nodes[fusion_sampler_id] = {"class_type": "KSampler", "inputs": {
                "seed": min(seed + 2, 2**63 - 1),
                "steps": bounded(route1.get("fusionSteps"), 12, 6, 24),
                "cfg": bounded(route1.get("fusionCfg"), 4.5, 2, 8, integer=False),
                "sampler_name": "dpmpp_2m", "scheduler": "karras",
                "denoise": bounded(route1.get("fusionDenoise"), 0.18, 0.1, 0.26,
                                   integer=False),
                "model": model_ref, "positive": [fusion_condition_id, 0],
                "negative": [fusion_condition_id, 1],
                "latent_image": [fusion_condition_id, 2],
            }}
            nodes[fusion_decode_id] = {"class_type": "VAEDecode", "inputs": {
                "samples": [fusion_sampler_id, 0], "vae": vae_ref,
            }}
            final_composite_id = alloc()
            nodes[final_composite_id] = {"class_type": "ImageCompositeMasked", "inputs": {
                "destination": [base_composite_id, 0], "source": [fusion_decode_id, 0],
                "x": 0, "y": 0, "resize_source": False, "mask": [ring_id, 0],
            }}
        else:
            final_composite_id = alloc()
            nodes[final_composite_id] = {"class_type": "ImageCompositeMasked", "inputs": {
                "destination": [load_image_id, 0], "source": [pass2_decode_id, 0],
                "x": 0, "y": 0, "resize_source": False, "mask": mask_ref,
            }}
        save_id = alloc()
        nodes[save_id] = {"class_type": "SaveImage", "inputs": {
            "filename_prefix": "EasyPanel_Route1", "images": [final_composite_id, 0],
        }}
        return {"prompt": nodes, "client_id": "easy-panel"}

    # Local repaint: encode the uploaded image with a hand-drawn mask so the
    # KSampler only re-draws the masked region (denoise < 1 keeps the rest).
    # Whole-image redraw (img2img): encode a base image (e.g. a Krea 2 render) and
    # re-draw it with the current model at denoise < 1. Works for Anima / Krea 2 /
    # Illustrious alike, which is how the Krea 2 -> Illustrious/Anima anime pass works.
    sampling_width, sampling_height = width, height
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
        if _iw > 0 and _ih > 0:
            # VAEEncode crops to the model's spatial alignment. Keep the hires
            # target based on the latent size that the first sampler really sees.
            sampling_width = max(8, _iw - _iw % 8)
            sampling_height = max(8, _ih - _ih % 8)
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

    depth = data.get("depth") or {}
    if not isinstance(depth, dict):
        raise ValueError("Depth 空间控制设置格式无效。")
    if depth.get("enabled"):
        if anima or krea2:
            raise ValueError("当前 Xinsir Depth ControlNet 仅支持 SDXL / Illustrious，不能用于 Anima / Krea 2。")
        depth_image = validate_input_image(str(depth.get("image", "") or ""))
        depth_controlnet = str(depth.get("controlnet", "") or "").strip()
        if not depth_controlnet:
            raise ValueError("请选择 Depth ControlNet。")
        depth_strength = bounded(depth.get("strength"), 0.55, 0, 2, integer=False)
        depth_start = bounded(depth.get("start"), 0, 0, 1, integer=False)
        depth_end = bounded(depth.get("end"), 0.75, 0, 1, integer=False)
        if depth_end < depth_start:
            raise ValueError("Depth 控制结束比例不能早于开始比例。")
        depth_load_id, depth_pre_id, depth_cn_id, depth_apply_id = [alloc() for _ in range(4)]
        nodes[depth_load_id] = {"class_type": "LoadImage", "inputs": {"image": depth_image}}
        nodes[depth_pre_id] = {"class_type": "DepthAnythingV2Preprocessor", "inputs": {
            "image": [depth_load_id, 0], "ckpt_name": "depth_anything_v2_vits.pth",
            "resolution": 1024,
        }}
        nodes[depth_cn_id] = {"class_type": "ControlNetLoader", "inputs": {
            "control_net_name": depth_controlnet,
        }}
        nodes[depth_apply_id] = {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": positive_ref, "negative": negative_ref,
            "control_net": [depth_cn_id, 0], "image": [depth_pre_id, 0],
            "strength": depth_strength, "start_percent": depth_start,
            "end_percent": depth_end,
        }}
        positive_ref, negative_ref = [depth_apply_id, 0], [depth_apply_id, 1]

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
    color_reference_ref = None
    hires_enabled = bool(capabilities.get("hires_fix")) and not anima and not krea2 and (
        str(data.get("illustriousMode", "precision")) == "hires"
    )
    if hires_enabled:
        hires_defaults = sampling_profile.get("hires") or {}
        scale = bounded(data.get("hiresScale"), hires_defaults.get("scale", 1.25),
                        1.0, 8.0, integer=False)
        hires_denoise = bounded(data.get("hiresDenoise"), hires_defaults.get("denoise", 0.35),
                                0.05, 1.0, integer=False)
        hires_steps = bounded(data.get("hiresSteps"), hires_defaults.get("steps", 20), 1, 150)
        hires_cfg = bounded(data.get("hiresCfg"), hires_defaults.get("cfg", 4.5), 1, 30, integer=False)
        hires_sampler = str(hires_defaults.get("sampler", "auto") or "auto")
        hires_scheduler = str(hires_defaults.get("scheduler", "auto") or "auto")
        requested_hires_sampler = str(data.get("hiresSampler", "") or "").strip()
        requested_hires_scheduler = str(data.get("hiresScheduler", "") or "").strip()
        if requested_hires_sampler and requested_hires_sampler != "auto":
            hires_sampler = requested_hires_sampler
        if requested_hires_scheduler and requested_hires_scheduler != "auto":
            hires_scheduler = requested_hires_scheduler
        if hires_sampler == "auto":
            hires_sampler = sampler_name
        if hires_scheduler == "auto":
            hires_scheduler = scheduler
        # Two-stage prompts: the first pass decides composition, the second pass
        # only adds detail. Regional conditioning is a masked graph instead of
        # plain text, so it always keeps the first-stage refs.
        hires_mode = normalized_hires_prompt_mode(data)
        if regional_mode:
            hires_mode = "inherit"
        hires_positive_text, hires_negative_text = merge_hires_prompt(
            base_positive, negative,
            str(data.get("hiresPositive", "") or "")[:4000],
            str(data.get("hiresNegative", "") or "")[:4000], hires_mode)
        hires_positive_ref, hires_negative_ref = positive_ref, negative_ref
        if hires_mode != "inherit":
            hires_positive_id, hires_negative_id = alloc(), alloc()
            nodes[hires_positive_id] = {"class_type": "CLIPTextEncode", "inputs": {
                "text": hires_positive_text, "clip": clip_ref}}
            nodes[hires_negative_id] = {"class_type": "CLIPTextEncode", "inputs": {
                "text": hires_negative_text, "clip": clip_ref}}
            hires_positive_ref = [hires_positive_id, 0]
            hires_negative_ref = [hires_negative_id, 0]
        # Match JavaScript Math.round used by the size preview. Python round()
        # uses bankers' rounding and disagrees at exact .5 boundaries.
        hires_width = max(8, int(sampling_width * scale / 8 + 0.5) * 8)
        hires_height = max(8, int(sampling_height * scale / 8 + 0.5) * 8)
        base_decode_id, upscale_loader_id, model_upscale_id, resize_id, hires_encode_id, hires_sampler_id = (
            alloc(), alloc(), alloc(), alloc(), alloc(), alloc()
        )

        # Decode before resizing so the learned anime upscaler can reconstruct
        # line art and texture in pixel space. Its native output is 4x; resize it
        # back to the requested 1.10-1.50x target before VAE encoding/refinement.
        if vae_mode == "tiled":
            nodes[base_decode_id] = {"class_type": "VAEDecodeTiled", "inputs": {
                "samples": sample_ref, "vae": vae_ref,
                "tile_size": vae_tile_size, "overlap": vae_overlap,
                "temporal_size": 64, "temporal_overlap": 8,
            }}
        else:
            nodes[base_decode_id] = {"class_type": "VAEDecode", "inputs": {
                "samples": sample_ref, "vae": vae_ref,
            }}
        color_reference_ref = [base_decode_id, 0]
        nodes[upscale_loader_id] = {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": HIRES_UPSCALE_MODEL},
        }
        nodes[model_upscale_id] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": [upscale_loader_id, 0],
                       "image": [base_decode_id, 0]},
        }
        nodes[resize_id] = {
            "class_type": "ImageScale",
            "inputs": {"image": [model_upscale_id, 0], "upscale_method": "lanczos",
                       "width": hires_width, "height": hires_height, "crop": "disabled"},
        }
        if vae_mode == "tiled":
            nodes[hires_encode_id] = {"class_type": "VAEEncodeTiled", "inputs": {
                "pixels": [resize_id, 0], "vae": vae_ref,
                "tile_size": vae_tile_size, "overlap": vae_overlap,
                "temporal_size": 64, "temporal_overlap": 8,
            }}
        else:
            nodes[hires_encode_id] = {"class_type": "VAEEncode", "inputs": {
                "pixels": [resize_id, 0], "vae": vae_ref,
            }}
        nodes[hires_sampler_id] = {
            "class_type": "KSampler",
            "inputs": {"seed": seed, "steps": hires_steps, "cfg": hires_cfg,
                       "sampler_name": hires_sampler, "scheduler": hires_scheduler,
                       "denoise": hires_denoise, "model": model_ref,
                       "positive": hires_positive_ref, "negative": hires_negative_ref,
                       "latent_image": [hires_encode_id, 0]},
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

    image_ref = [decode_id, 0]

    # Output enhancement is separate from generative hires. This gives Anima and
    # Krea 2 a safe post-only upscale path and reserves tiled diffusion for large
    # SDXL/Illustrious exports. Combining both would multiply pixels twice and is
    # almost always an accidental OOM, so the API rejects it explicitly.
    output_enhancement = data.get("outputEnhancement") or {}
    if not isinstance(output_enhancement, dict):
        raise ValueError("输出增强设置格式无效。")
    post_mode = str(output_enhancement.get("mode", "off") or "off")
    if post_mode not in {"off", "anime6b", "seedvr2", "ultimate"}:
        raise ValueError("未知的输出增强模式。")
    if hires_enabled and post_mode != "off":
        raise ValueError("高清二次采样与输出超分不能同时开启；请选择其中一种，避免重复放大和显存溢出。")
    if repair and post_mode != "off":
        raise ValueError("局部修复不能同时执行整图输出超分；请先完成修复，再把结果作为底图放大。")
    post_scale = bounded(output_enhancement.get("scale"), 1.5, 1.1, 4.0, integer=False)
    post_width = max(8, int(sampling_width * post_scale / 8 + 0.5) * 8)
    post_height = max(8, int(sampling_height * post_scale / 8 + 0.5) * 8)
    if post_mode != "off" and color_reference_ref is None:
        color_reference_ref = image_ref

    if post_mode == "anime6b":
        loader_id, upscale_id, resize_id = alloc(), alloc(), alloc()
        nodes[loader_id] = {"class_type": "UpscaleModelLoader",
                            "inputs": {"model_name": HIRES_UPSCALE_MODEL}}
        nodes[upscale_id] = {"class_type": "ImageUpscaleWithModel", "inputs": {
            "upscale_model": [loader_id, 0], "image": image_ref,
        }}
        nodes[resize_id] = {"class_type": "ImageScale", "inputs": {
            "image": [upscale_id, 0], "upscale_method": "lanczos",
            "width": post_width, "height": post_height, "crop": "disabled",
        }}
        image_ref = [resize_id, 0]
    elif post_mode == "seedvr2":
        resize_id, preprocess_id, seed_model_id, seed_vae_id = [alloc() for _ in range(4)]
        seed_encode_id, seed_cond_id, seed_sampler_id, seed_decode_id, seed_post_id = [alloc() for _ in range(5)]
        nodes[resize_id] = {"class_type": "ImageScale", "inputs": {
            "image": image_ref, "upscale_method": "lanczos",
            "width": post_width, "height": post_height, "crop": "disabled",
        }}
        nodes[preprocess_id] = {"class_type": "SeedVR2Preprocess",
                                "inputs": {"resized_images": [resize_id, 0]}}
        nodes[seed_model_id] = {"class_type": "UNETLoader",
                                "inputs": {"unet_name": SEEDVR2_MODEL, "weight_dtype": "default"}}
        nodes[seed_vae_id] = {"class_type": "VAELoader", "inputs": {"vae_name": SEEDVR2_VAE}}
        nodes[seed_encode_id] = {"class_type": "VAEEncodeTiled", "inputs": {
            "pixels": [preprocess_id, 0], "vae": [seed_vae_id, 0],
            "tile_size": 512, "overlap": 128, "temporal_size": 4096, "temporal_overlap": 8,
        }}
        nodes[seed_cond_id] = {"class_type": "SeedVR2Conditioning", "inputs": {
            "model": [seed_model_id, 0], "vae_conditioning": [seed_encode_id, 0],
        }}
        nodes[seed_sampler_id] = {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 1, "cfg": 1.0, "sampler_name": "euler",
            "scheduler": "simple", "denoise": 1.0, "model": [seed_model_id, 0],
            "positive": [seed_cond_id, 0], "negative": [seed_cond_id, 1],
            "latent_image": [seed_encode_id, 0],
        }}
        nodes[seed_decode_id] = {"class_type": "VAEDecodeTiled", "inputs": {
            "samples": [seed_sampler_id, 0], "vae": [seed_vae_id, 0],
            "tile_size": 512, "overlap": 128, "temporal_size": 4096, "temporal_overlap": 8,
        }}
        seed_color_method = str(output_enhancement.get("seedvrColor", "lab") or "lab")
        if seed_color_method not in {"lab", "wavelet", "adain", "none"}:
            seed_color_method = "lab"
        nodes[seed_post_id] = {"class_type": "SeedVR2PostProcessing", "inputs": {
            "images": [seed_decode_id, 0], "original_resized_images": [resize_id, 0],
            "color_correction_method": seed_color_method,
        }}
        image_ref = [seed_post_id, 0]
    elif post_mode == "ultimate":
        if anima or krea2:
            raise ValueError("Ultimate SD Upscale 仅对 SDXL / Illustrious 开放；Anima / Krea 2 请使用后处理超分。")
        loader_id, ultimate_id = alloc(), alloc()
        nodes[loader_id] = {"class_type": "UpscaleModelLoader",
                            "inputs": {"model_name": HIRES_UPSCALE_MODEL}}
        nodes[ultimate_id] = {"class_type": "UltimateSDUpscale", "inputs": {
            "image": image_ref, "model": model_ref, "positive": positive_ref,
            "negative": negative_ref, "vae": vae_ref, "upscale_by": post_scale,
            "seed": seed, "steps": bounded(output_enhancement.get("steps"), 20, 8, 40),
            "cfg": bounded(output_enhancement.get("cfg"), sampling_profile.get("hires", {}).get("cfg", cfg),
                           1, 15, integer=False),
            "sampler_name": sampler_name, "scheduler": scheduler,
            "denoise": bounded(output_enhancement.get("denoise"), 0.2, 0.05, 0.6, integer=False),
            "upscale_model": [loader_id, 0], "mode_type": "Linear",
            "tile_width": bounded(output_enhancement.get("tileSize"), 512, 256, 1024),
            "tile_height": bounded(output_enhancement.get("tileSize"), 512, 256, 1024),
            "mask_blur": 8, "tile_padding": 32, "seam_fix_mode": "None",
            "seam_fix_denoise": 1.0, "seam_fix_width": 64,
            "seam_fix_mask_blur": 8, "seam_fix_padding": 16,
            "force_uniform_tiles": True, "tiled_decode": vae_mode == "tiled", "batch_size": 1,
        }}
        image_ref = [ultimate_id, 0]

    detailer = output_enhancement.get("faceDetailer") or {}
    detailer_enabled = bool(isinstance(detailer, dict) and detailer.get("enabled"))
    limb_detailer = output_enhancement.get("limbDetailer") or {}
    if not isinstance(limb_detailer, dict):
        raise ValueError("手脚修复设置格式无效。")
    hand_detailer_enabled = bool(limb_detailer.get("hands"))
    foot_detailer_enabled = bool(limb_detailer.get("feet"))
    limb_detailer_allowed = not krea2 and not regional_mode and not repair
    auto_color = output_enhancement.get("colorMatch") or {}
    if (isinstance(auto_color, dict) and auto_color.get("enabled")
            and color_reference_ref is None
            and (detailer_enabled or (limb_detailer_allowed
                                      and (hand_detailer_enabled or foot_detailer_enabled)))):
        color_reference_ref = image_ref
    if detailer_enabled:
        if krea2:
            raise ValueError("Krea 2 Turbo 不启用 FaceDetailer；请使用参考图或后处理超分保持五官。")
        if regional_mode:
            raise ValueError("多人分区不能自动运行单路 FaceDetailer；请生成后使用局部修复逐人处理。")
        detector_id, detailer_id = alloc(), alloc()
        nodes[detector_id] = {"class_type": "UltralyticsDetectorProvider",
                              "inputs": {"model_name": FACE_DETECTOR_MODEL}}
        nodes[detailer_id] = {"class_type": "FaceDetailer", "inputs": {
            "image": image_ref, "model": model_ref, "clip": clip_ref, "vae": vae_ref,
            "guide_size": bounded(detailer.get("guideSize"), 512, 256, 1024),
            "guide_size_for": True, "max_size": 1024, "seed": seed,
            "steps": bounded(detailer.get("steps"), 12, 6, 30),
            "cfg": bounded(detailer.get("cfg"), sampling_profile.get("hires", {}).get("cfg", cfg),
                           1, 15, integer=False),
            "sampler_name": sampler_name, "scheduler": scheduler,
            "positive": positive_ref, "negative": negative_ref,
            "denoise": bounded(detailer.get("denoise"), 0.35, 0.15, 0.65, integer=False),
            "feather": 5, "noise_mask": True, "force_inpaint": True,
            "bbox_threshold": 0.3, "bbox_dilation": 10, "bbox_crop_factor": 3.0,
            "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
            "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False", "drop_size": 10,
            "bbox_detector": [detector_id, 0], "wildcard": "", "cycle": 1,
            "noise_mask_feather": 20, "tiled_encode": vae_mode == "tiled",
            "tiled_decode": vae_mode == "tiled",
        }}
        image_ref = [detailer_id, 0]

    def apply_limb_detailer(current_image: list, detector_model: str,
                            positive_suffix: str, negative_suffix: str) -> list:
        positive_encode_id, negative_encode_id, detector_id, detailer_id = [alloc() for _ in range(4)]
        nodes[positive_encode_id] = {"class_type": "CLIPTextEncode", "inputs": {
            "text": unique_prompt_terms(prompt, positive_suffix), "clip": clip_ref,
        }}
        nodes[negative_encode_id] = {"class_type": "CLIPTextEncode", "inputs": {
            "text": unique_prompt_terms(negative, negative_suffix), "clip": clip_ref,
        }}
        nodes[detector_id] = {"class_type": "UltralyticsDetectorProvider",
                              "inputs": {"model_name": detector_model}}
        nodes[detailer_id] = {"class_type": "FaceDetailer", "inputs": {
            "image": current_image, "model": model_ref, "clip": clip_ref, "vae": vae_ref,
            "guide_size": bounded(limb_detailer.get("guideSize"), 512, 256, 1024),
            "guide_size_for": True, "max_size": 1024, "seed": seed,
            "steps": bounded(limb_detailer.get("steps"), 12, 8, 30),
            "cfg": bounded(limb_detailer.get("cfg"),
                           sampling_profile.get("hires", {}).get("cfg", cfg),
                           1, 15, integer=False),
            "sampler_name": sampler_name, "scheduler": scheduler,
            "positive": [positive_encode_id, 0], "negative": [negative_encode_id, 0],
            "denoise": bounded(limb_detailer.get("denoise"), 0.35, 0.15, 0.6,
                               integer=False),
            "feather": 8, "noise_mask": True, "force_inpaint": True,
            # Limb detectors are prone to mistaking ropes, lanterns and small
            # background decorations for hands/feet.  Keep the pass local and
            # require a confident, non-trivial detection before inpainting.
            "bbox_threshold": 0.5, "bbox_dilation": 8, "bbox_crop_factor": 1.8,
            "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
            "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False", "drop_size": 32,
            "bbox_detector": [detector_id, 0], "wildcard": "", "cycle": 1,
            "noise_mask_feather": 12, "tiled_encode": vae_mode == "tiled",
            "tiled_decode": vae_mode == "tiled",
        }}
        return [detailer_id, 0]

    def editable_limb_prompt(key: str, fallback: str) -> str:
        return str(limb_detailer.get(key, fallback) or "").strip()

    if limb_detailer_allowed and hand_detailer_enabled:
        default_hand_positive = ("anatomically correct hands, detailed gloves, correct finger shapes, "
                         "sharp hand details, clean lineart") if "glove" in prompt.lower() else (
            "anatomically correct hands, five fingers on each hand, separated fingers, "
            "natural hand pose, sharp hand details, clean lineart"
        )
        hand_positive = editable_limb_prompt("handPositive", default_hand_positive)
        hand_negative = editable_limb_prompt(
            "handNegative",
            "bad hands, malformed hands, extra fingers, missing fingers, fused fingers, blurry hands",
        )
        image_ref = apply_limb_detailer(
            image_ref, HAND_DETECTOR_MODEL, hand_positive,
            hand_negative,
        )
    if limb_detailer_allowed and foot_detailer_enabled:
        normalized_positive = prompt.lower().replace("_", " ")
        toes_visible = any(token in normalized_positive for token in
                           ("barefoot", "bare feet", "toe", "sandals", "open toe"))
        default_foot_positive = (
            "anatomically correct feet, five toes on each foot, separated toes, natural foot pose, "
            "sharp foot details, clean lineart"
        ) if toes_visible else (
            "anatomically correct feet, detailed footwear, correct shoe shape, "
            "sharp foot details, clean lineart"
        )
        foot_positive = editable_limb_prompt("footPositive", default_foot_positive)
        foot_negative = editable_limb_prompt(
            "footNegative",
            "bad feet, malformed feet, extra toes, missing toes, fused toes, blurry feet",
        )
        image_ref = apply_limb_detailer(
            image_ref, FOOT_DETECTOR_MODEL, foot_positive,
            foot_negative,
        )

    if isinstance(auto_color, dict) and auto_color.get("enabled") and color_reference_ref:
        color_method = str(auto_color.get("method", "reinhard_lab") or "reinhard_lab")
        if color_method not in {"reinhard_lab", "mkl_lab", "histogram"}:
            color_method = "reinhard_lab"
        color_match_id = alloc()
        nodes[color_match_id] = {"class_type": "ColorTransfer", "inputs": {
            "image_target": image_ref, "image_ref": color_reference_ref,
            "method": color_method, "source_stats": "per_frame",
            "strength": bounded(auto_color.get("strength"), 0.7, 0.0, 1.0, integer=False),
        }}
        image_ref = [color_match_id, 0]

    # Optional manual post-processing uses the installed ComfyUI_LayerStyle pack.
    # The chain is deliberately absent when disabled, so the default workflow stays unchanged.
    color = data.get("colorCorrection", {})
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

    transparent = data.get("transparentBackground") or {}
    if not isinstance(transparent, dict):
        raise ValueError("透明背景设置格式无效。")
    transparent_mode = str(transparent.get("mode", "off") or "off")
    if transparent_mode not in {"off", "auto", "complex"}:
        raise ValueError("未知的透明背景模式。")

    if transparent_mode != "off":
        # Keep the RGB source by default.  It is useful both as a normal result
        # and as the pixel source when the browser-side manual alpha editor
        # restores hair, ribbons, translucent fabric or small accessories.
        if transparent.get("keepOriginal", True):
            original_save_id = alloc()
            nodes[original_save_id] = {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": safe_generation_filename_prefix(data, "EasyPanel") + ("_RGB" if data.get("filenamePrefix") else ""), "images": image_ref},
            }

        detail_method = str(transparent.get("detailMethod", "GuidedFilter") or "GuidedFilter")
        if detail_method not in {"GuidedFilter", "PyMatting", "VITMatte", "VITMatte(local)",
                                 "vitmatte-base-composition-1k"}:
            detail_method = "GuidedFilter"
        rmbg_id = alloc()
        nodes[rmbg_id] = {
            "class_type": "LayerMask: RmBgUltra V2",
            "inputs": {
                "image": image_ref,
                "detail_method": detail_method,
                "detail_erode": bounded(transparent.get("detailErode"), 6, 1, 255),
                "detail_dilate": bounded(transparent.get("detailDilate"), 6, 1, 255),
                "black_point": bounded(transparent.get("blackPoint"), 0.01, 0.01, 0.98,
                                       integer=False),
                "white_point": bounded(transparent.get("whitePoint"), 0.99, 0.02, 0.99,
                                       integer=False),
                "process_detail": transparent_mode == "complex",
                "device": "cuda",
                "max_megapixels": bounded(transparent.get("maxMegapixels"), 2.0, 1.0, 16.0,
                                          integer=False),
            },
        }
        image_ref = [rmbg_id, 0]

    save_id = alloc()
    default_prefix = "EasyPanel_Transparent" if transparent_mode != "off" else "EasyPanel"
    filename_prefix = safe_generation_filename_prefix(data, default_prefix)
    if transparent_mode != "off" and data.get("filenamePrefix"):
        filename_prefix += "_Transparent"
    nodes[save_id] = {"class_type": "SaveImage", "inputs": {
        "filename_prefix": filename_prefix, "images": image_ref,
    }}
    return {"prompt": nodes, "client_id": "easy-panel"}


def build_clarity_upscale_workflow(data: dict) -> dict:
    """Upscale one existing output without diffusion or prompt regeneration."""
    if not isinstance(data, dict):
        raise ValueError("清晰版请求格式无效。")
    image_name = prepare_generation_image(str(data.get("name", "") or ""))
    scale = bounded(data.get("scale"), 1.5, 1.1, 2.0, integer=False)
    nodes = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {
            "model_name": HIRES_UPSCALE_MODEL,
        }},
        "3": {"class_type": "ImageUpscaleWithModel", "inputs": {
            "upscale_model": ["2", 0], "image": ["1", 0],
        }},
        # Anime6B outputs 4x. Scale it back to the requested delivery size so
        # the image gains reconstructed edges without creating a huge 4x file.
        "4": {"class_type": "ImageScaleBy", "inputs": {
            "image": ["3", 0], "upscale_method": "lanczos",
            "scale_by": scale / 4.0,
        }},
        "5": {"class_type": "SaveImage", "inputs": {
            "filename_prefix": "EasyPanel_Clarity", "images": ["4", 0],
        }},
    }
    return {"prompt": nodes, "client_id": "easy-panel-clarity"}


def _model_file(model_name: str) -> Path | None:
    relative = Path(str(model_name or "").replace("\\", os.sep).replace("/", os.sep))
    candidates = [CHECKPOINT_DIR / relative, COMFY_MODELS / "diffusion_models" / relative,
                  COMFY_MODELS / "unet" / relative]
    return next((path for path in candidates if path.is_file()), None)


def _lora_file(lora_name: str) -> Path | None:
    relative = Path(str(lora_name or "").replace("\\", os.sep).replace("/", os.sep))
    direct = LORA_DIR / relative
    if direct.is_file():
        return direct
    basename = relative.name.casefold()
    if LORA_DIR.is_dir():
        return next((path for path in LORA_DIR.rglob("*")
                     if path.is_file() and path.name.casefold() == basename), None)
    return None


def file_signature(path: Path | None) -> dict:
    """Fast content fingerprint: size plus first/last 1 MiB, cached by stat."""
    if path is None or not path.is_file():
        return {"exists": False, "size": None, "mtime_ns": None, "fingerprint": ""}
    stat = path.stat()
    cache_key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    cached = _FILE_SIGNATURE_CACHE.get(cache_key)
    if cached:
        return dict(cached)
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(1024 * 1024))
        if stat.st_size > 1024 * 1024:
            handle.seek(max(0, stat.st_size - 1024 * 1024))
            digest.update(handle.read(1024 * 1024))
    result = {"exists": True, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
              "fingerprint": digest.hexdigest(), "path": str(path)}
    _FILE_SIGNATURE_CACHE[cache_key] = result
    return dict(result)


def snapshot_environment(data: dict) -> dict:
    return {
        "panelVersion": PANEL_VERSION,
        "model": {"name": str(data.get("model", "")),
                  **file_signature(_model_file(str(data.get("model", ""))))},
        "characterLoras": [{"name": str(item.get("name", "")), "weight": item.get("weight")}
                           for item in (data.get("characterLoras") or []) if isinstance(item, dict)],
        "styleLoras": [{"name": str(item.get("name", "")), "weight": item.get("weight")}
                       for item in (data.get("styleLoras") or []) if isinstance(item, dict)],
        "loras": [{"name": str(item.get("name", "")), "weight": item.get("weight"),
                   **file_signature(_lora_file(str(item.get("name", ""))))}
                  for item in (data.get("loras") or []) if isinstance(item, dict)],
    }


def load_snapshots() -> list[dict]:
    if not SNAPSHOT_FILE.is_file():
        return []
    try:
        parsed = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def write_snapshots(items: list[dict]) -> None:
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = SNAPSHOT_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(items[-200:], ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, SNAPSHOT_FILE)


def _snapshot_scalar(value, max_text: int = 4096):
    """Keep JSON scalars while preventing accidental oversized metadata."""
    if isinstance(value, str):
        return value[:max_text]
    if isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    return None


def _snapshot_json_clone(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return {}


def _snapshot_safe_value(value, depth: int = 0, max_text: int = 4096):
    """Copy known JSON data and drop secret-looking keys from nested options."""
    if depth > 5:
        return None
    scalar = _snapshot_scalar(value, max_text)
    if scalar is not None:
        return scalar
    if isinstance(value, list):
        result = []
        for item in value[:64]:
            cleaned = _snapshot_safe_value(item, depth + 1, max_text)
            if cleaned is not None:
                result.append(cleaned)
        return result
    if isinstance(value, dict):
        result = {}
        for raw_key, raw_value in list(value.items())[:96]:
            key = str(raw_key)
            lowered = key.casefold().replace("-", "_")
            if any(marker in lowered for marker in SNAPSHOT_SECRET_KEY_MARKERS):
                continue
            cleaned = _snapshot_safe_value(raw_value, depth + 1, max_text)
            if cleaned is not None:
                result[key] = cleaned
        return result
    return None


def _snapshot_safe_mapping(value, allowed_keys: set[str] | None = None) -> dict:
    if not isinstance(value, dict):
        return {}
    result = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        if allowed_keys is not None and key not in allowed_keys:
            continue
        lowered = key.casefold().replace("-", "_")
        if any(marker in lowered for marker in SNAPSHOT_SECRET_KEY_MARKERS):
            continue
        cleaned = _snapshot_safe_value(raw_value)
        if cleaned is not None:
            result[key] = cleaned
    return result


def _snapshot_text(value, limit: int = 4096) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return str(value).strip()[:limit]


def _snapshot_value(payload: dict, request_generation: dict, key: str):
    value = payload.get(key)
    if value is None or value == "":
        value = request_generation.get(key)
    return value


def _snapshot_characters(source_request: dict) -> list[dict]:
    visual = source_request.get("visual") if isinstance(source_request.get("visual"), dict) else source_request
    raw_characters = visual.get("characters") if isinstance(visual.get("characters"), list) else []
    allowed = {
        "id", "name", "gender", "trigger", "appearance", "outfit", "outfitPrompt",
        "expression", "pose", "action", "heldItems", "held_items", "prompt", "extra",
        "extraPrompt", "style", "mode", "appearance_variant_id", "appearance_preset_id",
        "clothingPresetId", "appearancePresetId", "characterPresetId", "loras",
    }
    result = []
    for raw in raw_characters[:6]:
        if isinstance(raw, str):
            raw = {"id": raw}
        item = _snapshot_safe_mapping(raw, allowed)
        if item:
            result.append(item)
    return result


def _snapshot_loras(payload: dict) -> list[dict]:
    def name_key(value) -> str:
        return _snapshot_text(value, 800).replace("\\", "/").casefold()

    character_names = {
        name_key(item.get("name"))
        for item in (payload.get("characterLoras") or [])
        if isinstance(item, dict) and name_key(item.get("name"))
    }
    style_names = {
        name_key(item.get("name"))
        for item in (payload.get("styleLoras") or [])
        if isinstance(item, dict) and name_key(item.get("name"))
    }
    trigger_by_name = {}
    try:
        trigger_by_name = {
            name_key(name): _snapshot_text(trigger, 2400)
            for name, trigger in selected_lora_trigger_entries(payload)
            if name_key(name) and _snapshot_text(trigger, 2400)
        }
    except Exception:
        # Snapshot creation must not fail because optional memo metadata is bad.
        trigger_by_name = {}
    raw_loras = payload.get("loras")
    if not isinstance(raw_loras, list) or not raw_loras:
        raw_loras = list(payload.get("characterLoras") or []) + list(payload.get("styleLoras") or [])
    result = []
    seen = set()
    for raw in raw_loras[:64]:
        if not isinstance(raw, dict):
            continue
        name = _snapshot_text(raw.get("name"), 800)
        if not name:
            continue
        normalized_name = name_key(name)
        role = "character" if normalized_name in character_names else "style" if normalized_name in style_names else "other"
        unique_key = (role, normalized_name)
        if unique_key in seen:
            continue
        seen.add(unique_key)
        entry = {
            "name": name,
            "role": role,
            "weight": _snapshot_scalar(raw.get("weight")) if raw.get("weight") is not None else None,
            "trigger": _snapshot_text(raw.get("trigger"), 2400) or trigger_by_name.get(normalized_name, ""),
        }
        if entry["weight"] is None:
            entry.pop("weight")
        result.append(entry)
    return result


def _snapshot_regions(payload: dict) -> list[dict]:
    allowed = {"name", "prompt", "subject", "lora", "x", "y", "width", "height", "strength", "preset"}
    result = []
    for raw in (payload.get("regions") or [])[:16]:
        item = _snapshot_safe_mapping(raw, allowed)
        if item:
            result.append(item)
    return result


def _snapshot_vae(payload: dict, request_generation: dict) -> dict:
    raw = _snapshot_value(payload, request_generation, "vae")
    if isinstance(raw, dict):
        return _snapshot_safe_mapping(raw, {"name", "model", "mode", "enabled", "tileSize", "overlap"})
    name = _snapshot_text(raw, 800)
    return {"name": name} if name else {}


def _snapshot_enhancements(payload: dict, request_generation: dict) -> dict:
    hires = {}
    for key in ("illustriousMode", "hiresScale", "hiresDenoise", "hiresSteps", "hiresCfg",
                "hiresSampler", "hiresScheduler"):
        value = _snapshot_value(payload, request_generation, key)
        if value is not None and value != "":
            cleaned = _snapshot_scalar(value)
            if cleaned is not None:
                hires[key] = cleaned
    result = {"hires": hires}
    allowed_nested = {
        "enabled", "mode", "image", "mask", "grow", "denoise", "scale", "steps", "cfg",
        "sampler", "scheduler", "controlnet", "strength", "start", "end", "suppressSimple",
        "tileSize", "overlap", "source", "target", "model", "vae", "faceDetailer",
        "handDetailer", "footDetailer", "limbDetailer", "b1", "b2", "s1", "s2",
        "multiplier", "colorMatch", "matchStrength", "positive", "negative", "sagScale",
        "sagBlur", "pagScale", "poseJson", "seedvrColor", "guideSize", "hands", "feet",
        "handPositive", "handNegative", "footPositive", "footNegative", "brightness",
        "contrast", "saturation", "gamma", "red", "green", "blue", "hue", "hsvSaturation",
        "value", "blackPoint", "whitePoint", "grayPoint", "keepOriginal", "detailMethod",
        "detailErode", "detailDilate", "maxMegapixels", "method",
    }
    for key in ("repair", "img2img", "pose", "depth", "colorCorrection", "outputEnhancement",
                "modelEnhancement", "transparentBackground", "guidance"):
        raw = _snapshot_value(payload, request_generation, key)
        result[key] = _snapshot_safe_mapping(raw, allowed_nested)
    return result


def build_snapshot_source(data: dict, source_request: dict | None = None, compiled: dict | None = None) -> dict:
    """Build the allowlisted, explainable source used by Web and Android restore."""
    payload = data if isinstance(data, dict) else {}
    request = source_request if isinstance(source_request, dict) else {}
    request_generation = request.get("generation") if isinstance(request.get("generation"), dict) else {}
    visual = request.get("visual") if isinstance(request.get("visual"), dict) else {}
    sections = payload.get("promptSections") if isinstance(payload.get("promptSections"), dict) else {}
    if not sections and isinstance(visual.get("promptSections"), dict):
        sections = visual["promptSections"]
    source = {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "characters": _snapshot_characters(request),
        "subject": _snapshot_text(sections.get("subject"), 12000),
        "appearance": _snapshot_text(sections.get("appearance"), 12000),
        "clothing": _snapshot_text(sections.get("clothing"), 12000),
        "pose": _snapshot_text(sections.get("pose"), 12000),
        "composition": _snapshot_text(sections.get("composition"), 12000),
        "scene": _snapshot_text(sections.get("scene"), 12000),
        "lighting": _snapshot_text(sections.get("lighting"), 12000),
        "styleColoring": _snapshot_text(sections.get("style"), 12000),
        "naturalLanguage": _snapshot_text(sections.get("naturalLanguage"), 12000),
        "manual": _snapshot_text(sections.get("manual"), 12000),
        "regionGlobalPrompt": _snapshot_text(
            _snapshot_value(payload, request_generation, "regionGlobalPrompt"), 12000
        ),
        "negative": _snapshot_text(payload.get("negative") or request_generation.get("negative"), 32000),
        "checkpoint": _snapshot_text(_snapshot_value(payload, request_generation, "model"), 800),
        "vae": _snapshot_vae(payload, request_generation),
        "loras": _snapshot_loras(payload),
        "generation": {},
        "regions": _snapshot_regions(payload),
        "enhancements": _snapshot_enhancements(payload, request_generation),
    }
    generation_keys = (
        "seed", "sampler", "scheduler", "steps", "cfg", "width", "height", "quality",
        "promptMode", "safetyLevel", "mature", "regional", "illustriousMode",
    )
    for key in generation_keys:
        value = _snapshot_value(payload, request_generation, key)
        if value is None or value == "":
            continue
        cleaned = _snapshot_scalar(value)
        if cleaned is not None:
            source["generation"][key] = cleaned
    quality_profile = payload.get("qualityProfile")
    if isinstance(quality_profile, dict):
        source["generation"]["qualityProfile"] = _snapshot_safe_mapping(
            quality_profile, {"steps", "cfg", "sampler", "scheduler"}
        )
    profile = compiled.get("profile") if isinstance(compiled, dict) else None
    if isinstance(profile, dict):
        source["modelStrategy"] = _snapshot_safe_mapping(
            profile, {"family", "name", "quality", "negative", "guidance_supported", "supports_hires"}
        )
    return source


def snapshot_workflow(source_request: dict | None = None) -> dict:
    is_rpg = isinstance(source_request, dict)
    return {
        "kind": "rpg" if is_rpg else "panel",
        "operation": "rpg.generate" if is_rpg else "panel.generate",
        "panelVersion": PANEL_VERSION,
        "apiVersion": RPG_API_VERSION if is_rpg else None,
        "promptCompiler": "compile_prompt",
    }


def _snapshot_compiled(compiled: dict) -> dict:
    keys = (
        "positive", "negative", "sources", "diagnostics", "automation", "sections", "triggers",
        "profile", "sampling", "warnings", "errors", "overridden", "deduplication", "positiveTerms", "negativeTerms",
    )
    return {key: _snapshot_safe_value(compiled.get(key), max_text=32768)
            for key in keys if compiled.get(key) is not None}


def normalize_generation_snapshot(item: dict) -> dict:
    """Return a current-schema view without rewriting legacy snapshot files."""
    if not isinstance(item, dict):
        return {}
    normalized = _snapshot_json_clone(item) or {}
    payload = normalized.get("payload") if isinstance(normalized.get("payload"), dict) else {}
    normalized["payload"] = payload
    raw_compiled = item.get("compiled") if isinstance(item.get("compiled"), dict) else {}
    try:
        generated = compile_prompt(payload)
    except Exception:
        generated = {}
    if generated:
        generated = {**generated, "sampling": snapshot_sampling_trace(payload, generated)}
    merged_compiled = {}
    for key in (
        "positive", "negative", "sources", "diagnostics", "automation", "sections", "triggers",
        "profile", "sampling", "warnings", "errors", "overridden", "deduplication", "positiveTerms", "negativeTerms",
    ):
        value = raw_compiled.get(key) if key in raw_compiled else generated.get(key)
        if value is not None:
            merged_compiled[key] = _snapshot_safe_value(value, max_text=32768)
    normalized["compiled"] = merged_compiled
    raw_source = item.get("source") if isinstance(item.get("source"), dict) else {}
    fallback_source = build_snapshot_source(payload, compiled=generated)
    source = {}
    for key in (
        "schemaVersion", "characters", *SNAPSHOT_SOURCE_SECTION_KEYS, "regionGlobalPrompt", "negative",
        "checkpoint", "vae", "loras", "generation", "regions", "enhancements", "modelStrategy",
    ):
        if key in raw_source:
            cleaned = _snapshot_safe_value(raw_source.get(key), max_text=32768)
            if cleaned is not None:
                source[key] = cleaned
    for key, value in fallback_source.items():
        if key not in source or source[key] in (None, "", [], {}):
            source[key] = value
    source["schemaVersion"] = SNAPSHOT_SCHEMA_VERSION
    normalized["source"] = source
    normalized["schemaVersion"] = SNAPSHOT_SCHEMA_VERSION
    normalized.setdefault("workflow", snapshot_workflow())
    if not isinstance(normalized.get("workflow"), dict):
        normalized["workflow"] = snapshot_workflow()
    normalized.setdefault("outputs", [])
    if not isinstance(normalized.get("outputs"), list):
        normalized["outputs"] = []
    normalized["outputs"] = [Path(str(name)).name for name in normalized["outputs"] if Path(str(name)).name][:16]
    normalized.setdefault("label", "")
    normalized.setdefault("experiment", None)
    return normalized


def find_generation_snapshot(snapshot_id: str) -> dict | None:
    wanted = str(snapshot_id or "").casefold()
    for item in reversed(load_snapshots()):
        if isinstance(item, dict) and str(item.get("id", "")).casefold() == wanted:
            return normalize_generation_snapshot(item)
    return None


def generation_snapshot_summary(item: dict) -> dict:
    snapshot = normalize_generation_snapshot(item)
    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    generation = source.get("generation") if isinstance(source.get("generation"), dict) else {}
    compiled = snapshot.get("compiled") if isinstance(snapshot.get("compiled"), dict) else {}
    prompt_sources = []
    for entry in compiled.get("sources") or []:
        if not isinstance(entry, dict):
            continue
        prompt_sources.append({
            "key": _snapshot_text(entry.get("key"), 80),
            "label": _snapshot_text(entry.get("label"), 160),
            "kind": _snapshot_text(entry.get("kind"), 40),
            "enabled": bool(entry.get("enabled", True)),
            "termCount": len(entry.get("terms") or []) if isinstance(entry.get("terms"), list) else 0,
        })
    sections = [key for key in SNAPSHOT_SOURCE_SECTION_KEYS if source.get(key)]
    return {
        "id": _snapshot_text(snapshot.get("id"), 64),
        "createdAt": snapshot.get("createdAt"),
        "promptId": _snapshot_text(snapshot.get("promptId"), 64),
        "label": _snapshot_text(snapshot.get("label"), 240),
        "schemaVersion": snapshot.get("schemaVersion", SNAPSHOT_SCHEMA_VERSION),
        "workflow": snapshot.get("workflow") or {},
        "model": _snapshot_text(source.get("checkpoint"), 800),
        "seed": generation.get("seed"),
        "width": generation.get("width"),
        "height": generation.get("height"),
        "quality": _snapshot_text(generation.get("quality"), 40),
        "loraCount": len(source.get("loras") or []),
        "outputCount": len(snapshot.get("outputs") or []),
        "outputs": snapshot.get("outputs") or [],
        "characterCount": len(source.get("characters") or []),
        "sourceSections": sections,
        "promptSources": prompt_sources,
    }


def snapshot_sampling_trace(payload: dict, compiled: dict | None = None) -> dict:
    """Explain the saved sampler values without changing any prompt text."""
    data = payload if isinstance(payload, dict) else {}
    profile = compiled.get("profile") if isinstance(compiled, dict) else {}
    profile = profile if isinstance(profile, dict) else {}
    quality_profile = data.get("qualityProfile") if isinstance(data.get("qualityProfile"), dict) else {}
    settings = {}
    for key in ("steps", "cfg", "sampler", "scheduler", "hiresScale", "hiresDenoise",
                "hiresSteps", "hiresCfg", "hiresSampler", "hiresScheduler"):
        value = data.get(key)
        if value is not None and value != "":
            cleaned = _snapshot_scalar(value)
            if cleaned is not None:
                settings[key] = cleaned
    overridden = [key for key in ("steps", "cfg", "sampler", "scheduler")
                  if key in settings and key in quality_profile and settings[key] != quality_profile[key]]
    reasons = []
    if quality_profile:
        reasons.append({
            "code": "quality-profile",
            "message": "基础采样值来自保存时的模型质量策略。",
            "quality": _snapshot_text(data.get("quality"), 40),
            "profile": _snapshot_safe_mapping(quality_profile, {"steps", "cfg", "sampler", "scheduler"}),
        })
    if overridden:
        reasons.append({
            "code": "sampling-override",
            "message": "这些采样项在保存请求中覆盖了质量策略。",
            "fields": overridden,
        })
    reasons.append({
        "code": "snapshot-values",
        "message": "其余采样值来自本次快照保存的生成参数。",
    })
    return {
        "model": _snapshot_text(data.get("model"), 800),
        "quality": _snapshot_text(data.get("quality"), 40),
        "modelFamily": _snapshot_text(profile.get("family"), 40),
        "settings": settings,
        "qualityProfile": _snapshot_safe_mapping(
            quality_profile, {"steps", "cfg", "sampler", "scheduler"}
        ),
        "overriddenFields": overridden,
        "reasons": reasons,
    }


def create_generation_snapshot(data: dict, prompt_id: str = "", source_request: dict | None = None) -> dict:
    clean = json.loads(json.dumps(data, ensure_ascii=False))
    compiled = compile_prompt(clean)
    compiled = {**compiled, "sampling": snapshot_sampling_trace(clean, compiled)}
    snapshot = {
        "id": uuid.uuid4().hex,
        "createdAt": int(time.time() * 1000),
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "promptId": prompt_id,
        "outputs": [],
        "label": str((clean.get("experiment") or {}).get("label", "") or ""),
        "experiment": clean.get("experiment") or None,
        "payload": clean,
        "compiled": _snapshot_compiled(compiled),
        "source": build_snapshot_source(clean, source_request=source_request, compiled=compiled),
        "workflow": snapshot_workflow(source_request),
        "environment": snapshot_environment(clean),
    }
    items = load_snapshots()
    items.append(snapshot)
    write_snapshots(items)
    return snapshot


def attach_snapshot_outputs(snapshot_id: str, outputs) -> dict:
    names = [Path(str(name)).name for name in (outputs or []) if Path(str(name)).name]
    items = load_snapshots()
    target = next((item for item in items if item.get("id") == snapshot_id), None)
    if target is None:
        raise ValueError("找不到生成快照。")
    target["outputs"] = list(dict.fromkeys(names))[:16]
    write_snapshots(items)
    update_creative_index_status_best_effort(snapshot_id, {
        "status": "completed",
        "images": outputs if isinstance(outputs, list) else [],
    })
    return normalize_generation_snapshot(target)


def compare_snapshot_environment(snapshot_id: str) -> dict:
    target = next((item for item in load_snapshots() if item.get("id") == snapshot_id), None)
    if target is None:
        raise ValueError("找不到生成快照。")
    current = snapshot_environment(target.get("payload") or {})
    original = target.get("environment") or {}
    differences: list[str] = []
    for label, before, after in [("基础模型", original.get("model") or {}, current.get("model") or {})]:
        if before.get("fingerprint") != after.get("fingerprint") or before.get("exists") != after.get("exists"):
            differences.append(f"{label}文件已变化或缺失：{before.get('name', '')}")
    before_loras = {item.get("name"): item for item in original.get("loras") or []}
    after_loras = {item.get("name"): item for item in current.get("loras") or []}
    for name, before in before_loras.items():
        after = after_loras.get(name) or {}
        if before.get("fingerprint") != after.get("fingerprint") or before.get("exists") != after.get("exists"):
            differences.append("LoRA 文件已变化或缺失：" + str(name))
    if original.get("panelVersion") != PANEL_VERSION:
        differences.append(f"面板版本不同：{original.get('panelVersion')} → {PANEL_VERSION}")
    return {"same": not differences, "differences": differences, "current": current,
            "snapshot": normalize_generation_snapshot(target)}


def rpg_model_catalog() -> dict:
    """Return only models that the existing Easy Panel workflow can submit."""
    info = comfy_json("/object_info")
    all_checkpoints = object_info_choices(info, "CheckpointLoaderSimple", "ckpt_name")
    checkpoints = [name for name in all_checkpoints if not checkpoint_issue(name)]
    diffusion_models = object_info_choices(info, "UNETLoader", "unet_name")
    return {
        "checkpoints": checkpoints,
        "anima_models": [name for name in diffusion_models if is_anima_model(name)],
        "krea2_models": [name for name in diffusion_models if is_krea2_model(name)],
        "qualityProfiles": rpg_quality_profiles(),
    }


CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)


def resolve_rpg_output_image(name: str, subfolder: str = "") -> Path:
    """Resolve a ComfyUI output image without allowing traversal outside OUTPUT."""

    safe_name = Path(str(name or "")).name
    if not safe_name or safe_name != str(name or ""):
        raise FileNotFoundError("invalid image name")
    normalized_subfolder = str(subfolder or "").replace("\\", "/").strip("/")
    root = OUTPUT.resolve()
    candidate = (root / Path(normalized_subfolder) / safe_name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise FileNotFoundError("image not found") from None
    if not candidate.is_file():
        raise FileNotFoundError("image not found")
    return candidate


@lru_cache(maxsize=256)
def build_rpg_thumbnail(path: str, modified_ns: int, file_size: int) -> tuple[bytes, str]:
    """Build and cache a small library preview without changing the source file."""

    from PIL import Image, ImageOps

    with Image.open(path) as source:
        transpose = getattr(ImageOps, "exif_transpose", None)
        image = transpose(source) if callable(transpose) else source.copy()
        resampling = getattr(Image, "Resampling", Image)
        image.thumbnail((360, 360), resampling.LANCZOS)
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        output = io.BytesIO()
        if has_alpha:
            image.convert("RGBA").save(output, format="PNG", optimize=True)
            content_type = "image/png"
        else:
            image.convert("RGB").save(output, format="JPEG", quality=82, optimize=True, progressive=True)
            content_type = "image/jpeg"
    return output.getvalue(), content_type


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

    def is_rpg_request(self):
        return urllib.parse.urlparse(self.path).path.startswith("/api/rpg/")

    def is_loopback_client(self):
        try:
            client_address = getattr(self, "client_address", None)
            if not client_address:
                # Direct unit-test harnesses may call do_GET/do_POST on an
                # uninitialized handler; there is no network peer to protect.
                return True
            address = ipaddress.ip_address(str(client_address[0]))
        except (AttributeError, IndexError, TypeError, ValueError):
            return False
        mapped = getattr(address, "ipv4_mapped", None)
        return address.is_loopback or bool(mapped and mapped.is_loopback)

    def rpg_session_value(self):
        try:
            cookies = SimpleCookie()
            cookies.load(str(self.headers.get("Cookie", "") or ""))
            morsel = cookies.get(RPG_SESSION_COOKIE)
            return str(morsel.value if morsel else "").strip()
        except Exception:
            return ""

    def rpg_header_token(self):
        direct = str(self.headers.get("X-RPG-Token", "") or "").strip()
        if direct:
            return direct
        authorization = str(self.headers.get("Authorization", "") or "").strip()
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        if authorization.lower().startswith("basic "):
            encoded = authorization[6:].strip()
            try:
                decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return ""
            _username, separator, password = decoded.partition(":")
            return password.strip() if separator else ""
        return ""

    def has_valid_rpg_header(self):
        expected = _rpg_expected_token()
        provided = self.rpg_header_token()
        return bool(expected and provided and hmac.compare_digest(provided, expected))

    def has_valid_rpg_session(self):
        return _valid_rpg_session_cookie(self.rpg_session_value())

    def issue_rpg_session(self):
        if _rpg_expected_token():
            value = _new_rpg_session_cookie_value()
            self._rpg_session_header = (
                f"{RPG_SESSION_COOKIE}={value}; Max-Age={RPG_SESSION_MAX_AGE}; "
                "Path=/; HttpOnly; SameSite=Strict"
            )

    def add_rpg_session_header(self):
        cookie = str(getattr(self, "_rpg_session_header", "") or "")
        if cookie:
            self.send_header("Set-Cookie", cookie)

    def send_auth_error(self, message: str, status=HTTPStatus.UNAUTHORIZED):
        self.send_json({"error": message}, status, auth_challenge=status == HTTPStatus.UNAUTHORIZED)

    def require_panel_auth(self):
        """Protect the legacy panel API while preserving local desktop access."""
        if self.is_loopback_client():
            return True
        if not _rpg_expected_token():
            self.send_auth_error("远程面板未配置访问 Token。", HTTPStatus.SERVICE_UNAVAILABLE)
            return False
        if self.has_valid_rpg_session():
            return True
        if self.has_valid_rpg_header():
            self.issue_rpg_session()
            return True
        self.send_auth_error("需要 Easy Panel Token 才能访问远程面板。")
        return False

    def add_rpg_cors_headers(self):
        if self.is_rpg_request():
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-RPG-Token, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def rpg_token_value(self):
        return self.rpg_header_token()

    def require_rpg_auth(self):
        if not _rpg_expected_token():
            if self.is_loopback_client():
                return True
            self.send_auth_error("远程 RPG API 未配置访问 Token。", HTTPStatus.SERVICE_UNAVAILABLE)
            return False
        if self.has_valid_rpg_session():
            return True
        if self.has_valid_rpg_header():
            self.issue_rpg_session()
            return True
        self.send_auth_error("RPG API Token 不正确。")
        return False

    def send_json(self, body: dict, status=HTTPStatus.OK, auth_challenge=False):
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.add_rpg_cors_headers()
            if auth_challenge:
                self.send_header("WWW-Authenticate", 'Basic realm="Easy Panel", charset="UTF-8"')
            self.add_rpg_session_header()
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return True
        except CLIENT_DISCONNECT_ERRORS:
            # Reloading the panel or cancelling fetch() closes the browser socket.
            # This is normal and must not be converted into a second error response.
            return False

    def do_OPTIONS(self):
        if not self.is_rpg_request():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.add_rpg_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

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
        self.add_rpg_session_header()
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
            if (parsed.path == "/" or parsed.path == "/output"
                    or (parsed.path.startswith("/api/")
                        and not parsed.path.startswith("/api/rpg/"))):
                if not self.require_panel_auth():
                    return
            if parsed.path == "/api/shared-state":
                state, recovered = SHARED_STATE_STORE.read_with_metadata()
                self.send_json({"ok": True, "state": state, "recovered": recovered})
            elif parsed.path == "/api/rpg/ping":
                self.send_json({
                    "ok": True,
                    "api_version": RPG_API_VERSION,
                    "service": "ComfyUI Easy Panel RPG Bridge",
                    "token_required": token_required(),
                })
            elif parsed.path == "/api/rpg/library/generations":
                if not self.require_rpg_auth():
                    return
                query = urllib.parse.parse_qs(parsed.query)
                operation = query.get("operation", [""])[0].strip().casefold()
                if operation and operation not in CREATIVE_INDEX_OPERATIONS and operation != "unknown":
                    self.send_json({
                        "error": "不支持的作品库操作类型。",
                        "allowed_operations": sorted((*CREATIVE_INDEX_OPERATIONS, "unknown")),
                    }, HTTPStatus.BAD_REQUEST)
                    return
                status = query.get("status", [""])[0].strip().casefold()
                if status and status not in CREATIVE_INDEX_STATUSES:
                    self.send_json({
                        "error": "不支持的作品库任务状态。",
                        "allowed_statuses": sorted(CREATIVE_INDEX_STATUSES),
                    }, HTTPStatus.BAD_REQUEST)
                    return
                creative_index = get_creative_index()
                ensure_creative_index_from_legacy_best_effort(creative_index)
                reconcile_creative_index_jobs()
                prune_creative_missing_outputs()
                result = creative_index.list_generations(
                    limit=query.get("limit", [20])[0],
                    offset=query.get("offset", [0])[0],
                    operation=operation,
                    status=status,
                    model=query.get("model", [""])[0],
                    sort=query.get("sort", ["created_at"])[0],
                    order=query.get("order", ["desc"])[0],
                )
                self.send_json({
                    "api_version": RPG_API_VERSION,
                    "index_schema_version": CREATIVE_INDEX_SCHEMA_VERSION,
                    **result,
                })
            elif re.fullmatch(r"/api/rpg/library/generations/[0-9a-fA-F]{32}/lineage", parsed.path):
                if not self.require_rpg_auth():
                    return
                generation_id = parsed.path.split("/")[-2].lower()
                creative_index = get_creative_index()
                ensure_creative_index_from_legacy_best_effort(creative_index)
                reconcile_creative_index_jobs()
                prune_creative_missing_outputs()
                lineage = creative_index.get_lineage(generation_id)
                if lineage is None:
                    self.send_json({"error": "没有找到该作品。"}, HTTPStatus.NOT_FOUND)
                    return
                self.send_json({
                    "api_version": RPG_API_VERSION,
                    "index_schema_version": CREATIVE_INDEX_SCHEMA_VERSION,
                    "lineage": lineage,
                })
            elif re.fullmatch(r"/api/rpg/library/generations/[0-9a-fA-F]{32}", parsed.path):
                if not self.require_rpg_auth():
                    return
                generation_id = parsed.path.rsplit("/", 1)[-1].lower()
                creative_index = get_creative_index()
                ensure_creative_index_from_legacy_best_effort(creative_index)
                reconcile_creative_index_jobs()
                prune_creative_missing_outputs()
                generation = creative_index.get_generation(generation_id)
                if generation is None:
                    self.send_json({"error": "没有找到该作品。"}, HTTPStatus.NOT_FOUND)
                    return
                self.send_json({
                    "api_version": RPG_API_VERSION,
                    "index_schema_version": CREATIVE_INDEX_SCHEMA_VERSION,
                    "generation": generation,
                })
            elif parsed.path == "/api/rpg/capabilities":
                if not self.require_rpg_auth():
                    return
                profiles = load_rpg_profiles()
                self.send_json({
                    "api_version": RPG_API_VERSION,
                    "async_jobs": True,
                    "idempotent_request_id": True,
                    "job_recovery": True,
                    "image_subfolders": True,
                    "regional_two_character": True,
                    "poll_interval_ms": int(profiles.get("defaults", {}).get("pollIntervalMs", 1800)),
                    "limits": {"characters_per_scene": 6, "width": [512, 1920], "height": [512, 1920]},
                })
            elif parsed.path == "/api/rpg/snapshots":
                if not self.require_rpg_auth():
                    return
                query = urllib.parse.parse_qs(parsed.query)
                limit = bounded(query.get("limit", [20])[0], 20, 1, 50)
                items = load_snapshots()
                summaries = [generation_snapshot_summary(item) for item in reversed(items[-limit:])]
                self.send_json({
                    "api_version": RPG_API_VERSION,
                    "schema_version": SNAPSHOT_SCHEMA_VERSION,
                    "snapshots": summaries,
                })
            elif re.fullmatch(r"/api/rpg/snapshots/[0-9a-fA-F]{32}", parsed.path):
                if not self.require_rpg_auth():
                    return
                snapshot_id = parsed.path.rsplit("/", 1)[-1]
                snapshot = find_generation_snapshot(snapshot_id)
                if snapshot is None:
                    self.send_json({"error": "没有找到该生成快照。"}, HTTPStatus.NOT_FOUND)
                    return
                self.send_json({
                    "api_version": RPG_API_VERSION,
                    "schema_version": SNAPSHOT_SCHEMA_VERSION,
                    "snapshot": snapshot,
                })
            elif re.fullmatch(r"/api/rpg/jobs/by-request/[0-9A-Za-z_-]{1,48}", parsed.path):
                if not self.require_rpg_auth():
                    return
                request_id = parsed.path.rsplit("/", 1)[-1]
                metadata = find_rpg_job_by_request_id(request_id)
                prompt_id = str(metadata.get("prompt_id") or "")
                if not prompt_id:
                    self.send_json({"error": "没有找到该 requestId 对应的任务。"}, HTTPStatus.NOT_FOUND)
                    return
                history = comfy_json("/history/" + prompt_id)
                self.send_json(sync_rpg_status_to_creative_index(
                    rpg_status_with_output_recovery(prompt_id, history, metadata)
                ))
            elif parsed.path == "/api/rpg/profiles":
                if not self.require_rpg_auth():
                    return
                self.send_json(load_rpg_profiles())
            elif parsed.path == "/api/rpg/models":
                if not self.require_rpg_auth():
                    return
                catalog = rpg_model_catalog()
                self.send_json({"api_version": RPG_API_VERSION, **catalog})
            elif re.fullmatch(r"/api/rpg/jobs/[0-9a-fA-F-]{36}", parsed.path):
                if not self.require_rpg_auth():
                    return
                prompt_id = parsed.path.rsplit("/", 1)[-1].lower()
                history = comfy_json("/history/" + prompt_id)
                self.send_json(sync_rpg_status_to_creative_index(
                    rpg_status_with_output_recovery(prompt_id, history)
                ))
            elif parsed.path == "/api/rpg/image":
                if not self.require_rpg_auth():
                    return
                query = urllib.parse.parse_qs(parsed.query)
                name = query.get("name", [""])[0]
                subfolder = query.get("subfolder", [""])[0]
                preview = query.get("preview", [""])[0].strip().casefold() in {"1", "true", "yes", "thumbnail"}
                try:
                    file = resolve_rpg_output_image(name, subfolder)
                except FileNotFoundError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                if preview:
                    try:
                        stat = file.stat()
                        content, content_type = build_rpg_thumbnail(str(file), stat.st_mtime_ns, stat.st_size)
                    except Exception:
                        # A malformed/unsupported image should not break the
                        # library; fall back to the original authenticated file.
                        content = file.read_bytes()
                else:
                    content = file.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "private, max-age=86400")
                self.add_rpg_cors_headers()
                self.add_rpg_session_header()
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif parsed.path == "/":
                content = (ROOT / "index.html").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.add_rpg_session_header()
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
                all_checkpoints = object_info_choices(info, "CheckpointLoaderSimple", "ckpt_name")
                checkpoints, unavailable_checkpoints = [], []
                for checkpoint in all_checkpoints:
                    issue = checkpoint_issue(checkpoint)
                    if issue:
                        unavailable_checkpoints.append({"name": checkpoint, "reason": issue})
                    else:
                        checkpoints.append(checkpoint)
                loras = object_info_choices(info, "LoraLoader", "lora_name")
                controlnets = object_info_choices(info, "ControlNetLoader", "control_net_name")
                diffusion_models = object_info_choices(info, "UNETLoader", "unet_name")
                anima_models = [name for name in diffusion_models if is_anima_model(name)]
                krea2_models = [name for name in diffusion_models if is_krea2_model(name)]
                text_encoders = object_info_choices(info, "CLIPLoader", "clip_name")
                vaes = object_info_choices(info, "VAELoader", "vae_name")
                upscale_models = object_info_choices(info, "UpscaleModelLoader", "model_name")
                detector_models = object_info_choices(info, "UltralyticsDetectorProvider", "model_name")
                clip_vision_models = object_info_choices(info, "CLIPVisionLoader", "clip_name")
                anima_ready = ANIMA_TEXT_ENCODER in text_encoders and ANIMA_VAE in vaes
                krea2_ready = KREA2_TEXT_ENCODER in text_encoders and KREA2_VAE in vaes
                seedvr_nodes = all(name in info for name in (
                    "SeedVR2Preprocess", "SeedVR2Conditioning", "SeedVR2PostProcessing",
                ))
                workflow_features = {
                    "anime6b": HIRES_UPSCALE_MODEL in upscale_models,
                    "color_transfer": "ColorTransfer" in info,
                    "ultimate": "UltimateSDUpscale" in info,
                    "transparent_background": "LayerMask: RmBgUltra V2" in info,
                    "face_detailer_node": "FaceDetailer" in info,
                    "face_detector_provider": "UltralyticsDetectorProvider" in info,
                    "face_detector_model": FACE_DETECTOR_MODEL in detector_models,
                    "hand_detector_model": HAND_DETECTOR_MODEL in detector_models,
                    "foot_detector_model": FOOT_DETECTOR_MODEL in detector_models,
                    "face_detailer": (
                        "FaceDetailer" in info
                        and "UltralyticsDetectorProvider" in info
                        and FACE_DETECTOR_MODEL in detector_models
                    ),
                    "hand_detailer": (
                        "FaceDetailer" in info
                        and "UltralyticsDetectorProvider" in info
                        and HAND_DETECTOR_MODEL in detector_models
                    ),
                    "foot_detailer": (
                        "FaceDetailer" in info
                        and "UltralyticsDetectorProvider" in info
                        and FOOT_DETECTOR_MODEL in detector_models
                    ),
                    "seedvr2_nodes": seedvr_nodes,
                    "seedvr2_model": SEEDVR2_MODEL in diffusion_models,
                    "seedvr2_vae": SEEDVR2_VAE in vaes,
                    "seedvr2": seedvr_nodes and SEEDVR2_MODEL in diffusion_models and SEEDVR2_VAE in vaes,
                    "ipadapter": (
                        "IPAdapterAdvanced" in info
                        and any("ip-adapter-plus_sdxl" in str(name).lower() for name in object_info_choices(
                            info, "IPAdapterModelLoader", "ipadapter_file"
                        ))
                        and bool(clip_vision_models)
                    ),
                }
                sampling_profiles = {name: model_sampling_profile(name)
                                     for name in checkpoints + anima_models + krea2_models}
                embeddings, embedding_meta = embedding_catalog()
                self.send_json({"checkpoints": checkpoints, "unavailable_checkpoints": unavailable_checkpoints,
                                "anima_models": anima_models, "anima_ready": anima_ready,
                                "krea2_models": krea2_models, "krea2_ready": krea2_ready,
                                "anima_tag_count": len(ANIMA_TAG_INDEX), "loras": loras,
                                "loraMeta": lora_meta_map(loras), "controlnets": controlnets,
                                "embeddings": embeddings, "embeddingMeta": embedding_meta,
                                "upscaleModels": upscale_models, "detectorModels": detector_models,
                                "workflowFeatures": workflow_features,
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
            elif parsed.path == "/api/lora-aliases":
                self.send_json({"aliases": load_lora_rename_aliases()})
            elif parsed.path == "/api/lora-sidecars":
                self.send_json({"entries": load_lora_sidecars()})
            elif parsed.path == "/api/output-images":
                self.send_json({"entries": list_output_images()})
            elif parsed.path == "/api/snapshots":
                items = load_snapshots()
                self.send_json({"entries": [normalize_generation_snapshot(item)
                                             for item in reversed(items[-200:])]})
            elif parsed.path == "/api/snapshot-compare":
                snapshot_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
                if not re.fullmatch(r"[0-9a-f]{32}", snapshot_id):
                    raise ValueError("无效快照编号。")
                self.send_json(compare_snapshot_environment(snapshot_id))
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
                self.add_rpg_session_header()
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
        path = urllib.parse.urlparse(self.path).path
        if path not in {"/api/generate", "/api/generate-batch", "/api/clarity-upscale", "/api/preview-pose", "/api/translate", "/api/google-translate", "/api/prompt-instruction", "/api/lora-notes", "/api/lora-import-sidecar", "/api/upload-pose", "/api/anima-tags", "/api/anima-preflight", "/api/illustrious-preflight", "/api/prompt-compile", "/api/read-image", "/api/read-output", "/api/upload-inpaint", "/api/krea2-preflight", "/api/preview-color", "/api/snapshot-outputs", "/api/rpg/generate", "/api/rpg/prompt-instruction", "/api/rpg/profiles", "/api/rpg/library/delete", "/api/shared-state"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if path.startswith("/api/") and not path.startswith("/api/rpg/") and not self.require_panel_auth():
            return
        if path.startswith("/api/rpg/") and not self.require_rpg_auth():
            return
        self.path = path
        try:
            if self.path == "/api/shared-state":
                size = bounded(self.headers.get("Content-Length"), 0, 0, SHARED_STATE_MAX_REQUEST_BYTES)
                if not size:
                    raise ValueError("共享数据请求为空。")
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("共享数据请求不完整。")
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("共享数据请求必须是 JSON 对象。")
                payload = data.get("state") if isinstance(data.get("state"), dict) else data
                self.send_json(SHARED_STATE_STORE.merge(payload, data.get("baseRevision")))
                return
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
            if self.path == "/api/rpg/profiles":
                document = data.get("profiles") if isinstance(data.get("profiles"), dict) else data
                self.send_json(save_rpg_profiles(document))
                return
            if self.path == "/api/rpg/library/delete":
                generation_id = str(data.get("generation_id") or "").strip().lower()
                if not re.fullmatch(r"[0-9a-f]{32}", generation_id):
                    raise ValueError("作品编号无效。")
                creative_index = get_creative_index()
                ensure_creative_index_from_legacy_best_effort(creative_index)
                result = creative_index.delete_generation(generation_id, OUTPUT)
                if result is None:
                    self.send_json({"error": "没有找到该作品。"}, HTTPStatus.NOT_FOUND)
                    return
                self.send_json({
                    "api_version": RPG_API_VERSION,
                    "index_schema_version": CREATIVE_INDEX_SCHEMA_VERSION,
                    **result,
                })
                return
            if self.path in {"/api/prompt-instruction", "/api/rpg/prompt-instruction"}:
                self.send_json(build_prompt_instruction(
                    data.get("text", ""),
                    data.get("model", ""),
                    data.get("safetyLevel", "safe"),
                ))
                return
            if self.path == "/api/rpg/generate":
                client = data.get("client") if isinstance(data.get("client"), dict) else {}
                request_id = str(client.get("requestId") or data.get("requestId") or "").strip()
                if request_id:
                    existing = find_rpg_job_by_request_id(request_id)
                    existing_prompt_id = str(existing.get("prompt_id") or "")
                    if existing_prompt_id:
                        history = comfy_json("/history/" + existing_prompt_id)
                        status = sync_rpg_status_to_creative_index(
                            rpg_status_with_output_recovery(existing_prompt_id, history, existing)
                        )
                        status["deduplicated"] = True
                        status["status_url"] = "/api/rpg/jobs/" + existing_prompt_id
                        self.send_json(status, HTTPStatus.OK)
                        return
                payload = build_rpg_payload(data, rpg_model_catalog())
                result = comfy_json("/prompt", "POST", build_workflow(payload))
                prompt_id = str(result.get("prompt_id") or "")
                if not re.fullmatch(r"[0-9a-fA-F-]{36}", prompt_id):
                    raise ValueError("ComfyUI 没有返回有效的任务编号。")
                snapshot = create_generation_snapshot(payload, prompt_id, source_request=data)
                record_rpg_job(prompt_id, data, payload, snapshot["id"])
                indexed = index_snapshot_best_effort(
                    snapshot,
                    source_request=data,
                    operation=infer_creative_operation(data),
                    status="queued",
                    request_id=request_id,
                )
                response = {
                    "api_version": RPG_API_VERSION,
                    "job_id": prompt_id,
                    "prompt_id": prompt_id,
                    "status": "queued",
                    "snapshot_id": snapshot["id"],
                    "status_url": "/api/rpg/jobs/" + prompt_id,
                }
                if indexed.get("generation_id"):
                    response["generation_id"] = indexed["generation_id"]
                self.send_json(response, HTTPStatus.ACCEPTED)
                return
            if self.path == "/api/read-output":
                name = str(data.get("name", "") or "").strip()
                safe_name = Path(name).name
                file = OUTPUT / safe_name
                if safe_name != name or not file.is_file():
                    raise ValueError("找不到该输出图片。")
                self.send_json(parse_generation_info(file.read_bytes()))
                return
            if self.path == "/api/snapshot-outputs":
                self.send_json(attach_snapshot_outputs(str(data.get("id", "")), data.get("outputs") or []))
                return
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
                self.add_rpg_session_header()
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
            elif self.path == "/api/clarity-upscale":
                info = comfy_json("/object_info")
                available = object_info_choices(info, "UpscaleModelLoader", "model_name")
                if HIRES_UPSCALE_MODEL not in available:
                    raise ValueError("缺少 Anime6B 放大模型，无法生成同图清晰版。")
                self.send_json(comfy_json("/prompt", "POST", build_clarity_upscale_workflow(data)))
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
                    result = comfy_json("/prompt", "POST", item["workflow"])
                    prompt_id = result.get("prompt_id")
                    snapshot = create_generation_snapshot(item["payload"], str(prompt_id or ""))
                    indexed = index_snapshot_best_effort(
                        snapshot,
                        source_request=item.get("payload") if isinstance(item.get("payload"), dict) else {},
                        status="queued",
                    )
                    submitted.append({"index": index, "task_index": item["task_index"],
                                      "image_index": item["image_index"],
                                      "image_count": item["image_count"],
                                      "prompt_id": prompt_id, "snapshot_id": snapshot["id"],
                                      "label": snapshot["label"],
                                      **({"generation_id": indexed["generation_id"]}
                                         if indexed.get("generation_id") else {})})
                self.send_json({"jobs": submitted, "logical_tasks": len(jobs),
                                "total_images": len(submitted)})
            else:
                result = comfy_json("/prompt", "POST", build_workflow(data))
                snapshot = create_generation_snapshot(data, str(result.get("prompt_id") or ""))
                indexed = index_snapshot_best_effort(
                    snapshot,
                    source_request=data,
                    status="queued",
                )
                self.send_json({
                    **result,
                    "snapshot_id": snapshot["id"],
                    **({"generation_id": indexed["generation_id"]}
                       if indexed.get("generation_id") else {}),
                })
        except CLIENT_DISCONNECT_ERRORS:
            return
        except urllib.error.HTTPError as exc:
            self.send_json({"error": exc.read().decode("utf-8", "replace")}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


if __name__ == "__main__":
    start_creative_index_reconciler()
    print(f"Easy Panel: http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
