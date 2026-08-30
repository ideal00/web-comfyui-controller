from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("easy_panel_transparent_test", ROOT / "easy_panel.py")
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


def base_payload() -> dict:
    return {
        "model": "waiIllustriousSDXL_v140.safetensors",
        "promptSections": {"subject": "1girl", "scene": "simple background"},
        "negative": "",
        "width": 768,
        "height": 1024,
        "steps": 20,
        "cfg": 5,
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "guidance": {"mode": "off"},
    }


class TransparentBackgroundWorkflowTests(unittest.TestCase):
    def build(self, settings: dict) -> dict:
        data = base_payload()
        data["transparentBackground"] = settings
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            return easy_panel.build_workflow(data)["prompt"]

    @staticmethod
    def by_type(nodes: dict, class_type: str) -> list[dict]:
        return [node for node in nodes.values() if node["class_type"] == class_type]

    def test_normal_character_uses_fast_auto_alpha_and_keeps_source(self):
        nodes = self.build({"mode": "auto", "keepOriginal": True})
        rmbg = self.by_type(nodes, "LayerMask: RmBgUltra V2")
        self.assertEqual(1, len(rmbg))
        self.assertFalse(rmbg[0]["inputs"]["process_detail"])
        prefixes = [node["inputs"]["filename_prefix"]
                    for node in self.by_type(nodes, "SaveImage")]
        self.assertIn("EasyPanel", prefixes)
        self.assertIn("EasyPanel_Transparent", prefixes)

    def test_complex_character_exposes_bounded_edge_parameters(self):
        nodes = self.build({
            "mode": "complex",
            "keepOriginal": False,
            "detailMethod": "PyMatting",
            "detailErode": 7,
            "detailDilate": 9,
            "blackPoint": 0.05,
            "whitePoint": 0.94,
            "maxMegapixels": 3,
        })
        inputs = self.by_type(nodes, "LayerMask: RmBgUltra V2")[0]["inputs"]
        self.assertTrue(inputs["process_detail"])
        self.assertEqual("PyMatting", inputs["detail_method"])
        self.assertEqual((7, 9, 0.05, 0.94, 3.0), (
            inputs["detail_erode"], inputs["detail_dilate"], inputs["black_point"],
            inputs["white_point"], inputs["max_megapixels"],
        ))
        saves = self.by_type(nodes, "SaveImage")
        self.assertEqual(["EasyPanel_Transparent"],
                         [node["inputs"]["filename_prefix"] for node in saves])

    def test_unknown_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知的透明背景模式"):
            self.build({"mode": "javascript"})


class TransparentBackgroundUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.advanced = (ROOT / "web/assets/js/model-advanced.js").read_text(encoding="utf-8")
        cls.editor = (ROOT / "web/assets/js/transparent-background.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "web/assets/css/panel.css").read_text(encoding="utf-8")

    def test_beginner_auto_complex_and_manual_paths_are_visible(self):
        for marker in (
            "普通角色 · 自动抠图",
            "复杂角色 · 精细边缘",
            'id="transparentComplexControls"',
            "手动修正最近的透明图",
            'id="transparentOutputPanel"',
            'byId("studioSettingsView")',
            'insertAdjacentElement("afterend", transparentPanel)',
            'id="transparentMaskEditor"',
            "＋ 补留角色",
            "－ 擦除背景",
            "导出修正后的透明 PNG",
            "/assets/js/transparent-background.js?v=1",
        ):
            self.assertIn(marker, self.html + self.advanced)

    def test_payload_capability_and_editor_wiring_exist(self):
        for marker in (
            "data.transparentBackground",
            "transparent_background",
            "window.transparentBackgroundChanged",
            "function captureTransparentResults",
            "function paintTransparentAlpha",
            "function undoTransparentMask",
            "function resetTransparentMask",
            "function exportTransparentMaskPng",
        ):
            self.assertIn(marker, self.advanced + self.editor)
        self.assertIn(".transparent-mask-editor", self.css)
        self.assertIn(".transparent-result", self.css)
        self.assertIn(".transparent-output-panel", self.css)

    def test_installer_payload_matches_runtime_files(self):
        for source in (
            "easy_panel.py",
            "index.html",
            "web/assets/css/panel.css",
            "web/assets/js/model-advanced.js",
            "web/assets/js/transparent-background.js",
        ):
            self.assertEqual((ROOT / source).read_bytes(),
                             (ROOT / "installers/payload" / source).read_bytes(), source)


if __name__ == "__main__":
    unittest.main()
