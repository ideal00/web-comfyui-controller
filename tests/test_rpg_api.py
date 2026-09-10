from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from easy_panel_app import rpg_api

MODULE_PATH = Path(__file__).resolve().parents[1] / "easy_panel.py"
SPEC = importlib.util.spec_from_file_location("easy_panel_rpg_under_test", MODULE_PATH)
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


CATALOG = {
    "checkpoints": [
        "plain_sdxl.safetensors",
        "waiIllustriousSDXL_v140.safetensors",
    ],
    "anima_models": ["anima_test.safetensors"],
    "krea2_models": [],
}

PROFILES = {
    "version": 1,
    "defaults": {
        "model": "",
        "width": 832,
        "height": 1216,
        "safetyLevel": "safe",
        "style": "soft anime illustration",
        "negative": "",
        "regional": False,
    },
        "characters": {
        "luna": {
            "name": "Luna",
            "gender": "female",
            "trigger": "luna",
            "appearance": "grey hair, bob cut, blue eyes",
            "loras": [{"name": "characters/luna.safetensors", "weight": 0.9}],
            "default_outfit": "default",
            "outfits": {
                "default": "blue jacket, blue shorts",
                "maid": "maid, white apron",
            },
        },
        "meru": {
            "name": "Meru",
            "gender": "female",
            "trigger": "meru",
            "baseAppearance": "purple hair, pointy ears",
            "characterPresetId": "character-1",
            "appearancePresetId": "",
            "clothingPresetId": "clothing-1",
            "appearance_variants": {
                "variant-1": {
                    "displayName": "battle outfit",
                    "characterPresetId": "character-1",
                    "appearancePresetId": "appearance-1",
                    "clothingPresetId": "clothing-1",
                    "appearancePresetPrompt": "long hair, purple eyes",
                    "appearanceRemove": "purple hair",
                    "appearanceAdd": "short hair",
                    "clothingPrompt": "torn clothes, blue coat",
                },
            },
            "loras": [{"name": "characters/meru.safetensors", "weight": 0.85}],
            "default_outfit": "variant-1",
            "outfits": {"variant-1": "legacy outfit must not win"},
        },
    },
}


class RpgApiTests(unittest.TestCase):
    def test_default_model_prefers_wai_illustrious(self):
        selected = rpg_api.choose_rpg_model("", PROFILES["defaults"], CATALOG)
        self.assertEqual("waiIllustriousSDXL_v140.safetensors", selected)

    def test_single_character_scene_compiles_to_panel_payload(self):
        data = {
            "client": {"gameId": "demo", "sceneId": "turn15"},
            "visual": {
                "characters": [{"id": "luna", "outfit": "maid", "expression": "shy, blush",
                                "pose": "standing", "action": "looking away"}],
                "location": "school rooftop",
                "time": "sunset",
                "shot": "cowboy shot",
                "lighting": "warm rim light",
            },
            "generation": {"seed": -1},
        }
        payload = rpg_api.build_rpg_payload(data, CATALOG, PROFILES)
        self.assertEqual("waiIllustriousSDXL_v140.safetensors", payload["model"])
        self.assertEqual("RPGBox_demo_turn15", payload["filenamePrefix"])
        self.assertIn("luna", payload["promptSections"]["subject"])
        self.assertIn("grey hair", payload["promptSections"]["appearance"])
        self.assertIn("maid", payload["promptSections"]["clothing"])
        self.assertIn("shy", payload["promptSections"]["pose"])
        self.assertIn("school rooftop", payload["promptSections"]["scene"])
        self.assertEqual("characters/luna.safetensors", payload["loras"][0]["name"])

    def test_person_and_style_loras_are_reported_as_separate_layers(self):
        data = {
            "visual": {
                "characters": [{"id": "luna", "outfit": "maid"}],
                "location": "quiet cafe",
            },
            "generation": {
                "model": "waiIllustriousSDXL_v140.safetensors",
                "style": "rella",
                "styleFamily": "Illustrious",
                "styleLoras": [{
                    "name": "Illustrious_Hosiery_Test/03_通用功能/Rella画师风格.safetensors",
                    "weight": 0.75,
                }],
                "loras": [{
                    "name": "Illustrious_Hosiery_Test/03_通用功能/Rella画师风格.safetensors",
                    "weight": 0.75,
                }],
            },
        }
        payload = rpg_api.build_rpg_payload(data, CATALOG, PROFILES)
        self.assertEqual("characters/luna.safetensors", payload["characterLoras"][0]["name"])
        self.assertEqual("Illustrious_Hosiery_Test/03_通用功能/Rella画师风格.safetensors",
                         payload["styleLoras"][0]["name"])
        self.assertEqual(["characters/luna.safetensors",
                          "Illustrious_Hosiery_Test/03_通用功能/Rella画师风格.safetensors"],
                         [item["name"] for item in payload["loras"]])
        self.assertIn("rella", payload["promptSections"]["style"])
        with self.assertRaisesRegex(ValueError, "不兼容"):
            rpg_api.build_rpg_payload({
                "visual": {"characters": [{"id": "luna"}], "location": "cafe"},
                "generation": {
                    "model": "anima_test.safetensors",
                    "style": "rella",
                    "styleFamily": "Illustrious",
                    "styleLoras": [{"name": "Illustrious/style.safetensors", "weight": 0.8}],
                },
            }, CATALOG, PROFILES)

    def test_two_character_regional_request_builds_existing_regional_workflow(self):
        data = {
            "visual": {
                "characters": [
                    {"id": "luna", "action": "holding hands"},
                    {"id": "meru", "action": "holding hands"},
                ],
                "location": "city street",
                "shot": "two shot",
                "groupAction": "holding hands",
            },
            "generation": {"regional": True},
        }
        payload = rpg_api.build_rpg_payload(data, CATALOG, PROFILES)
        self.assertEqual(2, len(payload["regions"]))
        self.assertEqual("characters/luna.safetensors", payload["regions"][0]["lora"])
        self.assertEqual("characters/meru.safetensors", payload["regions"][1]["lora"])
        triggers = [
            ("characters/luna.safetensors", "luna"),
            ("characters/meru.safetensors", "meru"),
        ]
        with patch.object(easy_panel, "checkpoint_issue", return_value=None), \
                patch.object(easy_panel, "selected_lora_trigger_entries", return_value=triggers):
            workflow = easy_panel.build_workflow(payload)["prompt"]
        self.assertEqual(2, sum(node["class_type"] == "CreateHookLora" for node in workflow.values()))
        save_nodes = [node for node in workflow.values() if node["class_type"] == "SaveImage"]
        self.assertEqual(1, len(save_nodes))
        self.assertTrue(save_nodes[0]["inputs"]["filename_prefix"].startswith("RPGBox_"))

    def test_quality_profiles_are_family_specific_and_forwarded(self):
        illustrious = rpg_api.build_rpg_payload({
            "visual": {"characters": [{"id": "luna"}], "location": "market"},
            "generation": {"quality": "fast"},
        }, CATALOG, PROFILES)
        self.assertEqual(20, illustrious["steps"])
        self.assertEqual(5.0, illustrious["cfg"])
        self.assertEqual("euler_ancestral", illustrious["sampler"])
        self.assertEqual("normal", illustrious["scheduler"])

        anima = rpg_api.build_rpg_payload({
            "visual": {"characters": [{"id": "meru"}], "location": "cafe"},
            "generation": {"model": "anima_test.safetensors", "quality": "detailed"},
        }, CATALOG, PROFILES)
        self.assertEqual(42, anima["steps"])
        self.assertEqual(5.0, anima["cfg"])
        self.assertEqual("er_sde", anima["sampler"])
        self.assertEqual("simple", anima["scheduler"])
        self.assertFalse(anima["regions"])

    def test_appearance_variant_uses_references_and_keeps_layers_separate(self):
        data = {
            "visual": {
                "characters": [{"id": "meru", "outfit": "variant-1"}],
                "location": "city street",
            },
            "generation": {},
        }
        payload = rpg_api.build_rpg_payload(data, CATALOG, PROFILES)
        self.assertIn("long hair", payload["promptSections"]["appearance"])
        self.assertIn("short hair", payload["promptSections"]["appearance"])
        self.assertNotIn("purple hair", payload["promptSections"]["appearance"])
        self.assertEqual("torn clothes, blue coat", payload["promptSections"]["clothing"])
        character = rpg_api._character_prompt({"id": "meru", "outfit": "variant-1"}, PROFILES["characters"]["meru"])
        self.assertEqual("appearance-1", character["appearance_preset_id"])
        self.assertIn("torn clothes", character["outfit"])

    def test_plain_role_profile_has_no_synthetic_lora_or_character_trigger(self):
        profiles = {
            **PROFILES,
            "characters": {
                **PROFILES["characters"],
                "plain": {
                    "name": "Plain Card",
                    "mode": "plain",
                    "plainAppearancePrompt": "short brown hair, blue eyes, casual jacket",
                    "gender": "female",
                    "loras": [{"name": "must-not-load.safetensors", "weight": 1.0}],
                },
            },
        }
        character = rpg_api._character_prompt({"id": "plain", "outfit": ""}, profiles["characters"]["plain"])
        self.assertEqual("plain", character["mode"])
        self.assertEqual([], character["loras"])
        self.assertNotIn("plain", character["prompt"])
        self.assertIn("short brown hair", character["prompt"])

        payload = rpg_api.build_rpg_payload({
            "visual": {"characters": [{"id": "plain"}], "location": "city street"},
            "generation": {"model": "waiIllustriousSDXL_v140.safetensors"},
        }, CATALOG, profiles)
        self.assertEqual([], payload["loras"])
        self.assertIn("short brown hair", payload["promptSections"]["appearance"])

    def test_history_status_returns_mobile_image_url(self):
        history = {
            "12345678-1234-1234-1234-123456789abc": {
                "outputs": {"9": {"images": [{"filename": "RPGBox_demo_00001_.png", "type": "output"}]}},
                "status": {"status_str": "success"},
            }
        }
        with patch.object(rpg_api, "find_rpg_job", return_value={"model": "wai"}):
            status = rpg_api.history_to_rpg_status("12345678-1234-1234-1234-123456789abc", history)
        self.assertEqual("completed", status["status"])
        self.assertEqual("/api/rpg/image?name=RPGBox_demo_00001_.png&type=output", status["images"][0]["url"])


    def test_history_status_preserves_output_subfolder(self):
        prompt_id = "12345678-1234-1234-1234-123456789abc"
        history = {
            prompt_id: {
                "outputs": {"9": {"images": [{
                    "filename": "scene.png",
                    "subfolder": "RPG/chapter1",
                    "type": "output",
                }]}},
                "status": {"status_str": "success"},
            }
        }
        with patch.object(rpg_api, "find_rpg_job", return_value={}):
            status = rpg_api.history_to_rpg_status(prompt_id, history)
        self.assertIn("subfolder=RPG%2Fchapter1", status["images"][0]["url"])

    def test_history_status_hides_the_hires_first_pass(self):
        prompt_id = "12345678-1234-1234-1234-123456789abc"
        history = {
            prompt_id: {
                "outputs": {
                    "7": {"images": [{"filename": "RPGBox_scene_base_00001_.png", "type": "output"}]},
                    "12": {"images": [{"filename": "RPGBox_scene_00001_.png", "type": "output"}]},
                },
                "status": {"status_str": "success"},
            }
        }
        with patch.object(rpg_api, "find_rpg_job", return_value={}):
            status = rpg_api.history_to_rpg_status(prompt_id, history)
        self.assertEqual(["RPGBox_scene_00001_.png"],
                         [image["filename"] for image in status["images"]])

        only_base = {
            prompt_id: {
                "outputs": {
                    "7": {"images": [{"filename": "RPGBox_scene_base_00001_.png", "type": "output"}]},
                },
                "status": {"status_str": "success"},
            }
        }
        with patch.object(rpg_api, "find_rpg_job", return_value={}):
            fallback = rpg_api.history_to_rpg_status(prompt_id, only_base)
        self.assertEqual(["RPGBox_scene_base_00001_.png"],
                         [image["filename"] for image in fallback["images"]])

    def test_request_id_job_recovery(self):
        rows = [
            {"prompt_id": "old", "request_id": "scene_1"},
            {"prompt_id": "new", "request_id": "scene_1"},
        ]
        with patch.object(rpg_api, "_load_rpg_jobs_unlocked", return_value=rows):
            self.assertEqual("new", rpg_api.find_rpg_job_by_request_id("scene_1")["prompt_id"])

    def test_token_is_optional_normally_and_enforced_when_configured(self):
        with patch.dict(os.environ, {"EASY_PANEL_RPG_TOKEN": ""}):
            self.assertTrue(rpg_api.check_rpg_token("anything"))
        with patch.dict(os.environ, {"EASY_PANEL_RPG_TOKEN": "secret-token"}):
            self.assertTrue(rpg_api.check_rpg_token("secret-token"))
            self.assertFalse(rpg_api.check_rpg_token("wrong"))


if __name__ == "__main__":
    unittest.main()
