"""批处理队列进度桥：队列期间也要有一张一张的进度与出图（panel.js 末尾模块）。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.task_queue import TaskQueue  # noqa: E402


def panel_source() -> str:
    return (PROJECT_DIR / "web/assets/js/panel.js").read_text(encoding="utf-8")


class QueueProgressBridgeTests(unittest.TestCase):
    """面板前端的接线：服务端队列（/api/tasks）→ 进度框与逐张结果。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.panel = panel_source()
        cls.bridge = cls.panel.split("批处理队列进度桥", 1)[-1]

    def test_bridge_polls_server_task_queue(self):
        self.assertIn("/api/tasks", self.bridge)
        self.assertIn("function queueBridgeStart(", self.bridge)
        self.assertIn("async function queueBridgeTick()", self.bridge)
        self.assertIn("QUEUE_BRIDGE_POLL_MS", self.bridge)

    def test_bridge_registers_prompt_and_plan_for_runner_tasks(self):
        self.assertIn("if(item.prompt_id&&!record.promptId)", self.bridge)
        self.assertIn("registerGenerationPrompt(record.promptId", self.bridge)
        # 执行计划（阶段名/采样步数）来自服务端任务项，进度框才能显示“首采采样 5/8”。
        self.assertIn("item.plan&&typeof item.plan==='object'?item.plan:null", self.bridge)

    def test_bridge_shows_images_one_by_one(self):
        self.assertIn("queueBridgeImages", self.bridge)
        self.assertIn("renderGeneratedImages(state.images)", self.bridge)
        self.assertIn("markGenerationPromptComplete(record.promptId)", self.bridge)

    def test_bridge_counts_only_this_batch(self):
        # 队列里常有历史遗留任务，进度必须只统计本次提交的任务，否则会停在“98/102”。
        self.assertIn("function queueBridgeScopeStats()", self.bridge)
        self.assertIn("stats.finished", self.bridge)
        self.assertIn("stats.pending", self.bridge)
        self.assertIn("state.ids.has(id)", self.bridge)
        self.assertNotIn("counts.completed||0}/${counts.total||state.total}", self.bridge)
        self.assertIn("队列其它任务", self.bridge)

    def test_bridge_wraps_send_and_render(self):
        self.assertIn("const queueBridgeOriginalSend=sendJobQueue;", self.bridge)
        self.assertIn("sendJobQueue=async function queueBridgeSend()", self.bridge)
        self.assertIn("const queueBridgeOriginalRender=renderGenerationProgress;", self.bridge)
        self.assertIn("renderGenerationProgress=function queueBridgeRender()", self.bridge)
        self.assertIn("window.__queueProgressBridge=", self.bridge)

    def test_bridge_finishes_when_own_tasks_done(self):
        self.assertIn("stats.finished>=stats.total", self.bridge)
        self.assertIn("finishGenerationProgress(stats.error===0", self.bridge)
        self.assertIn("queueBridgeStop()", self.bridge)

    def test_payload_copy_matches(self):
        payload = (PROJECT_DIR / "installers/payload/web/assets/js/panel.js").read_bytes()
        self.assertEqual((PROJECT_DIR / "web/assets/js/panel.js").read_bytes(), payload)

    def test_index_html_caches_bust_new_panel_js(self):
        for page in (PROJECT_DIR / "index.html", PROJECT_DIR / "installers/payload/index.html"):
            content = page.read_text(encoding="utf-8")
            self.assertIn("panel.js?v=74", content)


class TaskQueueSnapshotContractTests(unittest.TestCase):
    """进度桥依赖的接口契约：任务项要带 prompt_id 与执行计划。"""

    def test_snapshot_exposes_prompt_id_and_plan_for_running_task(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = TaskQueue(Path(folder) / "tasks.json")
            queue.add([{"label": "anima-base · seed 1", "payload": {"model": "anima-base-v1.0.safetensors"}}])
            task_id = queue.items()[0]["id"]
            plan = {"stages": {"3": "首采采样"}, "samplers": {"3": 30}, "samplerOrder": ["3"]}
            queue.mark(task_id, "running", prompt_id="prompt-abc", plan=plan)
            snapshot = queue.snapshot()
            self.assertEqual("prompt-abc", snapshot["running"]["prompt_id"])
            self.assertEqual(plan, snapshot["running"]["plan"])
            self.assertEqual(1, snapshot["counts"]["running"])

    def test_counts_include_total_for_scoped_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = TaskQueue(Path(folder) / "tasks.json")
            queue.add([{"label": "a"}, {"label": "b"}])
            counts = queue.counts()
            self.assertEqual(2, counts["total"])
            self.assertEqual(2, counts["pending"])
            self.assertEqual(0, counts["completed"])


if __name__ == "__main__":
    unittest.main()
