"""实时进度枢纽（ComfyProgressHub）的契约测试。

背景：ComfyUI 按 ``client_id`` 投递执行/进度事件，浏览器里开多个面板标签时，
每个标签各连一条 WebSocket 会互相顶掉映射 —— 用户正在看的那个页面收不到
``progress``，进度条表现为「一直 0%，结束时突然 100%」。

现在由服务端保持唯一上游连接，向所有 SSE 订阅者扇出，并把最后一帧留在内存里
供 ``/api/progress`` 轮询兜底。这些测试锁住这层语义，避免以后又退回「每页面一条
连接、没有兜底」的写法。
"""

from __future__ import annotations

import importlib.util
import json
import queue
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.comfy_progress_hub import ComfyProgressHub

SPEC = importlib.util.spec_from_file_location("easy_panel_progress_hub_test", PROJECT_DIR / "easy_panel.py")
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


def message(kind: str, **data) -> str:
    return json.dumps({"type": kind, "data": data})


class ComfyProgressHubTests(unittest.TestCase):
    """快照、扇出与重放帧。"""

    def make_hub(self) -> ComfyProgressHub:
        return ComfyProgressHub(url_provider=lambda: "ws://127.0.0.1:8188/ws")

    def test_snapshot_tracks_last_progress_and_node(self):
        hub = self.make_hub()
        hub.handle_message(message("execution_start", prompt_id="p1"))
        hub.handle_message(message("executing", prompt_id="p1", node=7))
        hub.handle_message(message("progress", prompt_id="p1", value=12, max=24))

        snapshot = hub.snapshot()
        self.assertEqual("p1", snapshot["last_progress"]["prompt_id"])
        self.assertEqual(12, snapshot["last_progress"]["value"])
        self.assertEqual(24, snapshot["last_progress"]["max"])
        self.assertEqual("7", snapshot["last_node"]["node"])
        self.assertEqual("progress", snapshot["last_event"]["type"])
        self.assertFalse(snapshot["connected"])
        self.assertEqual("easy-panel", snapshot["client_id"])

    def test_subscribers_receive_raw_messages_and_can_leave(self):
        hub = self.make_hub()
        channel = hub.subscribe()
        raw = message("progress", prompt_id="p1", value=3, max=24)
        hub.handle_message(raw)
        self.assertEqual(raw, channel.get_nowait())

        hub.unsubscribe(channel)
        hub.handle_message(message("progress", prompt_id="p1", value=4, max=24))
        with self.assertRaises(queue.Empty):
            channel.get_nowait()

    def test_replay_frames_rebuild_comfyui_shaped_messages(self):
        hub = self.make_hub()
        hub.handle_message(message("executing", prompt_id="p2", node="12"))
        hub.handle_message(message("progress", prompt_id="p2", value=6, max=20))

        frames = [json.loads(frame) for frame in hub.replay_frames()]
        self.assertEqual(["progress", "executing"], [frame["type"] for frame in frames])
        self.assertEqual({"value": 6, "max": 20, "prompt_id": "p2"}, frames[0]["data"])
        self.assertEqual({"node": "12", "prompt_id": "p2"}, frames[1]["data"])

    def test_replay_frames_are_empty_without_history(self):
        self.assertEqual([], self.make_hub().replay_frames())

    def test_malformed_messages_are_forwarded_but_not_recorded(self):
        hub = self.make_hub()
        channel = hub.subscribe()
        hub.handle_message("not json")
        self.assertEqual("not json", channel.get_nowait())
        snapshot = hub.snapshot()
        self.assertIsNone(snapshot["last_progress"])
        self.assertIsNone(snapshot["last_node"])

    def test_prompt_and_node_survive_a_page_reload(self):
        """刷新页面后仍要能补齐当前进度，而不是从 0% 重新开始。"""

        hub = self.make_hub()
        hub.handle_message(message("progress", prompt_id="p3", value=18, max=24))
        hub.handle_message(message("executing", prompt_id="p3", node="9"))
        hub.handle_message(message("progress", prompt_id="p3", value=19, max=24))

        snapshot = hub.snapshot()
        self.assertEqual(19, snapshot["last_progress"]["value"])
        self.assertEqual("9", snapshot["last_node"]["node"])


class ProgressWiringTests(unittest.TestCase):
    """后端与前端必须使用同一份进度快照。"""

    def test_backend_streams_from_the_hub(self):
        source = (PROJECT_DIR / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn("from easy_panel_app.comfy_progress_hub import ComfyProgressHub", source)
        self.assertIn("def comfy_progress_hub() -> ComfyProgressHub:", source)
        self.assertIn("hub = comfy_progress_hub()", source)
        self.assertIn("channel = hub.subscribe()", source)
        self.assertIn("hub.unsubscribe(channel)", source)
        self.assertIn("for frame in hub.replay_frames():", source)
        self.assertIn('elif parsed.path == "/api/progress":', source)
        self.assertIn('"progress": comfy_progress_hub().snapshot(),', source)
        # 不再每个 HTTP 请求各连一条 ComfyUI WebSocket（会互相顶掉 client_id）。
        self.assertNotIn("async def relay():", source)

    def test_frontend_falls_back_to_the_snapshot(self):
        panel = (PROJECT_DIR / "web/assets/js/panel.js").read_text(encoding="utf-8")
        self.assertIn("function applyProgressSnapshot(", panel)
        self.assertIn("async function loadProgressSnapshot(", panel)
        self.assertIn("function startProgressWatch(", panel)
        self.assertIn("function stopProgressWatch(", panel)
        self.assertIn("await(await fetch('/api/progress')).json()", panel)
        # EventSource 已经 CLOSED 时必须重建，否则永远不会再有进度来源。
        self.assertIn("comfyProgressSource.readyState!==2", panel)

        html = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("panel.js?v=", html)

    def test_progress_is_weighted_by_the_execution_plan(self):
        """两段式（首采 → 超分 → 二采）不能首采完就 100% 再回落到 15%。"""

        panel = (PROJECT_DIR / "web/assets/js/panel.js").read_text(encoding="utf-8")
        self.assertIn("function recordComfyProgress(", panel)
        self.assertIn("plan.samplerOrder", panel)
        self.assertIn("planRatio", panel)
        # SSE 与快照两条通道必须共用同一套加权，不能各自算 value/max。
        self.assertEqual(2, panel.count("recordComfyProgress(promptId,data.value,data.max)")
                         + panel.count("recordComfyProgress(String(progress.prompt_id),progress.value,progress.max)"))


if __name__ == "__main__":
    unittest.main()
