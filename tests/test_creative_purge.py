"""一键清理失败 / 取消作品的单元测试。"""

import gc
import tempfile
import unittest
from pathlib import Path

from easy_panel_app.creative_index import CreativeIndex


def add_generation(index, generation_id: str, status: str, filename: str = "", *, group: str = ""):
    with index._write_transaction() as connection:
        connection.execute(
            "INSERT INTO generations(generation_id, status, created_at, updated_at, operation) "
            "VALUES(?, ?, 1700000000000, 1700000000000, 'txt2img')",
            (generation_id, status),
        )
        if filename:
            connection.execute(
                "INSERT INTO artifacts(artifact_id, generation_id, filename, subfolder, "
                "image_type, artifact_kind, created_at) VALUES(?, ?, ?, '', 'output', 'output', ?)",
                (f"artifact-{generation_id[:8]}", generation_id, filename, 1700000000000),
            )
        if group:
            connection.execute(
                "INSERT OR IGNORE INTO favorite_groups(group_id, name, created_at, updated_at) "
                "VALUES(?, ?, 1, 1)", (group, f"组-{group}"))
            connection.execute(
                "INSERT INTO generation_favorite_groups(group_id, generation_id, created_at) "
                "VALUES(?, ?, 1)", (group, generation_id))


class PurgeFailedGenerationsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.index = CreativeIndex(self.root / "index.sqlite3")

    def tearDown(self):
        gc.collect()
        try:
            self.temp.cleanup()
        except PermissionError:
            pass  # Windows 偶尔会短暂占用 sqlite 文件，不影响测试结论

    def _touch(self, name: str) -> Path:
        path = self.output / name
        path.write_bytes(b"png")
        return path

    def test_purge_removes_error_and_cancelled_only(self):
        self._touch("EasyPanel_00001_.png")
        self._touch("EasyPanel_00002_.png")
        add_generation(self.index, "e" * 32, "error", "EasyPanel_00001_.png")
        add_generation(self.index, "c" * 32, "cancelled", "EasyPanel_00002_.png")
        add_generation(self.index, "k" * 32, "completed", "EasyPanel_00003_.png")
        add_generation(self.index, "f" * 32, "completed", "EasyPanel_00004_.png", group="g1")

        preview = self.index.purge_failed_generations(["error", "cancelled"], output_root=self.output,
                                                      dry_run=True)
        self.assertEqual(preview["deleted"], 2)
        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["removed_files"], 2)

        result = self.index.purge_failed_generations(["error", "cancelled"], output_root=self.output)
        self.assertEqual(result["deleted"], 2)
        self.assertEqual(result["removed_files"], 2)
        self.assertFalse((self.output / "EasyPanel_00001_.png").exists())
        self.assertFalse((self.output / "EasyPanel_00002_.png").exists())

        connection = self.index._connect()
        try:
            remaining = {row[0] for row in connection.execute(
                "SELECT generation_id FROM generations")}
        finally:
            connection.close()
        self.assertEqual(remaining, {"k" * 32, "f" * 32})

    def test_file_shared_with_favorite_is_kept(self):
        self._touch("EasyPanel_00010_.png")
        add_generation(self.index, "e" * 32, "error", "EasyPanel_00010_.png")
        add_generation(self.index, "f" * 32, "completed", "EasyPanel_00010_.png", group="g2")

        result = self.index.purge_failed_generations(["error"], output_root=self.output)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["removed_files"], 0)
        self.assertGreaterEqual(result["protected_files"], 1)
        self.assertTrue((self.output / "EasyPanel_00010_.png").exists())

    def test_empty_statuses_is_rejected(self):
        with self.assertRaises(Exception):
            self.index.purge_failed_generations([], output_root=self.output)

    def test_delete_and_purge_write_tombstones(self):
        self._touch("EasyPanel_00020_.png")
        add_generation(self.index, "e" * 32, "error", "EasyPanel_00020_.png")
        add_generation(self.index, "c" * 32, "cancelled")
        self.index.delete_generation("e" * 32, self.output)
        self.index.purge_failed_generations(["cancelled"], output_root=self.output)
        connection = self.index._connect()
        try:
            tombstones = {row[0] for row in connection.execute(
                "SELECT generation_id FROM purged_generations")}
        finally:
            connection.close()
        self.assertEqual(tombstones, {"e" * 32, "c" * 32})

    def test_tombstone_blocks_legacy_reimport(self):
        snapshot = {"snapshotId": "s-1", "promptId": "p-1", "createdAt": 1700000000000,
                    "model": "demo.safetensors"}
        first = self.index.upsert_snapshot(snapshot, status="error")
        self.assertTrue(first["created"])
        self.index.delete_generation(first["generation_id"], self.output)

        again = self.index.upsert_snapshot(snapshot, status="error")
        self.assertTrue(again.get("purged"))
        self.assertFalse(again["created"])
        connection = self.index._connect()
        try:
            remaining = connection.execute("SELECT COUNT(*) FROM generations").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(remaining, 0)

    def test_purge_unfavorited_keeps_only_favorites(self):
        self._touch("EasyPanel_00030_.png")
        self._touch("EasyPanel_00031_.png")
        add_generation(self.index, "f" * 32, "completed", "EasyPanel_00030_.png", group="g9")
        add_generation(self.index, "k" * 32, "completed", "EasyPanel_00031_.png")
        preview = self.index.purge_unfavorited(output_root=self.output, dry_run=True)
        self.assertEqual(preview["deleted"], 1)
        result = self.index.purge_unfavorited(output_root=self.output)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["removed_files"], 1)
        connection = self.index._connect()
        try:
            remaining = [row[0] for row in connection.execute(
                "SELECT generation_id FROM generations")]
        finally:
            connection.close()
        self.assertEqual(remaining, ["f" * 32])

    def test_missing_status_returns_zero(self):
        add_generation(self.index, "k" * 32, "completed")
        result = self.index.purge_failed_generations(["error"], output_root=self.output)
        self.assertEqual(result["deleted"], 0)

    def test_wiring_exists(self):
        panel = (Path(__file__).resolve().parents[1] / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn('"/api/rpg/library/purge"', panel)
        self.assertIn("purge_failed_generations", panel)
        self.assertIn("purge_unfavorited", panel)
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="creativeLibraryPurgeFailed"', html)
        script = (Path(__file__).resolve().parents[1] / "web" / "assets" / "js"
                  / "creative-library.js").read_text(encoding="utf-8")
        self.assertIn("purgeFailedLibrary", script)


if __name__ == "__main__":
    unittest.main()
