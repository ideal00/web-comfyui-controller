"""Small typed boundary around ComfyUI's local HTTP API."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from easy_panel_app.config import SETTINGS


# ComfyUI is a local process (127.0.0.1 by default) and must never be routed
# through a system or environment proxy: a proxy in the middle turns healthy
# loopback calls into "HTTP Error 502: Bad Gateway".  Build a dedicated opener
# with proxies disabled so panel requests always reach ComfyUI directly.
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


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
        with _NO_PROXY_OPENER.open(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


DEFAULT_CLIENT = ComfyClient()


def comfy_json(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    """Backward-compatible functional API used by the legacy facade."""

    return DEFAULT_CLIENT.request(path, method, payload)


__all__ = ["ComfyClient", "DEFAULT_CLIENT", "comfy_json"]
