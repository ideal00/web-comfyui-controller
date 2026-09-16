"""Anima「二采前手部修复」：可选的蒙版 inpaint 步骤（在 Anime6B 超分之前）。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.anima_highres import (  # noqa: E402
    HAND_REPAIR_DEFAULTS,
    HAND_REPAIR_DENOISE_RANGE,
    HAND_REPAIR_GROW_RANGE,
    HAND_REPAIR_STEPS_RANGE,
    normalize_anima_highres,
)
from easy_panel_app.model_profiles import (  # noqa: E402
    ANIMA_HIGHRES_DEFAULTS,
    capability_constraints,
    model_sampling_profile,
)

SPEC = importlib.util.spec_from_file_location(
    "easy_panel_anima_hand_repair_test", PROJECT_DIR / "easy_panel.py")
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)

MASK = "easy_panel/inpaint_mask_test123.png"


def payload(model: str = "anima-base-v1.0.safetensors") -> dict:
    return {
        "model": model,
        "promptSections": {"subject": "1girl", "pose": "hands on hips"},
        "negative": "blurry",
        "width": 768,
        "height": 1024,
        "steps": 8,
        "cfg": 4.8,
    }


class HandRepairNormalizeTests(unittest.TestCase):
    def normalize(self, hand: dict):
        return normalize_anima_highres(
            {"animaHighres": {"enabled": True, "handRepair": hand}},
            ANIMA_HIGHRES_DEFAULTS, 768, 1024, 4.2)

    def test_defaults_are_off_and_filled_in(self):
        spec = self.normalize({})
        hand = spec["handRepair"]
        self.assertFalse(hand["enabled"])
        self.assertEqual("", hand["mask"])
        self.assertEqual(HAND_REPAIR_DEFAULTS["denoise"], hand["denoise"])
        self.assertEqual(HAND_REPAIR_DEFAULTS["steps"], hand["steps"])
        self.assertEqual(HAND_REPAIR_DEFAULTS["grow"], hand["grow"])
        self.assertEqual(4.2, hand["cfg"])  # 跟随首采 CFG
        self.assertIn("five fingers", hand["positive"])
        self.assertIn("extra fingers", hand["negative"])

    def test_ranges_are_clamped(self):
        hand = self.normalize({"enabled": True, "mask": MASK, "denoise": 0.95,
                               "steps": 500, "grow": 999})["handRepair"]
        self.assertEqual(HAND_REPAIR_DENOISE_RANGE[1], hand["denoise"])
        self.assertEqual(HAND_REPAIR_STEPS_RANGE[1], hand["steps"])
        self.assertEqual(HAND_REPAIR_GROW_RANGE[1], hand["grow"])
        low = self.normalize({"enabled": True, "denoise": 0.0, "steps": 1, "grow": -5})["handRepair"]
        self.assertEqual(HAND_REPAIR_DENOISE_RANGE[0], low["denoise"])
        self.assertEqual(HAND_REPAIR_STEPS_RANGE[0], low["steps"])
        self.assertEqual(HAND_REPAIR_GROW_RANGE[0], low["grow"])

    def test_explicit_mask_and_prompts_are_kept(self):
        hand = self.normalize({"enabled": True, "mask": MASK, "positive": "delicate hands",
                               "negative": "six fingers"})["handRepair"]
        self.assertEqual(MASK, hand["mask"])
        self.assertEqual("delicate hands", hand["positive"])
        self.assertEqual("six fingers", hand["negative"])

    def test_constraints_expose_the_hand_repair_ranges(self):
        anima = model_sampling_profile("anima-base-v1.0.safetensors")
        contract = capability_constraints(anima, "highres_reconstruction")["hand_repair"]
        self.assertEqual([0.20, 0.65], contract["denoise"])
        self.assertEqual([8, 40], contract["steps"])
        self.assertEqual([0, 48], contract["grow"])


class HandRepairWorkflowTests(unittest.TestCase):
    def build(self, data: dict) -> dict:
        with patch.object(easy_panel, "checkpoint_issue", return_value=None), \
                patch.object(easy_panel, "validate_input_image",
                             side_effect=lambda name, label="姿势图": str(name)):
            return easy_panel.build_workflow(data)

    def nodes_of(self, workflow: dict, class_type: str) -> list[dict]:
        return [node for node in workflow["prompt"].values()
                if node.get("class_type") == class_type]

    def hand_data(self, **hand) -> dict:
        data = payload()
        data["animaHighres"] = {"enabled": True, "handRepair": {"enabled": True, "mask": MASK, **hand}}
        return data

    def test_mask_repair_runs_before_upscale(self):
        workflow = self.build(self.hand_data())
        graph = workflow["prompt"]
        samplers = self.nodes_of(workflow, "KSampler")
        # 首采 + 手部修复 + 二采 = 3 次采样。
        self.assertEqual(3, len(samplers))
        hand_id, hand_node = next(
            (node_id, node) for node_id, node in graph.items()
            if node.get("class_type") == "KSampler"
            and (node.get("_meta") or {}).get("stageLabel") == "二采前手部修复")
        hand_inputs = hand_node["inputs"]
        self.assertAlmostEqual(HAND_REPAIR_DEFAULTS["denoise"], hand_inputs["denoise"])
        self.assertEqual(HAND_REPAIR_DEFAULTS["steps"], hand_inputs["steps"])
        self.assertEqual("dpmpp_2m_sde_gpu", hand_inputs["sampler_name"])
        self.assertEqual("sgm_uniform", hand_inputs["scheduler"])

        masks = self.nodes_of(workflow, "LoadImageMask")
        self.assertEqual(1, len(masks))
        self.assertEqual(MASK, masks[0]["inputs"]["image"])
        inpaint = self.nodes_of(workflow, "VAEEncodeForInpaint")[0]["inputs"]
        self.assertEqual(HAND_REPAIR_DEFAULTS["grow"], inpaint["grow_mask_by"])
        # 修复用的 latent 来自 inpaint 编码，而 inpaint 的像素来自首采解码图。
        self.assertEqual("VAEEncodeForInpaint", graph[str(hand_inputs["latent_image"][0])]["class_type"])
        self.assertEqual("VAEDecode", graph[str(inpaint["pixels"][0])]["class_type"])

        # Anime6B 超分吃的是「修复后」的图，而不是首采原图。
        upscale = self.nodes_of(workflow, "ImageUpscaleWithModel")[0]["inputs"]
        repaired_decode_id = str(upscale["image"][0])
        self.assertEqual("VAEDecode", graph[repaired_decode_id]["class_type"])
        self.assertEqual(hand_id, str(graph[repaired_decode_id]["inputs"]["samples"][0]))
        self.assertNotEqual(str(inpaint["pixels"][0]), repaired_decode_id)

        prefixes = [node["inputs"]["filename_prefix"] for node in self.nodes_of(workflow, "SaveImage")]
        self.assertEqual(["EasyPanel_aux/EasyPanel_base", "EasyPanel_aux/EasyPanel_hand", "EasyPanel"],
                         prefixes)

    def test_disabled_keeps_two_samplers_and_no_mask_nodes(self):
        data = payload()
        data["animaHighres"] = {"enabled": True, "handRepair": {"enabled": False, "mask": MASK}}
        workflow = self.build(data)
        self.assertEqual(2, len(self.nodes_of(workflow, "KSampler")))
        self.assertEqual([], self.nodes_of(workflow, "LoadImageMask"))
        self.assertEqual([], self.nodes_of(workflow, "VAEEncodeForInpaint"))
        prefixes = [node["inputs"]["filename_prefix"] for node in self.nodes_of(workflow, "SaveImage")]
        self.assertNotIn("EasyPanel_aux/EasyPanel_hand", prefixes)

    def test_enabled_without_mask_is_rejected(self):
        data = payload()
        data["animaHighres"] = {"enabled": True, "handRepair": {"enabled": True}}
        with self.assertRaisesRegex(ValueError, "没有上传蒙版"):
            self.build(data)

    def test_hand_prompts_are_appended_to_first_pass_text(self):
        workflow = self.build(self.hand_data(positive="delicate hands", negative="six fingers"))
        texts = [node["inputs"]["text"] for node in self.nodes_of(workflow, "CLIPTextEncode")]
        self.assertTrue(any("delicate hands" in text for text in texts))
        self.assertTrue(any("six fingers" in text for text in texts))

    def test_preflight_reports_hand_repair_state(self):
        data = self.hand_data()
        report = easy_panel.anima_preflight(data)
        self.assertEqual([], report["errors"])
        self.assertTrue(any("手部修复" in warning for warning in report["warnings"]))
        missing = payload()
        missing["animaHighres"] = {"enabled": True, "handRepair": {"enabled": True}}
        report = easy_panel.anima_preflight(missing)
        self.assertTrue(any("没有上传蒙版" in error for error in report["errors"]))


class HandRepairFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (PROJECT_DIR / "web/assets/js/anima-highres.js").read_text(encoding="utf-8")
        cls.hand = (PROJECT_DIR / "web/assets/js/hand-workbench.js").read_text(encoding="utf-8")
        cls.pages = [(PROJECT_DIR / name).read_text(encoding="utf-8")
                     for name in ("index.html", "installers/payload/index.html")]

    def test_panel_exposes_the_hand_repair_controls(self):
        for marker in ("animaHighresHandEnabled", "animaHighresHandMask", "animaHighresHandImage",
                       "animaHighresHandDenoise", "animaHighresHandSteps", "animaHighresHandGrow",
                       "animaHighresHandCfg", "animaHighresHandPositive", "animaHighresHandNegative",
                       "animaHighresHandStatus", "二采前手部修复",
                       "window.animaHighresHandUpload", "window.animaHighresHandClear",
                       "window.animaHighresHandReceive", "handRepair: state.handRepair"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)

    def test_panel_uploads_mask_through_inpaint_endpoint(self):
        self.assertIn('fetch("/api/upload-inpaint"', self.script)
        self.assertIn('form.append("mask", maskBlob, "anima_hand_mask.png")', self.script)

    def test_panel_has_a_drawable_mask_editor(self):
        """像 Illustrious「局部修复」那样，蒙版要能在面板里自己画。"""

        for marker in ("animaHighresHandCanvas", "animaHighresHandBrush", "animaHighresHandBrushValue",
                       "animaHighresHandPaint", "animaHighresHandErase",
                       "window.animaHighresHandSetTool", "window.animaHighresHandUndo",
                       "window.animaHighresHandResetMask", "window.animaHighresHandSaveMask",
                       "window.animaHighresHandLoadBase", "window.animaHighresHandLoadLastBase",
                       "window.animaHighresHandUploadBase", "handPointerDown", "handStroke",
                       'addEventListener("pointerdown", handPointerDown)', "destination-out",
                       "rgba(255,60,60,0.55)", "touch-action:none"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)

    def test_mask_editor_exports_white_on_black_mask(self):
        self.assertIn('ctx.fillStyle = "#000000"', self.script)
        self.assertIn("exporter.toBlob(resolve, \"image/png\")", self.script)
        self.assertIn("handMaskPixels()", self.script)
        self.assertIn("蒙版是空的", self.script)

    def test_last_first_pass_button_aligns_seed_and_size(self):
        """「上次首采图」要顺手把 seed 与尺寸填回面板，蒙版才对得上。"""

        self.assertIn('fetch("/api/snapshots")', self.script)
        self.assertIn("comparisonOutputs", self.script)
        self.assertIn("subfolder=EasyPanel_aux", self.script)
        self.assertIn("seed.value = String(payload.seed)", self.script)
        self.assertIn("用同一 seed 重跑才对齐", self.script)

    def test_hand_editor_styles_are_shipped(self):
        css = (PROJECT_DIR / "web/assets/css/panel.css").read_text(encoding="utf-8")
        for marker in (".anima-hand-row", ".anima-hand-file"):
            with self.subTest(marker=marker):
                self.assertIn(marker, css)
        for page in self.pages:
            self.assertIn("anima-highres.js?v=8", page)

    def test_hand_workbench_routes_to_anima_panel(self):
        self.assertIn("window.modelFamilyClient", self.hand)
        self.assertIn("window.animaHighresHandReceive(data.image,data.mask", self.hand)

    def test_button_copy_covers_both_repair_paths(self):
        for page in self.pages:
            self.assertIn("发送蒙版到修复流程", page)


if __name__ == "__main__":
    unittest.main()
