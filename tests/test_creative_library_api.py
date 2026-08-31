from __future__ import annotations

import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from easy_panel_app.creative_index import CreativeIndex
import easy_panel


class CreativeLibraryApiTests(unittest.TestCase):
    def test_library_read_initializes_from_legacy_json_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot_path = root / "generation_snapshots.json"
            jobs_path = root / "rpg_jobs.json"
            db_path = root / "creative.sqlite3"
            output = root / "output"
            output.mkdir()
            snapshot_path.write_text(json.dumps([{
                "id": "a" * 32,
                "createdAt": 1,
                "schemaVersion": 2,
                "payload": {"model": "legacy.safetensors", "prompt": "legacy prompt", "seed": "7"},
                "source": {"checkpoint": "legacy.safetensors"},
                "compiled": {},
                "workflow": {"operation": "panel.generate"},
                "outputs": [],
            }], ensure_ascii=False), encoding="utf-8")
            jobs_path.write_text("[]", encoding="utf-8")
            before = snapshot_path.read_bytes()
            with patch.object(easy_panel, "CREATIVE_INDEX_FILE", db_path), \
                    patch.object(easy_panel, "SNAPSHOT_FILE", snapshot_path), \
                    patch.object(easy_panel, "RPG_JOB_FILE", jobs_path), \
                    patch.object(easy_panel, "OUTPUT", output):
                report = easy_panel.ensure_creative_index_from_legacy_best_effort()
                listing = easy_panel.get_creative_index().list_generations()
            self.assertEqual(1, report["inserted"])
            self.assertEqual(1, listing["total"])
            self.assertEqual(before, snapshot_path.read_bytes())

    def test_new_and_completed_job_adapters_are_one_way_best_effort(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "output"
            output.mkdir()
            (output / "done.png").write_bytes(b"done")
            index_path = root / "creative.sqlite3"
            source = {
                "id": "f" * 32,
                "createdAt": 100,
                "schemaVersion": 2,
                "payload": {"model": "m.safetensors", "seed": "5", "prompt": "hello"},
                "source": {"checkpoint": "m.safetensors"},
                "compiled": {},
                "workflow": {"operation": "rpg.generate"},
                "outputs": [],
            }
            with patch.object(easy_panel, "CREATIVE_INDEX_FILE", index_path), \
                    patch.object(easy_panel, "OUTPUT", output):
                created = easy_panel.index_snapshot_best_effort(
                    source,
                    source_request={"operation": "style_change"},
                    status="queued",
                )
                self.assertTrue(created["generation_id"])
                queued = easy_panel.get_creative_index().get_generation(created["generation_id"])
                self.assertEqual("queued", queued["status"])
                easy_panel.update_creative_index_status_best_effort(
                    source["id"],
                    {"status": "completed", "images": [{"filename": "done.png", "type": "output"}]},
                )
                completed = easy_panel.get_creative_index().get_generation(created["generation_id"])
                self.assertEqual("completed", completed["status"])
                self.assertEqual(1, len(completed["artifacts"]))

    def test_server_reconciles_completed_jobs_without_a_live_client(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "output"
            output.mkdir()
            (output / "recovered.png").write_bytes(b"recovered")
            snapshot_path = root / "generation_snapshots.json"
            jobs_path = root / "rpg_jobs.json"
            index_path = root / "creative.sqlite3"
            prompt_id = "prompt-reconcile"
            snapshot = {
                "id": "e" * 32,
                "createdAt": 100,
                "schemaVersion": 2,
                "promptId": prompt_id,
                "payload": {"model": "m.safetensors", "prompt": "recover me", "seed": "5"},
                "source": {"checkpoint": "m.safetensors"},
                "compiled": {},
                "workflow": {"operation": "panel.generate"},
                "outputs": [],
            }
            snapshot_path.write_text(json.dumps([snapshot]), encoding="utf-8")
            jobs_path.write_text("[]", encoding="utf-8")
            history = {
                prompt_id: {
                    "status": {"status_str": "success"},
                    "outputs": {"9": {"images": [{"filename": "recovered.png", "type": "output"}]}},
                }
            }
            with patch.object(easy_panel, "CREATIVE_INDEX_FILE", index_path), \
                    patch.object(easy_panel, "OUTPUT", output), \
                    patch.object(easy_panel, "SNAPSHOT_FILE", snapshot_path), \
                    patch.object(easy_panel, "RPG_JOB_FILE", jobs_path), \
                    patch.object(easy_panel, "comfy_json", return_value=history):
                created = easy_panel.index_snapshot_best_effort(snapshot, status="queued")
                self.assertEqual("queued", easy_panel.get_creative_index().get_generation(created["generation_id"])["status"])
                reconciled = easy_panel.reconcile_creative_index_jobs()
                recovered = easy_panel.get_creative_index().get_generation(created["generation_id"])

            self.assertEqual(1, reconciled)
            self.assertEqual("completed", recovered["status"])
            self.assertEqual(1, len(recovered["artifacts"]))
            self.assertEqual(["recovered.png"], json.loads(snapshot_path.read_text(encoding="utf-8"))[0]["outputs"])

    def test_server_reconciles_completed_rpg_output_without_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "output"
            output.mkdir()
            output_name = "RPGBox_game_scene_00001_.png"
            (output / output_name).write_bytes(b"recovered")
            snapshot_path = root / "generation_snapshots.json"
            jobs_path = root / "rpg_jobs.json"
            index_path = root / "creative.sqlite3"
            prompt_id = "prompt-output-fallback"
            snapshot = {
                "id": "d" * 32,
                "createdAt": 100,
                "schemaVersion": 2,
                "promptId": prompt_id,
                "payload": {
                    "model": "m.safetensors",
                    "prompt": "recover from output",
                    "seed": "5",
                    "filenamePrefix": "RPGBox_game_scene",
                },
                "source": {"checkpoint": "m.safetensors"},
                "compiled": {},
                "workflow": {"operation": "rpg.generate"},
                "outputs": [],
            }
            snapshot_path.write_text(json.dumps([snapshot]), encoding="utf-8")
            jobs_path.write_text("[]", encoding="utf-8")
            with patch.object(easy_panel, "CREATIVE_INDEX_FILE", index_path), \
                    patch.object(easy_panel, "OUTPUT", output), \
                    patch.object(easy_panel, "SNAPSHOT_FILE", snapshot_path), \
                    patch.object(easy_panel, "RPG_JOB_FILE", jobs_path), \
                    patch.object(easy_panel, "comfy_json", return_value={}):
                created = easy_panel.index_snapshot_best_effort(snapshot, status="queued")
                self.assertEqual("queued", easy_panel.get_creative_index().get_generation(created["generation_id"])["status"])
                reconciled = easy_panel.reconcile_creative_index_jobs()
                recovered = easy_panel.get_creative_index().get_generation(created["generation_id"])

            self.assertEqual(1, reconciled)
            self.assertEqual("completed", recovered["status"])
            self.assertEqual([output_name], [item["filename"] for item in recovered["artifacts"]])
            self.assertEqual([output_name], json.loads(snapshot_path.read_text(encoding="utf-8"))[0]["outputs"])

    def test_library_is_read_only_paginated_and_uses_existing_rpg_auth(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "output"
            output.mkdir()
            image_buffer = io.BytesIO()
            Image.new("RGB", (1200, 800), (12, 34, 56)).save(image_buffer, format="PNG")
            original_image = image_buffer.getvalue()
            (output / "library.png").write_bytes(original_image)
            index_path = root / "creative.sqlite3"
            index = CreativeIndex(index_path)
            result = index.upsert_snapshot({
                "id": "a" * 32,
                "createdAt": 100,
                "schemaVersion": 2,
                "promptId": "prompt-library",
                "payload": {"model": "library.safetensors", "seed": "99", "prompt": "private prompt", "width": 832, "height": 1216},
                "source": {"checkpoint": "library.safetensors"},
                "compiled": {"positive": "private prompt"},
                "workflow": {"operation": "panel.generate"},
                "outputs": ["library.png", "missing.png"],
            }, status="completed", output_root=output)
            generation_id = result["generation_id"]

            with patch.object(easy_panel, "CREATIVE_INDEX_FILE", index_path), \
                    patch.object(easy_panel, "OUTPUT", output), \
                    patch.object(easy_panel, "SNAPSHOT_FILE", root / "missing-snapshots.json"), \
                    patch.object(easy_panel, "RPG_JOB_FILE", root / "missing-jobs.json"), \
                    patch.dict(os.environ, {"EASY_PANEL_RPG_TOKEN": "library-token"}, clear=False):
                server = easy_panel.ThreadingHTTPServer(("127.0.0.1", 0), easy_panel.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    host, port = server.server_address

                    def request(method: str, path: str, headers=None, body=None):
                        connection = http.client.HTTPConnection(host, port, timeout=5)
                        connection.request(method, path, body=body, headers=headers or {})
                        response = connection.getresponse()
                        data = response.read()
                        status = response.status
                        connection.close()
                        return status, data

                    status, body = request("GET", "/api/rpg/library/generations")
                    self.assertEqual(401, status)
                    self.assertNotIn(b"private prompt", body)

                    auth = {"X-RPG-Token": "library-token"}
                    status, body = request("GET", "/api/rpg/library/generations?limit=1&status=completed", auth)
                    self.assertEqual(200, status)
                    listing = json.loads(body.decode("utf-8"))
                    self.assertEqual(1, listing["total"])
                    self.assertEqual(generation_id, listing["items"][0]["generation_id"])
                    self.assertEqual(1, listing["index_schema_version"])

                    status, body = request("GET", f"/api/rpg/library/generations/{generation_id}", auth)
                    self.assertEqual(200, status)
                    detail = json.loads(body.decode("utf-8"))["generation"]
                    self.assertEqual("private prompt", detail["snapshot"]["payload"]["prompt"])
                    self.assertFalse(detail["replay"]["can_submit"])
                    self.assertEqual("/api/rpg/image?name=library.png&type=output", detail["artifacts"][0]["url"])
                    missing = next(item for item in detail["artifacts"] if item["filename"] == "missing.png")
                    self.assertFalse(missing["exists"])
                    self.assertIsNone(missing["url"])
                    status, _body = request("GET", "/api/rpg/image?name=missing.png&type=output", auth)
                    self.assertEqual(404, status)

                    status, body = request("GET", "/api/rpg/image?name=library.png&type=output", auth)
                    self.assertEqual(200, status)
                    self.assertEqual(original_image, body)
                    status, preview = request("GET", "/api/rpg/image?name=library.png&type=output&preview=1", auth)
                    self.assertEqual(200, status)
                    self.assertTrue(preview.startswith(b"\xff\xd8"))
                    with Image.open(io.BytesIO(preview)) as preview_image:
                        self.assertEqual((360, 240), preview_image.size)

                    status, body = request("GET", f"/api/rpg/library/generations/{generation_id}/lineage", auth)
                    self.assertEqual(200, status)
                    self.assertEqual(generation_id, json.loads(body.decode("utf-8"))["lineage"]["generation_id"])

                    status, _body = request("GET", "/api/rpg/library/generations?operation=not-supported", auth)
                    self.assertEqual(400, status)
                    status, _body = request("POST", "/api/rpg/library/generations", auth, b"{}")
                    self.assertEqual(404, status)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
