"""Tests for CreativeIndex.delete_generation (record + local image deletion)."""

from __future__ import annotations

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
    result = index.upsert_snapshot(
        snapshot(snapshot_id, outputs=outputs),
        output_root=root,
        status="completed",
    )
    return result["generation_id"]


class CreativeIndexDeleteTests(unittest.TestCase):
    def test_delete_removes_record_and_output_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.png").write_bytes(b"a-png")
            (root / "b.png").write_bytes(b"b-png")
            index = CreativeIndex(root / "creative.sqlite3")
            generation_id = make_terminal(
                index, "a" * 32, root,
                [{"filename": "a.png", "type": "output"}, {"filename": "b.png", "type": "output"}],
            )
            self.assertTrue((root / "a.png").is_file())
            result = index.delete_generation(generation_id, root)
            self.assertIsNotNone(result)
            self.assertTrue(result["deleted"])
            self.assertEqual(2, len(result["removed_files"]))
            self.assertEqual(0, len(result["missing_files"]))
            self.assertEqual(2, result["artifact_count"])
            self.assertFalse((root / "a.png").exists())
            self.assertFalse((root / "b.png").exists())
            self.assertIsNone(index.get_generation(generation_id))
            self.assertEqual(0, index.list_generations()["total"])

    def test_delete_without_output_root_only_drops_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.png").write_bytes(b"a-png")
            index = CreativeIndex(root / "creative.sqlite3")
            generation_id = make_terminal(index, "b" * 32, root, [{"filename": "a.png", "type": "output"}])
            result = index.delete_generation(generation_id)  # no output_root
            self.assertTrue(result["deleted"])
            self.assertEqual(0, len(result["removed_files"]))
            self.assertTrue((root / "a.png").is_file())
            self.assertIsNone(index.get_generation(generation_id))

    def test_delete_reports_missing_file_without_failing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.png").write_bytes(b"a-png")
            index = CreativeIndex(root / "creative.sqlite3")
            generation_id = make_terminal(index, "c" * 32, root, [{"filename": "a.png", "type": "output"}])
            (root / "a.png").unlink()
            result = index.delete_generation(generation_id, root)
            self.assertTrue(result["deleted"])
            self.assertEqual(0, len(result["removed_files"]))
            self.assertEqual(1, len(result["missing_files"]))
            self.assertIsNone(index.get_generation(generation_id))

    def test_delete_unknown_generation_returns_none(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = CreativeIndex(root / "creative.sqlite3")
            self.assertIsNone(index.delete_generation("d" * 32, root))

    def test_delete_cascades_loras_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.png").write_bytes(b"a-png")
            index = CreativeIndex(root / "creative.sqlite3")
            generation_id = make_terminal(index, "e" * 32, root, [{"filename": "a.png", "type": "output"}])
            detail = index.get_generation(generation_id)
            self.assertGreaterEqual(len(detail["loras"]), 1)
            result = index.delete_generation(generation_id, root)
            self.assertTrue(result["deleted"])
            self.assertIsNone(index.get_generation(generation_id))


if __name__ == "__main__":
    unittest.main()
