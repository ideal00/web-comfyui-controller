import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class LoraMemoOverwriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "web/assets/js/panel.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "web/assets/css/panel.css").read_text(encoding="utf-8")

    def test_overwrite_mode_is_visible_and_enabled_by_default(self):
        self.assertIn('id="memoOutfitOverwriteMode" type="checkbox" checked', self.html)
        self.assertIn('onchange="toggleMemoOutfitOverwriteMode()"', self.html)
        self.assertIn('id="memoOutfitModeInfo"', self.html)
        self.assertIn(".memo-apply-mode{display:flex", self.css)

    def test_mode_is_persistent_and_defaults_to_overwrite(self):
        self.assertIn("easyPanelMemoOutfitOverwriteV1", self.js)
        self.assertIn("let memoOutfitOverwriteMode=true", self.js)
        self.assertIn("function loadMemoOutfitMode()", self.js)
        self.assertIn("localStorage.setItem(MEMO_OUTFIT_OVERWRITE_STORAGE", self.js)

    def test_overwrite_only_clears_the_same_main_class_across_loras(self):
        self.assertIn("const OUTFIT_MAIN_CLASSES=", self.js)
        self.assertIn("function replaceOutfitMainClass(item)", self.js)
        self.assertIn("outfitMainClass(entry.item)===mainClass", self.js)
        self.assertIn("outfitMainClass(entry.item)!==mainClass", self.js)
        self.assertIn("memoOutfitOverwriteMode?replaceOutfitMainClass(item):insertOutfitSections(item)", self.js)

    def test_editor_derives_one_main_class_from_the_first_populated_section(self):
        self.assertIn("memoOutfitMainClass", self.js)
        self.assertIn("const OUTFIT_SECTION_MAIN_CLASS=", self.js)
        self.assertIn("OUTFIT_SECTIONS.find(sec=>outfitSectionValue(item,sec))", self.js)
        self.assertIn("out.main_class=outfitMainClass(out)", self.js)
        self.assertIn("syncMemoOutfitMainClass", self.js)
        self.assertIn("同主类覆盖模式", self.html)
        for key in ("character", "appearance", "clothing", "pose", "composition", "scene", "lighting", "style", "coloring", "negative", "other"):
            self.assertIn("key:'%s'" % key, self.js)

    def test_every_section_is_supported_including_other(self):
        for key in (
            "subject", "appearance", "clothing", "pose", "composition", "scene",
            "lighting", "style", "coloring", "negative", "other",
        ):
            self.assertIn("key:'%s'" % key, self.js)
        self.assertIn("{key:'other',legacy:['manual'],field:'prompt',label:'其他标签'}", self.js)


if __name__ == "__main__":
    unittest.main()
