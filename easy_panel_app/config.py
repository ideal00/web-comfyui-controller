"""Runtime configuration with backward-compatible local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMFY_ROOT = Path(r"G:\ComfyUI\ComfyUI_windows_portable\ComfyUI")


def _path_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else default


def _port_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是 1–65535 的整数。") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} 必须是 1–65535 的整数。")
    return port


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    comfy_url: str
    project_root: Path
    output_dir: Path
    comfy_input_dir: Path
    lora_dir: Path
    tag_data_dir: Path
    anima_tag_file: Path
    lora_notes_file: Path

    @property
    def comfy_root(self) -> Path:
        return self.comfy_input_dir.parent

    @property
    def comfy_models_dir(self) -> Path:
        return self.comfy_root / "models"

    @property
    def checkpoint_dir(self) -> Path:
        return self.comfy_models_dir / "checkpoints"


def load_settings() -> Settings:
    """Load settings once at process start.

    Environment overrides make side-by-side and portable testing possible while
    preserving the exact paths and ports used by the existing launch scripts.
    """

    comfy_root = _path_env("EASY_PANEL_COMFY_ROOT", DEFAULT_COMFY_ROOT)
    project_root = _path_env("EASY_PANEL_ROOT", PROJECT_ROOT)
    comfy_input = _path_env("EASY_PANEL_COMFY_INPUT", comfy_root / "input")
    output = _path_env("EASY_PANEL_OUTPUT", comfy_root / "output")
    lora_dir = _path_env("EASY_PANEL_LORA_DIR", comfy_root / "models" / "loras")
    return Settings(
        host=os.environ.get("EASY_PANEL_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_port_env("EASY_PANEL_PORT", 8190),
        comfy_url=os.environ.get("EASY_PANEL_COMFY_URL", "http://127.0.0.1:8188").rstrip("/"),
        project_root=project_root,
        output_dir=output,
        comfy_input_dir=comfy_input,
        lora_dir=lora_dir,
        tag_data_dir=project_root / "vendor" / "tagcomplete-data",
        anima_tag_file=project_root / "vendor" / "anima-tags" / "anima-1.0.csv",
        lora_notes_file=project_root / "lora_notes.json",
    )


SETTINGS = load_settings()

# Compatibility aliases retained for the legacy facade and third-party scripts.
HOST = SETTINGS.host
PORT = SETTINGS.port
COMFY = SETTINGS.comfy_url
ROOT = SETTINGS.project_root
OUTPUT = SETTINGS.output_dir
COMFY_INPUT = SETTINGS.comfy_input_dir
LORA_DIR = SETTINGS.lora_dir
TAG_DATA = SETTINGS.tag_data_dir
ANIMA_TAG_DATA = SETTINGS.anima_tag_file
LORA_NOTES = SETTINGS.lora_notes_file
COMFY_MODELS = SETTINGS.comfy_models_dir
CHECKPOINT_DIR = SETTINGS.checkpoint_dir
