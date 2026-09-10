import json
import http.client
import threading
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from easy_panel_app.shared_state import (
    MAX_STATE_BYTES,
    SharedStateError,
    SharedStateStore,
)


def preset(name, content, *, item_id="preset_a", updated_at=100):
    return {
        "id": item_id,
        "name": name,
        "category": "pose",
        "content": content,
        "sections": {},
        "updatedAt": updated_at,
    }


class SharedStateTests(unittest.TestCase):
    def make_store(self, directory):
        return SharedStateStore(Path(directory) / "easy_panel_shared_state.json")

    def test_first_migration_and_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            first = store.merge(
                {
                    "promptPresets": [preset("站姿", "standing")],
                    "characterFavorites": ["characters/alice.safetensors"],
                },
                0,
            )
            self.assertTrue(first["changed"])
            self.assertEqual(1, first["state"]["revision"])

            second = store.merge(
                {
                    "promptPresets": [preset("坐姿", "sitting", item_id="preset_b", updated_at=200)],
                    "characterFavorites": ["characters/bob.safetensors"],
                },
                first["state"]["revision"],
            )
            self.assertEqual(2, second["state"]["revision"])
            self.assertEqual(2, len(second["state"]["promptPresets"]))
            self.assertEqual(
                ["characters/alice.safetensors", "characters/bob.safetensors"],
                second["state"]["characterFavorites"],
            )

    def test_duplicate_content_is_deduplicated_and_current_revision_can_update(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            first = store.merge({"promptPresets": [preset("同一", "same")]}, 0)
            duplicate = store.merge(
                {"promptPresets": [preset("同一", "same", item_id="another_id", updated_at=500)]},
                first["state"]["revision"],
            )
            self.assertFalse(duplicate["changed"])
            self.assertEqual(1, len(duplicate["state"]["promptPresets"]))

            updated = store.merge(
                {"promptPresets": [preset("同一", "changed", updated_at=600)]},
                duplicate["state"]["revision"],
            )
            self.assertEqual("changed", updated["state"]["promptPresets"][0]["content"])

    def test_revision_conflict_keeps_server_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            first = store.merge({"promptPresets": [preset("电脑", "server-old")]}, 0)
            server = store.merge(
                {"promptPresets": [preset("电脑", "computer-new", updated_at=200)]},
                first["state"]["revision"],
            )
            stale_phone = store.merge(
                {"promptPresets": [preset("电脑", "phone-stale", updated_at=900)]},
                first["state"]["revision"],
            )
            self.assertTrue(stale_phone["conflict"])
            self.assertEqual("revision_conflict", stale_phone["reason"])
            self.assertEqual("computer-new", stale_phone["state"]["promptPresets"][0]["content"])
            self.assertEqual(server["state"]["revision"], stale_phone["state"]["revision"])

    def test_empty_client_cannot_clear_server_favorites(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            first = store.merge({"characterFavorites": ["characters/kept.safetensors"]}, 0)
            empty_phone = store.merge(
                {"promptPresets": [], "characterFavorites": []},
                0,
            )
            self.assertFalse(empty_phone["changed"])
            self.assertEqual(first["state"], empty_phone["state"])

    def test_corrupt_primary_recovers_from_backup_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            first = store.merge({"characterFavorites": ["characters/one.safetensors"]}, 0)
            second = store.merge({"characterFavorites": ["characters/two.safetensors"]}, first["state"]["revision"])
            self.assertTrue(store.backup_path.is_file())
            store.path.write_text("{not valid json", encoding="utf-8")

            recovered, was_recovered = store.read_with_metadata()
            self.assertTrue(was_recovered)
            self.assertEqual(first["state"], recovered)
            self.assertEqual(recovered, json.loads(store.path.read_text(encoding="utf-8")))
            self.assertNotEqual(second["state"], recovered)

    def test_oversize_and_path_like_favorite_are_rejected_without_write(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            with self.assertRaises(SharedStateError):
                store.merge({"promptPresets": [preset("太长", "x" * 12001)]}, 0)
            with self.assertRaises(SharedStateError):
                store.merge({"characterFavorites": ["../outside.safetensors"]}, 0)
            store.path.write_bytes(b"x" * (MAX_STATE_BYTES + 1))
            recovered, was_recovered = store.read_with_metadata()
            self.assertFalse(was_recovered)
            self.assertEqual([], recovered["promptPresets"])
            self.assertEqual([], recovered["characterFavorites"])

    def test_concurrent_atomic_merges_keep_every_new_favorite(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)

            def add(index):
                return store.merge(
                    {"characterFavorites": [f"characters/fixture_{index}.safetensors"]},
                    0,
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(add, range(24)))
            state = store.read()
            self.assertEqual(24, len(state["characterFavorites"]))
            self.assertEqual([], list(Path(directory).glob(".*.tmp")))

    def test_http_api_reads_and_merges_without_touching_generation_routes(self):
        import easy_panel

        with tempfile.TemporaryDirectory() as directory:
            previous_store = easy_panel.SHARED_STATE_STORE
            store = self.make_store(directory)
            easy_panel.SHARED_STATE_STORE = store
            server = easy_panel.ThreadingHTTPServer(("127.0.0.1", 0), easy_panel.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                connection = http.client.HTTPConnection(host, port, timeout=5)
                connection.request("GET", "/api/shared-state")
                response = connection.getresponse()
                self.assertEqual(200, response.status)
                initial = json.loads(response.read().decode("utf-8"))
                self.assertEqual([], initial["state"]["characterFavorites"])

                body = json.dumps(
                    {
                        "baseRevision": 0,
                        "state": {"promptPresets": [preset("API", "standing")], "characterFavorites": []},
                    }
                ).encode("utf-8")
                connection.request(
                    "POST",
                    "/api/shared-state",
                    body=body,
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                self.assertEqual(200, response.status)
                merged = json.loads(response.read().decode("utf-8"))
                self.assertEqual("API", merged["state"]["promptPresets"][0]["name"])
                self.assertEqual(1, merged["state"]["revision"])
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                easy_panel.SHARED_STATE_STORE = previous_store

    def test_runtime_and_installer_payload_are_identical(self):
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "easy_panel.py",
            "easy_panel_app/shared_state.py",
            "index.html",
            "web/assets/css/panel.css",
            "web/assets/js/panel.js",
            "web/assets/js/shared-state.js",
        ):
            self.assertEqual(
                (root / relative).read_bytes(),
                (root / "installers" / "payload" / relative).read_bytes(),
                relative,
            )


    def test_expression_category_is_kept_and_unknown_categories_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            merged = store.merge(
                {
                    "promptPresets": [
                        dict(preset("娇羞斜视", "coy smile, half-closed eyes"), category="expression"),
                        dict(preset("未知分类", "x", item_id="preset_b"), category="not-a-category"),
                    ],
                    "characterFavorites": [],
                },
                0,
            )
            categories = {item["name"]: item["category"]
                          for item in merged["state"]["promptPresets"]}
            # 表情是正式分类；未知分类仍然回退到“其他补充”。
            self.assertEqual("expression", categories["娇羞斜视"])
            self.assertEqual("manual", categories["未知分类"])
            self.assertEqual(2, len(store.read()["promptPresets"]))


if __name__ == "__main__":
    unittest.main()
