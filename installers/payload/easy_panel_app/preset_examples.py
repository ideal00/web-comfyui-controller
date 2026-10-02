"""Durable example images for personal prompt presets, separate from outputs."""
from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from easy_panel_app.config import ROOT

EXAMPLE_DIR = ROOT / "preset_examples"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
_IMAGE_ID = re.compile(r"^[0-9a-f]{64}$")


def normalize_example_id(value) -> str:
    return value if isinstance(value, str) and _IMAGE_ID.fullmatch(value) else ""


def example_path(image_id: str) -> Path:
    if not normalize_example_id(image_id):
        raise ValueError("例图编号无效。")
    return EXAMPLE_DIR / (image_id + ".webp")


def save_example(content: bytes) -> dict:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("例图为空或超过 20 MB。")
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("例图仅支持 PNG、JPG 或 WebP。")
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("例图像素过多，请先缩小图片。")
            source.load()
            transpose = getattr(ImageOps, "exif_transpose", None)
            image = (transpose(source) if transpose else source).convert("RGBA")
            image.thumbnail((1600, 1600), getattr(Image, "Resampling", Image).LANCZOS)
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=90, method=4)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("例图像素过多，请先缩小图片。") from exc
    except (OSError, SyntaxError) as exc:
        raise ValueError("无法读取例图，请上传有效的 PNG、JPG 或 WebP。") from exc
    data = output.getvalue()
    image_id = hashlib.sha256(data).hexdigest()
    EXAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    path = example_path(image_id)
    if not path.exists():
        with tempfile.NamedTemporaryFile(dir=EXAMPLE_DIR, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with temporary.open("wb") as handle:
                handle.write(data)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"ok": True, "exampleImage": image_id,
            "url": "/api/preset-examples/image?id=" + image_id,
            "width": image.width, "height": image.height}
