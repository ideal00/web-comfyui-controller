import unittest
from pathlib import Path
from unittest.mock import patch

import easy_panel


ROOT = Path(__file__).resolve().parents[1]


class ClarityAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "web/assets/js/clarity-analysis.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "web/assets/css/panel.css").read_text(encoding="utf-8")

    def test_clarity_panel_is_automatic_and_can_be_retested(self):
        for marker in (
            "/assets/js/clarity-analysis.js?v=2",
            'id = "clarityAnalysisPanel"',
            "自动清晰度检测",
            "重新检测",
            "new MutationObserver",
            "scheduleClarityAnalysis",
        ):
            self.assertIn(marker, self.html + self.script)

    def test_analysis_uses_whole_and_upper_regions(self):
        for marker in (
            "function regionMetrics",
            "const whole = regionMetrics",
            "const upper = regionMetrics",
            "整图锐度",
            "人物上部",
            "edgeRatio",
        ):
            self.assertIn(marker, self.script)

    def test_recommendations_do_not_apply_enhancement_automatically(self):
        for marker in ("建议 Anime6B", "建议优先高清二采", "SeedVR2 1.25×", "通常无需整图增强"):
            self.assertIn(marker, self.script)
        self.assertNotIn("outputEnhancementMode').value", self.script)

    def test_user_can_select_one_image_and_generate_a_clarity_copy(self):
        for marker in (
            "clarityUpscalePanel", "clarityUpscaleTarget", "生成同图清晰版",
            "generateSelectedClarityVersion", "/api/clarity-upscale",
            "generatedViewerImages", "清晰版 · 来源", "原图仍保留",
        ):
            self.assertIn(marker, self.script)

    def test_clarity_workflow_is_postprocess_only(self):
        with patch.object(easy_panel, "prepare_generation_image", return_value="easy_panel/source.png"):
            workflow = easy_panel.build_clarity_upscale_workflow({"name": "source.png", "scale": 1.5})
        nodes = workflow["prompt"]
        classes = [node["class_type"] for node in nodes.values()]
        self.assertEqual(classes, [
            "LoadImage", "UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScaleBy", "SaveImage",
        ])
        self.assertNotIn("KSampler", classes)
        self.assertEqual(nodes["4"]["inputs"]["scale_by"], 0.375)
        self.assertEqual(nodes["5"]["inputs"]["filename_prefix"], "EasyPanel_Clarity")

    def test_runtime_and_installer_payload_match(self):
        self.assertEqual(
            (ROOT / "web/assets/js/clarity-analysis.js").read_bytes(),
            (ROOT / "installers/payload/web/assets/js/clarity-analysis.js").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
