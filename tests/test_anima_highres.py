"""Anima 高清重建（Highres Reconstruction）的契约测试。

复用主流程的 Hires 链（Anime6B → 缩放 → VAEEncode → 二采 → Decode），由
``animaHighres.enabled`` 触发；参数按 Anima profile 约束（1.15–2.0× /
denoise 0.20–0.30 / 长边上限 2560），不套用 Illustrious 的「二采目的」上限。
与 Detail Refine（同尺寸润色）互不替代。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.anima_highres import (
    ANIMA_HIGHRES_PRESETS,
    DEFAULT_MAX_LONG_EDGE,
    HIGHRES_DENOISE_CAP,
    HIGHRES_DENOISE_FLOOR,
    HIGHRES_SCALE_CAP,
    HIGHRES_SCALE_FLOOR,
    normalize_anima_highres,
)
from easy_panel_app.model_profiles import ANIMA_HIGHRES_DEFAULTS, model_sampling_profile

SPEC = importlib.util.spec_from_file_location("easy_panel_anima_highres_test", PROJECT_DIR / "easy_panel.py")
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


def payload(model: str) -> dict:
    return {
        "model": model,
        "promptSections": {"subject": "1girl", "scene": "rainy street"},
        "negative": "blurry",
        "width": 832,
        "height": 1216,
        "steps": 34,
        "cfg": 4.8,
    }


class AnimaHighresParameterTests(unittest.TestCase):
    """参数收敛与目标尺寸。"""

    def normalize(self, raw, defaults=None, width=832, height=1216, cfg=4.8):
        return normalize_anima_highres(
            {"animaHighres": raw},
            ANIMA_HIGHRES_DEFAULTS if defaults is None else defaults,
            width, height, cfg)

    def test_defaults_and_target_size(self):
        spec = self.normalize({})
        self.assertFalse(spec["enabled"])
        self.assertEqual(1.5, spec["scale"])
        self.assertEqual(0.25, spec["denoise"])
        self.assertEqual(20, spec["steps"])
        self.assertEqual(4.8, spec["cfg"])
        self.assertEqual(DEFAULT_MAX_LONG_EDGE, spec["maxLongEdge"])
        self.assertEqual((1248, 1824), (spec["targetWidth"], spec["targetHeight"]))
        self.assertEqual("RealESRGAN_x4plus_anime_6B.pth", spec["upscaler"])

    def test_scale_and_denoise_are_clamped_to_anima_range(self):
        spec = self.normalize({"enabled": True, "scale": 3.0, "denoise": 0.9})
        self.assertEqual(HIGHRES_SCALE_CAP, spec["scale"])
        self.assertEqual(HIGHRES_DENOISE_CAP, spec["denoise"])
        spec = self.normalize({"enabled": True, "scale": 1.0, "denoise": 0.05})
        self.assertEqual(HIGHRES_SCALE_FLOOR, spec["scale"])
        self.assertEqual(HIGHRES_DENOISE_FLOOR, spec["denoise"])

    def test_max_long_edge_shrinks_target_keeping_alignment(self):
        spec = self.normalize({"enabled": True, "scale": 2.0}, width=1152, height=1536)
        self.assertLessEqual(max(spec["targetWidth"], spec["targetHeight"]), 2560)
        self.assertEqual(0, spec["targetWidth"] % 8)
        self.assertEqual(0, spec["targetHeight"] % 8)
        expected = int(2304 * (2560 / 3072) / 8 + 0.5) * 8
        self.assertEqual(expected, spec["targetWidth"])

    def test_cfg_falls_back_to_first_pass_when_profile_has_none(self):
        spec = normalize_anima_highres({"animaHighres": {}}, {}, 832, 1216, 4.2)
        self.assertEqual(4.2, spec["cfg"])

    def test_presets_are_listed_for_the_frontend(self):
        self.assertEqual(1.25, ANIMA_HIGHRES_PRESETS["conservative"]["scale"])
        self.assertEqual(0.25, ANIMA_HIGHRES_PRESETS["recommended"]["denoise"])
        self.assertEqual(0.29, ANIMA_HIGHRES_PRESETS["strong"]["denoise"])
        self.assertEqual(24, ANIMA_HIGHRES_PRESETS["strong"]["steps"])


class AnimaHighresProfileTests(unittest.TestCase):
    """Anima 的 capabilities 与 hires 默认值。"""

    def test_anima_capabilities_open_hires_and_flag_highres(self):
        for name in ("anima-base-v1.0.safetensors", "anima-kei-v3.safetensors"):
            with self.subTest(name=name):
                profile = model_sampling_profile(name)
                self.assertEqual("anima", profile["family"])
                self.assertTrue(profile["capabilities"]["hires_fix"])
                self.assertTrue(profile["capabilities"]["anima_highres"])
                self.assertFalse(profile["capabilities"]["regional_prompting"])
                self.assertEqual(1.5, profile["hires"]["scale"])
                self.assertEqual(0.20, profile["hires"]["min_denoise"])
                self.assertEqual(0.30, profile["hires"]["max_denoise"])
                self.assertEqual(2560, profile["hires"]["max_long_edge"])

    def test_illustrious_keeps_its_own_hires_defaults(self):
        profile = model_sampling_profile("waiIllustriousSDXL_v140.safetensors")
        self.assertEqual("illustrious", profile["family"])
        self.assertTrue(profile["capabilities"]["hires_fix"])
        self.assertNotIn("max_long_edge", profile["hires"])


class AnimaHighresWorkflowTests(unittest.TestCase):
    """build_workflow 的触发条件与节点链。"""

    def build(self, data: dict) -> dict:
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            return easy_panel.build_workflow(data)

    def nodes_of(self, workflow: dict, class_type: str) -> list[dict]:
        return [node for node in workflow["prompt"].values()
                if node.get("class_type") == class_type]

    def test_enabled_builds_upscale_then_second_pass(self):
        data = payload("anima-base-v1.0.safetensors")
        data["animaHighres"] = {"enabled": True}
        workflow = self.build(data)
        graph = workflow["prompt"]
        samplers = self.nodes_of(workflow, "KSampler")
        self.assertEqual(2, len(samplers))
        refine = samplers[1]["inputs"]
        self.assertAlmostEqual(0.25, refine["denoise"])
        self.assertEqual(20, refine["steps"])
        self.assertAlmostEqual(4.8, refine["cfg"])
        self.assertEqual("er_sde", refine["sampler_name"])
        self.assertEqual("simple", refine["scheduler"])
        # 超分 → 缩放 → VAEEncode 链存在，且二采 latent 来自放大后的图。
        self.assertEqual(1, len(self.nodes_of(workflow, "UpscaleModelLoader")))
        self.assertEqual(1, len(self.nodes_of(workflow, "ImageUpscaleWithModel")))
        scales = self.nodes_of(workflow, "ImageScale")
        self.assertEqual(1, len(scales))
        self.assertEqual(1248, scales[0]["inputs"]["width"])
        self.assertEqual(1824, scales[0]["inputs"]["height"])
        self.assertEqual(
            "RealESRGAN_x4plus_anime_6B.pth",
            self.nodes_of(workflow, "UpscaleModelLoader")[0]["inputs"]["model_name"],
        )
        latent_source = graph[str(refine["latent_image"][0])]
        self.assertEqual("VAEEncode", latent_source["class_type"])
        # 首采对照图与成品各一个 SaveImage。
        saves = self.nodes_of(workflow, "SaveImage")
        prefixes = [node["inputs"]["filename_prefix"] for node in saves]
        self.assertEqual(["EasyPanel_base", "EasyPanel"], prefixes)

    def test_disabled_keeps_single_sampler(self):
        data = payload("anima-base-v1.0.safetensors")
        self.assertEqual(1, len(self.nodes_of(self.build(data), "KSampler")))
        data["animaHighres"] = {"enabled": False}
        self.assertEqual(1, len(self.nodes_of(self.build(data), "KSampler")))

    def test_anima_ignores_illustrious_purpose_cap(self):
        # 二采目的「保留首采」上限是 Illustrious 的 0.23；Anima 不受它影响。
        data = payload("anima-base-v1.0.safetensors")
        data["animaHighres"] = {"enabled": True, "denoise": 0.29}
        data["hiresPurpose"] = "preserve"
        refine = self.nodes_of(self.build(data), "KSampler")[1]["inputs"]
        self.assertAlmostEqual(0.29, refine["denoise"])

    def test_hires_prompt_append_reaches_second_pass(self):
        data = payload("anima-base-v1.0.safetensors")
        data["animaHighres"] = {"enabled": True}
        data["hiresPromptMode"] = "append"
        data["hiresPositive"] = "fine individual hair strands"
        nodes = self.build(data)
        texts = [node["inputs"]["text"] for node in self.nodes_of(nodes, "CLIPTextEncode")]
        self.assertTrue(any("fine individual hair strands" in text for text in texts))

    def test_krea2_is_still_rejected(self):
        data = payload("krea2TurboFp8.safetensors")
        data["animaHighres"] = {"enabled": True}
        nodes = self.build(data)
        self.assertEqual(1, len(self.nodes_of(nodes, "KSampler")))

    def test_output_enhancement_conflicts_with_highres(self):
        data = payload("anima-base-v1.0.safetensors")
        data["animaHighres"] = {"enabled": True}
        data["outputEnhancement"] = {"mode": "anime6b", "scale": 1.5}
        with self.assertRaisesRegex(ValueError, "不能同时开启"):
            self.build(data)


class AnimaHighresUiTests(unittest.TestCase):
    """前端接线：脚本加载、档位、payload 注入。"""

    def test_page_loads_the_script(self):
        html = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("/assets/js/anima-highres.js?v=", html)

    def test_script_exposes_the_panel_and_state(self):
        script = (PROJECT_DIR / "web/assets/js/anima-highres.js").read_text(encoding="utf-8")
        for marker in ("animaHighresEnabled", "高清重建", "保守", "推荐", "强化",
                       "animaHighresState", "pushToHiresControls", "animaHighresApplyPreset",
                       "fine individual hair strands"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

    def test_custom_prompt_has_paste_and_clear_buttons(self):
        """自定义二采提示词与提示词分区一致：可一键粘贴/清除。"""

        script = (PROJECT_DIR / "web/assets/js/anima-highres.js").read_text(encoding="utf-8")
        self.assertIn('id="animaHighresCustomPaste"', script)
        self.assertIn('id="animaHighresCustomClear"', script)
        self.assertIn('class="prompt-section-paste"', script)
        self.assertIn('class="prompt-section-clear"', script)
        self.assertIn('onclick="animaHighresCustomPaste()"', script)
        self.assertIn('onclick="animaHighresCustomClear()"', script)
        self.assertIn("window.animaHighresCustomPaste = async function", script)
        self.assertIn("window.animaHighresCustomClear = function", script)
        # 粘贴/清除后必须走一次刷新，让二采参数与校验同步。
        self.assertIn("已从剪贴板填入自定义二采提示词。", script)
        self.assertIn("已清空自定义二采提示词。", script)

    def test_panel_reads_anima_highres_for_output_size(self):
        panel_js = (PROJECT_DIR / "web/assets/js/panel.js").read_text(encoding="utf-8")
        self.assertIn("animaHighresEnabled", panel_js)
        self.assertIn("max_long_edge", panel_js)


if __name__ == "__main__":
    unittest.main()
