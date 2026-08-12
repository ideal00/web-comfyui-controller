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

    def test_large_seeds_and_hires_metadata_are_restored_without_precision_loss(self):
        javascript = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")

        self.assertIn("BigInt(seed)+BigInt(index)", javascript)
        self.assertNotIn("Number.isSafeInteger(Number(seed))", javascript)
        self.assertIn("String(data.seed)", javascript)
        self.assertIn("data.hires?.enabled&&supportsHiresClient()", javascript)
        self.assertIn("data.hires.sampler&&$('hiresSampler')", javascript)
        self.assertIn('self.path == "/api/read-output"', backend)
        self.assertIn("self.send_json(parse_generation_info(file.read_bytes()))\n                return", backend)

    def test_output_enhancement_ui_is_capability_gated_and_payload_backed(self):
        advanced = (ROOT / "web" / "assets" / "js" / "model-advanced.js").read_text(
            encoding="utf-8")
        panel = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")

        for token in ("anime6b", "seedvr2", "ultimate", "faceDetailerEnabled",
                      "handDetailerEnabled", "footDetailerEnabled",
                      "limbDetailer", "autoColorMatchEnabled", "workflowFeatures"):
            self.assertIn(token, advanced)
        self.assertIn("data.outputEnhancement", advanced)
        self.assertIn("data.hand_detailer", panel)
        self.assertIn("data.foot_detailer", panel)
        self.assertIn("hiresSampler", panel)
        self.assertIn("hiresScheduler", panel)

    def test_all_final_and_limb_prompts_are_editable_and_payload_backed(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(
            encoding="utf-8")
        advanced = (ROOT / "web" / "assets" / "js" / "model-advanced.js").read_text(
            encoding="utf-8")
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")

        self.assertIn('<textarea id="compiledPositive"', html)
        self.assertIn('<textarea id="compiledNegative"', html)
        self.assertIn('oninput="finalPromptChanged()"', html)
        self.assertIn('onclick="rebuildFinalPrompt()"', html)
        self.assertIn('onclick="clearFinalPrompt()"', html)
        self.assertIn("promptOverride:finalPromptOverride()", javascript)
        self.assertIn("data.promptOverride=finalPromptOverride()", javascript)
        self.assertIn("手动原样提交", javascript)
        self.assertIn("最终正负向已按图片原文恢复", javascript)
        self.assertIn('id="handDetailerPositive"', advanced)
        self.assertIn('id="handDetailerNegative"', advanced)
        self.assertIn('id="footDetailerPositive"', advanced)
        self.assertIn('id="footDetailerNegative"', advanced)
        self.assertIn('handPositive: byId("handDetailerPositive")', advanced)
        self.assertIn('override.get("positive", "")', backend)
        self.assertIn('"overridden": overridden', backend)

    def test_advanced_functions_have_matching_help_and_recommended_defaults(self):
        advanced = (ROOT / "web" / "assets" / "js" / "model-advanced.js").read_text(
            encoding="utf-8")

        self.assertIn('class="small" title=', advanced)
        for phrase in ("默认推荐", "推荐 1.5×", "推荐 1.25×", "推荐 512",
                       "推荐 0.70", "推荐 12"):
            self.assertIn(phrase, advanced)
        self.assertIn('anime6b: { scale: 1.5', advanced)
        self.assertIn('seedvr2: { scale: 1.25', advanced)
        self.assertIn('ultimate: { scale: 1.5', advanced)
        self.assertIn('value="1.5"', advanced)
        self.assertIn('id="handDetailerEnabled" type="checkbox" onchange=', advanced)
        self.assertIn('id="footDetailerEnabled" type="checkbox" onchange=', advanced)
        self.assertNotIn('id="handDetailerEnabled" type="checkbox" checked', advanced)
        self.assertNotIn('id="footDetailerEnabled" type="checkbox" checked', advanced)
        self.assertIn('id="limbDetailerDenoise"', advanced)
        self.assertIn('id="limbDetailerDenoise" type="number" min="0.15" max="0.6" step="0.05" value="0.35"', advanced)
        self.assertIn("features.hand_detailer === false", advanced)
        self.assertIn("features.foot_detailer === false", advanced)

    def test_lora_rows_support_buttons_and_drag_reordering(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(
            encoding="utf-8")
        css = (ROOT / "web" / "assets" / "css" / "panel.css").read_text(
            encoding="utf-8")

        self.assertIn("可拖动“↕序号”", html)
        self.assertIn("function moveLoraRow(row,direction)", javascript)
        self.assertIn("handle.draggable=true", javascript)
        self.assertIn("handle.ondragstart", javascript)
        self.assertIn("row.ondragover", javascript)
        self.assertIn("commitLoraOrder", javascript)
        self.assertIn("saveLoraState();renderRegions();promptEditorChanged()", javascript)
        self.assertIn("querySelectorAll('.lora-row')", javascript)
        self.assertIn(".lora-drag-handle", css)
        self.assertIn(".lora-row.dragging", css)


if __name__ == "__main__":
    unittest.main()
