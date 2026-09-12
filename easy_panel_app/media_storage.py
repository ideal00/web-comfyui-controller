"""Safe upload and ComfyUI input/output file handling."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from easy_panel_app.config import COMFY_INPUT, OUTPUT


def _multipart_image(content_type: str, body: bytes, field: str) -> tuple[bytes, str]:
    match = re.search(r'boundary=(?:"([^"]+)"|([^;\s]+))', content_type, re.I)
    if not match:
        raise ValueError("图片上传格式不正确。")
    marker = b"--" + (match.group(1) or match.group(2)).encode("utf-8")
    field_bytes = f'name="{field}"'.encode("utf-8")
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
        filename_match = re.search(br'filename="([^\"]*)"', headers)
        filename = filename_match.group(1).decode("utf-8", "replace") if filename_match else "image.png"
        return content, filename
    raise ValueError("未找到图片文件。")


def save_pose_upload(content_type: str, body: bytes) -> str:
    content, filename = _multipart_image(content_type, body, "pose")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("姿势图仅支持 PNG、JPG 或 WEBP。")
    target_dir = COMFY_INPUT / "easy_panel"
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"easy_panel/pose_{uuid.uuid4().hex[:12]}{suffix}"
    (COMFY_INPUT / stored_name).write_bytes(content)
    return stored_name


def extract_image_upload(content_type: str, body: bytes, field: str = "image") -> bytes:
    return _multipart_image(content_type, body, field)[0]


def save_reference_upload(content_type: str, body: bytes, field: str = "image") -> dict:
    """保存“上传图片提取透明 PNG”用的参考图，统一转成 PNG 放进 ComfyUI input。"""

    content, filename = _multipart_image(content_type, body, field)
    suffix = Path(filename).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("参考图仅支持 PNG、JPG 或 WEBP。")
    target_dir = COMFY_INPUT / "easy_panel"
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"easy_panel/reference_{uuid.uuid4().hex[:12]}.png"
    size: tuple[int, int] | None = None
    try:
        import io

        from PIL import Image, ImageOps

        image = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
        image.save(COMFY_INPUT / stored_name, format="PNG")
        size = image.size
    except Exception:
        # 模型只认像素，就算 Pillow 不认这种编码也照原字节存下来交给 ComfyUI。
        (COMFY_INPUT / stored_name).write_bytes(content)
    return {"image": stored_name, "name": filename, "size": size}


def copy_output_to_input(name: str) -> str:
    """把作品库/最近输出里的图片复制进 ComfyUI input，供 LoadImage 读取。"""

    relative = Path(str(name or "").replace("\\", "/"))
    if not relative.name or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("参考图路径无效。")
    source = (OUTPUT / relative).resolve()
    try:
        source.relative_to(OUTPUT.resolve())
    except ValueError as exc:
        raise ValueError("参考图路径无效。") from exc
    if not source.is_file():
        raise ValueError(f"找不到输出图片：{relative.name}")
    suffix = source.suffix.lower() or ".png"
    target_dir = COMFY_INPUT / "easy_panel"
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"easy_panel/reference_{uuid.uuid4().hex[:12]}{suffix}"
    (COMFY_INPUT / stored_name).write_bytes(source.read_bytes())
    return stored_name


def save_inpaint_upload(content_type: str, body: bytes) -> dict:
    image_bytes = extract_image_upload(content_type, body, "image")
    mask_bytes = extract_image_upload(content_type, body, "mask")
    target_dir = COMFY_INPUT / "easy_panel"
    target_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"easy_panel/inpaint_{uuid.uuid4().hex[:12]}.png"
    mask_name = f"easy_panel/inpaint_mask_{uuid.uuid4().hex[:12]}.png"
    try:
        import io
        from PIL import Image, ImageOps
    except ImportError:
        (COMFY_INPUT / image_name).write_bytes(image_bytes)
        (COMFY_INPUT / mask_name).write_bytes(mask_bytes)
        return {"image": image_name, "mask": mask_name}
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
        mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
    except Exception as exc:
        raise ValueError("原图或蒙版无法解析：" + str(exc)) from exc
    if mask.size != image.size:
        mask = mask.resize(image.size, Image.LANCZOS)
    image.save(COMFY_INPUT / image_name, format="PNG")
    mask.save(COMFY_INPUT / mask_name, format="PNG")
    return {"image": image_name, "mask": mask_name}


def list_output_images(limit: int = 80) -> list[dict]:
    if not OUTPUT.is_dir():
        return []
    try:
        candidates = sorted(OUTPUT.rglob("*"), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    entries: list[dict] = []
    for file in candidates:
        if file.suffix.lower() not in {".png", ".webp", ".jpg", ".jpeg"}:
            continue
        # 高清二采的首采对照图不是成品，不能出现在“最近输出”与图生图候选里。
        if "_base_" in file.name:
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


__all__ = [
    "extract_image_upload",
    "list_output_images",
    "prepare_generation_image",
    "save_inpaint_upload",
    "save_pose_upload",
    "validate_input_image",
]
