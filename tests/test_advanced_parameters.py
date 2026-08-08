from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "easy_panel.py"
SPEC = importlib.util.spec_from_file_location("easy_panel_advanced_test", MODULE_PATH)
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


def payload(model: str) -> dict:
    return {
        "model": model,
        "promptSections": {"subject": "1girl", "scene": "studio"},
        "negative": "",
        "width": 768,
        "height": 1024,
        "steps": 17,
        "cfg": 4.2,
        "sampler": "dpmpp_2m",
        "scheduler": "beta",
        "guidance": {"mode": "off"},
    }


class SamplingProfileTests(unittest.TestCase):
    def build(self, data: dict) -> dict:
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            return easy_panel.build_workflow(data)["prompt"]

    @staticmethod
    def nodes_of(nodes: dict, class_type: str) -> list[dict]:
        return [node for node in nodes.values() if node["class_type"] == class_type]

    def test_installed_model_recommendations_match_validated_profiles(self):
        expected = {
            "spectacularAnimeILXL_10.safetensors": (30, 5.0, "dpmpp_2m_sde", "simple"),
            "milmuAnimeIllustriousXL_vPred01.safetensors": (30, 5.5, "dpmpp_2m_sde", "karras"),
            "gockSoAnimeLoveSong_gocksoanimeLoveSong.safetensors": (30, 7.0, "dpmpp_2m_sde", "karras"),
            "anima-base-v1.0.safetensors": (34, 4.8, "er_sde", "simple"),
            "krea2TurboOfficialComfy_krea2TurboFp8.safetensors": (8, 1.0, "euler", "simple"),
        }
        for model, values in expected.items():
            with self.subTest(model=model):
                profile = easy_panel.model_sampling_profile(model)
                self.assertEqual(values, (profile["steps"], profile["cfg"],
                                          profile["sampler"], profile["scheduler"]))
                self.assertTrue(profile["combos"])
                self.assertNotIn(profile["label"], {"推荐", "官方 Turbo"})

    def test_manual_override_reaches_non_locked_ksampler(self):
        nodes = self.build(payload("waiIllustriousSDXL_v140.safetensors"))
        sampler = self.nodes_of(nodes, "KSampler")[0]["inputs"]
        self.assertEqual((17, 4.2, "dpmpp_2m", "beta"),
                         (sampler["steps"], sampler["cfg"],
                          sampler["sampler_name"], sampler["scheduler"]))

    def test_krea2_locked_contract_ignores_manual_values(self):
        nodes = self.build(payload("krea2TurboOfficialComfy_krea2TurboFp8.safetensors"))
        sampler = self.nodes_of(nodes, "KSampler")[0]["inputs"]
        self.assertEqual((8, 1.0, "euler", "simple"),
                         (sampler["steps"], sampler["cfg"],
                          sampler["sampler_name"], sampler["scheduler"]))

    def test_sag_and_pag_create_real_model_patch_nodes(self):
        for mode, class_type in (("sag", "SelfAttentionGuidance"),
                                 ("pag", "PerturbedAttentionGuidance")):
            data = payload("waiIllustriousSDXL_v140.safetensors")
            data["guidance"] = {"mode": mode, "sagScale": 0.4,
                                "sagBlur": 2.0, "pagScale": 1.8}
            nodes = self.build(data)
            self.assertEqual(1, len(self.nodes_of(nodes, class_type)))
            sampler_model = self.nodes_of(nodes, "KSampler")[0]["inputs"]["model"]
            patch_ids = {node_id for node_id, node in nodes.items()
                         if node["class_type"] == class_type}
            self.assertIn(sampler_model[0], patch_ids)

    def test_unsupported_or_conflicting_guidance_is_rejected(self):
        krea = payload("krea2TurboOfficialComfy_krea2TurboFp8.safetensors")
        krea["guidance"] = {"mode": "pag"}
        with self.assertRaisesRegex(ValueError, "不支持 SAG/PAG"):
            self.build(krea)

        regional = payload("waiIllustriousSDXL_v140.safetensors")
        regional["guidance"] = {"mode": "sag"}
        regional["regions"] = [
            {"prompt": "alice, blue hair", "subject": "1girl",
             "x": 0, "y": 0, "width": 0.54, "height": 1},
            {"prompt": "bob, red hair", "subject": "1girl",
             "x": 0.46, "y": 0, "width": 0.54, "height": 1},
        ]
        with self.assertRaisesRegex(ValueError, "多人分区不能同时启用"):
            self.build(regional)

    def test_hires_controls_reach_second_sampler(self):
        data = payload("waiIllustriousSDXL_v140.safetensors")
        data.update({"illustriousMode": "hires", "hiresScale": 1.2,
                     "hiresDenoise": 0.25, "hiresSteps": 16, "hiresCfg": 4.0})
        nodes = self.build(data)
        samplers = self.nodes_of(nodes, "KSampler")
        self.assertEqual(2, len(samplers))
        second = samplers[1]["inputs"]
        self.assertEqual((16, 4.0, 0.25),
                         (second["steps"], second["cfg"], second["denoise"]))
        upscale = self.nodes_of(nodes, "LatentUpscaleBy")[0]["inputs"]
        self.assertEqual(1.2, upscale["scale_by"])

    def test_milmu_keeps_v_prediction_node_with_new_sampler(self):
        data = payload("milmuAnimeIllustriousXL_vPred01.safetensors")
        data["sampler"] = "auto"
        data["scheduler"] = "auto"
        data["steps"] = 30
        data["cfg"] = 5.5
        nodes = self.build(data)
        model_sampling = self.nodes_of(nodes, "ModelSamplingDiscrete")
        self.assertEqual("v_prediction", model_sampling[0]["inputs"]["sampling"])
        sampler = self.nodes_of(nodes, "KSampler")[0]["inputs"]
        self.assertEqual(("dpmpp_2m_sde", "karras"),
                         (sampler["sampler_name"], sampler["scheduler"]))


class BatchQueueTests(unittest.TestCase):
    def test_twenty_two_tasks_with_three_images_expand_to_sixty_six(self):
        jobs = [{"prompt": f"task {index}", "batchCount": 3, "seed": str(1000 + index * 10)}
                for index in range(22)]

        expanded = easy_panel.expand_generation_jobs(jobs)

        self.assertEqual(66, len(expanded))
        self.assertEqual((0, 0, 3, "1000"),
                         (expanded[0]["task_index"], expanded[0]["image_index"],
                          expanded[0]["image_count"], expanded[0]["payload"]["seed"]))
        self.assertEqual((0, 2, "1002"),
                         (expanded[2]["task_index"], expanded[2]["image_index"],
                          expanded[2]["payload"]["seed"]))
        self.assertEqual((21, 2, "1212"),
                         (expanded[-1]["task_index"], expanded[-1]["image_index"],
                          expanded[-1]["payload"]["seed"]))
        self.assertTrue(all("batchCount" not in item["payload"] for item in expanded))

    def test_random_seed_is_preserved_for_every_expanded_image(self):
        expanded = easy_panel.expand_generation_jobs(
            [{"prompt": "random", "batchCount": 3, "seed": "-1"}])
        self.assertEqual(["-1", "-1", "-1"],
                         [item["payload"]["seed"] for item in expanded])

    def test_batch_queue_limits_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "1-16"):
            easy_panel.expand_generation_jobs([{"batchCount": 17}])
        with self.assertRaisesRegex(ValueError, "超过 200 张"):
            easy_panel.expand_generation_jobs([{"batchCount": 16} for _ in range(13)])
        with self.assertRaisesRegex(ValueError, "1-50"):
            easy_panel.expand_generation_jobs([{"batchCount": 1} for _ in range(51)])


if __name__ == "__main__":
    unittest.main()
