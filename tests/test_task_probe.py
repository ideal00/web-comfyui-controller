"""任务队列探测：正在执行的任务不能因为"history 里还没有"被判失败。

背景（真实事故）：ComfyUI 的 /history 只记录**已经执行完**的任务，正在排队或正在
执行的任务只在 /queue 里。之前的 probe 只看 /history，于是出图耗时超过宽限时间
（默认 15 次 × 2 秒）的任务会被判定为"找不到记录"，图片生成了面板却显示失败。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PANEL_ROOT = Path(__file__).resolve().parents[1]
if str(PANEL_ROOT) not in sys.path:
    sys.path.insert(0, str(PANEL_ROOT))

SPEC = importlib.util.spec_from_file_location("easy_panel_task_probe_test", PANEL_ROOT / "easy_panel.py")
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)

from easy_panel_app.task_queue import RUNNING, TaskQueue, TaskQueueRunner


PROMPT_ID = "711c6bff-3823-4e30-b147-70b3ca5e2e7c"


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float = 1.0) -> None:
        self.value += seconds


def history_entry(state: str = "success", filename: str = "EasyPanel_x_00001_.png") -> dict:
    return {PROMPT_ID: {
        "status": {"status_str": state, "messages": []},
        "outputs": {"9": {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}},
    }}


class TaskComfyProbeTests(unittest.TestCase):
    """probe 必须同时看 /history 与 /queue。"""

    def probe(self, history: dict, queue: dict | Exception) -> tuple[str, dict]:
        def fake_comfy_json(path, method="GET", payload=None):
            if str(path).startswith("/history"):
                if isinstance(history, Exception):
                    raise history
                return history
            if str(path) == "/queue":
                if isinstance(queue, Exception):
                    raise queue
                return queue
            raise AssertionError("unexpected path " + str(path))

        with patch.object(easy_panel, "comfy_json", fake_comfy_json):
            return easy_panel.task_comfy_probe(PROMPT_ID)

    def test_history_success_reports_completed_with_images(self):
        status, payload = self.probe(history_entry("success"), {"queue_running": [], "queue_pending": []})
        self.assertEqual("completed", status)
        self.assertEqual(["EasyPanel_x_00001_.png"], [item["filename"] for item in payload["images"]])

    def test_history_error_reports_error(self):
        status, payload = self.probe(history_entry("error"), {})
        self.assertEqual("error", status)
        self.assertIn("error", payload)

    def test_running_task_in_comfy_queue_is_not_missing(self):
        """真实事故：任务正在执行，history 里还没有，但 /queue 里有。"""

        status, _ = self.probe({}, {"queue_running": [[0, PROMPT_ID, {}, {}, ["9"]]], "queue_pending": []})
        self.assertEqual("running", status)

    def test_pending_task_in_comfy_queue_is_not_missing(self):
        status, _ = self.probe({}, {"queue_running": [], "queue_pending": [[1, PROMPT_ID, {}, {}, ["9"]]]})
        self.assertEqual("running", status)

    def test_queue_entries_may_be_mappings(self):
        status, _ = self.probe({}, {"queue_pending": [{"prompt_id": PROMPT_ID}]})
        self.assertEqual("running", status)

    def test_missing_when_absent_from_history_and_queue(self):
        status, payload = self.probe({}, {"queue_running": [], "queue_pending": []})
        self.assertEqual("missing", status)
        self.assertEqual({}, payload)

    def test_queue_lookup_failure_reports_unknown(self):
        """探测本身出错（网络抖动）必须区分于"确认不存在"。"""

        status, _ = self.probe(history_entry("success"), RuntimeError("boom"))
        self.assertEqual("completed", status)  # history 有结果时不受影响
        status, _ = self.probe({}, RuntimeError("boom"))
        self.assertEqual("unknown", status)


class QueueRunnerUnknownStatusTests(unittest.TestCase):
    """unknown 状态不能累加 missing 计数，否则网络抖动会误杀任务。"""

    def queue(self, folder: str) -> TaskQueue:
        return TaskQueue(Path(folder) / "tasks.json")

    def test_unknown_status_keeps_task_running(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = self.queue(folder)
            queue.add([{"label": "A", "payload": {"model": "m", "seed": "1", "prompt": "x"}}])
            clock = FakeClock()
            runner = TaskQueueRunner(queue, submit=lambda item: {"prompt_id": "pid-1"},
                                     probe=lambda _pid: ("unknown", {}), poll_seconds=1.0,
                                     clock=clock, missing_grace=2)
            self.assertEqual("submitted", runner.tick())
            for _ in range(6):
                clock.advance(2.0)
                self.assertEqual("waiting", runner.tick())
            self.assertEqual(RUNNING, queue.snapshot()["items"][0]["status"])

    def test_running_status_resets_missing_counter(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = self.queue(folder)
            queue.add([{"label": "A", "payload": {"model": "m", "seed": "1", "prompt": "x"}}])
            clock = FakeClock()
            answers = iter(["missing", "running", "missing", "running", "missing"])
            runner = TaskQueueRunner(queue, submit=lambda item: {"prompt_id": "pid-1"},
                                     probe=lambda _pid: (next(answers, "running"), {}),
                                     poll_seconds=1.0, clock=clock, missing_grace=2)
            self.assertEqual("submitted", runner.tick())
            for _ in range(5):
                clock.advance(2.0)
                runner.tick()
            self.assertEqual(RUNNING, queue.snapshot()["items"][0]["status"])

    def test_confirmed_missing_still_fails_after_grace(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = self.queue(folder)
            queue.add([{"label": "A", "payload": {"model": "m", "seed": "1", "prompt": "x"}}])
            queue.set_flags(auto_skip=True)
            clock = FakeClock()
            runner = TaskQueueRunner(queue, submit=lambda item: {"prompt_id": "pid-1"},
                                     probe=lambda _pid: ("missing", {}), poll_seconds=1.0,
                                     clock=clock, missing_grace=2)
            self.assertEqual("submitted", runner.tick())
            clock.advance(2.0)
            self.assertEqual("waiting", runner.tick())
            clock.advance(2.0)
            self.assertEqual("error", runner.tick())


if __name__ == "__main__":
    unittest.main()
