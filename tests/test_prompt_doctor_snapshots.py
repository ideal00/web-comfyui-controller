import base64
import json
import http.client
import os
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import easy_panel


def prompt_payload(**overrides):
    data = {
        "model": "waiIllustriousSDXL_v140.safetensors",
        "loras": [],
        "promptSections": {
            "subject": "1girl, solo",
            "appearance": "(high ponytail:1.4)",
            "clothing": "",
            "pose": "standing",
            "composition": "",
            "scene": "simple background",
            "lighting": "neutral lighting",
            "style": "",
            "manual": "",
        },
        "negative": "hair down, loose hair",
        "safetyLevel": "nsfw",
        "promptMode": "custom",
        "seed": "123456789012345678",
        "width": 832,
        "height": 1216,
    }
    data.update(overrides)
    return data


class PromptDoctorTests(unittest.TestCase):
    def test_weighted_hairstyle_and_opposing_negative_are_reported(self):
        result = easy_panel.compile_prompt(prompt_payload())
        codes = [item["code"] for item in result["diagnostics"]]
        self.assertIn("high-weight", codes)
        self.assertIn("hairstyle-pull", codes)

    def test_positive_negative_exact_conflict_is_reported(self):
        data = prompt_payload(negative="standing")
        result = easy_panel.compile_prompt(data)
        self.assertIn("positive-negative", [item["code"] for item in result["diagnostics"]])

    def test_every_automatic_source_can_be_disabled(self):
        switches = {key: False for key in easy_panel.prompt_automation({})}
        data = prompt_payload(
            promptAutomation=switches,
            promptSections={**prompt_payload()["promptSections"], "scene": ""},
            negative="",
        )
        result = easy_panel.compile_prompt(data)
        self.assertNotIn("masterpiece", result["positive"])
        self.assertNotIn("simple background", result["positive"])
        self.assertEqual(result["negative"], "")
        self.assertTrue(all(not item["enabled"] for item in result["sources"]
                            if item["key"] in switches))


class SnapshotTests(unittest.TestCase):
    def test_snapshot_preserves_exact_payload_and_compiled_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot_file = Path(folder) / "snapshots.json"
            with patch.object(easy_panel, "SNAPSHOT_FILE", snapshot_file):
                snapshot = easy_panel.create_generation_snapshot(prompt_payload(), "prompt-1")
                stored = json.loads(snapshot_file.read_text(encoding="utf-8"))
                self.assertEqual(stored[0]["id"], snapshot["id"])
                self.assertEqual(stored[0]["payload"]["seed"], "123456789012345678")
                self.assertIn("sources", stored[0]["compiled"])
                easy_panel.attach_snapshot_outputs(snapshot["id"], ["EasyPanel_00001_.png"])
                self.assertEqual(easy_panel.load_snapshots()[0]["outputs"],
                                 ["EasyPanel_00001_.png"])

    def test_schema_v2_source_keeps_reproducible_sections_and_safe_traces(self):
        data = prompt_payload(
            model="model.safetensors",
            characterLoras=[{"name": "characters/luna.safetensors", "weight": 0.85}],
            loras=[{"name": "characters/luna.safetensors", "weight": 0.85}],
            vae={"mode": "tiled", "tileSize": 512, "token": "must-not-leak"},
            regions=[{"name": "left", "prompt": "luna", "x": 0, "y": 0, "width": 0.5, "height": 1}],
            regionGlobalPrompt="shared cafe interaction",
            repair={"image": "source.png", "mask": "mask.png", "denoise": 0.4},
            modelEnhancement={"mode": "freeu_v2", "b1": 1.3},
            colorCorrection={"enabled": True, "brightness": "1.05", "grayPoint": "1.1"},
            transparentBackground={"mode": "complex", "detailMethod": "PyMatting", "maxMegapixels": 2},
            pose={"enabled": True, "poseJson": "[{\"people\": []}]", "strength": 0.8},
            outputEnhancement={"mode": "anime6b", "scale": 2},
            guidance={"mode": "sag", "sagScale": 0.4},
        )
        request = {
            "client": {"gameId": "demo", "sceneId": "turn-1", "requestId": "request-1"},
            "visual": {"characters": [{"id": "luna", "appearance": "blue eyes", "outfit": "dress"}]},
            "generation": {"seed": "123456789012345678"},
        }
        with tempfile.TemporaryDirectory() as folder:
            snapshot_file = Path(folder) / "snapshots.json"
            with patch.object(easy_panel, "SNAPSHOT_FILE", snapshot_file), \
                    patch.object(easy_panel, "selected_lora_trigger_entries",
                                  return_value=[("characters/luna.safetensors", "luna")]):
                snapshot = easy_panel.create_generation_snapshot(data, "prompt-1", request)
                source = snapshot["source"]
                self.assertEqual(2, snapshot["schemaVersion"])
                self.assertEqual("model.safetensors", source["checkpoint"])
                self.assertEqual("tiled", source["vae"]["mode"])
                self.assertNotIn("token", source["vae"])
                self.assertEqual("luna", source["loras"][0]["trigger"])
                self.assertEqual("characters/luna.safetensors", source["loras"][0]["name"])
                self.assertEqual("123456789012345678", source["generation"]["seed"])
                self.assertEqual("anime6b", source["enhancements"]["outputEnhancement"]["mode"])
                self.assertEqual("source.png", source["enhancements"]["repair"]["image"])
                self.assertEqual("shared cafe interaction", source["regionGlobalPrompt"])
                self.assertEqual("freeu_v2", source["enhancements"]["modelEnhancement"]["mode"])
                self.assertEqual("1.05", source["enhancements"]["colorCorrection"]["brightness"])
                self.assertEqual("PyMatting", source["enhancements"]["transparentBackground"]["detailMethod"])
                self.assertEqual("[{\"people\": []}]", source["enhancements"]["pose"]["poseJson"])
                self.assertEqual(0.4, source["enhancements"]["guidance"]["sagScale"])
                self.assertEqual("left", source["regions"][0]["name"])
                self.assertEqual("rpg.generate", snapshot["workflow"]["operation"])
                self.assertIn("profile", snapshot["compiled"])
                self.assertIn("sources", snapshot["compiled"])
                self.assertIn("automation", snapshot["compiled"])
                self.assertIn("diagnostics", snapshot["compiled"])
                self.assertIn("deduplication", snapshot["compiled"])
                self.assertIn("sampling", snapshot["compiled"])
                self.assertEqual("sdxl", source["modelStrategy"]["family"])
                self.assertEqual("model.safetensors", snapshot["compiled"]["sampling"]["model"])
                self.assertIsInstance(snapshot["compiled"]["sampling"]["reasons"], list)
                self.assertIsInstance(snapshot["compiled"]["positive"], str)
                self.assertIsInstance(snapshot["compiled"]["negative"], str)
                self.assertTrue(snapshot["compiled"]["automation"]["loraTriggers"])
                self.assertEqual(snapshot["compiled"]["deduplication"]["positiveFinal"],
                                 snapshot["compiled"]["positiveTerms"])

    def test_rpg_payload_snapshot_and_restore_sources_keep_roles_scene_and_loras(self):
        request = {
            "client": {"gameId": "demo", "sceneId": "tea", "requestId": "request-tea"},
            "visual": {
                "characters": [
                    {
                        "id": "luna", "name": "Luna", "gender": "female",
                        "appearance": "blue eyes", "outfitPrompt": "blue dress", "pose": "standing",
                        "loras": [{"name": "characters/luna.safetensors", "weight": 0.8}],
                    },
                    {
                        "id": "kai", "name": "Kai", "gender": "male",
                        "appearance": "silver hair", "outfitPrompt": "black coat", "pose": "sitting",
                        "loras": [{"name": "characters/kai.safetensors", "weight": 0.7}],
                    },
                ],
                "location": "quiet cafe", "scene": "at sunset", "lighting": "warm light",
                "shot": "medium shot", "groupAction": "sharing tea",
            },
            "generation": {
                "model": "waiIllustriousSDXL_v140.safetensors", "quality": "balanced",
                "seed": "123456789", "regional": True,
            },
        }
        catalog = {
            "checkpoints": ["waiIllustriousSDXL_v140.safetensors"],
            "anima_models": [], "krea2_models": [],
        }
        profiles = {"defaults": {}, "characters": {}}
        with tempfile.TemporaryDirectory() as folder:
            snapshot_file = Path(folder) / "snapshots.json"
            with patch.object(easy_panel, "SNAPSHOT_FILE", snapshot_file), \
                    patch.object(easy_panel, "selected_lora_trigger_entries", return_value=[
                        ("characters/luna.safetensors", "luna_trigger"),
                        ("characters/kai.safetensors", "kai_trigger"),
                    ]):
                payload = easy_panel.build_rpg_payload(request, catalog, profiles)
                snapshot = easy_panel.create_generation_snapshot(payload, "prompt-tea", request)
                source = snapshot["source"]
                positive = snapshot["compiled"]["positive"]
                self.assertEqual(["luna", "kai"], [item["id"] for item in source["characters"]])
                self.assertEqual(2, len(source["loras"]))
                self.assertEqual({"character"}, {item["role"] for item in source["loras"]})
                self.assertEqual({"luna_trigger", "kai_trigger"},
                                 {item["trigger"] for item in source["loras"]})
                self.assertEqual(2, len(source["regions"]))
                self.assertEqual("quiet cafe, at sunset", source["scene"])
                self.assertEqual("sharing tea", source["regionGlobalPrompt"])
                self.assertEqual(1, positive.count("luna_trigger"))
                self.assertEqual(1, positive.count("kai_trigger"))
                self.assertEqual(1, positive.count("quiet cafe"))
                self.assertEqual(1, positive.count("at sunset"))

    def test_legacy_snapshot_is_normalized_without_rewriting_its_exact_payload(self):
        payload = prompt_payload(negative="legacy negative", prompt="legacy prompt")
        legacy = {
            "id": "a" * 32,
            "createdAt": 123,
            "promptId": "prompt-legacy",
            "outputs": ["legacy.png"],
            "payload": payload,
            "compiled": {"positive": "legacy final positive"},
        }
        normalized = easy_panel.normalize_generation_snapshot(legacy)
        self.assertEqual(2, normalized["schemaVersion"])
        self.assertEqual(payload, normalized["payload"])
        self.assertEqual("legacy final positive", normalized["compiled"]["positive"])
        self.assertEqual("legacy negative", normalized["source"]["negative"])
        self.assertEqual("panel.generate", normalized["workflow"]["operation"])
        self.assertEqual(["legacy.png"], normalized["outputs"])

    def test_mobile_snapshot_api_requires_token_and_returns_summary_then_detail(self):
        payload = prompt_payload(seed="123456789012345678")
        legacy = {
            "id": "b" * 32,
            "createdAt": 456,
            "promptId": "prompt-mobile",
            "outputs": [],
            "payload": payload,
        }
        with tempfile.TemporaryDirectory() as folder:
            snapshot_file = Path(folder) / "snapshots.json"
            snapshot_file.write_text(json.dumps([legacy], ensure_ascii=False), encoding="utf-8")
            with patch.object(easy_panel, "SNAPSHOT_FILE", snapshot_file), \
                    patch.dict(os.environ, {"EASY_PANEL_RPG_TOKEN": "local-token"}, clear=False):
                server = easy_panel.ThreadingHTTPServer(("127.0.0.1", 0), easy_panel.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    host, port = server.server_address
                    connection = http.client.HTTPConnection(host, port, timeout=5)
                    connection.request("GET", "/api/rpg/snapshots")
                    response = connection.getresponse()
                    self.assertEqual(401, response.status)
                    response.read()

                    connection.request("GET", "/api/rpg/snapshots?limit=5",
                                       headers={"X-RPG-Token": "local-token"})
                    response = connection.getresponse()
                    self.assertEqual(200, response.status)
                    listing = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(1, len(listing["snapshots"]))
                    self.assertEqual(2, listing["snapshots"][0]["schemaVersion"])
                    self.assertNotIn("payload", listing["snapshots"][0])

                    connection.request("GET", "/api/rpg/snapshots/" + legacy["id"],
                                       headers={"X-RPG-Token": "local-token"})
                    response = connection.getresponse()
                    self.assertEqual(200, response.status)
                    detail = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload, detail["snapshot"]["payload"])
                    self.assertEqual(2, detail["snapshot"]["schemaVersion"])
                    connection.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

    def test_remote_snapshot_detail_compare_and_output_require_authentication(self):
        payload = prompt_payload(seed="987654321")
        snapshot_id = "c" * 32
        legacy = {
            "id": snapshot_id,
            "createdAt": 789,
            "promptId": "prompt-remote",
            "outputs": ["secret.png"],
            "payload": payload,
        }

        class RemoteAddressServer(easy_panel.ThreadingHTTPServer):
            def get_request(self):
                request, _address = super().get_request()
                # Keep a real TCP/HTTP exchange but exercise the non-loopback
                # authorization branch deterministically on every CI host.
                return request, ("192.0.2.10", 12345)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot_file = root / "snapshots.json"
            output_dir = root / "output"
            output_dir.mkdir()
            (output_dir / "secret.png").write_bytes(b"private-output")
            snapshot_file.write_text(json.dumps([legacy], ensure_ascii=False), encoding="utf-8")
            with patch.object(easy_panel, "SNAPSHOT_FILE", snapshot_file), \
                    patch.object(easy_panel, "OUTPUT", output_dir), \
                    patch.dict(os.environ, {"EASY_PANEL_RPG_TOKEN": "remote-token"}, clear=False):
                server = RemoteAddressServer(("127.0.0.1", 0), easy_panel.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    host, port = server.server_address

                    def request(path, headers=None):
                        connection = http.client.HTTPConnection(host, port, timeout=5)
                        connection.request("GET", path, headers=headers or {})
                        response = connection.getresponse()
                        body = response.read()
                        cookie = response.getheader("Set-Cookie", "")
                        connection.close()
                        return response.status, body, cookie

                    status, body, _ = request("/api/snapshots")
                    self.assertEqual(401, status)
                    self.assertNotIn(b"987654321", body)

                    status, body, _ = request("/api/rpg/snapshots/" + snapshot_id)
                    self.assertEqual(401, status)
                    self.assertNotIn(b"987654321", body)

                    status, body, _ = request("/api/snapshot-compare?id=" + snapshot_id)
                    self.assertEqual(401, status)
                    self.assertNotIn(b"987654321", body)

                    status, body, _ = request("/output?name=secret.png")
                    self.assertEqual(401, status)
                    self.assertNotIn(b"private-output", body)

                    status, body, _ = request("/api/rpg/image?name=secret.png")
                    self.assertEqual(401, status)
                    self.assertNotIn(b"private-output", body)

                    status, body, cookie = request("/api/snapshots", {"X-RPG-Token": "remote-token"})
                    self.assertEqual(200, status)
                    self.assertIn(b"987654321", body)
                    self.assertIn("HttpOnly", cookie)
                    session_cookie = cookie.split(";", 1)[0]

                    status, body, _ = request("/api/snapshot-compare?id=" + snapshot_id,
                                              {"Cookie": session_cookie})
                    self.assertEqual(200, status)
                    self.assertIn(b"987654321", body)

                    status, body, _ = request("/output?name=secret.png", {"Cookie": session_cookie})
                    self.assertEqual(200, status)
                    self.assertEqual(b"private-output", body)

                    basic = base64.b64encode(b"easy-panel:remote-token").decode("ascii")
                    status, body, cookie = request("/api/snapshots", {"Authorization": "Basic " + basic})
                    self.assertEqual(200, status)
                    self.assertIn(b"987654321", body)
                    self.assertIn("HttpOnly", cookie)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)


class NewFeatureUiTests(unittest.TestCase):
    def test_doctor_sources_experiment_and_snapshots_are_wired(self):
        html = Path("index.html").read_text(encoding="utf-8")
        javascript = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        snapshot_flow = Path("web/assets/js/snapshot-flow.js").read_text(encoding="utf-8")
        for marker in ("promptAutomationControls", "promptDoctor", "experimentMode", "snapshotList"):
            self.assertIn(marker, html)
        for function in ("createStrictExperiment", "restoreSnapshot", "replaySnapshot",
                         "compareSnapshot", "attachSnapshotOutputs"):
            self.assertIn("function " + function, javascript)
        self.assertIn("promptAutomation:promptAutomationPayload()", javascript)
        self.assertIn("snapshot-flow.js", html)
        for function in ("sourceTrace", "restoreAdvancedPayload", "restoreSnapshotSeedOnly", "continueSnapshotEdit"):
            self.assertIn(function, snapshot_flow)
        for marker in ("deduplication", "最终 positive", "自动注入开关", "为什么这样取值"):
            self.assertIn(marker, snapshot_flow)


if __name__ == "__main__":
    unittest.main()
