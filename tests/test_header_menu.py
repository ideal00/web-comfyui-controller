"""预览栏收纳 + 顶部「⋯ 更多」菜单 + 抽屉「⚙ 界面」菜单契约测试。

需求（2026-09-23）：
  - P1 预览栏：宽高滑块 / 队列 / 采样标签收进「⚙ 预览设置」，图片区域顶到标题栏下方并在可见高度里居中；
  - P1 中等宽度（≤1340px）：框宽 / 功能编辑 / 打开 ComfyUI 不再整体隐藏，统一进「⋯ 更多」；
  - P2 输入框字号：不再占一张卡片，收进抽屉标题栏的「⚠ 界面 / 外观」小菜单。

契约：主面板与 installers/payload 的页面、样式、脚本逐字节一致。
"""

from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGES = [ROOT / "index.html", ROOT / "installers/payload/index.html"]
CSS = ROOT / "web/assets/css/panel.css"
PAYLOAD_CSS = ROOT / "installers/payload/web/assets/css/panel.css"
HEADER_SCRIPT = ROOT / "web/assets/js/header-menu.js"
PAYLOAD_HEADER_SCRIPT = ROOT / "installers/payload/web/assets/js/header-menu.js"

HEADER_ACTIONS = ("🧩 功能编辑", 'class="layout-size-menu"', "打开 ComfyUI ↗")


class PreviewPanelLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = [page.read_text(encoding="utf-8") for page in PAGES]
        cls.css = CSS.read_text(encoding="utf-8")

    def test_preview_settings_hold_the_size_sliders_queue_and_tags(self):
        for page in self.pages:
            self.assertIn('class="preview-settings" id="previewSettingsMenu"', page)
            self.assertIn("⚙ 预览设置", page)
            self.assertIn('class="preview-settings-body"', page)
            body = page[page.index('class="preview-settings-body"') : page.index('id="result"')]
            for marker in ('id="previewWidth"', 'id="previewHeight"', 'id="queue"', 'id="samplerBadge"', 'id="schedulerBadge"'):
                self.assertIn(marker, body, f"{marker} 应放在 ⚙ 预览设置 里")
            # 旧的独立滑块行不再存在
            self.assertNotIn('class="preview-controls"', page)

    def test_image_area_comes_first_and_is_centered(self):
        for page in self.pages:
            preview = page[page.index('class="card preview-card"') : page.index("</aside>", page.index('class="card preview-card"'))]
            self.assertLess(preview.index('id="generationProgress"'), preview.index('id="result"'))
            self.assertLess(preview.index('class="preview-settings"'), preview.index('id="result"'))
            self.assertIn('id="result"', preview)
        for marker in (
            ".preview-card{display:flex;flex-direction:column}",
            ".preview-card>.result{flex:1 1 auto;height:auto;min-height:var(--preview-height);display:grid;place-items:center}",
            "@media(min-width:1341px){.preview-card{height:calc(100vh - 78px)}}",
            ".preview-settings-body{",
        ):
            self.assertIn(marker, self.css)


class HeaderMoreMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = [page.read_text(encoding="utf-8") for page in PAGES]
        cls.css = CSS.read_text(encoding="utf-8")
        cls.source = HEADER_SCRIPT.read_text(encoding="utf-8")

    def test_header_actions_live_in_the_more_menu(self):
        for page in self.pages:
            self.assertIn('class="studio-more" id="studioMoreMenu"', page)
            self.assertIn("⋯ 更多", page)
            body_start = page.index('class="studio-more-body"')
            # 注意：框宽弹层里还有一个内层 </header>，所以切到页头结束（studioLayout 之前）
            body = page[body_start : page.index('<div class="studio-layout"', body_start)]
            for marker in HEADER_ACTIONS:
                self.assertIn(marker, body, f"{marker} 应该在 ⋯ 更多 菜单里")

    def test_actions_are_not_hidden_on_medium_widths(self):
        self.assertNotIn(".studio-header-actions{display:none}", self.css)
        # ≤1340px / ≤820px 两处都要保留操作区（分别给 3 列 / 2 列排版）
        self.assertIn(".studio-header{grid-template-columns:auto minmax(0,1fr) auto}}", self.css)
        self.assertIn(".studio-nav{order:2;grid-column:1/-1}.studio-header-actions{order:1}", self.css)
        for marker in (
            ".studio-more>summary{",
            ".studio-more-body{position:absolute",
            "@media(min-width:1341px){.studio-more>summary{display:none}",
        ):
            self.assertIn(marker, self.css)

    def test_header_menu_script_contract(self):
        for page in self.pages:
            self.assertIn('<script src="/assets/js/header-menu.js?v=1"></script>', page)
        for marker in (
            'const WIDE_QUERY = "(min-width:1341px)"',
            "function sync(menu, wide)",
            'byId("studioMoreMenu")',
            "window.EasyPanelHeaderMenu = testApi;",
            "module.exports = testApi;",
            'typeof document === "undefined"',
        ):
            self.assertIn(marker, self.source)

    def test_payload_copies_are_identical(self):
        self.assertEqual(PAGES[0].read_bytes(), PAGES[1].read_bytes())
        self.assertEqual(CSS.read_bytes(), PAYLOAD_CSS.read_bytes())
        self.assertEqual(HEADER_SCRIPT.read_bytes(), PAYLOAD_HEADER_SCRIPT.read_bytes())


class RailAppearanceMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = [page.read_text(encoding="utf-8") for page in PAGES]
        cls.css = CSS.read_text(encoding="utf-8")

    def test_font_size_moved_into_a_small_menu(self):
        for page in self.pages:
            self.assertIn('class="rail-appearance" id="railAppearanceMenu"', page)
            self.assertIn("⚙ 界面", page)
            self.assertNotIn("railFontSizeFold", page)
            menu = page[page.index('class="rail-appearance"') : page.index('id="customFeatureCard"')]
            for marker in ('id="inputFontSize"', 'id="inputFontSizeValue"', "输入框字号"):
                self.assertIn(marker, menu, f"{marker} 应该在 ⚙ 界面 菜单里")
        for marker in (
            ".rail-appearance>summary{",
            ".rail-appearance-body{position:absolute",
            ".rail-appearance-body .input-size-row{",
        ):
            self.assertIn(marker, self.css)


if __name__ == "__main__":
    unittest.main()
