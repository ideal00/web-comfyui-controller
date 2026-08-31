from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from easy_panel_app.creative_index import CreativeIndex
from tools.migrate_creative_index_ids import (
    apply_migration,
    build_migration_plan,
    rollback_database,
)


def source_snapshot(snapshot_id: str, prompt_id: str, output: str) -> dict:
    return {
        "id": snapshot_id,
        "createdAt": 1,
        "schemaVersion": 2,
        "promptId": prompt_id,
        "payload": {
            "model": "migration-model.safetensors",
            "prompt": f"prompt-{prompt_id}",
            "seed": "7",
            "width": 832,
            "height": 1216,
            "loras": [{"name": "migration.safetensors", "weight": 0.8}],
        },
        "source": {"checkpoint": "migration-model.safetensors"},
        "compiled": {"positive": f"prompt-{prompt_id}"},
        "workflow": {"operation": "panel.generate", "version": "test"},
        "environment": {"panelVersion": "test"},
        "outputs": [output],
    }


class CreativeIndexMigrationTests(unittest.TestCase):
    def test_runtime_and_installer_payload_include_the_rebuild_tool_and_index(self):
        root = Path(__file__).resolve().parents[1]
        pairs = (
            (root / "easy_panel_app" / "creative_index.py",
             root / "installers" / "payload" / "easy_panel_app" / "creative_index.py"),
            (root / "easy_panel.py", root / "installers" / "payload" / "easy_panel.py"),
            (root / "web" / "assets" / "js" / "creative-library.js",
             root / "installers" / "payload" / "web" / "assets" / "js" / "creative-library.js"),
            (root / "tools" / "rebuild_creative_index.py",
             root / "installers" / "payload" / "tools" / "rebuild_creative_index.py"),
            (root / "tools" / "migrate_creative_index_ids.py",
             root / "installers" / "payload" / "tools" / "migrate_creative_index_ids.py"),
        )
        for runtime, payload in pairs:
            self.assertTrue(payload.is_file(), payload)
            self.assertEqual(runtime.read_bytes(), payload.read_bytes(), runtime.as_posix())

    def test_dry_run_maps_random_ids_and_apply_preserves_foreign_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "parent.png").write_bytes(b"parent")
            (root / "child.png").write_bytes(b"child")
            database = root / "creative.sqlite3"
            index = CreativeIndex(database)
            parent = index.upsert_snapshot(
                source_snapshot("a" * 32, "prompt-parent", "parent.png"),
                output_root=root,
            )
            child = index.upsert_snapshot(
                source_snapshot("b" * 32, "prompt-child", "child.png"),
                output_root=root,
            )
            parent_artifact = index.get_generation(parent["generation_id"])["artifacts"][0]["artifact_id"]
            child_artifact = index.get_generation(child["generation_id"])["artifacts"][0]["artifact_id"]
            self.assertTrue(index.add_derivation(
                parent_generation_id=parent["generation_id"],
                child_generation_id=child["generation_id"],
                parent_artifact_id=parent_artifact,
                child_artifact_id=child_artifact,
                operation="img2img",
            ))

            connection = sqlite3.connect(database)
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(
                "UPDATE generations SET generation_id = 'old-parent' WHERE generation_id = ?",
                (parent["generation_id"],),
            )
            connection.execute(
                "UPDATE generations SET generation_id = 'old-child' WHERE generation_id = ?",
                (child["generation_id"],),
            )
            connection.execute(
                "UPDATE artifacts SET artifact_id = 'old-parent-artifact', generation_id = 'old-parent' WHERE artifact_id = ?",
                (parent_artifact,),
            )
            connection.execute(
                "UPDATE artifacts SET artifact_id = 'old-child-artifact', generation_id = 'old-child' WHERE artifact_id = ?",
                (child_artifact,),
            )
            connection.execute(
                """UPDATE derivations SET parent_generation_id = 'old-parent', child_generation_id = 'old-child',
                   parent_artifact_id = 'old-parent-artifact', child_artifact_id = 'old-child-artifact'""",
            )
            connection.execute("UPDATE generation_loras SET generation_id = 'old-parent' WHERE generation_id = ?", (parent["generation_id"],))
            connection.execute("UPDATE generation_loras SET generation_id = 'old-child' WHERE generation_id = ?", (child["generation_id"],))
            connection.commit()
            connection.close()

            before = hashlib.sha256(database.read_bytes()).hexdigest()
            plan = build_migration_plan(database)
            self.assertTrue(plan["safe_to_apply"])
            self.assertEqual(2, len(plan["generation_mapping"]))
            self.assertEqual({"old-parent", "old-child"}, {
                item["old"] for item in plan["generation_mapping"]
            })
            self.assertEqual(2, len(plan["artifact_mapping"]))
            self.assertEqual(before, hashlib.sha256(database.read_bytes()).hexdigest())

            backup = root / "backup.sqlite3"
            applied = apply_migration(database, backup_path=backup)
            self.assertTrue(backup.is_file())
            self.assertEqual(2, len(applied["generation_mapping"]))
            connection = sqlite3.connect(database)
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))
            generation_ids = {row[0] for row in connection.execute("SELECT generation_id FROM generations")}
            artifact_ids = {row[0] for row in connection.execute("SELECT artifact_id FROM artifacts")}
            self.assertNotIn("old-parent", generation_ids)
            self.assertNotIn("old-parent-artifact", artifact_ids)
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM derivations").fetchone()[0])
            connection.close()

            rolled_back = rollback_database(database, backup)
            self.assertEqual("rollback", rolled_back["mode"])
            connection = sqlite3.connect(database)
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))
            self.assertEqual({"old-parent", "old-child"}, {
                row[0] for row in connection.execute("SELECT generation_id FROM generations")
            })
            self.assertEqual({"old-parent-artifact", "old-child-artifact"}, {
                row[0] for row in connection.execute("SELECT artifact_id FROM artifacts")
            })
            connection.close()

    def test_dry_run_rejects_stable_generation_collision(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "creative.sqlite3"
            index = CreativeIndex(database)
            first = index.upsert_snapshot(source_snapshot("a" * 32, "", "first.png"))
            second = index.upsert_snapshot(source_snapshot("b" * 32, "", "first.png"))
            self.assertNotEqual(first["generation_id"], second["generation_id"])

            connection = sqlite3.connect(database)
            connection.execute("PRAGMA foreign_keys = OFF")
            snapshot_json = connection.execute(
                "SELECT snapshot_json FROM generations WHERE generation_id = ?",
                (first["generation_id"],),
            ).fetchone()[0]
            connection.execute(
                "UPDATE generations SET snapshot_id = NULL, prompt_id = '', request_id = '', snapshot_json = ?",
                (snapshot_json,),
            )
            connection.commit()
            connection.close()
            plan = build_migration_plan(database)
            self.assertFalse(plan["safe_to_apply"])
            self.assertTrue(any(item["kind"] == "generation_id_collision" for item in plan["conflicts"]))


if __name__ == "__main__":
    unittest.main()
