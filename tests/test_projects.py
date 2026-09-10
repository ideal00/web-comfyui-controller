from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.creative_index import CreativeIndex, CreativeIndexError  # noqa: E402


def snapshot(snapshot_id: str, *, seed: str = "42", fingerprint: str = "", created_at: int = 1) -> dict:
    payload = {
        "model": "library-model.safetensors",
        "prompt": "1girl, quiet cafe",
        "negative": "bad anatomy",
        "seed": seed,
        "width": 832,
        "height": 1216,
    }
    document = {
        "id": snapshot_id,
        "createdAt": created_at,
        "schemaVersion": 2,
        "promptId": "",
        "payload": payload,
        "source": {"checkpoint": payload["model"], "generation": {"seed": seed}},
        "compiled": {"positive": payload["prompt"]},
        "workflow": {"operation": "panel.generate"},
        "environment": {"panelVersion": "test-panel"},
        "status": "completed",
        "outputs": [],
    }
    if fingerprint:
        document["fingerprint"] = fingerprint
    return document


class ProjectTests(unittest.TestCase):
    """作品项目：分区、精选、关联资源与删除清理。"""

    def build(self, folder: str) -> tuple[CreativeIndex, list[str]]:
        index = CreativeIndex(Path(folder) / "creative.sqlite3")
        index.initialize()
        ids = []
        for name, seed in (("a", "1"), ("b", "2"), ("c", "3")):
            result = index.upsert_snapshot(snapshot(name * 32, seed=seed, created_at=int(seed)),
                                           operation="txt2img", status="completed")
            ids.append(result["generation_id"])
        return index, ids

    def test_default_sections_and_crud(self):
        with tempfile.TemporaryDirectory() as folder:
            index, _ = self.build(folder)
            created = index.create_project("Luna 角色图集")
            project = created["project"]
            self.assertTrue(created["created"])
            self.assertIn("基准角色", project["sections"])
            self.assertIn("最终精选", project["sections"])

            again = index.create_project("Luna 角色图集")
            self.assertFalse(again["created"])
            self.assertEqual(project["project_id"], again["project"]["project_id"])

            renamed = index.update_project(project["project_id"], name="Luna 图集 2026",
                                           sections=["基准角色", "夜景"])
            self.assertEqual("Luna 图集 2026", renamed["name"])
            self.assertEqual(["基准角色", "夜景"], renamed["sections"])

            listed = index.list_projects()
            self.assertEqual(1, listed["total"])
            self.assertEqual(0, listed["items"][0]["item_count"])

            removed = index.delete_project(project["project_id"])
            self.assertTrue(removed["deleted"])
            self.assertEqual({}, index.get_project(project["project_id"]) or {})
            self.assertIsNone(index.get_project(project["project_id"]))

    def test_items_are_grouped_by_section(self):
        with tempfile.TemporaryDirectory() as folder:
            index, ids = self.build(folder)
            project_id = index.create_project("Luna")["project"]["project_id"]
            result = index.add_project_items(project_id, ids[:2], section="基准角色")
            self.assertEqual(2, result["added"])
            self.assertEqual(1, (index.add_project_items(project_id, ids[0]) or {})["skipped"])

            index.add_project_items(project_id, ids[2], section="夜景")
            detail = index.get_project(project_id)
            self.assertEqual(3, detail["total"])
            grouped = {entry["name"]: len(entry["items"]) for entry in detail["sections"]}
            self.assertEqual({"基准角色": 2, "夜景": 1}, {k: v for k, v in grouped.items() if v})
            self.assertEqual(3, detail["project"]["item_count"])

            with self.assertRaises(CreativeIndexError):
                index.add_project_items(project_id, ids[0], section="不存在的分区")

    def test_move_item_between_sections_and_remove(self):
        with tempfile.TemporaryDirectory() as folder:
            index, ids = self.build(folder)
            project_id = index.create_project("Luna")["project"]["project_id"]
            index.add_project_items(project_id, ids[:2], section="基准角色")
            detail = index.get_project(project_id)
            item = detail["sections"][0]["items"][0]
            moved = index.update_project_item(project_id, item["item_id"], section="最终精选",
                                              note="最佳版本")
            self.assertEqual("最终精选", moved["section"])
            self.assertEqual("最佳版本", moved["note"])

            removed = index.remove_project_items(project_id, item_ids=[item["item_id"]])
            self.assertEqual(1, removed["removed"])
            self.assertEqual(1, index.get_project(project_id)["total"])

            removed = index.remove_project_items(project_id, generation_ids=[ids[1]])
            self.assertEqual(1, removed["removed"])
            self.assertEqual(0, index.get_project(project_id)["total"])

    def test_cover_and_links(self):
        with tempfile.TemporaryDirectory() as folder:
            index, ids = self.build(folder)
            project_id = index.create_project("Luna")["project"]["project_id"]
            index.add_project_items(project_id, ids[0], section="基准角色")
            cover = index.set_project_cover(project_id, generation_id=ids[0])
            self.assertIsNotNone(cover)

            index.add_project_link(project_id, "lora", "Illustrious_Hosiery_Test/02_人物模板/Luna.safetensors",
                                   label="Luna 基准")
            index.add_project_link(project_id, "preset", "日常服装", label="Prompt 预设")
            index.add_project_link(project_id, "experiment", "cfg 5 / 7 / 9", label="单变量实验")
            index.add_project_link(project_id, "favorite_group", "g" * 32, label="最终精选组")
            detail = index.get_project(project_id)
            self.assertEqual(1, len(detail["links"]["lora"]))
            self.assertEqual(1, len(detail["links"]["preset"]))
            self.assertEqual(1, len(detail["links"]["experiment"]))
            self.assertEqual(1, len(detail["links"]["favorite_group"]))

            link_id = detail["links"]["lora"][0]["link_id"]
            index.remove_project_link(project_id, link_id)
            self.assertEqual([], index.get_project(project_id)["links"]["lora"])

            with self.assertRaises(CreativeIndexError):
                index.add_project_link(project_id, "unknown", "x")

    def test_deleting_a_work_removes_it_from_projects(self):
        with tempfile.TemporaryDirectory() as folder:
            index, ids = self.build(folder)
            project_id = index.create_project("Luna")["project"]["project_id"]
            index.add_project_items(project_id, ids, section="基准角色")
            index.delete_generation(ids[0])
            self.assertEqual(2, index.get_project(project_id)["total"])


class FingerprintQueryTests(unittest.TestCase):
    """重复任务检测：按指纹找到已完成的相同作品。"""

    def test_fingerprint_is_stored_and_queryable(self):
        with tempfile.TemporaryDirectory() as folder:
            index = CreativeIndex(Path(folder) / "creative.sqlite3")
            index.initialize()
            first = index.upsert_snapshot(snapshot("a" * 32, fingerprint="fp-1"),
                                          operation="txt2img", status="completed")
            index.upsert_snapshot(snapshot("b" * 32, seed="7", fingerprint="fp-2", created_at=2),
                                  operation="txt2img", status="completed")
            index.upsert_snapshot(snapshot("c" * 32, seed="9", fingerprint="fp-1", created_at=3),
                                  operation="txt2img", status="queued")

            stored = index.get_generation(first["generation_id"])
            self.assertEqual("fp-1", stored["fingerprint"])

            found = index.find_generations_by_fingerprint("fp-1")
            self.assertEqual(1, found["total"])  # 只有已完成的那条
            self.assertEqual(first["generation_id"], found["items"][0]["generation_id"])

            everything = index.find_generations_by_fingerprint("fp-1", statuses=())
            self.assertEqual(2, everything["total"])

            self.assertEqual(0, index.find_generations_by_fingerprint("").get("total"))
            self.assertEqual(0, index.find_generations_by_fingerprint("nope")["total"])


if __name__ == "__main__":
    unittest.main()
