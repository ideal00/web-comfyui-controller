"""颜色修饰（color-modifier.js）接线契约测试。

需求（2026-09-24，用户方案）：两个选词入口 —— 可视化词条库与「标签搜索与填入」——
在写入 Prompt 的那一刻共用同一个组合函数：blue_hair + 深 dark → dark_blue_hair，
然后再交给 Prompt 方言层（Anima：dark blue hair / Illustrious：dark_blue_hair）。

行为细节由 tests/color_modifier.node-test.cjs 覆盖（真实运行 JS 模块）；
本文件只锁定接线与数据边界：
  - 修饰词只是 UI 状态（localStorage），绝不写进标签库 / 组件存档（canonicalTag 不变）；
  - 控件注入在「标签搜索与填入」标题行，不新增标签数据；
  - 主面板与 installers/payload 的脚本、页面逐字节一致。
"""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGES = [ROOT / "index.html", ROOT / "installers/payload/index.html"]
MODULE = ROOT / "web/assets/js/color-modifier.js"
PAYLOAD_MODULE = ROOT / "installers/payload/web/assets/js/color-modifier.js"
LIBRARY = ROOT / "web/assets/js/visual-tag-library.js"
PAYLOAD_LIBRARY = ROOT / "installers/payload/web/assets/js/visual-tag-library.js"
PANEL_JS = ROOT / "web/assets/js/panel.js"
PAYLOAD_PANEL_JS = ROOT / "installers/payload/web/assets/js/panel.js"
NODE_TEST = ROOT / "tests/color_modifier.node-test.cjs"


class ColorModifierModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MODULE.read_text(encoding="utf-8")
        cls.library = LIBRARY.read_text(encoding="utf-8")
        cls.panel_js = PANEL_JS.read_text(encoding="utf-8")
        cls.pages = [page.read_text(encoding="utf-8") for page in PAGES]

    def test_module_exposes_composer_and_ui_state(self):
        for marker in ("easyPanelColorModifierV1", "window.EasyPanelColorModifier",
                       "function compose(tag, modifier)", "function composeTags(",
                       "MODIFIERS", "COLOR_WORDS", "COLORABLE_ATTRIBUTES",
                       'id="colorModifier"', "颜色修饰", ".prompt-tag-search .field-title"):
            self.assertIn(marker, self.source, marker)

    def test_modifier_table_matches_the_agreed_vocabulary(self):
        """明度/深浅 + 饱和度两组的 10 个修饰词，与用户定稿词表一致。"""
        for key in ("light", "dark", "pale", "deep", "bright",
                    "vivid", "muted", "soft", "desaturated", "rich"):
            self.assertIn(f'{{ key: "{key}"', self.source, key)

    def test_only_color_tags_are_touched(self):
        """同形陷阱必须在模块里显式挡掉（blue_archive / ice_cream / 角色限定名）。"""
        self.assertIn('if (tag.charAt(0) === "@") return true;', self.source)
        self.assertIn('if (tag.indexOf("(") >= 0', self.source)
        self.assertIn("可着色属性", self.source)
        self.assertIn("ice_cream", self.source)
        self.assertIn("blue_archive", self.source)

    def test_node_behaviour_suite_exists(self):
        node = NODE_TEST.read_text(encoding="utf-8")
        self.assertIn("modifier.compose('blue_hair', 'dark')", node)
        self.assertIn("modifier.compose('dark_blue_hair', 'dark')", node)
        self.assertIn("modifier.compose('blue hair', 'dark')", node)
        self.assertIn("'ice_cream'", node)
        self.assertIn("'long_hair'", node)
        self.assertIn("dialect.formatTag(composed, { dialect: 'space' })", node)


class ColorModifierWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = LIBRARY.read_text(encoding="utf-8")
        cls.panel_js = PANEL_JS.read_text(encoding="utf-8")
        cls.pages = [page.read_text(encoding="utf-8") for page in PAGES]

    def test_visual_library_composes_before_dialect(self):
        """可视化词条库的唯一写入出口 addTag 必须先做颜色修饰，再过方言。"""
        self.assertIn("function composeColorTag(tag)", self.library)
        self.assertIn("const composed = composeColorTag(tag);", self.library)
        self.assertIn("const formatted = formatTag(composed, kind);", self.library)
        self.assertEqual(1, self.library.count("window.appendEnglish("))

    def test_card_preview_and_live_rerender(self):
        """卡片上的「写入：」跟着颜色修饰走；换修饰词时重画卡片（不重新请求数据）。"""
        self.assertIn("composeColorTag(entry.formatted || formatTag(entry.tag, entry.kind))", self.library)
        self.assertIn("rerender: () => {", self.library)
        self.assertIn("if (overlay && !overlay.hidden) renderGrid();", self.library)
        self.assertIn("library.rerender()", MODULE.read_text(encoding="utf-8"))

    def test_visual_library_batch_and_hires_paths_compose(self):
        """多选批量、复制、二采补充词三条支路同样经过组合函数。"""
        self.assertIn("formatTag(composeColorTag(item.tag), item.kind)", self.library)
        self.assertGreaterEqual(self.library.count("composeColorTag(item.tag)"), 3)

    def test_library_storage_keeps_canonical_tags(self):
        """修饰词不能进存档：组件仍存 Danbooru 原形（canonicalTag 不过方言、不过修饰）。"""
        self.assertIn("const tags = state.selected.map((item) => canonicalTag(item.tag))", self.library)
        self.assertNotIn("canonicalTag(composeColorTag(", self.library)

    def test_tag_search_insert_composes_then_formats(self):
        """「标签搜索与填入」点候选：compose → formatTag → appendEnglish。"""
        self.assertIn("EasyPanelColorModifier?EasyPanelColorModifier.compose(item.tag)", self.panel_js)
        self.assertIn("EasyPanelDialect?EasyPanelDialect.formatTag(composed):composed", self.panel_js)
        self.assertIn("esc(composed!==item.tag?item.tag+' → '+tag:tag)", self.panel_js)

    def test_scripts_loaded_in_both_pages_before_panel(self):
        for page in self.pages:
            self.assertIn("/assets/js/color-modifier.js?v=", page)
            self.assertLess(page.index("color-modifier.js"), page.index("panel.js?v="))
            self.assertLess(page.index("prompt-dialect.js"), page.index("color-modifier.js"))

    def test_payload_copies_are_identical(self):
        for runtime, payload in ((MODULE, PAYLOAD_MODULE), (LIBRARY, PAYLOAD_LIBRARY),
                                 (PANEL_JS, PAYLOAD_PANEL_JS)):
            self.assertEqual(runtime.read_bytes(), payload.read_bytes(), runtime.name)

    def test_panel_js_cache_busts_in_both_pages(self):
        versions = []
        for page in self.pages:
            match = re.search(r"panel\.js\?v=(\d+)", page)
            self.assertIsNotNone(match)
            versions.append(match.group(1))
        self.assertEqual(versions[0], versions[1])


if __name__ == "__main__":
    unittest.main()
