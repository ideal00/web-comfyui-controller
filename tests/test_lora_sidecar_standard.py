# -*- coding: utf-8 -*-
"""LORA_MEMO_RULES.md §3.1 标准同名 TXT 的解析与渲染回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.lora_sidecars import (  # noqa: E402
    SIDECAR_MARKER,
    parse_lora_sidecar,
    parse_standard_sidecar,
    render_sidecar,
)

STANDARD_TEXT = """【显示标题】测试角色
【模型文件名】test character.safetensors
【相对路径】Illustrious_Hosiery_Test/02_人物模板/test character.safetensors
【SHA256】abc123
【底模】Illustrious
【建议权重】0.6-0.8
【页面URL】https://civitai.red/models/1?modelVersionId=2
【顶层触发词】无

名称：角色
主类：角色 / character / subject
提示词：
testcharacter
名称：角色外貌
主类：外貌 / appearance / appearance
提示词：
long black hair, red eyes, hair ribbon
名称：服装·默认
主类：服装 / clothing / clothing
提示词：
white dress, black thighhighs
"""

HEADER_ONLY_TEXT = """【显示标题】只有头部
【模型文件名】header only.safetensors
【相对路径】Illustrious_Hosiery_Test/01_服装/header only.safetensors
【SHA256】deadbeef
【底模】Illustrious
【建议权重】
【页面URL】
【顶层触发词】无（未确认独立触发词）

备注：未确认页面来源。
"""


class StandardSidecarTests(unittest.TestCase):
    def test_standard_items_keep_name_and_main_class(self) -> None:
        items, meta = parse_standard_sidecar(STANDARD_TEXT)
        self.assertEqual([item[0] for item in items], ["角色", "角色外貌", "服装·默认"])
        self.assertEqual([item[1] for item in items], ["subject", "appearance", "clothing"])
        self.assertEqual(meta["title"], "测试角色")
        self.assertEqual(meta["base_model"], "Illustrious")
        self.assertEqual(meta["weight"], "0.6-0.8")
        self.assertEqual(meta["url"], "https://civitai.red/models/1?modelVersionId=2")
        self.assertEqual(meta["_explicit_trigger"], "1")

    def test_parse_lora_sidecar_reads_standard_sidecar(self) -> None:
        parsed = parse_lora_sidecar(STANDARD_TEXT, "test character.safetensors")
        self.assertEqual(parsed["title"], "测试角色")
        self.assertEqual(parsed["weight"], "0.6-0.8")
        self.assertEqual(parsed["trigger"], "")
        self.assertEqual(len(parsed["outfits"]), 3)
        names = {item["name"] for item in parsed["outfits"]}
        self.assertEqual(names, {"角色", "角色外貌", "服装·默认"})
        by_name = {item["name"]: item for item in parsed["outfits"]}
        self.assertEqual(by_name["角色"]["subject"], "testcharacter")
        self.assertEqual(by_name["角色外貌"]["appearance"], "long black hair, red eyes, hair ribbon")
        self.assertEqual(by_name["服装·默认"]["clothing"], "white dress, black thighhighs")

    def test_header_only_sidecar_has_no_fake_items(self) -> None:
        parsed = parse_lora_sidecar(HEADER_ONLY_TEXT, "header only.safetensors")
        self.assertEqual(parsed["outfits"], [])
        self.assertEqual(parsed["title"], "只有头部")
        self.assertEqual(parsed["base_model"], "Illustrious")

    def test_legacy_bracket_blocks_still_parse(self) -> None:
        legacy = "[服装]\nwhite shirt, black skirt\n"
        parsed = parse_lora_sidecar(legacy, "01_服装/legacy.safetensors")
        self.assertEqual(len(parsed["outfits"]), 1)
        self.assertEqual(parsed["outfits"][0]["clothing"], "white shirt, black skirt")

    def test_render_sidecar_round_trips_through_parser(self) -> None:
        document = {
            "title": "生成测试",
            "file_name": "generated.safetensors",
            "relative_path": "Illustrious_Hosiery_Test/03_通用功能/generated.safetensors",
            "sha256": "0" * 64,
            "base_model": "Illustrious",
            "weight": "0.7",
            "trigger": "",
            "url": "https://civitai.red/models/9?modelVersionId=10",
            "outfits": [
                {"name": "默认服装", "clothing": "red skirt, white blouse"},
                {"name": "手腕饰品", "clothing": "wrist cuffs"},
            ],
        }
        rendered = render_sidecar(document, "Illustrious_Hosiery_Test/03_通用功能/generated.safetensors")
        self.assertTrue(rendered.startswith(SIDECAR_MARKER))
        self.assertIn("【显示标题】生成测试", rendered)
        self.assertIn("【页面URL】https://civitai.red/models/9?modelVersionId=10", rendered)
        self.assertIn("【顶层触发词】无", rendered)
        parsed = parse_lora_sidecar(rendered, "generated.safetensors")
        self.assertEqual(parsed["title"], "生成测试")
        self.assertEqual(parsed["weight"], "0.7")
        self.assertEqual(parsed["trigger"], "")
        self.assertEqual([item["name"] for item in parsed["outfits"]], ["默认服装", "手腕饰品"])
        self.assertEqual(parsed["outfits"][0]["clothing"], "red skirt, white blouse")

    def test_render_without_url_uses_note_line(self) -> None:
        rendered = render_sidecar({"title": "无来源", "weight": "", "trigger": "", "url": "",
                                   "outfits": [{"name": "外观", "appearance": "blue eyes"}]},
                                  "Illustrious_Hosiery_Test/02_人物模板/x.safetensors")
        self.assertIn("【顶层触发词】无（未确认独立触发词）", rendered)
        self.assertIn("备注：", rendered)
        rendered_items, _ = parse_standard_sidecar(rendered)
        self.assertEqual(rendered_items[0][0], "外观")


if __name__ == "__main__":
    unittest.main()
