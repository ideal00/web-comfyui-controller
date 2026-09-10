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


if __name__ == "__main__":
    unittest.main()
