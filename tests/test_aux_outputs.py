"""辅助图（首采对照 / 机位快速预览）统一进 EasyPanel_aux：不进作品库，也能正常预览。"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app import creative_index as ci
from easy_panel_app.creative_index import CreativeIndex

SPEC = importlib.util.spec_from_file_location("easy_panel_aux_outputs_test", PROJECT_DIR / "easy_panel.py")
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


def record() -> dict:
    return {"positive": "1girl", "negative": "", "loras": [], "model": "m",
            "seed": 7, "width": 832, "height": 1216}


def db_rows(path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    connection = sqlite3.connect(path)
    try:
        return [tuple(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()


class PrefixRoutingTests(unittest.TestCase):
    def test_auxiliary_payload_goes_to_subfolder(self):
        prefix = easy_panel.generation_filename_prefix(
            {"auxiliaryOutput": True, "filenamePrefix": "camPreview"})
        self.assertEqual("EasyPanel_aux/camPreview", prefix)

    def test_normal_payload_stays_in_root(self):
        self.assertEqual("EasyPanel", easy_panel.generation_filename_prefix({}))
        self.assertEqual("EasyPanel_Transparent",
                         easy_panel.generation_filename_prefix(
                             {"transparentBackground": {"mode": "alpha"}}))

    def test_auxiliary_generation_prefix_is_idempotent(self):
        self.assertEqual("EasyPanel_aux/EasyPanel_base",
                         easy_panel.auxiliary_generation_prefix({}, "_base"))
        self.assertEqual("EasyPanel_aux/camPreview",
                         easy_panel.auxiliary_generation_prefix(
                             {"auxiliaryOutput": True, "filenamePrefix": "camPreview"}))

    def test_safe_output_subfolder_blocks_traversal(self):
        self.assertIsNone(easy_panel.safe_output_subfolder("../outside"))
        self.assertIsNone(easy_panel.safe_output_subfolder(""))
        self.assertIsNone(easy_panel.safe_output_subfolder(".."))
        self.assertIsNotNone(easy_panel.safe_output_subfolder("EasyPanel_aux"))


class AuxSubfolderHelperTests(unittest.TestCase):
    def test_helper_matches_folder_segments_only(self):
        self.assertTrue(ci.is_aux_subfolder("EasyPanel_aux"))
        self.assertTrue(ci.is_aux_subfolder("EasyPanel_aux/nested"))
        self.assertFalse(ci.is_aux_subfolder(""))
        self.assertFalse(ci.is_aux_subfolder("EasyPanel"))
        self.assertFalse(ci.is_aux_subfolder("EasyPanel_aux_backup"))


class ImportSkipTests(unittest.TestCase):
    def test_aux_files_are_not_imported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "EasyPanel_03001_.png").write_bytes(b"x" * 64)
            aux = root / "EasyPanel_aux"
            aux.mkdir()
            (aux / "EasyPanel_03002_.png").write_bytes(b"x" * 64)
            (aux / "camPreview_03003_.png").write_bytes(b"x" * 64)
            index = CreativeIndex(root / "creative.sqlite3")
            with patch.object(ci, "_comfy_record_from_png", return_value=record()):
                result = index.import_output_images(root)
            rows = db_rows(root / "creative.sqlite3",
                           "SELECT filename, subfolder FROM artifacts")
            self.assertEqual(1, result["imported"])
            self.assertEqual([("EasyPanel_03001_.png", "")], rows)

    def test_index_report_ignores_aux_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            aux = root / "EasyPanel_aux"
            aux.mkdir()
            (aux / "EasyPanel_03004_.png").write_bytes(b"x" * 64)
            index = CreativeIndex(root / "creative.sqlite3")
            report = index.index_report(root)
            self.assertEqual(0, report["scanned_files"])
            self.assertEqual(0, report["orphan_total"])


class FrontendWiringTests(unittest.TestCase):
    def test_frontend_sends_subfolder_and_marks_aux(self):
        panel = (PROJECT_DIR / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")
        self.assertIn("&subfolder=", panel)
        workbench = (PROJECT_DIR / "web" / "assets" / "js" / "result-workbench.js").read_text(encoding="utf-8")
        self.assertIn("outputUrl", workbench)
        camera = (PROJECT_DIR / "web" / "assets" / "js" / "camera-control.js").read_text(encoding="utf-8")
        self.assertIn("auxiliaryOutput", camera)

    def test_backend_routes_and_skips_aux(self):
        backend = (PROJECT_DIR / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn("AUX_OUTPUT_SUBFOLDER", backend)
        self.assertIn('data.get("auxiliaryOutput")', backend)
        self.assertIn("auxiliary_generation_prefix(data, \"_base\")", backend)
        self.assertIn("safe_output_subfolder", backend)
        # 骨架预览图也是辅助产物，跟首采对照一样进 aux 子目录。
        self.assertIn('AUX_OUTPUT_SUBFOLDER + "/EasyPanelPose"', backend)
        panel = (PROJECT_DIR / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")
        self.assertIn("'&subfolder='+encodeURIComponent(saved.subfolder)", panel)


if __name__ == "__main__":
    unittest.main()
