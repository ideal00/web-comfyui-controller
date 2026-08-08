from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "easy_panel.py"
SPEC = importlib.util.spec_from_file_location("easy_panel_under_test", MODULE_PATH)
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


def regional_payload() -> dict:
    return {
        "model": "waiIllustriousSDXL_test.safetensors",
        "loras": [
            {"name": "characters/alice.safetensors", "weight": 0.8},
            {"name": "characters/bob.safetensors", "weight": 0.7},
            {"name": "styles/soft.safetensors", "weight": 0.35},
        ],
        "promptSections": {
            "subject": "2girls, alice, bob",
            "appearance": "blue hair, red hair",
            "clothing": "white dress, black jacket",
            "pose": "standing together",
            "composition": "two shot",
            "scene": "classroom",
            "lighting": "afternoon sunlight",
            "style": "soft anime illustration",
            "manual": "alice on the left, bob on the right",
        },
        "negative": "",
        "width": 1216,
        "height": 832,
        "steps": 24,
        "cfg": 5,
        "regions": [
            {"name": "Alice", "subject": "1girl", "lora": "characters/alice.safetensors",
             "prompt": "alice, blue hair, white dress, hug, kiss", "x": 0, "y": 0,
             "width": 0.5, "height": 1, "strength": 1},
            {"name": "Bob", "subject": "1girl", "lora": "characters/bob.safetensors",
             "prompt": "bob, red hair, black jacket, hug, kiss", "x": 0.5, "y": 0,
             "width": 0.5, "height": 1, "strength": 1},
        ],
    }


class RegionalPromptingTests(unittest.TestCase):
    def build(self, data: dict) -> dict:
        triggers = [
            ("characters/alice.safetensors", "alice_trigger"),
            ("characters/bob.safetensors", "bob_trigger"),
            ("styles/soft.safetensors", "soft_style"),
        ]
        with patch.object(easy_panel, "checkpoint_issue", return_value=None), \
                patch.object(easy_panel, "selected_lora_trigger_entries", return_value=triggers):
            return easy_panel.build_workflow(data)["prompt"]

    def test_character_loras_and_prompts_are_region_isolated(self):
        nodes = self.build(regional_payload())
        by_type = lambda class_type: [node for node in nodes.values()
                                      if node["class_type"] == class_type]

        self.assertEqual(2, len(by_type("CreateHookLora")))
        self.assertEqual(2, len(by_type("SetClipHooks")))
        self.assertEqual(2, len(by_type("ConditioningSetMask")))
        self.assertEqual(2, len(by_type("FeatherMask")))
        self.assertEqual(2, len(by_type("MaskComposite")))
        self.assertEqual(1, len(by_type("ConditioningSetDefaultCombine")))
        self.assertEqual([0, 559], sorted(node["inputs"]["x"]
                                          for node in by_type("MaskComposite")))
        feather_edges = [node["inputs"] for node in by_type("FeatherMask")]
        self.assertEqual([97], [item["right"] for item in feather_edges if item["right"]])
        self.assertEqual([97], [item["left"] for item in feather_edges if item["left"]])

        globally_loaded = [node["inputs"]["lora_name"] for node in by_type("LoraLoader")]
        self.assertEqual(["styles/soft.safetensors"], globally_loaded)

        default_node = by_type("ConditioningSetDefaultCombine")[0]
        base_encode_id = default_node["inputs"]["cond_DEFAULT"][0]
        base_prompt = nodes[base_encode_id]["inputs"]["text"].lower()
        self.assertIn("classroom", base_prompt)
        self.assertIn("soft_style", base_prompt)
        self.assertNotIn("alice", base_prompt)
        self.assertNotIn("bob", base_prompt)
        self.assertNotIn("blue hair", base_prompt)
        self.assertNotIn("red hair", base_prompt)
        self.assertIn("2girls", base_prompt)
        self.assertIn("single continuous scene", base_prompt)
        self.assertIn("hug", base_prompt)
        self.assertIn("kiss", base_prompt)

        negative_prompt = next(node["inputs"]["text"].lower() for node in by_type("CLIPTextEncode")
                               if "split screen" in node["inputs"]["text"].lower())
        self.assertIn("1boy", negative_prompt)
        self.assertIn("male", negative_prompt)
        self.assertIn("collage", negative_prompt)

        hooked_clip_ids = {node_id for node_id, node in nodes.items()
                           if node["class_type"] == "SetClipHooks"}
        local_prompts = [node["inputs"]["text"].lower() for node in nodes.values()
                         if node["class_type"] == "CLIPTextEncode"
                         and isinstance(node["inputs"]["clip"], list)
                         and node["inputs"]["clip"][0] in hooked_clip_ids]
        self.assertEqual(2, len(local_prompts))
        alice_prompt = next(text for text in local_prompts if "alice_trigger" in text)
        bob_prompt = next(text for text in local_prompts if "bob_trigger" in text)
        self.assertNotIn("bob_trigger", alice_prompt)
        self.assertNotIn("red hair", alice_prompt)
        self.assertNotIn("hug", alice_prompt)
        self.assertIn("character on the left", alice_prompt)
        self.assertNotIn("alice_trigger", bob_prompt)
        self.assertNotIn("blue hair", bob_prompt)
        self.assertNotIn("kiss", bob_prompt)
        self.assertIn("character on the right", bob_prompt)

    def test_excessive_overlapping_regions_are_rejected(self):
        data = regional_payload()
        data["regions"][1]["x"] = 0.1
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            with self.assertRaisesRegex(ValueError, "区域发生重叠"):
                easy_panel.build_workflow(data)

    def test_modest_overlap_is_allowed_for_soft_transition(self):
        data = regional_payload()
        data["regions"][0]["width"] = 0.54
        data["regions"][1]["x"] = 0.46
        data["regions"][1]["width"] = 0.54
        nodes = self.build(data)
        self.assertEqual(2, sum(node["class_type"] == "ConditioningSetMask"
                                for node in nodes.values()))

    def test_single_filled_region_is_rejected(self):
        data = regional_payload()
        data["regions"][1]["prompt"] = ""
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            with self.assertRaisesRegex(ValueError, "至少需要两个"):
                easy_panel.build_workflow(data)

    def test_weak_region_strength_is_raised_to_safe_minimum(self):
        data = regional_payload()
        data["regions"][0]["strength"] = 0.25
        nodes = self.build(data)
        strengths = [node["inputs"]["strength"] for node in nodes.values()
                     if node["class_type"] == "ConditioningSetMask"]
        self.assertEqual([0.75, 1.0], strengths)


if __name__ == "__main__":
    unittest.main()
