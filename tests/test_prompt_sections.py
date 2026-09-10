from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "easy_panel.py"
SPEC = importlib.util.spec_from_file_location("easy_panel_sections_test", MODULE_PATH)
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)

from easy_panel_app import prompt_utils  # noqa: E402  (panel root must be on sys.path)


SECTIONS = {
    "subject": "1girl, solo, luna",
    "appearance": "grey hair, blue eyes, long hair",
    "expression": "soft smile",
    "clothing": "white coat, blue bikini top",
    "pose": "sitting, leaning against wall",
    "composition": "wide shot, side view, full body",
    "scene": "ruins, collapsed building",
    "lighting": "soft daylight",
}


def payload(**overrides) -> dict:
    data = {
        "model": "waiIllustriousSDXL_v140.safetensors",
        "promptSections": dict(SECTIONS),
        "negative": "",
        "width": 768,
        "height": 1024,
        "steps": 17,
        "cfg": 4.2,
        "sampler": "dpmpp_2m",
        "scheduler": "beta",
        "guidance": {"mode": "off"},
    }
    data.update(overrides)
    return data


class ReplaceSectionTests(unittest.TestCase):
    """One section changes; every other section and the hi-res fields keep their values."""

    def compiled(self, data: dict) -> dict:
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            return easy_panel.compile_prompt(data)

    def test_replace_clothing_keeps_appearance(self):
        compiled = self.compiled(payload(sectionEdit={"section": "clothing", "value": "maid outfit"}))
        self.assertIn("maid outfit", compiled["positive"])
        self.assertNotIn("white coat", compiled["positive"])
        self.assertIn("grey hair", compiled["positive"])
        self.assertIn("blue eyes", compiled["positive"])
        self.assertEqual("maid outfit", compiled["sections"]["clothing"])
        self.assertEqual(SECTIONS["appearance"], compiled["sections"]["appearance"])

    def test_replace_scene_keeps_composition(self):
        compiled = self.compiled(payload(sectionEdit={"section": "scene", "value": "forest"}))
        self.assertIn("forest", compiled["positive"])
        self.assertNotIn("ruins", compiled["positive"])
        self.assertEqual(SECTIONS["composition"], compiled["sections"]["composition"])
        self.assertIn("wide shot", compiled["positive"])

    def test_replace_pose_keeps_clothing(self):
        compiled = self.compiled(payload(sectionEdit={"section": "pose", "value": "standing"}))
        self.assertEqual("standing", compiled["sections"]["pose"])
        self.assertEqual(SECTIONS["clothing"], compiled["sections"]["clothing"])
        self.assertIn("white coat", compiled["positive"])

    def test_replace_expression_keeps_scene(self):
        compiled = self.compiled(payload(sectionEdit={"section": "expression", "value": "angry, frown"}))
        self.assertEqual("angry, frown", compiled["sections"]["expression"])
        self.assertEqual(SECTIONS["scene"], compiled["sections"]["scene"])
        self.assertIn("ruins", compiled["positive"])

    def test_append_mode_keeps_existing_terms(self):
        compiled = self.compiled(payload(sectionEdit={
            "section": "clothing", "value": "maid headdress", "mode": "append"}))
        self.assertIn("white coat", compiled["positive"])
        self.assertIn("maid headdress", compiled["positive"])

    def test_section_edit_records_before_and_after_for_the_library(self):
        applied = easy_panel.apply_section_edit(payload(sectionEdit={
            "section": "clothing", "value": "maid outfit"}))
        self.assertEqual("white coat, blue bikini top", applied["sectionEdit"]["before"])
        self.assertEqual("maid outfit", applied["sectionEdit"]["after"])
        self.assertEqual("outfit_change", easy_panel.infer_creative_operation(applied))

        scene = easy_panel.apply_section_edit(payload(sectionEdit={
            "section": "scene", "value": "forest"}))
        self.assertEqual("scene_change", easy_panel.infer_creative_operation(scene))

        expression = easy_panel.apply_section_edit(payload(sectionEdit={
            "section": "expression", "value": "angry"}))
        self.assertEqual("section_change", easy_panel.infer_creative_operation(expression))

    def test_unknown_section_is_rejected_and_ignored(self):
        with self.assertRaises(ValueError):
            prompt_utils.replace_prompt_section(SECTIONS, "hairstyle", "twintails")
        applied = easy_panel.apply_section_edit(payload(sectionEdit={
            "section": "hairstyle", "value": "twintails"}))
        self.assertNotIn("sectionEdit", applied)
        self.assertEqual(SECTIONS, applied["promptSections"])

    def test_unknown_terms_fall_back_to_manual(self):
        parsed = prompt_utils.parse_prompt_sections("1girl, zzzcustomtoken, grey hair")
        self.assertIn("zzzcustomtoken", parsed.get("manual", ""))
        self.assertIn("grey hair", parsed.get("appearance", ""))

    def test_replace_section_preserves_hires_prompt(self):
        data = payload(
            illustriousMode="hires", hiresScale=1.2, hiresPromptMode="append",
            hiresPositive="detailed fabric texture", hiresCompositionLock=True,
            sectionEdit={"section": "clothing", "value": "maid outfit"},
        )
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            nodes = easy_panel.build_workflow(data)["prompt"]
        encoded = [node["inputs"]["text"] for node in nodes.values()
                   if node["class_type"] == "CLIPTextEncode"]
        hires_text = [item for item in encoded if "detailed fabric texture" in item]
        self.assertEqual(1, len(hires_text))
        self.assertIn("maid outfit", hires_text[0])
        self.assertNotIn("white coat", hires_text[0])
        # The hi-res supplement stays out of the first pass.
        first_pass = [item for item in encoded if "maid outfit" in item and "detailed fabric texture" not in item]
        self.assertTrue(first_pass)

    def test_compose_and_diff_helpers(self):
        after = prompt_utils.replace_prompt_section(SECTIONS, "clothing", "maid outfit")
        self.assertEqual(
            [{"section": "clothing", "before": SECTIONS["clothing"], "after": "maid outfit"}],
            prompt_utils.diff_prompt_sections(SECTIONS, after),
        )
        composed = prompt_utils.compose_prompt_sections(after)
        self.assertTrue(composed.startswith("1girl, solo, luna, grey hair, blue eyes, long hair"))


class SectionSwapWiringTests(unittest.TestCase):
    def test_frontend_uses_the_generic_section_swap(self):
        script = (Path(__file__).resolve().parents[1] / "web/assets/js/result-workbench.js").read_text(encoding="utf-8")
        for marker in ("SECTION_SWAP", "openSectionSwap", "swapChosenMode", "sectionEdit",
                       "换服装", "换场景", "换姿势", "换表情", "生成新版本", "仅应用到表单"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)
        panel = (Path(__file__).resolve().parents[1] / "web/assets/js/panel.js").read_text(encoding="utf-8")
        self.assertIn("expression:'promptExpression'", panel)


if __name__ == "__main__":
    unittest.main()
