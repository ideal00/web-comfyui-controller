import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import easy_panel


class ClarityAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "web/assets/js/clarity-analysis.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "web/assets/css/panel.css").read_text(encoding="utf-8")

    def test_clarity_panel_is_automatic_and_can_be_retested(self):
        for marker in (
            "/assets/js/clarity-analysis.js?v=5",
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

    def test_clarity_panel_offers_history_images_and_model_choice(self):
        """抽屉里可以直接选之前生成的图，并且增强方式/模型/倍率都能选。"""

        for marker in (
            "clarityDrawerPanel", "studioToolDrawerContent", "clarityDrawerTarget",
            "clarityDrawerEngine", "clarityDrawerScale", "clarityUpscaleModel",
            "/api/upscale-models", "历史输出", "optgroup", "clarityUpscalePreview",
            "loadClarityCatalog", "generateDrawerClarityVersion",
        ):
            self.assertIn(marker, self.script)

    def test_main_panel_stays_simple(self):
        """主界面保持原样：只处理本次生成的图，不带模型/倍率控件。"""

        self.assertIn("— 当前没有生成图片 —", self.script)
        self.assertNotIn("clarityUpscaleTarget\", \"clarityUpscalePreview", self.script)
        self.assertNotIn('id="clarityUpscaleModel" aria-label="选择放大模型"', self.script)

    def test_clarity_seedvr2_engine_builds_seedvr2_graph(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "easy_panel"
            source.mkdir(parents=True)
            Image.new("RGB", (512, 768), (10, 20, 30)).save(source / "source.png")
            with patch.object(easy_panel, "COMFY_INPUT", Path(folder)), \
                 patch.object(easy_panel, "prepare_generation_image",
                              return_value="easy_panel/source.png"):
                workflow = easy_panel.build_clarity_upscale_workflow(
                    {"name": "source.png", "scale": 1.25, "engine": "seedvr2"})
        nodes = workflow["prompt"]
        classes = [node["class_type"] for node in nodes.values()]
        self.assertIn("SeedVR2Preprocess", classes)
        self.assertIn("SeedVR2PostProcessing", classes)
        self.assertNotIn("UpscaleModelLoader", classes)
        self.assertEqual(nodes["2"]["inputs"]["width"], 640)
        self.assertEqual(nodes["2"]["inputs"]["height"], 960)
        self.assertEqual(nodes["10"]["inputs"]["color_correction_method"], "lab")

    def test_clarity_scale_can_go_up_to_4x(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "easy_panel"
            source.mkdir(parents=True)
            Image.new("RGB", (512, 768), (10, 20, 30)).save(source / "source.png")
            with patch.object(easy_panel, "COMFY_INPUT", Path(folder)), \
                 patch.object(easy_panel, "prepare_generation_image",
                              return_value="easy_panel/source.png"):
                workflow = easy_panel.build_clarity_upscale_workflow({"name": "source.png", "scale": 9})
        resize = workflow["prompt"]["4"]["inputs"]
        self.assertEqual((2048, 3072), (resize["width"], resize["height"]))

    def test_upscale_catalog_reports_seedvr2_readiness(self):
        info = {"UpscaleModelLoader": {"input": {"required": {"model_name": [["m.pth"]]}}},
                "SeedVR2Preprocess": {}, "SeedVR2Conditioning": {}, "SeedVR2PostProcessing": {}}
        with patch.object(easy_panel, "comfy_json", return_value=info):
            catalog = easy_panel.upscale_model_catalog()
        self.assertTrue(catalog["seedvr2"]["ready"])
        self.assertEqual(catalog["seedvr2"]["model"], easy_panel.SEEDVR2_MODEL)

    def test_unknown_engine_falls_back_to_upscale(self):
        self.assertEqual(easy_panel.clarity_upscale_engine({"engine": "nope"}), "upscale")
        self.assertEqual(easy_panel.clarity_upscale_engine({}), "upscale")
        self.assertEqual(easy_panel.clarity_upscale_engine({"engine": "SEEDVR2"}), "seedvr2")

    def test_clarity_uses_the_selected_upscale_model(self):
        with patch.object(easy_panel, "prepare_generation_image", return_value="easy_panel/source.png"):
            workflow = easy_panel.build_clarity_upscale_workflow(
                {"name": "source.png", "scale": 1.5, "model": "4x-UltraSharp.pth"})
        self.assertEqual(workflow["prompt"]["2"]["inputs"]["model_name"], "4x-UltraSharp.pth")

    def test_clarity_defaults_to_the_bundled_anime_model(self):
        with patch.object(easy_panel, "prepare_generation_image", return_value="easy_panel/source.png"):
            workflow = easy_panel.build_clarity_upscale_workflow({"name": "source.png"})
        self.assertEqual(workflow["prompt"]["2"]["inputs"]["model_name"],
                         easy_panel.HIRES_UPSCALE_MODEL)

    def test_clarity_resizes_to_source_times_scale_for_any_model(self):
        """换任何放大模型都要得到同样的成品尺寸：原图 × 倍率，而不是靠模型原生倍率。"""

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "easy_panel"
            source.mkdir(parents=True)
            Image.new("RGB", (512, 768), (10, 20, 30)).save(source / "source.png")
            with patch.object(easy_panel, "COMFY_INPUT", Path(folder)), \
                 patch.object(easy_panel, "prepare_generation_image",
                              return_value="easy_panel/source.png"):
                workflow = easy_panel.build_clarity_upscale_workflow(
                    {"name": "source.png", "scale": 1.5, "model": "2x-model.pth"})
        resize = workflow["prompt"]["4"]
        self.assertEqual(resize["class_type"], "ImageScale")
        self.assertEqual(resize["inputs"]["width"], 768)
        self.assertEqual(resize["inputs"]["height"], 1152)
        self.assertEqual(resize["inputs"]["crop"], "disabled")

    def test_upscale_model_catalog_prefers_anime6b(self):
        info = {"UpscaleModelLoader": {"input": {"required": {"model_name": [
            ["RealESRGAN_x4plus_anime_6B.pth", "4x-UltraSharp.pth"]]}}}}
        with patch.object(easy_panel, "comfy_json", return_value=info):
            catalog = easy_panel.upscale_model_catalog()
        self.assertEqual(catalog["models"],
                         ["RealESRGAN_x4plus_anime_6B.pth", "4x-UltraSharp.pth"])
        self.assertEqual(catalog["default"], easy_panel.HIRES_UPSCALE_MODEL)

    def test_upscale_model_catalog_falls_back_to_first_available(self):
        info = {"UpscaleModelLoader": {"input": {"required": {"model_name": [
            ["4x-UltraSharp.pth"]]}}}}
        with patch.object(easy_panel, "comfy_json", return_value=info):
            catalog = easy_panel.upscale_model_catalog()
        self.assertEqual(catalog["default"], "4x-UltraSharp.pth")

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
        self.assertEqual(nodes["save"]["inputs"]["filename_prefix"], "EasyPanel_Clarity")

    def test_runtime_and_installer_payload_match(self):
        self.assertEqual(
            (ROOT / "web/assets/js/clarity-analysis.js").read_bytes(),
            (ROOT / "installers/payload/web/assets/js/clarity-analysis.js").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
