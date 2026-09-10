from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GenerationGuardTests(unittest.TestCase):
    """生成前检查（含显存风险）与批量单变量实验。"""

    def test_both_pages_load_the_new_scripts_after_the_workbench(self):
        for page in (ROOT / "index.html", ROOT / "installers/payload/index.html"):
            with self.subTest(page=page.as_posix()):
                html = page.read_text(encoding="utf-8")
                self.assertIn("/assets/js/preflight-check.js?v=", html)
                self.assertIn("/assets/js/batch-experiment.js?v=", html)
                self.assertLess(html.index("result-workbench.js?v="),
                                html.index("preflight-check.js?v="))
                self.assertLess(html.index("preflight-check.js?v="),
                                html.index("batch-experiment.js?v="))
                self.assertIn('onclick="openBatchExperiment()"', html)

    def test_preflight_reuses_existing_endpoints_and_reports_relative_vram(self):
        script = (ROOT / "web/assets/js/preflight-check.js").read_text(encoding="utf-8")
        for marker in ("/api/prompt-compile", "/api/anima-preflight", "/api/krea2-preflight",
                       "/api/illustrious-preflight", "显存风险", "相对等级",
                       "8GB", "VRAM_BUDGET_MB", "基础生成", "当前二采峰值", "1.5× 尺寸参考",
                       "继续生成", "返回修改", "本次会话不再提示"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)
        self.assertIn("__preflightCheck", script)
        self.assertIn("__preflightWrapped", script)
        self.assertIn("global.generate", script)

    def test_preflight_never_blocks_when_the_check_itself_fails(self):
        script = (ROOT / "web/assets/js/preflight-check.js").read_text(encoding="utf-8")
        self.assertIn("检查本身失败绝不阻塞生成", script)
        # The guard must resolve to "proceed" when it cannot build a report.
        self.assertIn("return { proceed: true, report: null };", script)

    def test_experiment_sweeps_one_variable_and_labels_each_job(self):
        script = (ROOT / "web/assets/js/batch-experiment.js").read_text(encoding="utf-8")
        for marker in ("openBatchExperiment", "单变量实验", "enqueueJob", "experiment",
                       "single-variable", "hiresDenoise", "hiresScale",
                       "MAX_VALUES", "只加入队列", "加入并开始", "__batchExperiment"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)
        # 即使某个取值加入队列失败，也必须把原值写回输入框。
        self.assertIn("writeVariable(variable, original)", script)

    def test_runtime_and_installer_payload_stay_identical(self):
        for relative in ("web/assets/js/preflight-check.js", "web/assets/js/batch-experiment.js"):
            with self.subTest(relative=relative):
                self.assertEqual(
                    (ROOT / relative).read_bytes(),
                    (ROOT / "installers" / "payload" / relative).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
