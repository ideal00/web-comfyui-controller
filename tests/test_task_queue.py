from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.task_queue import (
    CANCELLED,
    COMPLETED,
    ERROR,
    PENDING,
    RUNNING,
    SKIPPED,
    TaskQueue,
    TaskQueueRunner,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float = 1.0) -> None:
        self.value += seconds


def payload(seed: str = "1") -> dict:
    return {"model": "m.safetensors", "seed": seed, "prompt": "1girl"}


class TaskQueueTests(unittest.TestCase):
    """面板任务队列：暂停 / 取消后续 / 只跑入选 / 清理失败。"""

    def queue(self, folder: str) -> TaskQueue:
        return TaskQueue(Path(folder) / "tasks.json")

    def test_add_pause_resume_and_selected_only(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = self.queue(folder)
            queue.add([{"label": "A", "payload": payload("1")},
                       {"label": "B", "payload": payload("2"), "selected": False}])
            self.assertEqual(2, queue.snapshot()["counts"]["total"])

            queue.control("pause")
            self.assertTrue(queue.paused)
            self.assertIsNone(queue.next_task())

            queue.control("run")
            queue.control("select-only", value=True)
            first = queue.next_task()
            self.assertEqual("A", first["label"])
            queue.mark(first["id"], COMPLETED)
            self.assertIsNone(queue.next_task())
            snapshot = queue.snapshot()
            self.assertEqual(1, snapshot["counts"][SKIPPED])
            self.assertEqual(1, snapshot["counts"][COMPLETED])

    def test_cancel_pending_returns_prompt_ids_for_comfy_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = self.queue(folder)
            queue.add([{"label": "A", "payload": payload("1")},
                       {"label": "B", "payload": payload("2")}])
            items = queue.items()
            queue.mark(items[0]["id"], RUNNING, prompt_id="p-1")
            result = queue.control("cancel-pending")
            self.assertEqual(1, result["cancelled"])
            self.assertEqual([], result["prompt_ids"])
            self.assertEqual(CANCELLED, queue.get(items[1]["id"])["status"])
            self.assertEqual(RUNNING, queue.get(items[0]["id"])["status"])

            result = queue.control("cancel-current")
            self.assertEqual(["p-1"], result["prompt_ids"])
            self.assertEqual(1, result["cancelled"])
            self.assertEqual(CANCELLED, queue.get(items[0]["id"])["status"])

    def test_clean_failed_keeps_finished(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = self.queue(folder)
            queue.add([{"label": "A", "payload": payload("1")},
                       {"label": "B", "payload": payload("2")},
                       {"label": "C", "payload": payload("3")}])
            items = queue.items()
            queue.mark(items[0]["id"], COMPLETED)
            queue.mark(items[1]["id"], ERROR, error="CUDA OOM")
            queue.mark(items[2]["id"], CANCELLED)
            result = queue.control("clean-failed")
            self.assertEqual(2, result["removed"])
            remaining = queue.items()
            self.assertEqual([COMPLETED], [item["status"] for item in remaining])
            self.assertEqual(1, queue.snapshot()["counts"]["total"])

    def test_state_survives_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = self.queue(folder)
            queue.add([{"label": "A", "payload": payload("1")}])
            queue.set_flags(paused=True, auto_skip=False)
            again = self.queue(folder)
            self.assertTrue(again.paused)
            self.assertFalse(again.auto_skip)
            self.assertEqual(1, again.snapshot()["counts"]["total"])


class TaskQueueRunnerTests(unittest.TestCase):
    """失败自动跳过：单个任务失败只标记它，队列继续跑下一个。"""

    def build(self, folder: str, *, auto_skip: bool = True):
        queue = TaskQueue(Path(folder) / "tasks.json")
        clock = FakeClock()
        submitted: list[str] = []

        def submit(item: dict) -> dict:
            submitted.append(str(item["label"]))
            return {"prompt_id": "p-" + str(item["label"]), "snapshot_id": "s-" + str(item["label"])}

        state = {"fail": {"C"}}

        def probe(prompt_id: str):
            label = prompt_id.split("-")[-1]
            if label in state["fail"]:
                return "error", {"error": "CUDA out of memory"}
            return "completed", {"images": []}

        runner = TaskQueueRunner(queue, submit=submit, probe=probe, poll_seconds=0.5,
                                 clock=clock, missing_grace=2)
        queue.set_flags(auto_skip=auto_skip)
        return queue, runner, clock, submitted, state

    def test_auto_skip_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            queue, runner, clock, submitted, _ = self.build(folder)
            queue.add([{"label": label, "payload": payload(str(index))}
                       for index, label in enumerate(["A", "B", "C", "D"], start=1)])

            for _ in range(40):
                clock.advance()
                runner.tick()

            counts = queue.snapshot()["counts"]
            self.assertEqual(4, counts["total"])
            self.assertEqual(3, counts[COMPLETED])
            self.assertEqual(1, counts[ERROR])
            self.assertEqual(["A", "B", "C", "D"], submitted)
            self.assertFalse(queue.paused)
            failed = [item for item in queue.items() if item["status"] == ERROR][0]
            self.assertEqual("C", failed["label"])
            self.assertIn("CUDA", failed["error"])

    def test_disabling_auto_skip_pauses_the_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            queue, runner, clock, submitted, state = self.build(folder, auto_skip=False)
            state["fail"] = {"B"}
            queue.add([{"label": "A", "payload": payload("1")},
                       {"label": "B", "payload": payload("2")},
                       {"label": "C", "payload": payload("3")}])
            for _ in range(20):
                clock.advance()
                runner.tick()

            statuses = [item["status"] for item in queue.items()]
            self.assertEqual([COMPLETED, ERROR, PENDING], statuses)
            self.assertTrue(queue.paused)
            self.assertEqual(["A", "B"], submitted)
            self.assertIn("暂停", queue.snapshot()["message"])

            # 重新运行后，剩下的任务会继续投递
            queue.control("run")
            for _ in range(20):
                clock.advance()
                runner.tick()
            self.assertEqual(2, queue.snapshot()["counts"][COMPLETED])
            self.assertEqual(["A", "B", "C"], submitted)

    def test_submit_failure_is_recorded_and_queue_continues(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = TaskQueue(Path(folder) / "tasks.json")
            calls = {"n": 0}

            def submit(item: dict) -> dict:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("ComfyUI 拒绝请求")
                return {"prompt_id": "p-2"}

            runner = TaskQueueRunner(queue, submit=submit, probe=lambda _pid: ("completed", {}))
            queue.add([{"label": "A", "payload": payload("1")},
                       {"label": "B", "payload": payload("2")}])
            self.assertEqual("error", runner.tick())
            self.assertEqual(ERROR, queue.items()[0]["status"])
            self.assertEqual("submitted", runner.tick())
            self.assertEqual(RUNNING, queue.items()[1]["status"])

    def test_next_task_reports_idle_when_paused(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = TaskQueue(Path(folder) / "tasks.json")
            runner = TaskQueueRunner(queue, submit=lambda item: {"prompt_id": "p"},
                                     probe=lambda pid: ("running", {}))
            queue.add([{"label": "A", "payload": payload("1")}])
            self.assertEqual(PENDING, queue.items()[0]["status"])
            queue.set_flags(paused=True)
            self.assertEqual("paused", runner.tick())


if __name__ == "__main__":
    unittest.main()
