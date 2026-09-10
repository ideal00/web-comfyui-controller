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


if __name__ == "__main__":
    unittest.main()
