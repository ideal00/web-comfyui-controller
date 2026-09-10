"""Tests for CreativeIndex.prune_missing_outputs (deleted-image record cleanup)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from easy_panel_app.creative_index import CreativeIndex


def snapshot(snapshot_id: str, *, seed: str = "1", outputs=None) -> dict:
    payload = {
        "model": "library-model.safetensors",
        "quality": "balanced",
        "prompt": "1girl, quiet cafe",
        "negative": "bad anatomy",
        "seed": seed,
        "width": 832,
        "height": 1216,
        "loras": [{"name": "character.safetensors", "weight": 0.8, "role": "character", "trigger": "hero"}],
    }
    return {
        "id": snapshot_id,
        "createdAt": 1,
        "schemaVersion": 2,
        "promptId": "prompt-" + snapshot_id[:8],
        "payload": payload,
        "source": {
            "checkpoint": payload["model"],
            "generation": {"seed": seed, "width": 832, "height": 1216},
            "loras": payload["loras"],
        },
        "compiled": {"positive": payload["prompt"], "negative": payload["negative"]},
        "workflow": {"operation": "panel.generate", "version": "test"},
        "environment": {"panelVersion": "test-panel"},
        "status": "completed",
        "outputs": list(outputs or []),
    }


def make_terminal(index: CreativeIndex, snapshot_id: str, root: Path, outputs) -> str:
    """Insert a terminal (completed) snapshot so prune will consider it."""
    result = index.upsert_snapshot(
        snapshot(snapshot_id, outputs=outputs),
        output_root=root,
        status="completed",
    )
    return result["generation_id"]


class CreativeIndexPruneTests(unittest.TestCase):
    def test_prune_deletes_records_whose_output_files_are_gone(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "survives.png").write_bytes(b"png")
            (root / "deleted.png").write_bytes(b"png")
            index = CreativeIndex(root / "creative.sqlite3")
            keep_id = make_terminal(index, "a" * 32, root, [{"filename": "survives.png", "type": "output"}])
            gone_id = make_terminal(index, "b" * 32, root, [{"filename": "deleted.png", "type": "output"}])
            (root / "deleted.png").unlink()

            first = index.prune_missing_outputs(root)
            self.assertEqual(2, first["scanned_generations"])
            self.assertEqual(1, first["pruned_generations"])
            self.assertIsNotNone(index.get_generation(keep_id))
            self.assertIsNone(index.get_generation(gone_id))

            # Second run is a no-op (idempotent).
            second = index.prune_missing_outputs(root)
            self.assertEqual(0, second["pruned_generations"])
            self.assertEqual(1, index.list_generations()["total"])

    def test_prune_keeps_record_when_at_least_one_output_survives_and_refreshes_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "first.png").write_bytes(b"png")
            (root / "second.png").write_bytes(b"png")
            index = CreativeIndex(root / "creative.sqlite3")
            generation_id = make_terminal(
                index, "c" * 32, root,
                [{"filename": "first.png", "type": "output"}, {"filename": "second.png", "type": "output"}],
            )
            (root / "first.png").unlink()

            result = index.prune_missing_outputs(root)
            self.assertEqual(0, result["pruned_generations"])
            self.assertGreaterEqual(result["refreshed_artifacts"], 1)
            detail = index.get_generation(generation_id)
            self.assertIsNotNone(detail)
            by_filename = {artifact["filename"]: artifact for artifact in detail["artifacts"]}
            self.assertFalse(by_filename["first.png"]["exists"])
            self.assertIsNone(by_filename["first.png"]["url"])
            self.assertTrue(by_filename["second.png"]["exists"])
            self.assertIsNotNone(by_filename["second.png"]["url"])
            # Thumbnail now points at the surviving file (first existing artifact).
            self.assertIsNotNone(detail["thumbnail_url"])

    def test_prune_never_touches_rows_without_output_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = CreativeIndex(root / "creative.sqlite3")
            queued_id = index.upsert_snapshot(snapshot("d" * 32, outputs=[]), output_root=root)["generation_id"]
            result = index.prune_missing_outputs(root)
            self.assertEqual(0, result["scanned_generations"])
            self.assertEqual(0, result["pruned_generations"])
            self.assertIsNotNone(index.get_generation(queued_id))

    def test_prune_cascades_artifacts_loras_and_derivations(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "child.png").write_bytes(b"png")
            (root / "parent.png").write_bytes(b"png")
            index = CreativeIndex(root / "creative.sqlite3")
            parent_id = make_terminal(index, "e" * 32, root, [{"filename": "parent.png", "type": "output"}])
            child_id = make_terminal(index, "f" * 32, root, [{"filename": "child.png", "type": "output"}])
            parent_detail = index.get_generation(parent_id)
            index.add_derivation(
                child_generation_id=child_id,
                parent_generation_id=parent_id,
                parent_artifact_id=parent_detail["artifacts"][0]["artifact_id"],
                operation="seed_variant",
            )
            (root / "parent.png").unlink()
            (root / "child.png").unlink()

            result = index.prune_missing_outputs(root)
            self.assertEqual(2, result["pruned_generations"])
            self.assertIsNone(index.get_generation(parent_id))
            self.assertIsNone(index.get_generation(child_id))
            # Cascade must not leave orphan rows behind.
            import sqlite3

            connection = sqlite3.connect(index.path)
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("artifacts", "derivations", "generation_loras")
            }
            connection.close()
            self.assertEqual(0, counts["artifacts"])
            self.assertEqual(0, counts["derivations"])
            self.assertEqual(0, counts["generation_loras"])


if __name__ == "__main__":
    unittest.main()
