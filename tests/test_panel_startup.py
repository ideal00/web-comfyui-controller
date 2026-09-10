# -*- coding: utf-8 -*-
"""面板启动路径回归：任务队列后台线程必须能起来，不能把入口卡死。

之前 `start_task_queue_runner()` 在持有 `_TASK_QUEUE_LOCK` 的情况下又调用
`task_queue()`，而后者要拿同一把非重入锁 → 面板进程卡在绑定端口之前，
浏览器就表现为「打不开面板」。
"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import easy_panel  # noqa: E402


class PanelStartupTests(unittest.TestCase):
    def setUp(self):
        self._original_file = easy_panel.TASK_QUEUE_FILE
        self._original_queue = easy_panel._TASK_QUEUE
        self._original_runner = easy_panel._TASK_RUNNER
        self._folder = tempfile.TemporaryDirectory()
        easy_panel.TASK_QUEUE_FILE = Path(self._folder.name) / "tasks.json"
        easy_panel._TASK_QUEUE = None
        easy_panel._TASK_RUNNER = None

    def tearDown(self):
        runner = easy_panel._TASK_RUNNER
        if runner is not None:
            runner.stop()
        easy_panel.TASK_QUEUE_FILE = self._original_file
        easy_panel._TASK_QUEUE = self._original_queue
        easy_panel._TASK_RUNNER = self._original_runner
        self._folder.cleanup()

    def test_task_queue_runner_starts_without_deadlock(self):
        finished = threading.Event()
        captured: dict = {}

        def start():
            captured["runner"] = easy_panel.start_task_queue_runner()
            finished.set()

        thread = threading.Thread(target=start, daemon=True)
        thread.start()
        self.assertTrue(
            finished.wait(5),
            "start_task_queue_runner() 卡住了：启动函数和 task_queue() 不能共用非重入锁。",
        )
        self.assertTrue(captured["runner"].alive)

    def test_starting_twice_reuses_the_same_runner(self):
        first = easy_panel.start_task_queue_runner()
        second = easy_panel.start_task_queue_runner()
        self.assertIs(first, second)

    def test_runner_without_tasks_stays_idle(self):
        runner = easy_panel.start_task_queue_runner()
        self.assertEqual("idle", runner.tick())
        self.assertEqual(0, easy_panel.task_queue_snapshot()["counts"]["total"])


if __name__ == "__main__":
    unittest.main()
