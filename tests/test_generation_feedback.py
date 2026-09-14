"""生成反馈测试：友好错误分类、阶段计划、接口与前端接线。"""

from __future__ import annotations

import unittest
from pathlib import Path

import easy_panel
from easy_panel_app import rpg_api
from easy_panel_app.generation_errors import (
    GENERATION_ERROR_HINTS,
    STAGE_LABELS,
    friendly_comfy_error,
    friendly_error_text,
)

ROOT = Path(__file__).resolve().parent.parent


def error_item(message: str, *, node: str = "", node_type: str = "KSampler") -> dict:
    payload = {"exception_message": message, "node_type": node_type}
    if node:
        payload["node_title"] = node
    return {"status": {"status_str": "error", "messages": [["execution_error", payload]]}}


def base_payload(model: str = "anima-base-v1.0.safetensors", **overrides) -> dict:
    data = {
        "model": model,
        "promptSections": {"subject": "1girl, solo"},
        "negative": "blurry",
        "width": 832,
        "height": 1216,
        "seed": 7,
        "steps": 30,
        "cfg": 4.8,
    }
    data.update(overrides)
    return data


def plan_for(data: dict) -> dict:
    return easy_panel.generation_plan(easy_panel.build_workflow(data))


class FriendlyErrorTests(unittest.TestCase):
    def test_known_errors_are_classified(self):
        cases = [
            ("CUDA error: out of memory", "显存不足"),
            ("Value not in list: ckpt_name", "模型或文件缺失"),
            ("Cannot execute because node FaceDetailer does not exist", "缺少自定义节点"),
            ("Prompt outputs failed validation: KSampler", "节点参数校验失败"),
            ("execution interrupted", "生成已中断"),
            ("tuple index out of range", "区域提示词与当前模型不兼容"),
        ]
        for message, expected in cases:
            with self.subTest(message):
                friendly = friendly_comfy_error(error_item(message))
                self.assertEqual(expected, friendly["title"])
                self.assertTrue(friendly["solutions"])
                self.assertTrue(friendly["technical"])

    def test_unknown_error_falls_back_and_keeps_node(self):
        friendly = friendly_comfy_error(error_item("some exotic failure", node="FaceDetailer"))
        self.assertEqual("生成失败", friendly["title"])
        self.assertIn("FaceDetailer", friendly["reason"])

    def test_rule_table_is_populated_and_text_is_one_line(self):
        self.assertGreaterEqual(len(GENERATION_ERROR_HINTS), 6)
        friendly = friendly_comfy_error(error_item("CUDA out of memory"))
        text = friendly_error_text(friendly)
        self.assertIn("显存不足", text)
        self.assertIn("建议：", text)
        self.assertNotIn("\n", text)
        self.assertEqual("", friendly_error_text(None))

    def test_rpg_status_uses_the_same_explanation(self):
        status = rpg_api.history_to_rpg_status(
            "abc", {"abc": error_item("CUDA error: out of memory")})
        self.assertEqual("error", status["status"])
        self.assertIsInstance(status["error"], str)
        self.assertIn("显存不足", status["error"])
        self.assertEqual("显存不足", status["error_detail"]["title"])


class GenerationPlanTests(unittest.TestCase):
    def test_single_pass_plan(self):
        plan = plan_for(base_payload("waiIllustriousSDXL_v170.safetensors"))
        labels = set(plan["stages"].values())
        self.assertIn("首采采样", labels)
        self.assertNotIn("高清二采", labels)
        self.assertEqual(1, len(plan["samplers"]))
        self.assertIn("保存作品", labels)
        self.assertIn("加载模型", labels)

    def test_anima_highres_plan_marks_second_pass_and_upscale(self):
        plan = plan_for(base_payload(animaHighres={"enabled": True, "scale": 1.5,
                                                   "denoise": 0.25, "steps": 20}))
        labels = set(plan["stages"].values())
        self.assertIn("高清二采", labels)
        self.assertIn("超分放大", labels)
        self.assertEqual(2, len(plan["samplers"]))
        # 首采步数取自 payload（30），二采为高清二采的 20 步。
        self.assertEqual([30, 20], [plan["samplers"][node] for node in plan["samplerOrder"]])

    def test_detail_refine_plan_uses_refine_label(self):
        plan = plan_for(base_payload(animaDetailRefine={"enabled": True, "mode": "balanced"}))
        self.assertIn("细节重绘", set(plan["stages"].values()))

    def test_illustrious_hires_plan(self):
        plan = plan_for(base_payload("waiIllustriousSDXL_v170.safetensors",
                                     illustriousMode="hires", hiresScale=1.5,
                                     hiresDenoise=0.25, hiresSteps=20, hiresCfg=5))
        self.assertIn("高清二采", set(plan["stages"].values()))

    def test_seedvr2_sampler_is_labelled_as_output_enhancement(self):
        plan = plan_for(base_payload("waiIllustriousSDXL_v170.safetensors",
                                     outputEnhancement={"mode": "seedvr2"}))
        self.assertIn("输出增强采样", set(plan["stages"].values()))
        self.assertIn(1, plan["samplers"].values())

    def test_plan_survives_empty_workflow(self):
        plan = easy_panel.generation_plan({})
        self.assertEqual({"stages": {}, "samplers": {}, "samplerOrder": []}, plan)


class FeedbackWiringTests(unittest.TestCase):
    def test_backend_wires_friendly_history_and_plan(self):
        source = (ROOT / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn("entry[\"friendlyError\"] = friendly_comfy_error(entry)", source)
        self.assertIn("\"plan\": generation_plan(workflow)", source)
        self.assertIn("\"plan\": generation_plan(item[\"workflow\"])", source)
        self.assertIn("def generation_plan(", source)
        self.assertIn("friendly_error_text(friendly)", source)
        self.assertIn("STAGE_LABELS", source)

    def test_frontend_uses_stage_and_friendly_error(self):
        panel = (ROOT / "web/assets/js/panel.js").read_text(encoding="utf-8")
        self.assertIn("function generationStageText(", panel)
        self.assertIn("function friendlyErrorText(", panel)
        self.assertIn("function formatElapsed(", panel)
        self.assertIn("registerGenerationPrompt(data.prompt_id,data.plan)", panel)
        self.assertIn("comfyQueueInfo", panel)
        self.assertIn("item.friendlyError", panel)
        self.assertIn("当前：${stage}", panel)

        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("panel.js?v=67", html)

    def test_error_hint_labels_are_chinese(self):
        for label in STAGE_LABELS.values():
            self.assertTrue(any("\u4e00" <= char <= "\u9fff" for char in label), label)


if __name__ == "__main__":
    unittest.main()
