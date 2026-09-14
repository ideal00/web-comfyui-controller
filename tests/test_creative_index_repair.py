"""作品库入库协议测试：文件墓碑、空壳收养、重复引用、文件状态、修复索引。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import easy_panel
from easy_panel_app import creative_index as ci
from easy_panel_app.creative_index import CreativeIndex


def snapshot(snapshot_id: str, *, outputs=None) -> dict:
    body = {
        "model": "anima-base-v1.0.safetensors",
        "quality": "balanced",
        "prompt": "1girl, quiet cafe",
        "negative": "",
        "seed": "1",
        "width": 832,
        "height": 1216,
        "loras": [],
    }
    return {
        "id": snapshot_id,
        "createdAt": 1,
        "schemaVersion": 2,
        "promptId": "prompt-" + snapshot_id[:8],
        "payload": body,
        "source": {"checkpoint": body["model"], "generation": {"seed": "1", "width": 832, "height": 1216}, "loras": []},
        "compiled": {"positive": body["prompt"], "negative": body["negative"]},
        "workflow": {"operation": "panel.generate", "version": "test"},
        "environment": {"panelVersion": "test-panel"},
        "status": "completed",
        "outputs": list(outputs or []),
    }


def record() -> dict:
    return {"positive": "1girl", "negative": "", "loras": [], "model": "m",
            "seed": 7, "width": 832, "height": 1216}


def db_rows(path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    connection = sqlite3.connect(path)
    try:
        return [tuple(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()


class FileTombstoneTests(unittest.TestCase):
    def test_deleted_file_is_not_imported_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "EasyPanel_02001_.png"
            target.write_bytes(b"x" * 64)
            index = CreativeIndex(root / "creative.sqlite3")
            with patch.object(ci, "_comfy_record_from_png", return_value=record()):
                first = index.import_output_images(root)
            self.assertEqual(1, first["imported"])

            generation_id = db_rows(root / "creative.sqlite3", "SELECT generation_id FROM generations")[0][0]
            deleted = index.delete_generation(generation_id, root)
            self.assertTrue(deleted["deleted"])
            keys = db_rows(root / "creative.sqlite3", "SELECT file_key FROM purged_files")
            self.assertEqual([("EasyPanel_02001_.png",)], keys)

            # 文件被重新放回（同名）也不应再被扫描导入。
            target.write_bytes(b"y" * 64)
            with patch.object(ci, "_comfy_record_from_png", return_value=record()):
                second = index.import_output_images(root)
            self.assertEqual(0, second["imported"])
            self.assertEqual(1, second["skipped"])

    def test_purge_marks_file_tombstones(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "EasyPanel_02002_.png").write_bytes(b"x" * 64)
            index = CreativeIndex(root / "creative.sqlite3")
            result = index.upsert_snapshot(
                snapshot("1" * 32, outputs=[{"filename": "EasyPanel_02002_.png", "type": "output"}]),
                output_root=root,
                status="error",
            )
            self.assertTrue(result["generation_id"])
            purged = index.purge_failed_generations(("error",), output_root=root)
            self.assertEqual(1, purged["deleted"])
            keys = db_rows(root / "creative.sqlite3", "SELECT file_key FROM purged_files")
            self.assertEqual([("EasyPanel_02002_.png",)], keys)


class ArtifactIdentityTests(unittest.TestCase):
    def test_import_shell_is_adopted_by_the_real_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "EasyPanel_02003_.png").write_bytes(b"x" * 64)
            index = CreativeIndex(root / "creative.sqlite3")
            with patch.object(ci, "_comfy_record_from_png", return_value=record()):
                index.import_output_images(root)
            self.assertEqual(1, db_rows(root / "creative.sqlite3", "SELECT COUNT(*) FROM generations")[0][0])

            real = index.upsert_snapshot(snapshot("2" * 32), output_root=root, status="queued")
            index.update_snapshot_status(
                "2" * 32,
                status="completed",
                images=[{"filename": "EasyPanel_02003_.png", "type": "output"}],
                output_root=root,
            )
            generations = db_rows(root / "creative.sqlite3",
                                  "SELECT generation_id, operation FROM generations")
            self.assertEqual([(real["generation_id"], "txt2img")], generations)
            artifacts = db_rows(root / "creative.sqlite3",
                                "SELECT generation_id, filename, artifact_role FROM artifacts")
            self.assertEqual([(real["generation_id"], "EasyPanel_02003_.png", "final")], artifacts)

    def test_real_duplicates_are_reported_then_marked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "EasyPanel_02004_.png").write_bytes(b"x" * 64)
            index = CreativeIndex(root / "creative.sqlite3")
            first = index.upsert_snapshot(
                snapshot("3" * 32, outputs=[{"filename": "EasyPanel_02004_.png", "type": "output"}]),
                output_root=root, status="completed",
            )
            second = index.upsert_snapshot(
                snapshot("4" * 32, outputs=[{"filename": "EasyPanel_02004_.png", "type": "output"}]),
                output_root=root, status="completed",
            )
            # 真实作品之间的同名保留两条（历史编号回退场景），先报告为“存活重复”。
            owners = db_rows(root / "creative.sqlite3",
                             "SELECT generation_id FROM artifacts WHERE filename = 'EasyPanel_02004_.png'")
            self.assertEqual({first["generation_id"], second["generation_id"]},
                             {row[0] for row in owners})
            report = index.index_report(root)
            self.assertEqual(1, report["duplicate_total"])
            self.assertEqual(2, report["duplicates"][0]["owners"])

            marked = index.mark_duplicate_artifacts_missing()
            self.assertEqual(1, marked["marked"])
            self.assertEqual(0, index.index_report(root)["duplicate_total"])

    def test_repair_index_marks_real_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "EasyPanel_02005_.png").write_bytes(b"x" * 64)
            index = CreativeIndex(root / "creative.sqlite3")
            real = index.upsert_snapshot(
                snapshot("5" * 32, outputs=[{"filename": "EasyPanel_02005_.png", "type": "output"}]),
                output_root=root, status="completed",
            )
            # 直接用 SQL 构造旧的第二条引用，模拟历史库里的重复。
            with index._write_transaction() as connection:
                connection.execute(
                    """INSERT INTO generations(generation_id, prompt_id, request_id, operation, status,
                                               created_at, updated_at, model, seed, width, height,
                                               input_json, compiled_json, fingerprint)
                       VALUES('old1', '', '', 'txt2img', 'completed', 1, 1, 'm', '7', 832, 1216, '{}', '{}', '')"""
                )
                connection.execute(
                    """INSERT INTO artifacts(artifact_id, generation_id, filename, subfolder,
                                             image_type, artifact_kind, artifact_role, metadata_json, created_at)
                       VALUES('old-art', 'old1', 'EasyPanel_02005_.png', '', 'output', 'output', 'final',
                              '{"exists": true}', 2)"""
                )
            result = index.repair_index(root)
            self.assertEqual(1, result["duplicates"]["marked"])
            self.assertEqual(0, result["after"]["duplicate_total"])
            # 最新记录仍指向真实文件，旧记录被标记缺失（行不删，保留参数）。
            fresh = index.get_generation(real["generation_id"])
            self.assertTrue(fresh["artifacts"][0]["exists"])
            self.assertEqual("EasyPanel_02005_.png", (fresh["preview"] or {}).get("filename"))

    def test_import_records_file_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "EasyPanel_02006_.png").write_bytes(b"x" * 64)
            index = CreativeIndex(root / "creative.sqlite3")
            with patch.object(ci, "_comfy_record_from_png", return_value=record()):
                index.import_output_images(root)
            metadata_json = db_rows(root / "creative.sqlite3",
                                    "SELECT metadata_json FROM artifacts")[0][0]
            self.assertIn('"file_state":"ready"', metadata_json)
            self.assertIn('"file_size":64', metadata_json)


class FileStateReconcileTests(unittest.TestCase):
    def test_prune_refreshes_state_and_reports_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = CreativeIndex(root / "creative.sqlite3")
            (root / "EasyPanel_02007_.png").write_bytes(b"x" * 64)
            (root / "EasyPanel_02008_.png").write_bytes(b"y" * 64)
            index.upsert_snapshot(
                snapshot("6" * 32, outputs=[
                    {"filename": "EasyPanel_02007_.png", "type": "output"},
                    {"filename": "EasyPanel_02008_.png", "type": "output"},
                ]),
                output_root=root, status="completed",
            )
            (root / "EasyPanel_02008_.png").unlink()
            pruned = index.prune_missing_outputs(root)
            self.assertEqual(0, pruned["pruned_generations"])
            self.assertGreaterEqual(pruned["refreshed_artifacts"], 1)
            report = index.index_report(root)
            self.assertEqual(1, report["missing_artifacts"])
            self.assertEqual(1, report["generations"])

    def test_report_counts_orphans_and_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "EasyPanel_02009_.png").write_bytes(b"x" * 64)
            (root / "EasyPanel_02010_.png").write_bytes(b"y" * 64)
            index = CreativeIndex(root / "creative.sqlite3")
            index.upsert_snapshot(
                snapshot("7" * 32, outputs=[{"filename": "EasyPanel_02009_.png", "type": "output"}]),
                output_root=root, status="completed",
            )
            report = index.index_report(root)
            self.assertEqual(1, report["generations"])
            self.assertEqual(1, report["orphan_total"])
            self.assertEqual("EasyPanel_02010_.png", report["orphan_sample"][0])
            self.assertEqual(0, report["duplicate_total"])
            self.assertFalse(report["truncated"])

    def test_repair_index_runs_all_steps(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "EasyPanel_02011_.png").write_bytes(b"x" * 64)
            index = CreativeIndex(root / "creative.sqlite3")
            with patch.object(ci, "_comfy_record_from_png", return_value=record()):
                result = index.repair_index(root)
            self.assertEqual(1, result["imported"]["imported"])
            self.assertEqual(1, result["before"]["orphan_total"])
            self.assertEqual(0, result["after"]["orphan_total"])
            self.assertIn("pruned", result)
            self.assertIn("duplicates", result)


class OutputStabilityTests(unittest.TestCase):
    def test_wait_for_output_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "EasyPanel_02012_.png").write_bytes(b"x" * 64)
            with patch.object(easy_panel, "OUTPUT", root):
                self.assertTrue(easy_panel.wait_for_output_files(
                    [{"filename": "EasyPanel_02012_.png", "type": "output"}], timeout=1.0))
                self.assertFalse(easy_panel.wait_for_output_files(
                    [{"filename": "missing.png", "type": "output"}], timeout=0.3))
                self.assertFalse(easy_panel.wait_for_output_files([], timeout=0.1))

    def test_repair_route_is_wired(self):
        source = (Path(__file__).resolve().parent.parent / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn('"/api/rpg/library/repair"', source)
        self.assertIn("def wait_for_output_files", source)
        library = (Path(__file__).resolve().parent.parent
                   / "web/assets/js/creative-library.js").read_text(encoding="utf-8")
        self.assertIn("creativeLibraryRepair", library)
        self.assertIn("indexReportText", library)
        html = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="creativeLibraryRepair"', html)


if __name__ == "__main__":
    unittest.main()
