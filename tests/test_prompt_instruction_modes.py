"""中文描述转换的“高级覆写”模式单元测试。"""

import importlib.util
import sys
import unittest
from pathlib import Path

PANEL_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("easy_panel_prompt_mode_test", PANEL_ROOT / "easy_panel.py")
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)

MODEL = "waiIllustriousSDXL_v140.safetensors"


class PromptInstructionModeTest(unittest.TestCase):
    def test_standard_mode_keeps_two_line_format(self):
        result = easy_panel.build_prompt_instruction("蓝发女性，白衬衫", MODEL, "safe")
        instruction = result["instruction"]
        self.assertEqual(result["mode"], "standard")
        self.assertIn("POSITIVE:", instruction)
        self.assertIn("NEGATIVE:", instruction)
        self.assertNotIn("STAGE2_POSITIVE", instruction)
        self.assertNotIn("三维层叠", instruction)

    def test_damage_mode_injects_overwrite_rules(self):
        result = easy_panel.build_prompt_instruction("女骑士战败，铠甲大面积破损", MODEL, "safe", "advanced")
        instruction = result["instruction"]
        self.assertEqual(result["mode"], "advanced")
        self.assertIn("状态覆写", instruction)
        self.assertIn("三维层叠", instruction)
        self.assertIn("结构层", instruction)
        self.assertIn("展现层", instruction)
        self.assertIn("痕迹层", instruction)
        self.assertIn("STAGE2_POSITIVE", instruction)
        self.assertIn("STAGE2_NEGATIVE", instruction)
        self.assertIn("ANALYSIS", instruction)
        self.assertIn("PARAMS", instruction)
        self.assertIn("0.45~0.60", instruction)
        self.assertIn("清除", instruction)
        self.assertIn("换装", instruction)  # 通用覆写不只覆盖战损场景
        self.assertIn("女骑士战败", instruction)  # 用户原文必须带上

    def test_legacy_damage_mode_still_works(self):
        result = easy_panel.build_prompt_instruction("战损", MODEL, "safe", "damage")
        self.assertEqual(result["mode"], "advanced")
        self.assertIn("STAGE2_POSITIVE", result["instruction"])

    def test_damage_mode_still_carries_family_rules(self):
        result = easy_panel.build_prompt_instruction("破损的裙子", MODEL, "safe", "advanced")
        self.assertIn("当前模型族", result["instruction"])
        self.assertIn("规则：", result["instruction"])
        self.assertEqual(result["family"], "illustrious")

    def test_unknown_mode_falls_back_to_standard(self):
        result = easy_panel.build_prompt_instruction("测试", MODEL, "safe", "hack")
        self.assertEqual(result["mode"], "standard")
        self.assertNotIn("STAGE2_POSITIVE", result["instruction"])

    def test_empty_text_is_rejected(self):
        with self.assertRaises(ValueError):
            easy_panel.build_prompt_instruction("   ", MODEL, "safe", "advanced")

    def test_endpoint_passes_mode_through(self):
        source = (PANEL_ROOT / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn('data.get("mode", "standard")', source)
        self.assertIn("PROMPT_INSTRUCTION_MODES", source)
        self.assertIn("PROMPT_INSTRUCTION_ADVANCED_RULES", source)

    def test_frontend_mode_wiring(self):
        html = (PANEL_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="promptInstructionMode"', html)
        self.assertIn('value="advanced"', html)
        self.assertIn("prompt-mode.js", html)
        self.assertIn('id="translatedStage2Positive"', html)
        script = (PANEL_ROOT / "web" / "assets" / "js" / "prompt-mode.js").read_text(encoding="utf-8")
        self.assertIn("STAGE2_POSITIVE", script)
        self.assertIn("三维层叠", script)
        self.assertIn("copyStage2Prompt", script)
        self.assertIn("'advanced'", script)


if __name__ == "__main__":
    unittest.main()
