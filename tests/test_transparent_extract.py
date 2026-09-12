"""上传图片 → 算法提取透明 PNG（RmBgUltra）的单元测试。"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


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
        self.assertEqual(rmbg["inputs"]["max_megapixels"], 2.0)
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
        self.assertEqual(rmbg["max_megapixels"], 16.0)

    def test_unknown_method_and_mode_are_rejected(self):
        workflow = easy_panel.build_transparent_extract_workflow("upload.png", {
            "detailMethod": "bogus", "mode": "complex"})
        self.assertEqual(workflow["prompt"]["2"]["inputs"]["detail_method"], "GuidedFilter")
        with self.assertRaises(ValueError):
            easy_panel.build_transparent_extract_workflow("upload.png", {"mode": "hack"})
        with self.assertRaises(ValueError):
            easy_panel.build_transparent_extract_workflow("", {})


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
        self.assertEqual(result["mode"], "auto")

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
