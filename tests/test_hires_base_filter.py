# -*- coding: utf-8 -*-
"""作品库不得把二采的首采对照图（*_base_*.png）当成品返回。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.creative_index import CreativeIndex  # noqa: E402
from easy_panel_app.media_storage import list_output_images  # noqa: E402


def snapshot(snapshot_id: str, outputs: list[dict]) -> dict:
    payload = {
        "model": "library-model.safetensors",
        "prompt": "1girl, hires",
        "negative": "bad anatomy",
        "seed": "42",
        "width": 832,
        "height": 1216,
    }
    return {
        "id": snapshot_id,
        "createdAt": 1,
        "schemaVersion": 2,
        "promptId": "",
        "payload": payload,
        "source": {"checkpoint": payload["model"]},
        "compiled": {"positive": payload["prompt"]},
        "workflow": {"operation": "panel.generate"},
        "environment": {"panelVersion": "test-panel"},
        "status": "completed",
        "outputs": outputs,
    }


class HiresBaseFilterTests(unittest.TestCase):
    """一次二采任务只应作为一件成品出现。"""

    def build(self, folder: str):
        index = CreativeIndex(Path(folder) / "creative.sqlite3")
        index.initialize()
        generation = index.upsert_snapshot(
            snapshot("a" * 32, [
                {"filename": "EasyPanel_base_00010_.png", "subfolder": "", "type": "output"},
                {"filename": "EasyPanel_04477_.png", "subfolder": "", "type": "output"},
            ]),
            operation="txt2img",
            status="completed",
        )
        return index, generation["generation_id"]

    def test_detail_hides_the_first_pass_image(self):
        with tempfile.TemporaryDirectory() as folder:
            index, generation_id = self.build(folder)
            detail = index.get_generation(generation_id)
            names = [item["filename"] for item in detail["artifacts"]]
            self.assertEqual(["EasyPanel_04477_.png"], names)
            self.assertEqual(1, detail["hires_base_count"])
            self.assertEqual(1, detail["artifact_count"])
            self.assertEqual("EasyPanel_04477_.png", (detail["preview"] or {}).get("filename"))
            self.assertEqual(detail["preview"]["artifact_id"], detail["primary_artifact_id"])

            full = index.get_generation(generation_id, include_hires_base=True)
            self.assertEqual(2, len(full["artifacts"]))

    def test_summary_counts_only_finished_images(self):
        with tempfile.TemporaryDirectory() as folder:
            index, generation_id = self.build(folder)
            listed = index.list_generations(limit=10)
            entry = next(item for item in listed["items"] if item["generation_id"] == generation_id)
            self.assertEqual(1, entry["artifact_count"])
            self.assertIn("EasyPanel_04477_.png", entry["thumbnail_url"] or "")

    def test_recent_outputs_skip_first_pass_files(self):
        import easy_panel_app.media_storage as media_storage

        with tempfile.TemporaryDirectory() as folder:
            original = media_storage.OUTPUT
            media_storage.OUTPUT = Path(folder)
            try:
                (Path(folder) / "EasyPanel_base_00011_.png").write_bytes(b"png")
                (Path(folder) / "EasyPanel_04478_.png").write_bytes(b"png")
                names = [item["name"] for item in list_output_images()]
            finally:
                media_storage.OUTPUT = original
            self.assertEqual(["EasyPanel_04478_.png"], names)


if __name__ == "__main__":
    unittest.main()
