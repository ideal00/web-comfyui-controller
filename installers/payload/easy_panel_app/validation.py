"""Model-file validation that fails before a bad job reaches ComfyUI."""

from __future__ import annotations

import json
from pathlib import Path

from easy_panel_app.config import CHECKPOINT_DIR


def checkpoint_issue(model_name: str, checkpoint_dir: Path = CHECKPOINT_DIR) -> str | None:
    """Return why a file is not a complete checkpoint, or ``None`` when valid."""
    relative = Path(str(model_name or "").replace("\\", "/"))
    if not relative.name or relative.is_absolute() or ".." in relative.parts:
        return "基础模型路径无效。"
    root = checkpoint_dir.resolve()
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
    has_clip = any(
        key.startswith("cond_stage_model.")
        or (key.startswith("conditioner.embedders.") and ".transformer." in key)
        for key in keys
    )
    has_vae = any(key.startswith("first_stage_model.") or key.startswith("vae.") for key in keys)
    if has_clip and has_vae:
        return None
    return "这是仅含扩散网络（UNet）的拆分模型，缺少内置 CLIP / VAE，不能作为本面板的 SDXL Checkpoint 使用。"


__all__ = ["checkpoint_issue"]
