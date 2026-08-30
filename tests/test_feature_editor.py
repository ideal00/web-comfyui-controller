import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BeginnerFeatureEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "web/assets/css/panel.css").read_text(encoding="utf-8")
        cls.js = (ROOT / "web/assets/js/feature-editor.js").read_text(encoding="utf-8")

    def test_editor_is_accessible_and_beginner_oriented(self):
        for marker in (
            'onclick="openFeatureEditor()"',
            'id="customFeatureList"',
            'id="featureEditorDialog"',
            '三步完成：',
            '导出备份',
            '导入备份',
            '/assets/js/feature-editor.js?v=1',
        ):
            self.assertIn(marker, self.html)

    def test_safe_action_types_and_crud_are_implemented(self):
        for marker in (
            "link:'打开网页'",
            "prompt:'加入提示词'",
            "copy:'复制文字'",
            "jump:'面板跳转'",
            "builtin:'内置操作'",
            "function saveCustomFeature",
            "function deleteCustomFeature",
            "function moveCustomFeature",
            "function exportCustomFeatures",
            "function importCustomFeatures",
            "['http:','https:']",
        ):
            self.assertIn(marker, self.js)
        self.assertNotIn("eval(", self.js)
        self.assertNotIn("new Function", self.js)

    def test_features_are_persistent_but_do_not_modify_default_layout(self):
        self.assertIn("easyPanelCustomFeaturesV1", self.js)
        self.assertIn("localStorage.setItem(CUSTOM_FEATURE_STORAGE", self.js)
        self.assertIn(".custom-feature-card", self.css)
        self.assertIn(".feature-editor-dialog", self.css)
        self.assertNotIn("panel-widths-custom", self.js)

    def test_installer_payload_matches_runtime_files(self):
        pairs = (
            ("index.html", "installers/payload/index.html"),
            ("web/assets/css/panel.css", "installers/payload/web/assets/css/panel.css"),
            ("web/assets/js/feature-editor.js", "installers/payload/web/assets/js/feature-editor.js"),
        )
        for source, payload in pairs:
            self.assertEqual(
                (ROOT / source).read_bytes(),
                (ROOT / payload).read_bytes(),
                f"installer payload differs for {source}",
            )


if __name__ == "__main__":
    unittest.main()
