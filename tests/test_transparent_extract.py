"""上传图片 → 算法提取透明 PNG（RmBgUltra）的单元测试。"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


PANEL_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("easy_panel_transparent_extract_test", PANEL_ROOT / "easy_panel.py")
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


class TransparentExtractWorkflowTest(unittest.TestCase):
    def test_auto_mode_uses_rmbg_without_detail_pass(self):
        workflow = easy_panel.build_transparent_extract_workflow(
            "easy_panel/reference_abc.png", {"mode": "auto"})
        nodes = workflow["prompt"]
        self.assertEqual(nodes["1"]["class_type"], "LoadImage")
        self.assertEqual(nodes["1"]["inputs"]["image"], "easy_panel/reference_abc.png")
        rmbg = nodes["2"]
        self.assertEqual(rmbg["class_type"], "LayerMask: RmBgUltra V2")
        self.assertEqual(rmbg["inputs"]["image"], ["1", 0])
        self.assertIs(rmbg["inputs"]["process_detail"], False)
        self.assertEqual(rmbg["inputs"]["detail_method"], "GuidedFilter")
        self.assertEqual(rmbg["inputs"]["detail_erode"], 6)
        self.assertEqual(rmbg["inputs"]["detail_dilate"], 6)
        self.assertEqual(rmbg["inputs"]["black_point"], 0.01)
        self.assertEqual(rmbg["inputs"]["white_point"], 0.99)
        self.assertEqual(rmbg["inputs"]["max_megapixels"], 4.0)
        self.assertEqual(rmbg["inputs"]["device"], "cuda")
        save = nodes["3"]
        self.assertEqual(save["class_type"], "SaveImage")
        self.assertEqual(save["inputs"]["images"], ["2", 0])
        self.assertTrue(save["inputs"]["filename_prefix"].startswith("EasyPanel_Transparent_"))

    def test_complex_mode_clamps_parameters(self):
        workflow = easy_panel.build_transparent_extract_workflow("upload.png", {
            "mode": "complex",
            "detailMethod": "VITMatte",
            "detailErode": 0,
            "detailDilate": 900,
            "blackPoint": 5,
            "whitePoint": -2,
            "maxMegapixels": 99,
        })
        rmbg = workflow["prompt"]["2"]["inputs"]
        self.assertIs(rmbg["process_detail"], True)
        self.assertEqual(rmbg["detail_method"], "VITMatte")
        self.assertEqual(rmbg["detail_erode"], 1)
        self.assertEqual(rmbg["detail_dilate"], 255)
        self.assertEqual(rmbg["black_point"], 0.98)
        self.assertEqual(rmbg["white_point"], 0.02)
        self.assertEqual(rmbg["max_megapixels"], 64.0)

    def test_unknown_method_and_mode_are_rejected(self):
        workflow = easy_panel.build_transparent_extract_workflow("upload.png", {
            "detailMethod": "bogus", "mode": "complex"})
        self.assertEqual(workflow["prompt"]["2"]["inputs"]["detail_method"], "PyMatting")
        with self.assertRaises(ValueError):
            easy_panel.build_transparent_extract_workflow("upload.png", {"mode": "hack"})
        with self.assertRaises(ValueError):
            easy_panel.build_transparent_extract_workflow("", {})

    def test_tight_preset_uses_tighter_edges(self):
        workflow = easy_panel.build_transparent_extract_workflow("upload.png", {"preset": "tight"})
        rmbg = workflow["prompt"]["2"]["inputs"]
        self.assertIs(rmbg["process_detail"], True)
        self.assertEqual(rmbg["detail_erode"], 18)
        self.assertEqual(rmbg["black_point"], 0.20)
        self.assertEqual(workflow["prompt"]["3"]["inputs"]["images"], ["2", 0])
        classes = [node["class_type"] for node in workflow["prompt"].values()]
        self.assertNotIn("MaskEdgeUltraDetail V2", " ".join(classes))
        self.assertNotIn("JoinImageWithAlpha", classes)

    def test_detail_defaults_are_tightened(self):
        workflow = easy_panel.build_transparent_extract_workflow("upload.png", {"preset": "detail"})
        rmbg = workflow["prompt"]["2"]["inputs"]
        self.assertEqual(rmbg["detail_erode"], 12)
        self.assertEqual(rmbg["black_point"], 0.10)

    def test_legacy_hair_preset_maps_to_detail(self):
        workflow = easy_panel.build_transparent_extract_workflow("upload.png", {"preset": "hair"})
        rmbg = workflow["prompt"]["2"]["inputs"]
        self.assertIs(rmbg["process_detail"], True)
        self.assertEqual(rmbg["detail_erode"], 12)
        self.assertEqual(len(workflow["prompt"]), 3)

    def test_preset_takes_priority_over_legacy_mode(self):
        workflow = easy_panel.build_transparent_extract_workflow("upload.png", {
            "preset": "fast", "mode": "complex", "detailMethod": "PyMatting"})
        self.assertIs(workflow["prompt"]["2"]["inputs"]["process_detail"], False)
        self.assertEqual(workflow["prompt"]["2"]["inputs"]["detail_method"], "GuidedFilter")
        self.assertEqual(len(workflow["prompt"]), 3)

    def test_megapixels_allows_original_resolution(self):
        workflow = easy_panel.build_transparent_extract_workflow("upload.png", {"maxMegapixels": 32})
        self.assertEqual(workflow["prompt"]["2"]["inputs"]["max_megapixels"], 32.0)
        default = easy_panel.build_transparent_extract_workflow("upload.png", {})
        self.assertEqual(default["prompt"]["2"]["inputs"]["max_megapixels"], 4.0)


class ResolveTransparentSourceTest(unittest.TestCase):
    def test_output_prefix_copies_into_input(self):
        with patch.object(easy_panel, "copy_output_to_input", return_value="easy_panel/reference_1.png") as copy:
            resolved = easy_panel.resolve_transparent_source("output:EasyPanel_00001_.png")
        self.assertEqual(resolved, "easy_panel/reference_1.png")
        copy.assert_called_once_with("EasyPanel_00001_.png")

    def test_plain_input_name_passes_through(self):
        with patch.object(easy_panel, "copy_output_to_input") as copy:
            resolved = easy_panel.resolve_transparent_source("easy_panel/reference_abc.png")
        self.assertEqual(resolved, "easy_panel/reference_abc.png")
        copy.assert_not_called()

    def test_empty_source_is_rejected(self):
        with self.assertRaises(ValueError):
            easy_panel.resolve_transparent_source("   ")


class RunTransparentExtractTest(unittest.TestCase):
    def test_success_returns_transparent_output(self):
        calls = []

        def fake_comfy(path, method="GET", payload=None):
            calls.append((path, method))
            if path == "/prompt":
                return {"prompt_id": "abc123"}
            return {"abc123": {"status": {"status_str": "success"}, "outputs": {"3": {"images": [
                {"filename": "EasyPanel_Transparent_20260901-120000-ab12_00001_.png",
                 "subfolder": "", "type": "output"}]}}}}

        with patch.object(easy_panel, "comfy_json", side_effect=fake_comfy), \
                patch.object(easy_panel, "resolve_transparent_source",
                             return_value="easy_panel/reference_abc.png"):
            result = easy_panel.run_transparent_extract({"image": "x", "mode": "auto"})
        self.assertEqual(calls[0], ("/prompt", "POST"))
        self.assertEqual(result["filename"], "EasyPanel_Transparent_20260901-120000-ab12_00001_.png")
        self.assertEqual(result["url"], "/output?name=EasyPanel_Transparent_20260901-120000-ab12_00001_.png")
        self.assertEqual(result["preset"], "fast")
        # 测试环境里没有真实输出文件，清理会安全降级。
        self.assertEqual(result["gap_cleanup"]["removed"], 0)

    def test_clean_gaps_can_be_disabled(self):
        def fake_comfy(path, method="GET", payload=None):
            if path == "/prompt":
                return {"prompt_id": "abc123"}
            return {"abc123": {"status": {"status_str": "success"}, "outputs": {"3": {"images": [
                {"filename": "EasyPanel_Transparent_x_00001_.png", "subfolder": ""}]}}}}

        with patch.object(easy_panel, "comfy_json", side_effect=fake_comfy), \
                patch.object(easy_panel, "clean_transparent_residue") as cleanup, \
                patch.object(easy_panel, "resolve_transparent_source",
                             return_value="easy_panel/reference_abc.png"):
            result = easy_panel.run_transparent_extract({"image": "x", "cleanGaps": False})
        cleanup.assert_not_called()
        self.assertNotIn("gap_cleanup", result)

    def test_clean_gaps_swaps_in_cleaned_file(self):
        def fake_comfy(path, method="GET", payload=None):
            if path == "/prompt":
                return {"prompt_id": "abc123"}
            return {"abc123": {"status": {"status_str": "success"}, "outputs": {"3": {"images": [
                {"filename": "EasyPanel_Transparent_x_00001_.png", "subfolder": ""}]}}}}

        cleaned = {"name": "EasyPanel_Transparent_x_00001__clean.png", "removed": 512}
        with patch.object(easy_panel, "comfy_json", side_effect=fake_comfy), \
                patch.object(easy_panel, "clean_transparent_residue", return_value=cleaned), \
                patch.object(easy_panel, "resolve_transparent_source",
                             return_value="easy_panel/reference_abc.png"):
            result = easy_panel.run_transparent_extract({"image": "x"})
        self.assertEqual(result["filename"], cleaned["name"])
        self.assertIn("EasyPanel_Transparent_x_00001__clean.png", result["url"])
        self.assertEqual(result["gap_cleanup"]["removed"], 512)

    def test_error_state_surfaces_chinese_message(self):
        def fake_comfy(path, method="GET", payload=None):
            if path == "/prompt":
                return {"prompt_id": "abc123"}
            return {"abc123": {"status": {"status_str": "error", "messages": [
                ["execution_error", {"exception_message": "CUDA out of memory"}]]}}}

        with patch.object(easy_panel, "comfy_json", side_effect=fake_comfy), \
                patch.object(easy_panel, "resolve_transparent_source",
                             return_value="easy_panel/reference_abc.png"):
            with self.assertRaises(ValueError) as error:
                easy_panel.run_transparent_extract({"image": "x"})
        self.assertIn("抠图失败", str(error.exception))
        self.assertIn("CUDA out of memory", str(error.exception))

    def test_missing_prompt_id_is_rejected(self):
        with patch.object(easy_panel, "comfy_json", return_value={}), \
                patch.object(easy_panel, "resolve_transparent_source",
                             return_value="easy_panel/reference_abc.png"):
            with self.assertRaises(ValueError) as error:
                easy_panel.run_transparent_extract({"image": "x"})
        self.assertIn("任务编号", str(error.exception))

    def test_timeout_reports_clearly(self):
        with patch.object(easy_panel, "comfy_json", side_effect=[{"prompt_id": "abc123"}, {}]), \
                patch.object(easy_panel, "time", wraps=easy_panel.time) as fake_time, \
                patch.object(easy_panel, "resolve_transparent_source",
                             return_value="easy_panel/reference_abc.png"):
            fake_time.time.side_effect = [0.0, 0.0, 10_000.0]
            fake_time.sleep.return_value = None
            with self.assertRaises(ValueError) as error:
                easy_panel.run_transparent_extract({"image": "x"})
        self.assertIn("超时", str(error.exception))


class CleanResidueTest(unittest.TestCase):
    def test_background_gap_between_hair_is_removed(self):
        import importlib
        import tempfile

        media_storage = importlib.import_module("easy_panel_app.media_storage")
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pixels = np.zeros((80, 80, 4), dtype=np.uint8)
            pixels[..., :3] = (240, 238, 236)      # 背景色
            pixels[..., 3] = 0                     # 默认全透明
            pixels[20:60, 20:60, :3] = (60, 45, 40)  # 深色发丝块
            pixels[20:60, 20:60, 3] = 255
            pixels[38:44, 38:44, :3] = (240, 238, 236)  # 发丝之间的缝隙仍是背景色
            Image.fromarray(pixels, "RGBA").save(root / "cut.png")

            with patch.object(media_storage, "OUTPUT", root):
                result = media_storage.clean_transparent_residue("cut.png")
                cleaned = Image.open(root / result["name"]).convert("RGBA")

        self.assertGreaterEqual(result["removed"], 30)
        alpha = np.asarray(cleaned.getchannel("A"))
        self.assertTrue(np.all(alpha[38:44, 38:44] == 0))          # 缝隙被清掉
        self.assertTrue(np.all(alpha[22:26, 22:26] == 255))        # 发丝本体保留
        self.assertEqual(list(cleaned.getpixel((40, 40)))[3], 0)

    def test_connected_light_area_is_not_cleared(self):
        """白色礼服颜色也接近背景，但它与图像外部连通，不能被当成缝隙清掉。"""
        import importlib
        import tempfile

        media_storage = importlib.import_module("easy_panel_app.media_storage")
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pixels = np.zeros((96, 96, 4), dtype=np.uint8)
            pixels[..., :3] = (240, 238, 236)
            pixels[20:70, 16:56, :3] = (60, 45, 40)      # 深色发丝块
            pixels[20:70, 16:56, 3] = 255
            pixels[38:44, 38:44, :3] = (240, 238, 236)   # 发丝之间封闭的缝隙
            pixels[20:70, 56:96, :3] = (240, 238, 236)   # 贴着右边界的“衣服”
            pixels[20:70, 56:96, 3] = 255
            Image.fromarray(pixels, "RGBA").save(root / "cut.png")

            with patch.object(media_storage, "OUTPUT", root):
                result = media_storage.clean_transparent_residue("cut.png")
                cleaned = np.asarray(Image.open(root / result["name"]).convert("RGBA"))

        self.assertTrue(np.all(cleaned[38:44, 38:44, 3] == 0))     # 封闭缝隙被清掉
        self.assertTrue(np.all(cleaned[30:60, 70:90, 3] == 255))   # 与外部连通的衣服保留
        self.assertTrue(np.all(cleaned[30:60, 25:35, 3] == 255))   # 发丝本体保留

    def test_missing_file_is_rejected(self):
        import importlib

        media_storage = importlib.import_module("easy_panel_app.media_storage")
        with self.assertRaises(ValueError):
            media_storage.clean_transparent_residue("../secret.png")


class TransparentExtractWiringTest(unittest.TestCase):
    def test_endpoints_are_registered(self):
        source = (PANEL_ROOT / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn('"/api/upload-transparent-source"', source)
        self.assertIn('"/api/transparent-extract"', source)
        self.assertIn("run_transparent_extract(data)", source)
        self.assertIn("save_reference_upload(", source)

    def test_frontend_dialog_is_wired(self):
        html = (PANEL_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("transparent-extract.js", html)
        self.assertIn('id="transparentExtractOpen"', html)
        script = (PANEL_ROOT / "web" / "assets" / "js" / "transparent-extract.js").read_text(encoding="utf-8")
        self.assertIn("/api/upload-transparent-source", script)
        self.assertIn("/api/transparent-extract", script)
        self.assertIn("openTransparentMaskEditor", script)


if __name__ == "__main__":
    unittest.main()
