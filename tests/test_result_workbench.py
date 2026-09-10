from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ResultWorkbenchTests(unittest.TestCase):
    """The result workbench keeps a finished generation editable."""

    def test_runtime_and_installer_payload_match(self):
        self.assertEqual(
            (ROOT / "web/assets/js/result-workbench.js").read_bytes(),
            (ROOT / "installers/payload/web/assets/js/result-workbench.js").read_bytes(),
        )

    def test_both_pages_load_it_after_the_snapshot_flow(self):
        for page in (ROOT / "index.html", ROOT / "installers/payload/index.html"):
            with self.subTest(page=page.as_posix()):
                html = page.read_text(encoding="utf-8")
                self.assertIn("/assets/js/result-workbench.js?v=", html)
                self.assertLess(html.index("snapshot-flow.js?v="),
                                html.index("result-workbench.js?v="))

    def test_actions_cover_single_variable_variations(self):
        script = (ROOT / "web/assets/js/result-workbench.js").read_text(encoding="utf-8")
        for marker in ("继续编辑", "只换 Seed", "重复生成", "复制参数",
                       "继续二采", "转整图重绘",
                       "promptClothing", "promptScene", "promptPose", "promptExpression",
                       "renderGeneratedImages", "hiresPositive", "illustriousMode",
                       "img2imgOutput", "setStudioCreationTab"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

    def test_compare_dialog_pairs_first_and_second_pass(self):
        script = (ROOT / "web/assets/js/result-workbench.js").read_text(encoding="utf-8")
        for marker in ("HIRES_BASE_MARKER", "_base_", "首采 / 二采对照",
                       "构图保持", "基于二采参数与补充词的规则判断",
                       "isBaseImage", "lastBaseImages"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

    def test_hires_no_longer_saves_the_first_pass_image(self):
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")
        # 二采只保留成品：不再有 _base 的 SaveImage，但前缀选择器仍保留。
        self.assertNotIn('generation_filename_prefix(data, "_base")', backend)
        self.assertIn("def generation_filename_prefix", backend)
        self.assertIn("不再另存首采原图", backend)
        # 旧的 _base 文件仍要被手机端结果列表过滤掉，所以标记保留。
        mobile = (ROOT / "easy_panel_app/rpg_api.py").read_text(encoding="utf-8")
        self.assertIn('HIRES_BASE_MARKER = "_base_"', mobile)

    def test_library_uses_one_representative_image(self):
        index = (ROOT / "easy_panel_app/creative_index.py").read_text(encoding="utf-8")
        for marker in ("HIRES_BASE_FILE_MARKER", "def _preview_artifact_row",
                       "primary_artifact_id", "\"preview\": self._artifact_from_row"):
            with self.subTest(marker=marker):
                self.assertIn(marker, index)
        desktop = (ROOT / "web/assets/js/creative-library.js").read_text(encoding="utf-8")
        self.assertIn("previewArtifactOf", desktop)
        self.assertIn("首采对照，非成品", desktop)
        android_client = (ROOT / "android-client/src/components/EasyPanelMobileApp.tsx").read_text(encoding="utf-8")
        self.assertIn("isHiresBaseArtifact", android_client)
        self.assertIn("detail.preview?.artifact_id", android_client)
        types = (ROOT / "android-client/src/services/easyPanelLibrary.ts").read_text(encoding="utf-8")
        self.assertIn("preview?: EasyPanelGenerationArtifact | null", types)

    def test_workbench_wraps_payload_and_result_rendering(self):
        script = (ROOT / "web/assets/js/result-workbench.js").read_text(encoding="utf-8")
        self.assertIn("window.payload", script)
        self.assertIn("__workbenchWrapped", script)
        self.assertIn("resultWorkbench", script)


if __name__ == "__main__":
    unittest.main()
