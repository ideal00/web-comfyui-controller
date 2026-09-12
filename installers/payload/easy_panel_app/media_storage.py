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


def _output_path(name: str) -> Path:
    relative = Path(str(name or "").replace("\\", "/"))
    if not relative.name or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("抠图结果路径无效。")
    path = (OUTPUT / relative).resolve()
    try:
        path.relative_to(OUTPUT.resolve())
    except ValueError as exc:
        raise ValueError("抠图结果路径无效。") from exc
    if not path.is_file():
        raise ValueError(f"找不到抠图结果：{relative.name}")
    return path


def _box_mean(values, radius: int):
    import numpy as np

    pad = np.pad(values, radius + 1, mode="edge")
    integral = pad.cumsum(0).cumsum(1)
    size = 2 * radius + 1
    height, width = values.shape
    total = (integral[size:size + height, size:size + width]
             - integral[:height, size:size + width]
             - integral[size:size + height, :width]
             + integral[:height, :width])
    return total / (size * size)


def _component_size(mask, area_limit: int):
    """4 邻域连通域面积（只遍历候选像素，超过上限的块提前止损）。"""

    import numpy as np

    sizes = np.zeros(mask.shape, dtype=np.int32)
    visited = np.zeros(mask.shape, dtype=bool)
    height, width = mask.shape
    for start_y, start_x in zip(*np.nonzero(mask)):
        if visited[start_y, start_x]:
            continue
        stack = [(int(start_y), int(start_x))]
        visited[start_y, start_x] = True
        component: list[tuple[int, int]] = []
        overflow = False
        while stack:
            y, x = stack.pop()
            component.append((y, x))
            if len(component) > area_limit:
                overflow = True
                break
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    stack.append((ny, nx))
        size = area_limit + 1 if overflow else len(component)
        for y, x in component:
            sizes[y, x] = size
    return sizes


def _component_size(mask, area_limit: int):
    """4 邻域连通域面积（只遍历候选像素，超过上限的块提前止损）。"""

    import numpy as np

    sizes = np.zeros(mask.shape, dtype=np.int32)
    visited = np.zeros(mask.shape, dtype=bool)
    height, width = mask.shape
    for start_y, start_x in zip(*np.nonzero(mask)):
        if visited[start_y, start_x]:
            continue
        stack = [(int(start_y), int(start_x))]
        visited[start_y, start_x] = True
        component: list[tuple[int, int]] = []
        overflow = False
        while stack:
            y, x = stack.pop()
            component.append((y, x))
            if len(component) > area_limit:
                overflow = True
                break
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    stack.append((ny, nx))
        size = area_limit + 1 if overflow else len(component)
        for y, x in component:
            sizes[y, x] = size
    return sizes


def clean_transparent_residue(name: str, *, tolerance: float = 20, area_limit: int = 800,
                              dark_ratio: float = 0.25, window: int = 31) -> dict:
    """清掉发丝之间的缝隙背景。

    四个条件同时成立才算缝隙：颜色接近背景色、当前是不透明前景、把该像素当成背景后会成为
    **封闭孔洞**（不与图像外部连通）、四周被深色发丝包围、且连通块面积很小。白色礼服虽然
    颜色也接近背景，但与外部背景连通，因此不会被误删。

    ⚠️ 用户要求（2026-09-12）：抠图链路已经够用，**不要再往这里追加自动后处理**——
    之前每次加自动裁剪/清理都会裁到衣服。要新增任何后处理，必须先用真实婚纱图
    （白色礼服 + 白背景）验证“纯白衣物像素零改动”，并保留可关闭的开关。
    """

    import numpy as np
    from PIL import Image

    try:
        from scipy import ndimage
    except ImportError:
        return {"name": str(name), "removed": 0, "skipped": "缺少 scipy，跳过缝隙清理"}

    path = _output_path(name)
    with Image.open(path) as handle:
        image = handle.convert("RGBA")
    rgba = np.asarray(image).astype(np.float32)
    rgb, alpha = rgba[..., :3], rgba[..., 3] / 255.0
    transparent = alpha < 0.05
    if int(transparent.sum()) < 500:
        return {"name": path.name, "removed": 0, "skipped": "透明区太少，无法估计背景色"}
    background = np.median(rgb[transparent], axis=0)
    color_close = np.abs(rgb - background).max(axis=2) < tolerance
    solid = alpha > 0.7
    luminance = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    dark_ratio_map = _box_mean((luminance < 130).astype(np.float32), window // 2)

    # 把候选像素当作背景后，从图像外部洪水填充：填得到的就是“跟外面连通”的区域（衣服/背景）。
    bg_like = np.pad((alpha <= 0.5) | (color_close & solid), 1, constant_values=True)
    seed = np.zeros_like(bg_like)
    seed[0, :] = bg_like[0, :]
    seed[-1, :] = bg_like[-1, :]
    seed[:, 0] = bg_like[:, 0]
    seed[:, -1] = bg_like[:, -1]
    external = ndimage.binary_propagation(seed, mask=bg_like)[1:-1, 1:-1]

    candidate = color_close & solid & ~external & (dark_ratio_map > dark_ratio)
    if not candidate.any():
        return {"name": path.name, "removed": 0}
    labels, count = ndimage.label(candidate)
    sizes = np.zeros(count + 1, dtype=np.int32)
    if count:
        sizes[1:] = ndimage.sum(candidate, labels, range(1, count + 1))
    sizes_map = sizes[labels] if count else candidate.astype(np.int32)
    residue = candidate & (sizes_map <= area_limit)
    removed = int(residue.sum())
    if not removed:
        return {"name": path.name, "removed": 0}
    alpha[residue] = 0.0
    cleaned = image.copy()
    cleaned.putalpha(Image.fromarray((alpha * 255).round().astype("uint8")))
    target = path.with_name(path.stem + "_clean.png")
    cleaned.save(target, format="PNG")
    return {"name": target.name, "removed": removed, "source": path.name,
            "background": [int(value) for value in background]}


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
