"""Prompt 方言层契约测试（Python 侧）。

用例表 `tests/prompt_dialect_cases.json` 是 Python 与前端脚本的唯一共同真相：
`tests/prompt_dialect.node-test.cjs` 用同一份表跑 JS 实现，两边结果必须一致。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app import prompt_dialect as pd

CASES_FILE = Path(__file__).resolve().parent / "prompt_dialect_cases.json"
CASES = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]

#: 与 Danbooru 的 category 编号一致（vendor/tagcomplete 的 danbooru.csv 第 2 列）
CATEGORIES = {
    "hatsune_miku": 4,        # character
    "somebody_name": 1,       # artist
    "touhou": 3,              # copyright
    "shoes": 0,               # general
}


class RuleTests(unittest.TestCase):
    def test_shared_case_table_both_sides(self):
        for case in CASES:
            with self.subTest(tag=case["tag"], dialect=case["dialect"], family=case["family"]):
                resolved = pd.resolve_dialect(case["family"], case["dialect"])
                actual = pd.format_tag(
                    case["tag"], resolved,
                    kind=case.get("kind") or pd.classify_tag(case["tag"], CATEGORIES),
                    protect=bool(case.get("protect")),
                )
                self.assertEqual(case["expect"], actual, case.get("note", ""))

    def test_resolve_dialect_families(self):
        self.assertEqual("space", pd.resolve_dialect("anima", "auto"))
        self.assertEqual("space", pd.resolve_dialect("krea2", "auto"))
        self.assertEqual("canonical", pd.resolve_dialect("illustrious", "auto"))
        self.assertEqual("canonical", pd.resolve_dialect("sdxl", "auto"))
        self.assertEqual("canonical", pd.resolve_dialect("", "auto"))
        # 手动指定优先于模型族
        self.assertEqual("space", pd.resolve_dialect("illustrious", "space"))
        self.assertEqual("canonical", pd.resolve_dialect("anima", "canonical"))

    def test_classify_tag_kinds(self):
        self.assertEqual("score", pd.classify_tag("score_7"))
        self.assertEqual("score", pd.classify_tag("SCORE_9_UP"))
        self.assertEqual("artist", pd.classify_tag("@somebody"))
        self.assertEqual("character", pd.classify_tag("hatsune_miku", CATEGORIES))
        self.assertEqual("artist", pd.classify_tag("somebody_name", CATEGORIES))
        self.assertEqual("copyright", pd.classify_tag("touhou", CATEGORIES))
        self.assertEqual("general", pd.classify_tag("shoes", CATEGORIES))
        self.assertEqual("general", pd.classify_tag("unknown_tag"))
        self.assertEqual("unknown", pd.classify_tag(""))

    def test_trigger_never_converted_even_in_space_dialect(self):
        trigger = "some_custom_trigger_v2"
        self.assertEqual(trigger, pd.format_tag(trigger, "space", "trigger"))
        self.assertEqual(trigger, pd.format_tag(trigger, "space", "general", protect=True))
        self.assertEqual(trigger, pd.format_tag(trigger, "space", "general", protect=True))

    def test_format_tags_batch(self):
        kinds = {"high_heels": "general", "somebody_name": "artist"}
        self.assertEqual(["high heels", "@somebody name"],
                         pd.format_tags(["high_heels", "somebody_name"], "space", kinds))

    def test_empty_input(self):
        self.assertEqual("", pd.format_tag("", "space"))
        self.assertEqual([], pd.format_tags([], "space"))

    def test_convert_payload_shape(self):
        payload = pd.convert(["high_heels", "score_7"], family="anima", dialect="auto",
                             categories=CATEGORIES)
        self.assertEqual("space", payload["resolved"])
        self.assertEqual("anima", payload["family"])
        self.assertIn("results", payload)
        kinds = {item["tag"]: item["kind"] for item in payload["results"]}
        self.assertEqual("general", kinds["high_heels"])
        self.assertEqual("score", kinds["score_7"])
        self.assertEqual("score_7", payload["results"][1]["formatted"])
        self.assertIn("kind_label", payload["results"][0])
        self.assertIn("anima", payload["description"])
        self.assertIn("空格方言", payload["description"])

    def test_describe_mentions_source(self):
        self.assertIn("手动指定", pd.describe("space", "illustrious"))
        self.assertIn("按当前模型", pd.describe("auto", "anima"))


class PanelWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel_source = (PROJECT_DIR / "easy_panel.py").read_text(encoding="utf-8")
        cls.panel_js = (PROJECT_DIR / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")
        cls.dialect_js = (PROJECT_DIR / "web" / "assets" / "js" / "prompt-dialect.js").read_text(encoding="utf-8")
        cls.payload_dialect_js = (PROJECT_DIR / "installers" / "payload" / "web" / "assets" / "js"
                                  / "prompt-dialect.js").read_text(encoding="utf-8")

    def test_endpoint_and_helpers(self):
        self.assertIn('"/api/tag-dialect"', self.panel_source)
        self.assertIn("def format_prompt_tags", self.panel_source)
        self.assertIn("def dialect_categories", self.panel_source)
        self.assertIn("def normalize_dialect_choice", self.panel_source)

    def test_visual_tags_endpoint_applies_dialect(self):
        self.assertIn('payload["resolved_dialect"] = resolved', self.panel_source)
        self.assertIn('payload["dialect_description"] = prompt_dialect.describe', self.panel_source)

    def test_tag_search_insert_goes_through_dialect(self):
        self.assertIn("EasyPanelDialect?EasyPanelDialect.formatTag(item.tag):item.tag", self.panel_js)

    def test_frontend_layer_exposes_same_rules(self):
        for source in (self.dialect_js, self.payload_dialect_js):
            self.assertIn("SPACE_FAMILIES", source)
            self.assertIn("@", source)
            self.assertIn("EasyPanelDialect", source)

    def test_payload_copy_is_identical(self):
        self.assertEqual(self.dialect_js, self.payload_dialect_js)


if __name__ == "__main__":
    unittest.main()
