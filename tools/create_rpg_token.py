"""Create or reuse a local token for the Easy Panel mobile RPG API."""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "rpg_mobile_token.txt")
try:
    token = path.read_text(encoding="utf-8").strip() if path.exists() else ""
except OSError:
    token = ""
if len(token) < 24:
    token = secrets.token_urlsafe(24)
    path.write_text(token + "\n", encoding="utf-8")
print(token)
