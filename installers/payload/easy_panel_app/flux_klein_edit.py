"""FLUX.2 Klein 智能修图：对已有成品做整图语义细化 / 局部裁剪修复。

**节点链来源（不要凭经验重写）**：ComfyUI 官方模板
``templates/image_flux2_klein_image_edit_4b_distilled.json`` 里的
``Image Edit (Flux.2 Klein 4B Distilled)`` 子图，逐节点对应：

    UNETLoader(flux-2-klein-4b-fp8) + CLIPLoader(qwen_3_4b, type=flux2) + VAELoader(flux2-vae)
      → LoadImage → ImageScaleToTotalPixels(nearest-exact, 1MP) → GetImageSize
      → EmptyFlux2LatentImage(width, height, 1) / Flux2Scheduler(4, width, height)
      → CLIPTextEncode(指令) → ConditioningZeroOut → VAEEncode(参考图)
      → ReferenceLatent(正) / ReferenceLatent(负) → CFGGuider(cfg=1)
      → KSamplerSelect(euler) + RandomNoise → SamplerCustomAdvanced → VAEDecode → SaveImage

Klein 是 **4 步蒸馏 + 参考潜空间（ReferenceLatent）编辑** 模型：没有 denoise 滑杆，
CFG 固定 1.0，steps 固定 4。所以它与面板里 SD/Flux1 那套
「KSampler + denoise 图生图」不是一回事，**不要**把 denoise / CFG 界面套上去。

局部修复（mask）沿用官方「参考图编辑」的同一张图，只是把 ROI 先裁出来：
    原图 + 蒙版 → 后端算 bbox → 裁 ROI（crop）+ 羽化后的蒙版（mask）
      → Klein 编辑 crop → ImageCompositeMasked 贴回原图 → SaveImage
裁剪与羽化放在 Python 侧（可单测、不依赖额外自定义节点），ComfyUI 里只多一个
``ImageCompositeMasked``（面板 route1 已在用，输入名与本文件一致）。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from easy_panel_app.config import COMFY_INPUT, OUTPUT
from easy_panel_app.media_storage import copy_output_to_input, validate_input_image

#: 官方 4B Distilled 三件套（文件缺失时 ComfyUI 会在提交时报“不在可选列表里”）。
DEFAULT_UNET = "flux-2-klein-4b-fp8.safetensors"
DEFAULT_TEXT_ENCODER = "qwen_3_4b.safetensors"
DEFAULT_VAE = "flux2-vae.safetensors"

MODES = {"full": "整图细化", "regional": "局部修复"}

#: 修图策略：① UI 语义，不是 Klein 的“强度参数”；② 文案会拼进最终指令。
STRATEGIES = {
    "conservative": {
        "label": "保守",
        "lead": ("Conservative refinement. Keep the original image almost unchanged and "
                 "only apply the requested adjustments."),
        "tip": "只动指令里点名的细节，其余尽量保持原样。",
    },
    "standard": {
        "label": "标准",
        "lead": ("Balanced refinement. You may refine materials, hair strands, accessories, "
                 "expression and lighting as described, keeping everything else as it is."),
        "tip": "允许材质、发丝、配饰、表情与光影的自然细化。",
    },
    "restructure": {
        "label": "重构",
        "lead": ("Restructuring is allowed. You may redesign clothing, hairstyle and scene "
                 "elements or replace objects as described, while keeping the rest intact."),
        "tip": "允许改服装、发型、场景元素与物体替换。",
    },
}

#: 「保留内容」复选框 → 英文约束（顺序固定，方便测试与复现）。
PRESERVE_TERMS = {
    "identity": "the original character identity",
    "face": "the original facial features",
    "pose": "the original pose",
    "clothing": "the original clothing design",
    "composition": "the original camera framing and composition",
    "background": "the original background",
}

DEFAULT_PRESERVE = ("identity", "face", "pose", "clothing", "composition", "background")

MAX_INSTRUCTION = 1200
MAX_REFERENCES = 2
DEFAULT_STEPS = 4
STEPS_RANGE = (2, 8)
#: ImageScaleToTotalPixels 的对齐步长（官方 UI 模板里是折叠的高级输入，默认 1）。
RESOLUTION_STEPS = 8
MEGAPIXEL_RANGE = (0.4, 1.5)
DEFAULT_MEGAPIXELS = 1.0
FEATHER_RANGE = (0, 64)
GROW_RANGE = (0, 128)
PAD_RANGE = (0, 256)
MIN_ROI_SIDE = 256
MAX_ROI_SIDE = 1536


def _number(value, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


def _text(value, limit: int = 0) -> str:
    result = str(value or "").strip()
    if limit and len(result) > limit:
        result = result[:limit].strip()
    return result


def flux_edit_payload(data) -> dict:
    """取出 payload 里的 ``fluxEdit`` 请求体（不存在时返回空 dict）。"""

    if not isinstance(data, dict):
        return {}
    for source in (data, data.get("generation"), data.get("visual")):
        if isinstance(source, dict) and isinstance(source.get("fluxEdit"), dict):
            return source["fluxEdit"]
    return {}


def flux_edit_enabled(data) -> bool:
    request = flux_edit_payload(data)
    return bool(request.get("enabled"))


def normalize_flux_edit(data) -> dict:
    """把请求归一化成工作流能直接消费的结构（不做文件校验）。"""

    request = flux_edit_payload(data)
    mode = _text(request.get("mode") or "full").casefold()
    if mode not in MODES:
        mode = "full"
    strategy = _text(request.get("strategy") or "standard").casefold()
    if strategy not in STRATEGIES:
        strategy = "standard"
    # 缺字段（None）= 界面默认全勾；显式空列表 = 用户主动取消全部约束。
    preserve_raw = request.get("preserve")
    if isinstance(preserve_raw, str):
        preserve_raw = [item.strip() for item in preserve_raw.split(",")]
    preserve: list[str] = []
    if preserve_raw is None:
        preserve = list(DEFAULT_PRESERVE)
    elif isinstance(preserve_raw, (list, tuple)):
        for item in preserve_raw:
            key = _text(item).casefold()
            if key in PRESERVE_TERMS and key not in preserve:
                preserve.append(key)
    else:
        preserve = list(DEFAULT_PRESERVE)
    references: list[str] = []
    for item in request.get("references") if isinstance(request.get("references"), list) else []:
        name = _text(item)
        if name and name not in references:
            references.append(name)
    seed_value = request.get("seed", -1)
    try:
        seed = int(float(seed_value))
    except (TypeError, ValueError):
        seed = -1
    if seed < 0:
        seed = int(time.time_ns() % (2 ** 63 - 1)) or 1
    return {
        "enabled": bool(request.get("enabled")),
        "mode": mode,
        "mode_label": MODES[mode],
        "source": _text(request.get("source")),
        "mask": _text(request.get("mask")),
        "instruction": _text(request.get("instruction"), MAX_INSTRUCTION),
        "strategy": strategy,
        "strategy_label": STRATEGIES[strategy]["label"],
        "preserve": preserve,
        "references": references[:MAX_REFERENCES],
        "seed": seed,
        "steps": int(round(_number(request.get("steps"), DEFAULT_STEPS, *STEPS_RANGE))),
        "megapixels": round(_number(request.get("megapixels"), DEFAULT_MEGAPIXELS, *MEGAPIXEL_RANGE), 3),
        "feather": int(round(_number(request.get("feather"), 16, *FEATHER_RANGE))),
        "grow": int(round(_number(request.get("grow"), 24, *GROW_RANGE))),
        "pad": int(round(_number(request.get("pad"), 64, *PAD_RANGE))),
        "unet": _text(request.get("unet") or DEFAULT_UNET),
        "text_encoder": _text(request.get("textEncoder") or request.get("clip") or DEFAULT_TEXT_ENCODER),
        "vae": _text(request.get("vaeName") or DEFAULT_VAE),
    }


def validate_flux_edit(edit: dict) -> list[str]:
    """返回用户可读的错误列表（空列表=可以提交）。"""

    errors: list[str] = []
    if not edit.get("enabled"):
        return errors
    if not edit.get("source"):
        errors.append("请先选择要修的原图（结果卡的当前图片会自动带上）。")
    if not edit.get("instruction"):
        errors.append("请填写「修改描述」——Klein 靠它决定改什么。")
    if edit["mode"] == "regional" and not edit.get("mask"):
        errors.append("局部修复需要蒙版：请先用「手部工作台」圈出要改的区域，或导入一张黑白蒙版（白=重绘区）。")
    if len(edit.get("instruction", "")) >= MAX_INSTRUCTION:
        errors.append(f"修改描述过长（上限 {MAX_INSTRUCTION} 字）。")
    return errors


def compose_flux_instruction(edit: dict) -> str:
    """指令 = 策略开场白 + 用户描述 + 保留内容约束。"""

    parts = [STRATEGIES[edit["strategy"]]["lead"]]
    parts.append(edit["instruction"].rstrip("。. ") + ".")
    preserve = [PRESERVE_TERMS[key] for key in edit.get("preserve", []) if key in PRESERVE_TERMS]
    if preserve:
        parts.append("Preserve " + ", ".join(preserve) + ".")
    if edit["strategy"] == "conservative":
        parts.append("Do not redesign the character or change the composition.")
    return " ".join(part for part in parts if part).strip()


# --------------------------------------------------------------------------- #
# 局部修复：ROI 裁剪 + 羽化蒙版（Python 侧做完，ComfyUI 只负责贴回）
# --------------------------------------------------------------------------- #

def _input_dir() -> Path:
    folder = COMFY_INPUT / "easy_panel"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _resolve_output_image(name: str) -> Path:
    relative = Path(str(name or "").replace("\\", "/"))
    if not relative.name or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("原图路径无效。")
    path = (OUTPUT / relative).resolve()
    try:
        path.relative_to(OUTPUT.resolve())
    except ValueError as exc:
        raise ValueError("原图路径无效。") from exc
    if not path.is_file():
        raise ValueError(f"找不到原图：{relative.name}")
    return path


def resolve_source_image(name: str) -> tuple[str, Path, str]:
    """把「原图」解析成 ComfyUI input 里的文件名，并返回它的磁盘路径与来源。

    作品库 / 最近输出里的图会先复制进 ComfyUI input（LoadImage 只能读 input）。
    """

    candidate = _text(name)
    if not candidate:
        raise ValueError("请先选择要修的原图。")
    try:
        stored = validate_input_image(candidate, "原图")
    except ValueError:
        stored = ""
    if stored:
        return stored, (COMFY_INPUT / Path(stored.replace("\\", "/"))).resolve(), "input"
    source = _resolve_output_image(candidate)
    stored = copy_output_to_input(Path(candidate).name)
    return stored, source, "output"


def load_mask_layers(mask_name: str, size: tuple[int, int]):
    """读入蒙版并统一成原图尺寸的 0/255 ``L`` 图（白=重绘区）。"""

    from PIL import Image

    stored = validate_input_image(_text(mask_name), "蒙版")
    path = (COMFY_INPUT / Path(stored.replace("\\", "/"))).resolve()
    with Image.open(path) as handle:
        mask = handle.convert("L")
    if mask.size != size:
        mask = mask.resize(size, Image.LANCZOS)
    return mask


def roi_box(mask, *, grow: int, pad: int) -> tuple[int, int, int, int]:
    """蒙版的 bbox → 外扩 grow + pad → 对齐 8 → 夹到最小/最大边长。"""

    width, height = mask.size
    if grow:
        from PIL import ImageFilter
        mask = mask.filter(ImageFilter.MaxFilter(2 * (grow // 2) + 1 if grow >= 2 else 3))
    bbox = mask.point(lambda value: 255 if value > 127 else 0).getbbox()
    if not bbox:
        raise ValueError("蒙版是空的：请先在图上圈出要修改的区域。")
    left, top, right, bottom = bbox
    left, top = max(0, left - pad), max(0, top - pad)
    right, bottom = min(width, right + pad), min(height, bottom + pad)
    box_w, box_h = right - left, bottom - top
    # 太小的 ROI 模型施展不开；太大的 ROI 在 8GB 卡上容易爆显存。
    want_w = max(box_w, min(MIN_ROI_SIDE, width))
    want_h = max(box_h, min(MIN_ROI_SIDE, height))
    growth = max(want_w / box_w if box_w else 1.0, want_h / box_h if box_h else 1.0, 1.0)
    if growth > 1.0:
        box_w, box_h = int(round(box_w * growth)), int(round(box_h * growth))
    shrink = min(1.0, MAX_ROI_SIDE / max(box_w, box_h, 1))
    box_w, box_h = max(8, int(round(box_w * shrink))), max(8, int(round(box_h * shrink)))
    center_x, center_y = (left + right) // 2, (top + bottom) // 2
    left = max(0, min(width - box_w, center_x - box_w // 2))
    top = max(0, min(height - box_h, center_y - box_h // 2))
    return left - left % 8, top - top % 8, box_w - box_w % 8, box_h - box_h % 8


def prepare_regional_inputs(source_path: Path, mask_name: str, *,
                            grow: int = 24, pad: int = 64, feather: int = 16) -> dict:
    """裁出 ROI 与羽化蒙版，写进 ComfyUI input，返回工作流需要的文件名。

    文件名带内容哈希：同样的原图 + 蒙版 + 参数只会生成一份文件，重复提交不堆垃圾。
    """

    from PIL import Image, ImageFilter, ImageOps

    with Image.open(source_path) as handle:
        image = ImageOps.exif_transpose(handle).convert("RGB")
    mask = load_mask_layers(mask_name, image.size)
    box = roi_box(mask, grow=grow, pad=pad)
    x, y, box_w, box_h = box
    digest = hashlib.sha1(
        b"|s|" + str(source_path).encode("utf-8")
        + b"|m|" + mask.tobytes()
        + f"|b|{x},{y},{box_w},{box_h}|f|{feather}".encode("utf-8")
    ).hexdigest()[:12]
    folder = _input_dir()
    crop_name = f"easy_panel/flux_{digest}_roi.png"
    mask_crop_name = f"easy_panel/flux_{digest}_mask.png"
    image.crop((x, y, x + box_w, y + box_h)).save(folder / f"flux_{digest}_roi.png", format="PNG")
    cropped_mask = mask.crop((x, y, x + box_w, y + box_h))
    if feather:
        cropped_mask = cropped_mask.filter(ImageFilter.GaussianBlur(max(1, feather / 3.0)))
    cropped_mask.save(folder / f"flux_{digest}_mask.png", format="PNG")
    return {
        "crop": crop_name,
        "mask": mask_crop_name,
        "box": {"x": x, "y": y, "width": box_w, "height": box_h},
        "size": {"width": image.width, "height": image.height},
        "roi": {"width": box_w, "height": box_h},
    }


# --------------------------------------------------------------------------- #
# 工作流
# --------------------------------------------------------------------------- #

def _scaled_size(width: int, height: int, megapixels: float) -> tuple[int, int]:
    """ImageScaleToTotalPixels 之后的尺寸（与节点公式逐字对应，仅用于计划展示）。"""

    total = float(megapixels) * 1024 * 1024
    scale_by = (total / max(1, width * height)) ** 0.5
    return (max(8, round(width * scale_by / RESOLUTION_STEPS) * RESOLUTION_STEPS),
            max(8, round(height * scale_by / RESOLUTION_STEPS) * RESOLUTION_STEPS))


def image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as handle:
        return handle.width, handle.height


def build_flux_klein_edit_workflow(edit: dict, *, filename_prefix: str = "EasyPanel_FLUX") -> dict:
    """按官方 Distilled 子图建图；``edit`` 需先经过 :func:`normalize_flux_edit`。"""

    errors = validate_flux_edit(edit)
    if errors:
        raise ValueError("；".join(errors))

    instruction = compose_flux_instruction(edit)
    source_name, source_path, _source_kind = resolve_source_image(edit["source"])
    width, height = image_size(source_path)
    regional = edit["mode"] == "regional"

    nodes: dict[str, dict] = {}

    def add(node_id: str, class_type: str, inputs: dict, meta: dict | None = None) -> str:
        node = {"class_type": class_type, "inputs": inputs}
        if meta:
            node["_meta"] = meta
        nodes[node_id] = node
        return node_id

    # 加载器（官方：UNETLoader / CLIPLoader(type=flux2) / VAELoader）
    add("10", "UNETLoader", {"unet_name": edit["unet"], "weight_dtype": "default"})
    add("11", "CLIPLoader", {"clip_name": edit["text_encoder"], "type": "flux2"})
    add("12", "VAELoader", {"vae_name": edit["vae"]})

    edit_source = source_name
    composite: dict | None = None
    if regional:
        prepared = prepare_regional_inputs(
            source_path, edit["mask"], grow=edit["grow"], pad=edit["pad"], feather=edit["feather"])
        edit_source = prepared["crop"]
        composite = {"source": source_name, "mask": prepared["mask"],
                     "size": prepared["size"], **prepared["box"]}

    add("13", "LoadImage", {"image": edit_source})
    # 官方：参考图先归一到 1MP（nearest-exact），latent 与 scheduler 都按它算。
    # ⚠ `resolution_steps` 在官方 UI 模板里是高级输入（界面上折叠起来），转成 API
    # 格式时**必须显式给值**，否则 ComfyUI 报 required_input_missing。
    add("14", "ImageScaleToTotalPixels", {
        "image": ["13", 0], "upscale_method": "nearest-exact",
        "megapixels": edit["megapixels"], "resolution_steps": RESOLUTION_STEPS})
    add("15", "GetImageSize", {"image": ["14", 0]})
    add("16", "EmptyFlux2LatentImage", {
        "width": ["15", 0], "height": ["15", 1], "batch_size": 1})
    add("17", "Flux2Scheduler", {
        "steps": edit["steps"], "width": ["15", 0], "height": ["15", 1]})
    add("18", "CLIPTextEncode", {"text": instruction, "clip": ["11", 0]})
    add("19", "ConditioningZeroOut", {"conditioning": ["18", 0]})
    add("20", "VAEEncode", {"pixels": ["14", 0], "vae": ["12", 0]})

    positive_ref: list = ["18", 0]
    negative_ref: list = ["19", 0]
    # 多参考图：官方多图子图就是对正/负两条 conditioning 各叠一层 ReferenceLatent。
    reference_ids = ["20"]
    for index, reference in enumerate(edit.get("references", [])):
        stored, _path, _kind = resolve_source_image(reference)
        load_id, scale_id, encode_id = f"4{index}1", f"4{index}2", f"4{index}3"
        add(load_id, "LoadImage", {"image": stored})
        add(scale_id, "ImageScaleToTotalPixels", {
            "image": [load_id, 0], "upscale_method": "nearest-exact",
            "megapixels": edit["megapixels"], "resolution_steps": RESOLUTION_STEPS})
        add(encode_id, "VAEEncode", {"pixels": [scale_id, 0], "vae": ["12", 0]})
        reference_ids.append(encode_id)
    for index, latent_id in enumerate(reference_ids):
        positive_id, negative_id = f"3{index}1", f"3{index}2"
        add(positive_id, "ReferenceLatent", {"conditioning": positive_ref, "latent": [latent_id, 0]})
        add(negative_id, "ReferenceLatent", {"conditioning": negative_ref, "latent": [latent_id, 0]})
        positive_ref, negative_ref = [positive_id, 0], [negative_id, 0]

    add("23", "CFGGuider", {
        "model": ["10", 0], "positive": positive_ref, "negative": negative_ref, "cfg": 1.0})
    add("24", "KSamplerSelect", {"sampler_name": "euler"})
    add("25", "RandomNoise", {"noise_seed": int(edit["seed"])})
    add("26", "SamplerCustomAdvanced", {
        "noise": ["25", 0], "guider": ["23", 0], "sampler": ["24", 0],
        "sigmas": ["17", 0], "latent_image": ["16", 0]})
    add("27", "VAEDecode", {"samples": ["26", 0], "vae": ["12", 0]})

    final_ref: list = ["27", 0]
    if composite:
        # 模型把 ROI 归一到 1MP，贴回前先缩回 ROI 尺寸：ImageCompositeMasked 的
        # ``resize_source=False`` 是按像素坐标硬贴，尺寸必须一致（mask 会被自动
        # 插值到 source 尺寸，所以 ROI 大小的羽化蒙版是对的）。
        add("32", "ImageScale", {
            "image": ["27", 0], "upscale_method": "lanczos",
            "width": int(composite["width"]), "height": int(composite["height"]),
            "crop": "disabled"})
        add("28", "LoadImage", {"image": composite["source"]})
        add("29", "LoadImageMask", {"image": composite["mask"], "channel": "red"})
        add("30", "ImageCompositeMasked", {
            "destination": ["28", 0], "source": ["32", 0],
            "x": int(composite["x"]), "y": int(composite["y"]),
            "resize_source": False, "mask": ["29", 0]})
        final_ref = ["30", 0]

    add("31", "SaveImage", {"filename_prefix": filename_prefix, "images": final_ref},
        {"artifactStage": "base", "artifactRole": "final"})

    if regional and composite:
        output_size = [composite["size"]["width"], composite["size"]["height"]]
    else:
        output_size = list(_scaled_size(width, height, edit["megapixels"]))
    plan = {
        "stages": {"26": f"FLUX 智能修图（{'局部修复' if regional else '整图细化'}）"},
        "samplers": {"26": edit["steps"]},
        "samplerOrder": ["26"],
        "detailers": [],
        "upscalers": [],
        "samplerCount": 1,
        "detailerCount": 0,
        "output": output_size,
        "outputStage": "base",
        "fluxEdit": {
            "mode": edit["mode"],
            "modeLabel": edit["mode_label"],
            "strategy": edit["strategy"],
            "strategyLabel": edit["strategy_label"],
            "steps": edit["steps"],
            "megapixels": edit["megapixels"],
            "references": len(edit.get("references", [])),
            "instruction": instruction,
        },
    }
    return {"prompt": nodes, "client_id": "easy-panel", "plan": plan}


def flux_edit_request_summary(edit: dict) -> str:
    """快照 / 作品库用的中文摘要（列表里一眼看出改了什么）。"""

    pieces = [f"{edit['mode_label']}·{edit['strategy_label']}"]
    if edit.get("instruction"):
        text = re.sub(r"\s+", " ", edit["instruction"]).strip()
        pieces.append(text if len(text) <= 48 else text[:47] + "…")
    if edit["mode"] == "regional":
        pieces.append("带蒙版")
    if edit.get("references"):
        pieces.append(f"{len(edit['references'])} 张参考图")
    return " / ".join(pieces)


def snapshot_flux_edit(edit: dict) -> dict:
    """写进生成快照的 ``fluxEdit`` 字段（不含模型二进制，只留可复现的参数）。"""

    return {
        "mode": edit["mode"],
        "modeLabel": edit["mode_label"],
        "strategy": edit["strategy"],
        "strategyLabel": edit["strategy_label"],
        "instruction": edit["instruction"],
        "composedInstruction": compose_flux_instruction(edit),
        "preserve": list(edit.get("preserve", [])),
        "source": edit["source"],
        "mask": edit["mask"],
        "references": list(edit.get("references", [])),
        "seed": edit["seed"],
        "steps": edit["steps"],
        "megapixels": edit["megapixels"],
        "feather": edit["feather"],
        "grow": edit["grow"],
        "pad": edit["pad"],
        "summary": flux_edit_request_summary(edit),
    }


def flux_edit_json(edit: dict) -> str:
    return json.dumps(snapshot_flux_edit(edit), ensure_ascii=False)
