from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from easy_panel_app.creative_index import CreativeIndex


ROOT = Path(__file__).resolve().parents[1]


def snapshot(snapshot_id: str, *, seed: str = "42", created_at: int = 1) -> dict:
    payload = {
        "model": "library-model.safetensors",
        "prompt": "1girl, quiet cafe",
        "negative": "bad anatomy",
        "seed": seed,
        "width": 832,
        "height": 1216,
    }
    return {
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


class CreativeFavoritesTests(unittest.TestCase):
    """收藏 / 入选 / 评分 / 备注：只标记作品，不改变生成参数。"""

    def test_schema_adds_review_columns_for_new_and_old_databases(self):
        with tempfile.TemporaryDirectory() as folder:
            index = CreativeIndex(Path(folder) / "creative.sqlite3")
            index.initialize()
            with index._connection() as connection:
                columns = connection.execute("PRAGMA table_info(generations)").fetchall()
            names = {row[1] for row in columns}
            self.assertLessEqual({"favorite", "rating", "note"}, names)
        source = (ROOT / "easy_panel_app/creative_index.py").read_text(encoding="utf-8")
        self.assertIn('"favorite": "INTEGER NOT NULL DEFAULT 0"', source)
        self.assertIn('"rating": "INTEGER NOT NULL DEFAULT 0"', source)
        self.assertIn('"note": "TEXT NOT NULL DEFAULT \'\'"', source)
        self.assertIn("def set_generation_flags", source)

    def test_flags_round_trip_and_filter_the_library(self):
        with tempfile.TemporaryDirectory() as folder:
            index = CreativeIndex(Path(folder) / "creative.sqlite3")
            index.upsert_snapshot(snapshot("a" * 32, seed="1"), operation="txt2img", status="completed")
            index.upsert_snapshot(snapshot("b" * 32, seed="2", created_at=2), operation="txt2img", status="completed")
            first = index.list_generations(limit=10)
            self.assertEqual(2, first["total"])
            self.assertTrue(all(item["favorite"] is False for item in first["items"]))
            target = first["items"][0]["generation_id"]

            updated = index.set_generation_flags(target, favorite=True, rating=7, note="  构图最好  ")
            self.assertTrue(updated["favorite"])
            self.assertEqual(5, updated["rating"])
            self.assertEqual("构图最好", updated["note"])

            favorites = index.list_generations(limit=10, favorite="favorite")
            self.assertEqual(1, favorites["total"])
            self.assertEqual(target, favorites["items"][0]["generation_id"])
            unfavorites = index.list_generations(limit=10, favorite="unfavorite")
            self.assertEqual(1, unfavorites["total"])
            self.assertNotEqual(target, unfavorites["items"][0]["generation_id"])

            detail = index.get_generation(target)
            self.assertTrue(detail["favorite"])
            self.assertEqual(5, detail["rating"])
            self.assertEqual("构图最好", detail["note"])

            self.assertTrue(index.set_generation_flags(target, favorite=0)["favorite"] is False)
            self.assertEqual(0, index.list_generations(limit=10, favorite="favorite")["total"])
            self.assertIsNone(index.set_generation_flags("c" * 32, favorite=True))
            with self.assertRaises(ValueError):
                index.set_generation_flags(target)

    def test_desktop_api_and_ui_expose_the_marker(self):
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn('"/api/rpg/library/favorite"', backend)
        self.assertIn("favorite=query.get(\"favorite\", [\"\"])[0]", backend)
        self.assertIn("set_generation_flags(", backend)

        script = (ROOT / "web/assets/js/creative-library.js").read_text(encoding="utf-8")
        for marker in ("creativeLibraryFavorite", "saveFlags", "favoriteFlags",
                       "creative-library-item-star", "/api/rpg/library/favorite", "标记为入选"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="creativeLibraryFavorite"', html)
        self.assertIn("★ 已入选", html)

    def test_mobile_client_can_mark_and_filter_favorites(self):
        service = (ROOT / "android-client/src/services/easyPanelLibrary.ts").read_text(encoding="utf-8")
        for marker in ("favorite?: boolean", "rating?: number", "setEasyPanelGenerationFlags",
                       "libraryFlagsPayload", "/api/rpg/library/favorite", "favorite?: 'favorite' | 'unfavorite' | ''"):
            with self.subTest(marker=marker):
                self.assertIn(marker, service)
        hook = (ROOT / "android-client/src/hooks/useEasyPanelController.ts").read_text(encoding="utf-8")
        self.assertIn("saveLibraryFlags", hook)
        self.assertIn("toggleLibraryFavoriteFilter", hook)
        app = (ROOT / "android-client/src/components/EasyPanelMobileApp.tsx").read_text(encoding="utf-8")
        self.assertIn("只看入选", app)
        self.assertIn("epm-library-item-star", app)

    def test_runtime_and_installer_payload_stay_identical(self):
        for relative in ("easy_panel.py", "easy_panel_app/creative_index.py", "index.html",
                         "web/assets/js/creative-library.js", "web/assets/css/panel.css"):
            with self.subTest(relative=relative):
                self.assertEqual(
                    (ROOT / relative).read_bytes(),
                    (ROOT / "installers" / "payload" / relative).read_bytes(),
                )


class FavoriteGroupTests(unittest.TestCase):
    """自命名收藏组：多对多分类，不改变作品本身。"""

    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.index = CreativeIndex(Path(self._folder.name) / "creative.sqlite3")
        self.index.upsert_snapshot(snapshot("a" * 32, seed="1"), operation="txt2img", status="completed")
        self.index.upsert_snapshot(snapshot("b" * 32, seed="2", created_at=2), operation="txt2img", status="completed")
        items = self.index.list_generations(limit=10)["items"]
        self.ids = [item["generation_id"] for item in items]

    def tearDown(self):
        self._folder.cleanup()

    def test_group_crud_is_normalized_and_idempotent(self):
        created = self.index.create_favorite_group("  成图   候选  ")
        self.assertTrue(created["created"])
        self.assertEqual("成图 候选", created["group"]["name"])
        again = self.index.create_favorite_group("成图 候选")
        self.assertFalse(again["created"])
        self.assertEqual(created["group"]["group_id"], again["group"]["group_id"])
        other = self.index.create_favorite_group("需要修手")
        with self.assertRaises(ValueError):
            self.index.create_favorite_group("   ")
        with self.assertRaises(ValueError):
            self.index.rename_favorite_group(other["group"]["group_id"], "成图 候选")
        renamed = self.index.rename_favorite_group(other["group"]["group_id"], "修手")
        self.assertEqual("修手", renamed["name"])
        self.assertIsNone(self.index.rename_favorite_group("c" * 32, "无名"))
        self.assertIsNone(self.index.delete_favorite_group("c" * 32))

    def test_membership_is_many_to_many_and_filterable(self):
        group_id = self.index.create_favorite_group("参考姿势")["group"]["group_id"]
        spare_id = self.index.create_favorite_group("最终成图")["group"]["group_id"]
        summary = self.index.set_generation_groups(self.ids[0], [group_id, spare_id])
        self.assertEqual(2, len(summary["groups"]))
        self.assertEqual(1, self.index.list_generations(limit=10, group=group_id)["total"])
        self.assertEqual(1, self.index.list_generations(limit=10, group=spare_id)["total"])
        self.assertEqual(1, self.index.list_generations(limit=10, group="ungrouped")["total"])
        self.assertEqual(0, self.index.list_generations(limit=10, group="c" * 32)["total"])
        counts = {item["name"]: item["item_count"] for item in self.index.list_favorite_groups()["items"]}
        self.assertEqual({"参考姿势": 1, "最终成图": 1}, counts)

        detailed = self.index.get_generation(self.ids[0])
        self.assertEqual(["参考姿势", "最终成图"], [item["name"] for item in detailed["groups"]])

        self.index.set_generation_groups(self.ids[1], [group_id], mode="add")
        self.assertEqual(2, self.index.list_generations(limit=10, group=group_id)["total"])
        self.index.set_generation_groups(self.ids[0], [group_id], mode="remove")
        self.assertEqual(1, self.index.list_generations(limit=10, group=group_id)["total"])
        replaced = self.index.set_generation_groups(self.ids[0], [group_id])
        self.assertEqual(["参考姿势"], [item["name"] for item in replaced["groups"]])

        with self.assertRaises(ValueError):
            self.index.set_generation_groups(self.ids[0], ["c" * 32])
        self.assertIsNone(self.index.set_generation_groups("c" * 32, [group_id]))

    def test_deleting_a_group_or_a_generation_keeps_records_consistent(self):
        group_id = self.index.create_favorite_group("待筛选")["group"]["group_id"]
        self.index.set_generation_groups(self.ids[0], [group_id])
        removed = self.index.delete_favorite_group(group_id)
        self.assertTrue(removed["deleted"])
        self.assertEqual(1, removed["removed_links"])
        self.assertEqual(0, len(self.index.list_generations(limit=10)["items"][0]["groups"]))

        keep_id = self.index.create_favorite_group("保留")["group"]["group_id"]
        self.index.set_generation_groups(self.ids[0], [keep_id])
        self.index.delete_generation(self.ids[0])
        self.assertEqual(0, self.index.list_favorite_groups()["items"][0]["item_count"])


class FavoriteGroupApiTests(unittest.TestCase):
    def test_desktop_api_and_ui_expose_groups(self):
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn('\"/api/rpg/library/groups\"', backend)
        self.assertIn('group=query.get(\"group\", [\"\"])[0]', backend)
        self.assertIn('\"group_add\"', backend)
        self.assertIn('\"group_remove\"', backend)

        script = (ROOT / "web/assets/js/creative-library.js").read_text(encoding="utf-8")
        for marker in ("creativeLibraryGroup", "renderGroupOptions", "saveGroups", "createGroup",
                       "renameGroup", "deleteGroup", "creative-library-group-chip",
                       "收藏组", "ungrouped"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="creativeLibraryGroup"', html)
        self.assertIn("全部收藏组", html)

    def test_mobile_client_can_manage_groups(self):
        service = (ROOT / "android-client/src/services/easyPanelLibrary.ts").read_text(encoding="utf-8")
        for marker in ("EasyPanelFavoriteGroup", "getEasyPanelFavoriteGroups", "createEasyPanelFavoriteGroup",
                       "renameEasyPanelFavoriteGroup", "deleteEasyPanelFavoriteGroup", "safeGroupId",
                       "normalizeGroupName", "group', 'ungrouped'", "groupAdd"):
            with self.subTest(marker=marker):
                self.assertIn(marker, service)
        hook = (ROOT / "android-client/src/hooks/useEasyPanelController.ts").read_text(encoding="utf-8")
        for marker in ("libraryGroups", "setLibraryGroupFilter", "createLibraryGroup",
                       "renameLibraryGroup", "deleteLibraryGroup"):
            with self.subTest(marker=marker):
                self.assertIn(marker, hook)
        app = (ROOT / "android-client/src/components/EasyPanelMobileApp.tsx").read_text(encoding="utf-8")
        for marker in ("全部收藏组", "新建并加入", "epm-library-group-check", "epm-chip"):
            with self.subTest(marker=marker):
                self.assertIn(marker, app)


if __name__ == "__main__":
    unittest.main()
