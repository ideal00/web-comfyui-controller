# -*- coding: utf-8 -*-
"""输出文件名唯一性：防止 ComfyUI 编号回退覆盖旧图导致作品库串图。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import easy_panel  # noqa: E402
from easy_panel_app.creative_index import CreativeIndex  # noqa: E402
from easy_panel_app.fingerprint import generation_fingerprint  # noqa: E402


def snapshot(snapshot_id: str, filename: str, created_at: int) -> dict:
    payload = {"model": "m.safetensors", "prompt": "1girl", "seed": "1"}
    return {
        "id": snapshot_id,
        "createdAt": created_at,
        "schemaVersion": 2,
        "promptId": "",
        "payload": payload,
        "source": {"checkpoint": payload["model"]},
        "compiled": {"positive": payload["prompt"]},
        "workflow": {"operation": "panel.generate"},
        "environment": {"panelVersion": "test-panel"},
        "status": "completed",
        "outputs": [{"filename": filename, "subfolder": "", "type": "output"}],
    }


class UniquePrefixTests(unittest.TestCase):
    def test_prefix_is_unique_per_submission(self):
        base = {"model": "wai.safetensors", "seed": "1"}
        first = easy_panel.payload_with_unique_prefix(base)["filenamePrefix"]
        second = easy_panel.payload_with_unique_prefix(base)["filenamePrefix"]
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("EasyPanel_"))
        self.assertNotIn("filenamePrefix", base)

    def test_custom_prefix_is_kept_and_made_unique(self):
        prefix = easy_panel.payload_with_unique_prefix({"filenamePrefix": "我的角色"})["filenamePrefix"]
        self.assertTrue(prefix.startswith("EasyPanel_"), prefix)

    def test_built_workflow_uses_the_unique_prefix(self):
        payload = easy_panel.payload_with_unique_prefix({
            "model": "waiIllustriousSDXL_v170.safetensors",
            "prompt": "1girl",
            "negative": "",
            "seed": "1",
            "width": 832,
            "height": 1216,
            "steps": 28,
            "cfg": 5.0,
        })
        workflow = easy_panel.build_workflow(payload)
        prefixes = {node["inputs"].get("filename_prefix")
                    for node in workflow["prompt"].values()
                    if node.get("class_type") == "SaveImage"}
        self.assertIn(payload["filenamePrefix"], prefixes)

    def test_fingerprint_ignores_the_prefix(self):
        base = {"model": "wai.safetensors", "seed": "1", "prompt": "1girl"}
        self.assertEqual(generation_fingerprint(base),
                         generation_fingerprint({**base, "filenamePrefix": "EasyPanel_20260912-120000-abcd"}))


class DuplicateArtifactRepairTests(unittest.TestCase):
    """同名文件被多条记录引用时，旧记录应被标记缺失而不是显示别人的图。"""

    def test_older_records_are_marked_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            index = CreativeIndex(Path(folder) / "creative.sqlite3")
            index.initialize()
            old = index.upsert_snapshot(snapshot("a" * 32, "EasyPanel_04485_.png", 1),
                                        operation="txt2img", status="completed")
            index.upsert_snapshot(snapshot("b" * 32, "EasyPanel_04485_.png", 2),
                                  operation="txt2img", status="completed")
            newest = index.upsert_snapshot(snapshot("c" * 32, "EasyPanel_04485_.png", 3),
                                           operation="txt2img", status="completed")

            repaired = index.mark_duplicate_artifacts_missing()
            self.assertEqual(2, repaired["marked"])
            self.assertEqual(1, repaired["groups"])

            stale = index.get_generation(old["generation_id"])
            self.assertEqual(1, len(stale["artifacts"]))
            self.assertFalse(stale["artifacts"][0]["exists"])
            self.assertIsNone(stale["preview"])
            self.assertIn("覆盖", stale["artifacts"][0]["metadata"]["reason"])

            fresh = index.get_generation(newest["generation_id"])
            self.assertTrue(fresh["artifacts"][0]["exists"])
            self.assertEqual("EasyPanel_04485_.png", (fresh["preview"] or {}).get("filename"))

    def test_unique_names_are_left_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            index = CreativeIndex(Path(folder) / "creative.sqlite3")
            index.initialize()
            first = index.upsert_snapshot(snapshot("a" * 32, "EasyPanel_04501_.png", 1),
                                          operation="txt2img", status="completed")
            second = index.upsert_snapshot(snapshot("b" * 32, "EasyPanel_04502_.png", 2),
                                           operation="txt2img", status="completed")
            self.assertEqual(0, index.mark_duplicate_artifacts_missing()["marked"])
            for generation in (first, second):
                detail = index.get_generation(generation["generation_id"])
                self.assertTrue(detail["artifacts"][0]["exists"])


if __name__ == "__main__":
    unittest.main()
