import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class StudioLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "web/assets/css/panel.css").read_text(encoding="utf-8")
        cls.javascript = (ROOT / "web/assets/js/panel.js").read_text(encoding="utf-8")

    def test_desktop_workbench_regions_exist(self):
        for marker in (
            'class="studio-header"',
            'id="studioLayout"',
            'class="studio-rail studio-left"',
            'id="generationSection"',
            'id="loraSection"',
            'class="card preview-card"',
        ):
            self.assertIn(marker, self.html)

    def test_navigation_preserves_existing_tools(self):
        for action in (
            "jumpToPanelSection('promptComposer')",
            "jumpToPanelSection('generationSection')",
            "openHandWorkbench()",
            "jumpToPanelSection('loraSection')",
        ):
            self.assertIn(action, self.html)

    def test_four_column_desktop_layout_has_responsive_fallbacks(self):
        self.assertIn("--left-panel-width:260px", self.css)
        self.assertIn("grid-template-columns:minmax(230px,260px) minmax(500px,1fr) minmax(280px,340px) minmax(280px,320px)", self.css)
        self.assertIn(".studio-layout.panel-widths-custom", self.css)
        self.assertIn(".studio-generation{grid-column:2", self.css)
        self.assertIn(".preview-card{grid-column:3", self.css)
        self.assertIn(".studio-lora{grid-column:4", self.css)
        self.assertIn("@media(max-width:1340px)", self.css)
        self.assertIn("@media(max-width:1100px)", self.css)
        self.assertIn("@media(max-width:820px)", self.css)

    def test_each_major_panel_has_a_persistent_width_control(self):
        for marker in (
            'class="layout-size-menu"',
            'id="panelWidthLeft"',
            'id="panelWidthGeneration"',
            'id="panelWidthPreview"',
            'id="panelWidthLora"',
            'onclick="resetPanelWidths(event)"',
        ):
            self.assertIn(marker, self.html)
        for marker in (
            "function applyPanelWidths",
            "function loadPanelWidths",
            "function resetPanelWidths",
            "easyPanelPanelWidths",
            "loadPanelWidths();",
            "saved.version!==2",
            "classList.remove('panel-widths-custom')",
        ):
            self.assertIn(marker, self.javascript)

    def test_large_portrait_is_the_default_generation_size(self):
        self.assertIn("function loadDefaultGenerationSize", self.javascript)
        self.assertIn("preferred='864x1152'", self.javascript)
        self.assertIn("loadDefaultGenerationSize();", self.javascript)
        self.assertIn("String($('size')?.value||'864x1152')", self.javascript)


class SizePresetTests(unittest.TestCase):
    """比例档位：9:16 / 16:9 / 21:9 的新尺寸在电脑端与手机端保持一致。"""

    @classmethod
    def setUpClass(cls):
        cls.pages = [
            (ROOT / "index.html").read_text(encoding="utf-8"),
            (ROOT / "installers/payload/index.html").read_text(encoding="utf-8"),
        ]
        cls.mobile = (ROOT / "android-client/src/components/EasyPanelMobileApp.tsx").read_text(encoding="utf-8")

    def test_portrait_9_16_sizes_available(self):
        for html in self.pages:
            self.assertIn('value="832x1472">长竖图 832 × 1472（9:16）', html)

    def test_landscape_16_9_and_21_9_sizes_available(self):
        for html in self.pages:
            self.assertIn('value="1472x832">宽幅横图 1472 × 832（16:9）', html)
            self.assertIn('value="1344x576">宽银幕横图 1344 × 576（21:9）', html)

    def test_mobile_size_presets_keep_the_same_ratios(self):
        for marker in (
            "{ label: '9:16 长竖', width: 832, height: 1472 }",
            "{ label: '16:9 宽幅', width: 1472, height: 832 }",
            "{ label: '21:9', width: 1344, height: 576 }",
        ):
            self.assertIn(marker, self.mobile)

    def test_new_sizes_stay_inside_backend_limits(self):
        # 8 对齐 + Anima 长边上限 1536（1472/1344 都放得下），避免选了又被后端钳制。
        for width, height in ((832, 1472), (1472, 832), (1344, 576)):
            self.assertEqual(0, width % 8, width)
            self.assertEqual(0, height % 8, height)
            self.assertLessEqual(max(width, height), 1536)


class StudioHeaderDensityTests(unittest.TestCase):
    """创作区头部按钮横向排版 + Anima 提示词分层默认折叠。"""

    @classmethod
    def setUpClass(cls):
        cls.pages = [
            (ROOT / "index.html").read_text(encoding="utf-8"),
            (ROOT / "installers/payload/index.html").read_text(encoding="utf-8"),
        ]
        cls.css = (ROOT / "web/assets/css/panel.css").read_text(encoding="utf-8")
        cls.payload_css = (ROOT / "installers/payload/web/assets/css/panel.css").read_text(encoding="utf-8")

    def test_header_actions_are_horizontal(self):
        # `.studio-panel-heading>div` 的 grid 会盖掉单类选择器，必须用更高特异性压成一行。
        self.assertIn(
            ".studio-panel-heading>.studio-heading-actions{display:flex;flex-flow:row nowrap",
            self.css,
        )
        self.assertIn(
            ".studio-heading-actions button{min-height:36px;padding:7px 14px;white-space:nowrap}",
            self.css,
        )
        for html in self.pages:
            for marker in (
                '<div class="studio-heading-actions">',
                '<button class="studio-enqueue-top" type="button" onclick="enqueueJob()">＋ 加入队列</button>',
                '<button class="studio-generate-top" type="button" onclick="quickGenerateImage()">生成图片</button>',
            ):
                self.assertIn(marker, html)

    def test_narrow_screens_may_wrap_header_actions(self):
        self.assertIn(
            "@media(max-width:700px){.studio-main-heading{align-items:flex-start}"
            ".studio-panel-heading>.studio-heading-actions{flex-wrap:wrap",
            self.css,
        )

    def test_anima_layer_panel_is_a_collapsible_details_block(self):
        for html in self.pages:
            self.assertNotIn('<section class="memo" id="animaPromptPanel"', html)
            self.assertIn(
                '<details class="memo anima-layer-panel" id="animaPromptPanel" style="display:none">',
                html,
            )
            self.assertIn('<summary class="anima-layer-summary">', html)
            self.assertIn('<h3>Anima 提示词分层</h3>', html)
            self.assertIn('<span id="animaTagInfo" class="small">', html)
            self.assertIn('<span class="anima-layer-toggle"></span></summary>', html)
            self.assertIn(
                '<div id="animaPreflight" class="small" style="margin-top:8px"></div></details>',
                html,
            )

    def test_anima_layer_panel_defaults_to_closed(self):
        # 默认折叠靠 details 不带 open 属性，展开状态由浏览器维护。
        for html in self.pages:
            start = html.index('id="animaPromptPanel"')
            tag = html[html.rindex("<", 0, start): html.index(">", start) + 1]
            self.assertNotIn(" open", tag)

    def test_anima_layer_summary_styles_exist_in_both_copies(self):
        for marker in (
            ".anima-layer-panel>summary{",
            ".anima-layer-panel[open]>summary{",
            ".anima-layer-panel>summary::marker{",
            ".anima-layer-toggle::after{content:'点击展开填写'}",
            ".anima-layer-panel[open] .anima-layer-toggle::after{content:'点击收起'}",
        ):
            self.assertIn(marker, self.css)
            self.assertIn(marker, self.payload_css)

    def test_layer_child_panels_are_appended_inside_the_details(self):
        # 机位控制 / Anima 分层修正 / 二采面板插入到面板末尾；改成插到开头会把 summary 顶掉。
        for name in ("camera-control.js", "anima-refine.js", "anima-highres.js"):
            source = (ROOT / "web/assets/js" / name).read_text(encoding="utf-8")
            self.assertIn('byId("animaPromptPanel")', source)
            self.assertIn("anchor.appendChild(block);", source)


if __name__ == "__main__":
    unittest.main()
