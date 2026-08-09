"""Backward-compatible launcher for the safe LoRA TXT smart importer."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from lora_txt_to_json import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
