"""ComfyUI 实时进度：服务端只保持一条上游连接，多个页面共享。

为什么不让每个页面各连一条：ComfyUI 按 ``client_id`` 投递执行/进度事件，
浏览器里开多个面板标签时，每个标签都会用同一个 client_id 连一条 WebSocket，
后连的那条会顶掉前面的映射 —— 用户正在看的那个页面就再也收不到 ``progress``，
进度条表现为「一直 0%，结束时突然 100%」。

这里改成：服务端保持唯一上游连接，向所有订阅者（SSE）扇出，同时在内存里保留
一份快照，供 ``/api/progress`` 轮询兜底（页面刷新、断流都能立刻恢复）。
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import urllib.parse
from collections import deque
from typing import Any, Callable, Dict, List, Optional


class ComfyProgressHub:
    """唯一上游 WebSocket + 多订阅者扇出 + 内存快照。"""

    def __init__(self, url_provider: Callable[[], str], client_id: str = "easy-panel",
                 history: int = 40) -> None:
        self._url_provider = url_provider
        self._client_id = str(client_id or "easy-panel")
        self._history: deque[Dict[str, Any]] = deque(maxlen=max(4, int(history)))
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue] = set()
        self._started = False
        self._stop = threading.Event()
        self._connected = False
        self._error_count = 0
        self._last_progress: Dict[str, Any] = {}
        self._last_node: Dict[str, Any] = {}
        self._last_event: Dict[str, Any] = {}

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        """启动后台线程；重复调用是安全的。"""

        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._thread_main, name="comfy-progress-hub",
                         daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    # --------------------------------------------------------------- subscribers
    def subscribe(self) -> "queue.Queue[str]":
        channel: "queue.Queue[str]" = queue.Queue(maxsize=200)
        with self._lock:
            self._subscribers.add(channel)
        return channel

    def unsubscribe(self, channel: "queue.Queue[str]") -> None:
        with self._lock:
            self._subscribers.discard(channel)

    # ------------------------------------------------------------------ snapshot
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "connected": self._connected,
                "client_id": self._client_id,
                "last_progress": dict(self._last_progress) or None,
                "last_node": dict(self._last_node) or None,
                "last_event": dict(self._last_event) or None,
                "updated_at": int(time.time() * 1000),
                "error_count": self._error_count,
            }

    def replay_frames(self) -> List[str]:
        """给新接入的 SSE 客户端补最后一帧（形状与 ComfyUI 原始消息一致）。"""

        with self._lock:
            progress = dict(self._last_progress)
            node = dict(self._last_node)
        frames: List[str] = []
        if progress:
            frames.append(json.dumps({
                "type": "progress",
                "data": {
                    "value": progress.get("value", 0),
                    "max": progress.get("max", 0),
                    "prompt_id": progress.get("prompt_id", ""),
                },
            }))
        if node:
            frames.append(json.dumps({
                "type": "executing",
                "data": {"node": node.get("node"), "prompt_id": node.get("prompt_id", "")},
            }))
        return frames

    # ------------------------------------------------------------------- feeding
    def handle_message(self, raw: str) -> None:
        """记录一条 ComfyUI 消息并扇出；解析失败也要原样转发。"""

        now = int(time.time() * 1000)
        message: Any = None
        try:
            message = json.loads(str(raw))
        except (TypeError, ValueError):
            message = None
        message_type = ""
        prompt_id = ""
        node: Any = None
        value: Any = None
        maximum: Any = None
        if isinstance(message, dict):
            message_type = str(message.get("type") or "")
            data = message.get("data") if isinstance(message.get("data"), dict) else {}
            prompt_id = str(data.get("prompt_id") or "")
            node = data.get("node")
            value = data.get("value")
            maximum = data.get("max")
        with self._lock:
            self._history.append({
                "type": message_type,
                "prompt_id": prompt_id,
                "node": None if node is None else str(node),
                "value": _number(value),
                "max": _number(maximum),
                "at": now,
            })
            if message_type:
                self._last_event = {"type": message_type, "prompt_id": prompt_id, "at": now}
            if prompt_id and _number(value) is not None:
                self._last_progress = {
                    "prompt_id": prompt_id,
                    "value": int(_number(value) or 0),
                    "max": int(_number(maximum) or 0),
                    "at": now,
                }
            if prompt_id and node is not None:
                self._last_node = {"prompt_id": prompt_id, "node": str(node), "at": now}
            channels = list(self._subscribers)
        for channel in channels:
            try:
                channel.put_nowait(str(raw))
            except queue.Full:
                continue

    # --------------------------------------------------------------------- inner
    def _thread_main(self) -> None:
        while not self._stop.is_set():
            try:
                asyncio.run(self._session())
            except Exception:  # 网络/依赖问题：记录后重连，绝不拖垮面板
                with self._lock:
                    self._error_count += 1
                    self._connected = False
            if self._stop.is_set():
                break
            time.sleep(3.0)

    async def _session(self) -> None:
        import aiohttp

        url = str(self._url_provider() or "")
        if not url:
            return
        separator = "&" if "?" in url else "?"
        target = url + separator + urllib.parse.urlencode({"clientId": self._client_id})
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=None)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(target, heartbeat=30) as websocket:
                    with self._lock:
                        self._connected = True
                    async for message in websocket:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            self.handle_message(str(message.data))
                        elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break
        finally:
            with self._lock:
                self._connected = False


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


__all__ = ["ComfyProgressHub"]
