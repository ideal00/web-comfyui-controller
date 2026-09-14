"""Anima 细节重绘（Detail Refine）的契约测试。

它是 Anima 专属的同尺寸低温细化链，与 Illustrious 的二次采样（hires）是两套语义：
不放大、不加 Tile、不改变输出尺寸，只补高频细节。
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

from easy_panel_app.anima_refine import (
    DEFAULT_REFINE_MODE,
    DETAIL_MODULES,
    REFINE_MODES,
    merge_anima_detail_prompt,
    normalize_anima_detail_refine,
)

SPEC = importlib.util.spec_from_file_location("easy_panel_anima_refine_test", PROJECT_DIR / "easy_panel.py")
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


def payload(model: str) -> dict:
    return {
        "model": model,
        "promptSections": {"subject": "1girl", "scene": "rainy street"},
        "negative": "blurry",
        "width": 768,
        "height": 1024,
        "steps": 17,
        "cfg": 4.2,
    }


def refine_params(raw: dict) -> dict:
    """normalize_anima_detail_refine 接收的是完整请求，测试里包一层更省事。"""
    return normalize_anima_detail_refine({"animaDetailRefine": raw})


class AnimaRefineParameterTests(unittest.TestCase):
    """参数收敛与模式限幅。"""

    def test_disabled_by_default(self):
        params = refine_params({})
        self.assertFalse(params["enabled"])
        self.assertEqual(DEFAULT_REFINE_MODE, params["mode"])
        self.assertEqual(0.12, params["denoise"])
        self.assertEqual(16, params["steps"])
        self.assertEqual("inherit", params["seedMode"])
        self.assertEqual([], params["modules"])

    def test_mode_limits(self):
        for mode, (low, high, preset) in REFINE_MODES.items():
            with self.subTest(mode=mode):
                # 超高被压到该模式上限
                self.assertEqual(high, refine_params(
                    {"enabled": True, "mode": mode, "denoise": 0.9})["denoise"])
                # 超低被抬到该模式下限
                self.assertEqual(low, refine_params(
                    {"enabled": True, "mode": mode, "denoise": 0.01})["denoise"])
                # 未指定时用预设值
                self.assertEqual(preset, refine_params({"mode": mode})["denoise"])

    def test_unknown_mode_and_seed_fall_back(self):
        params = refine_params({"mode": "nope", "seedMode": "wild"})
        self.assertEqual(DEFAULT_REFINE_MODE, params["mode"])
        self.assertEqual("inherit", params["seedMode"])

    def test_unknown_modules_are_dropped(self):
        params = refine_params(
            {"enabled": True, "modules": ["hair", "not-a-module", "water", "hair"]})
        self.assertEqual(["hair", "water"], params["modules"])

    def test_steps_are_clamped(self):
        self.assertEqual(40, refine_params({"steps": 999})["steps"])
        self.assertEqual(6, refine_params({"steps": -5})["steps"])

    def test_every_module_has_a_label(self):
        from easy_panel_app.anima_refine import DETAIL_MODULE_LABELS
        self.assertEqual(set(DETAIL_MODULES), set(DETAIL_MODULE_LABELS))


class AnimaRefinePromptTests(unittest.TestCase):
    """细节词只追加，不改写首采。"""

    def test_modules_are_appended_to_the_base_prompt(self):
        params = refine_params({"enabled": True, "modules": ["hair", "water"]})
        merged = merge_anima_detail_prompt("1girl, solo, rainy street", params)
        self.assertTrue(merged.startswith("1girl, solo, rainy street"))
        self.assertIn(DETAIL_MODULES["hair"], merged)
        self.assertIn(DETAIL_MODULES["water"], merged)

    def test_custom_prompt_is_appended(self):
        params = refine_params({"enabled": True, "prompt": "wet reflective pavement"})
        merged = merge_anima_detail_prompt("1girl", params)
        self.assertIn("wet reflective pavement", merged)

    def test_no_extras_keeps_the_base_prompt_untouched(self):
        params = refine_params({"enabled": True})
        self.assertEqual("1girl, solo", merge_anima_detail_prompt("1girl, solo", params))


class AnimaRefineWorkflowTests(unittest.TestCase):
    """工作流契约：默认关闭、开启后只加一条同尺寸细化链。"""

    def build(self, data: dict) -> dict:
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            return easy_panel.build_workflow(data)

    def nodes_of(self, workflow: dict, class_type: str) -> list[dict]:
        return [node for node in workflow["prompt"].values()
                if node.get("class_type") == class_type]

    def test_disabled_keeps_a_single_sampler(self):
        nodes = self.build(payload("anima-base-v1.0.safetensors"))
        self.assertEqual(1, len(self.nodes_of(nodes, "KSampler")))
        self.assertEqual(0, len(self.nodes_of(nodes, "VAEEncode")))

    def test_enabled_adds_a_low_denoise_same_size_refine_pass(self):
        data = payload("anima-base-v1.0.safetensors")
        data["animaDetailRefine"] = {"enabled": True, "mode": "balanced",
                                     "modules": ["hair", "water"]}
        workflow = self.build(data)
        graph = workflow["prompt"]
        samplers = self.nodes_of(workflow, "KSampler")
        self.assertEqual(2, len(samplers))
        refine = samplers[1]["inputs"]
        self.assertEqual(0.12, refine["denoise"])
        self.assertEqual(16, refine["steps"])
        self.assertEqual(4.2, refine["cfg"])
        # 尺寸不变的证据：细化链的 latent 来自 VAEEncode（首采解码），中间没有放大节点。
        latent_source = graph[str(refine["latent_image"][0])]
        self.assertEqual("VAEEncode", latent_source["class_type"])
        self.assertEqual(0, len(self.nodes_of(workflow, "ImageUpscaleWithModel")))
        self.assertEqual(0, len(self.nodes_of(workflow, "ImageScale")))

    def test_enabled_saves_a_base_comparison_copy(self):
        data = payload("anima-base-v1.0.safetensors")
        data["animaDetailRefine"] = {"enabled": True}
        nodes = self.build(data)
        saves = self.nodes_of(nodes, "SaveImage")
        prefixes = [node["inputs"]["filename_prefix"] for node in saves]
        self.assertEqual(["EasyPanel_base", "EasyPanel"], prefixes)

    def test_refine_prompt_appends_detail_terms_without_touching_the_snapshot(self):
        data = payload("anima-base-v1.0.safetensors")
        data["animaDetailRefine"] = {"enabled": True, "modules": ["hair"]}
        nodes = self.build(data)
        texts = [node["inputs"]["text"] for node in self.nodes_of(nodes, "CLIPTextEncode")]
        self.assertTrue(any(DETAIL_MODULES["hair"] in text for text in texts))
        compiled = easy_panel.compile_prompt(data)
        self.assertIn("rainy street", compiled["positive"])
        self.assertNotIn(DETAIL_MODULES["hair"], compiled["positive"])

    def test_non_anima_models_reject_the_refine_flag(self):
        data = payload("waiIllustriousSDXL_v140.safetensors")
        data["animaDetailRefine"] = {"enabled": True}
        with self.assertRaisesRegex(ValueError, "只对 Anima 模型开放"):
            self.build(data)

    def test_seed_mode_controls_the_refine_seed(self):
        inherit = payload("anima-base-v1.0.safetensors")
        inherit["seed"] = 777
        inherit["animaDetailRefine"] = {"enabled": True, "seedMode": "inherit"}
        self.assertEqual(777, self.nodes_of(self.build(inherit), "KSampler")[1]["inputs"]["seed"])

        randomized = payload("anima-base-v1.0.safetensors")
        randomized["seed"] = 777
        randomized["animaDetailRefine"] = {"enabled": True, "seedMode": "random"}
        self.assertNotEqual(777, self.nodes_of(self.build(randomized), "KSampler")[1]["inputs"]["seed"])


class AnimaRefineUiTests(unittest.TestCase):
    """前端接线：Anima 专属区块、模式三选、模块按钮。"""

    def test_panel_script_documents_the_refine_block(self):
        script = (PROJECT_DIR / "web/assets/js/anima-refine.js").read_text(encoding="utf-8")
        for marker in ("animaDetailRefine", "细节增强", "保构图", "均衡", "场景强化",
                       "发丝", "水面", "Detail Prompt", "animaRefineToggleModule"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

    def test_page_loads_the_script(self):
        html = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("/assets/js/anima-refine.js?v=", html)


if __name__ == "__main__":
    unittest.main()
