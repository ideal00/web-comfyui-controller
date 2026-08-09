from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GenerationProgressUiTests(unittest.TestCase):
    def test_progress_bar_is_present_and_connected_to_comfy_progress_stream(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")

        self.assertIn('id="generationProgressBar"', html)
        self.assertIn("new EventSource(url)", javascript)
        self.assertIn("dataset.connection='connected'", javascript)
        self.assertIn("type==='progress'", javascript)
        self.assertIn("markGenerationPromptComplete(id)", javascript)
        self.assertIn('parsed.path == "/api/progress-stream"', backend)
        self.assertIn('"progress_stream": "/api/progress-stream"', backend)
        self.assertIn('client_id = "easy-panel"', backend)

    def test_installers_ship_the_two_page_runtime_launcher(self):
        builder = (ROOT / "installers" / "Build-Packages.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "installers" / "Install-EasyPanelModule.ps1").read_text(encoding="utf-8")
        launcher = (ROOT / "launchers" / "Start_ComfyUI_and_EasyPanel.bat").read_text(encoding="utf-8")

        self.assertIn('Copy-CleanDirectory (Join-Path $repositoryRoot "launchers")', builder)
        self.assertIn('Start_ComfyUI_and_EasyPanel.bat', installer)
        self.assertIn('http://127.0.0.1:8190', launcher)
        self.assertIn('http://127.0.0.1:8188', launcher)

    def test_single_and_batch_generation_both_start_progress_tracking(self):
        javascript = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")

        self.assertIn("beginGenerationProgress(count)", javascript)
        self.assertIn("beginGenerationProgress(expected,'队列生成进度')", javascript)
        self.assertGreaterEqual(javascript.count("registerGenerationPrompt("), 3)


if __name__ == "__main__":
    unittest.main()
