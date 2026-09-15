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


if __name__ == "__main__":
    unittest.main()
