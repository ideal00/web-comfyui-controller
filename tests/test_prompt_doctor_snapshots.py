import json
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


class NewFeatureUiTests(unittest.TestCase):
    def test_doctor_sources_experiment_and_snapshots_are_wired(self):
        html = Path("index.html").read_text(encoding="utf-8")
        javascript = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        for marker in ("promptAutomationControls", "promptDoctor", "experimentMode", "snapshotList"):
            self.assertIn(marker, html)
        for function in ("createStrictExperiment", "restoreSnapshot", "replaySnapshot",
                         "compareSnapshot", "attachSnapshotOutputs"):
            self.assertIn("function " + function, javascript)
        self.assertIn("promptAutomation:promptAutomationPayload()", javascript)


if __name__ == "__main__":
    unittest.main()
