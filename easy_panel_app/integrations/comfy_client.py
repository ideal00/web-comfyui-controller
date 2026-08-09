"""Small typed boundary around ComfyUI's local HTTP API."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from easy_panel_app.config import SETTINGS


@dataclass(frozen=True)
class ComfyClient:
    base_url: str = SETTINGS.comfy_url
    timeout: float = 45.0

    def request(self, path: str, method: str = "GET", payload: dict | None = None) -> dict:
        if not path.startswith("/"):
            raise ValueError("ComfyUI API 路径必须以 / 开头。")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


DEFAULT_CLIENT = ComfyClient()


def comfy_json(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    """Backward-compatible functional API used by the legacy facade."""

    return DEFAULT_CLIENT.request(path, method, payload)


__all__ = ["ComfyClient", "DEFAULT_CLIENT", "comfy_json"]
