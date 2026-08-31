from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easy_panel_app.creative_index import CreativeIndex


def snapshot(snapshot_id: str, *, created_at: int = 1, operation: str = "", status: str = "queued",
             prompt_id: str = "", request_id: str = "", outputs=None, seed: str = "42") -> dict:
    payload = {
        "model": "library-model.safetensors",
        "quality": "balanced",
        "prompt": "1girl, quiet cafe",
        "negative": "bad anatomy",
        "seed": seed,
        "width": 832,
        "height": 1216,
        "loras": [{"name": "character.safetensors", "weight": 0.8, "role": "character", "trigger": "hero"}],
        "token": "must-not-enter-index",
    }
    return {
        "id": snapshot_id,
        "createdAt": created_at,
        "schemaVersion": 2,
        "promptId": prompt_id,
        "requestId": request_id,
        "payload": payload,
        "source": {
            "checkpoint": payload["model"],
            "generation": {"seed": seed, "width": 832, "height": 1216, "quality": "balanced"},
            "loras": payload["loras"],
        },
        "compiled": {"positive": payload["prompt"], "negative": payload["negative"]},
        "workflow": {"operation": operation or "panel.generate", "version": "test"},
        "environment": {"panelVersion": "test-panel"},
        "status": status,
        "outputs": list(outputs or []),
    }


class CreativeIndexTests(unittest.TestCase):
    def test_empty_and_partial_databases_upgrade_to_v1(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "creative.sqlite3"
            index = CreativeIndex(path)
            self.assertEqual(1, index.initialize())

            connection = sqlite3.connect(path)
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            connection.close()
            self.assertTrue({"schema_meta", "generations", "artifacts", "derivations", "generation_loras"} <= tables)

            partial = Path(folder) / "partial.sqlite3"
            connection = sqlite3.connect(partial)
            connection.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO schema_meta VALUES ('schema_version', '0')")
            connection.execute("CREATE TABLE generations (generation_id TEXT PRIMARY KEY)")
            connection.commit()
            connection.close()
            self.assertEqual(1, CreativeIndex(partial).initialize())
            connection = sqlite3.connect(partial)
            generation_columns = {row[1] for row in connection.execute("PRAGMA table_info(generations)")}
            version = connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
            connection.close()
            self.assertIn("snapshot_json", generation_columns)
            self.assertEqual("1", version)

    def test_upsert_is_idempotent_and_keeps_full_sanitized_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "good.png").write_bytes(b"png")
            index = CreativeIndex(root / "creative.sqlite3")
            item = snapshot("a" * 32, prompt_id="prompt-1", request_id="request-1",
                            outputs=[{"filename": "good.png", "type": "output"}])
            first = index.upsert_snapshot(item, output_root=root)
            second = index.upsert_snapshot(item, output_root=root)
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertRegex(first["generation_id"], r"^[0-9a-f]{32}$")
            self.assertNotEqual(first["generation_id"], item["id"])
            listing = index.list_generations()
            self.assertEqual(1, listing["total"])
            self.assertEqual(1, listing["items"][0]["artifact_count"])
            detail = index.get_generation(first["generation_id"])
            self.assertIsNotNone(detail)
            self.assertEqual("must-not-enter-index", item["payload"]["token"])
            self.assertNotIn("token", detail["snapshot"]["payload"])
            self.assertEqual("42", detail["seed"])
            self.assertEqual("hero", detail["loras"][0]["trigger"])
            self.assertFalse(detail["replay"]["can_submit"])
            self.assertFalse(detail["variation"]["can_submit"])
            self.assertEqual("/api/rpg/image?name=good.png&type=output", detail["artifacts"][0]["url"])

    def test_missing_and_unsafe_artifacts_are_reported_and_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "good.png").write_bytes(b"png")
            index = CreativeIndex(root / "creative.sqlite3")
            result = index.upsert_snapshot(
                snapshot("b" * 32, outputs=["good.png", "missing.png", "../escape.png", {"filename": "sub/also-bad.png"}]),
                output_root=root,
            )
            self.assertEqual(1, result["generation"]["artifact_count"])
            self.assertGreaterEqual(len(result["warnings"]), 3)
            self.assertEqual(["good.png"], [item["filename"] for item in index.get_generation(result["generation_id"])["artifacts"]])

    def test_transaction_rolls_back_a_failed_row(self):
        with tempfile.TemporaryDirectory() as folder:
            index = CreativeIndex(Path(folder) / "creative.sqlite3")
            with patch.object(index, "_upsert_artifacts", side_effect=RuntimeError("simulated")):
                with self.assertRaises(RuntimeError):
                    index.upsert_snapshot(snapshot("c" * 32))
            self.assertEqual(0, index.list_generations()["total"])

    def test_derivation_and_lineage_are_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            index = CreativeIndex(Path(folder) / "creative.sqlite3")
            parent = index.upsert_snapshot(snapshot("d" * 32, created_at=1), status="completed")
            child = index.upsert_snapshot(snapshot("e" * 32, created_at=2, operation="style_change"),
                                          operation="style_change", parent_generation_id=parent["generation_id"])
            child_summary = next(item for item in index.list_generations()["items"]
                                if item["generation_id"] == child["generation_id"])
            self.assertEqual(1, child_summary["parent_count"])
            self.assertFalse(index.add_derivation(
                parent_generation_id=parent["generation_id"],
                child_generation_id=child["generation_id"],
                operation="style_change",
            ))
            lineage = index.get_lineage(child["generation_id"])
            self.assertEqual(parent["generation_id"], lineage["ancestors"][0]["generation_id"])
            self.assertTrue(lineage["edges"])
            parent_lineage = index.get_lineage(parent["generation_id"])
            self.assertEqual(child["generation_id"], parent_lineage["descendants"][0]["generation_id"])

    def test_filters_sort_and_unknown_operations_are_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            index = CreativeIndex(Path(folder) / "creative.sqlite3")
            index.upsert_snapshot(snapshot("f" * 32, created_at=1, operation="future_operation"), operation="future_operation")
            index.upsert_snapshot(snapshot("1" * 32, created_at=3, operation="img2img"), operation="img2img", status="completed")
            index.upsert_snapshot(snapshot("2" * 32, created_at=2, operation="style_change"), operation="style_change")
            self.assertEqual("unknown", next(item for item in index.list_generations()["items"]
                                               if item["generation_id"] != "" and item["created_at"] == 1)["operation"])
            filtered = index.list_generations(operation="img2img", status="completed", limit=1)
            self.assertEqual(1, filtered["total"])
            self.assertEqual("img2img", filtered["items"][0]["operation"])
            ascending = index.list_generations(sort="created_at", order="asc")
            self.assertEqual(1, ascending["items"][0]["created_at"])

    def test_legacy_import_is_repeatable_and_never_rewrites_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "legacy.png").write_bytes(b"legacy")
            snapshots_path = root / "generation_snapshots.json"
            jobs_path = root / "rpg_jobs.json"
            snapshots_path.write_text(json.dumps([
                snapshot("3" * 32, prompt_id="prompt-legacy", outputs=["legacy.png"]),
                "bad-row",
            ], ensure_ascii=False), encoding="utf-8")
            jobs_path.write_text(json.dumps([
                {"prompt_id": "prompt-legacy", "status": "completed", "images": [{"filename": "legacy.png"}]},
                {"request_id": "orphan-request", "model": "orphan.safetensors", "status": "queued"},
                42,
            ], ensure_ascii=False), encoding="utf-8")
            before = {
                path: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (snapshots_path, jobs_path)
            }
            index = CreativeIndex(root / "creative.sqlite3")
            report = index.import_legacy_files(snapshots_path, jobs_path, output_root=root)
            self.assertEqual(2, report["inserted"])
            self.assertGreaterEqual(report["skipped"], 2)
            self.assertEqual(2, index.list_generations()["total"])
            repeat = index.import_legacy_files(snapshots_path, jobs_path, output_root=root)
            self.assertEqual(2, index.list_generations()["total"])
            self.assertEqual(0, repeat["inserted"])
            self.assertEqual(before, {
                path: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (snapshots_path, jobs_path)
            })


if __name__ == "__main__":
    unittest.main()
