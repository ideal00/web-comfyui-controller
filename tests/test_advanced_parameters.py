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

    def test_object_info_choices_support_old_and_dynamic_combo_schema(self):
        old = {"Loader": {"input": {"required": {"name": [["a", "b"], {}]}}}}
        dynamic = {"Loader": {"input": {"required": {"name": ["COMBO", {
            "options": ["a", "b"], "multiselect": False,
        }]}}}}
        keyed = {"Loader": {"input": {"required": {"name": ["COMFY_DYNAMICCOMBO_V3", {
            "options": [{"key": "a"}, {"key": "b"}],
        }]}}}}
        for info in (old, dynamic, keyed):
            self.assertEqual(["a", "b"], easy_panel.object_info_choices(info, "Loader", "name"))

    def test_installed_model_recommendations_match_validated_profiles(self):
        expected = {
            "spectacularAnimeILXL_10.safetensors": (24, 7.0, "euler_ancestral", "beta"),
            "milmuAnimeIllustriousXL_vPred01.safetensors": (30, 6.0, "euler", "normal"),
            "gockSoAnimeLoveSong_gocksoanimeLoveSong.safetensors": (30, 7.0, "dpmpp_2m_sde", "karras"),
            "anima-base-v1.0.safetensors": (34, 4.8, "er_sde", "simple"),
            "krea2TurboOfficialComfy_krea2TurboFp8.safetensors": (8, 1.0, "euler", "simple"),
            "reedXXXIllustrious_v150.safetensors": (30, 7.0, "euler_ancestral", "normal"),
            "plantMilkModelSuite_walnut.safetensors": (28, 3.0, "euler", "normal"),
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
        self.assertFalse(self.nodes_of(nodes, "LatentUpscaleBy"))
        loader_node = self.nodes_of(nodes, "UpscaleModelLoader")[0]
        model_upscale_node = self.nodes_of(nodes, "ImageUpscaleWithModel")[0]
        self.assertEqual("RealESRGAN_x4plus_anime_6B.pth",
                         loader_node["inputs"]["model_name"])
        upscale_node = self.nodes_of(nodes, "ImageScale")[0]
        upscale = upscale_node["inputs"]
        self.assertEqual(("lanczos", 920, 1232, "disabled"),
                         (upscale["upscale_method"], upscale["width"],
                          upscale["height"], upscale["crop"]))
        first_decode = self.nodes_of(nodes, "VAEDecode")[0]
        encode = self.nodes_of(nodes, "VAEEncode")[0]
        node_id = lambda target: next(node_id for node_id, node in nodes.items()
                                      if node is target)
        self.assertEqual([node_id(loader_node), 0],
                         model_upscale_node["inputs"]["upscale_model"])
        self.assertEqual([node_id(first_decode), 0],
                         model_upscale_node["inputs"]["image"])
        self.assertEqual([node_id(model_upscale_node), 0], upscale["image"])
        self.assertEqual([next(node_id for node_id, node in nodes.items()
                               if node is upscale_node), 0], encode["inputs"]["pixels"])
        self.assertEqual([next(node_id for node_id, node in nodes.items()
                               if node is encode), 0], second["latent_image"])

    def test_model_specific_hires_and_generic_sdxl_capability(self):
        data = payload("gockSoAnimeLoveSong_gocksoanimeLoveSong.safetensors")
        data.update({"illustriousMode": "hires", "hiresSampler": "euler",
                     "hiresScheduler": "normal", "hiresScale": 1.25})
        nodes = self.build(data)
        samplers = self.nodes_of(nodes, "KSampler")
        self.assertEqual(2, len(samplers))
        self.assertEqual(("euler", "normal"),
                         (samplers[-1]["inputs"]["sampler_name"],
                          samplers[-1]["inputs"]["scheduler"]))

        wai = easy_panel.model_sampling_profile(
            "waiIllustriousSDXL_v140.safetensors")
        self.assertEqual(1.25, wai["hires"]["scale"])

    def test_post_only_anime6b_supports_anima_and_krea(self):
        for model in ("anima-base-v1.0.safetensors",
                      "krea2TurboOfficialComfy_krea2TurboFp8.safetensors"):
            with self.subTest(model=model):
                data = payload(model)
                data["outputEnhancement"] = {"mode": "anime6b", "scale": 2}
                nodes = self.build(data)
                self.assertEqual(1, len(self.nodes_of(nodes, "ImageUpscaleWithModel")))
                scale = self.nodes_of(nodes, "ImageScale")[-1]["inputs"]
                self.assertEqual((1536, 2048), (scale["width"], scale["height"]))

    def test_seedvr2_graph_uses_dedicated_one_step_model(self):
        data = payload("anima-base-v1.0.safetensors")
        data["outputEnhancement"] = {"mode": "seedvr2", "scale": 2,
                                     "seedvrColor": "wavelet"}
        nodes = self.build(data)
        self.assertEqual(1, len(self.nodes_of(nodes, "SeedVR2Preprocess")))
        self.assertEqual(1, len(self.nodes_of(nodes, "SeedVR2Conditioning")))
        post = self.nodes_of(nodes, "SeedVR2PostProcessing")[0]["inputs"]
        self.assertEqual("wavelet", post["color_correction_method"])
        seed_sampler = [node for node in self.nodes_of(nodes, "KSampler")
                        if node["inputs"]["steps"] == 1][0]["inputs"]
        self.assertEqual((1.0, "euler", "simple", 1.0),
                         (seed_sampler["cfg"], seed_sampler["sampler_name"],
                          seed_sampler["scheduler"], seed_sampler["denoise"]))

    def test_ultimate_detailer_and_native_color_transfer(self):
        data = payload("waiIllustriousSDXL_v140.safetensors")
        data["outputEnhancement"] = {
            "mode": "ultimate", "scale": 2, "steps": 18, "denoise": 0.2,
            "tileSize": 512,
            "faceDetailer": {"enabled": True, "guideSize": 512,
                               "steps": 12, "denoise": 0.35},
            "colorMatch": {"enabled": True, "method": "reinhard_lab", "strength": 0.7},
        }
        nodes = self.build(data)
        ultimate = self.nodes_of(nodes, "UltimateSDUpscale")[0]["inputs"]
        self.assertEqual((2.0, 18, 0.2, 512),
                         (ultimate["upscale_by"], ultimate["steps"],
                          ultimate["denoise"], ultimate["tile_width"]))
        self.assertEqual(1, len(self.nodes_of(nodes, "UltralyticsDetectorProvider")))
        self.assertEqual(1, len(self.nodes_of(nodes, "FaceDetailer")))
        color = self.nodes_of(nodes, "ColorTransfer")[0]["inputs"]
        self.assertEqual(("reinhard_lab", 0.7), (color["method"], color["strength"]))

    def test_hires_and_post_upscale_are_mutually_exclusive(self):
        data = payload("waiIllustriousSDXL_v140.safetensors")
        data.update({"illustriousMode": "hires",
                     "outputEnhancement": {"mode": "anime6b", "scale": 2}})
        with self.assertRaisesRegex(ValueError, "不能同时开启"):
            self.build(data)

    def test_hires_tiled_vae_uses_tiled_round_trip_and_final_decode(self):
        data = payload("waiIllustriousSDXL_v140.safetensors")
        data.update({"illustriousMode": "hires", "hiresScale": 1.25,
                     "vae": {"mode": "tiled", "tileSize": 512, "overlap": 64}})
        nodes = self.build(data)
        self.assertEqual(2, len(self.nodes_of(nodes, "VAEDecodeTiled")))
        self.assertEqual(1, len(self.nodes_of(nodes, "VAEEncodeTiled")))
        self.assertFalse(self.nodes_of(nodes, "VAEDecode"))
        self.assertFalse(self.nodes_of(nodes, "VAEEncode"))
        self.assertEqual(1, len(self.nodes_of(nodes, "UpscaleModelLoader")))
        self.assertEqual(1, len(self.nodes_of(nodes, "ImageUpscaleWithModel")))
        scale = self.nodes_of(nodes, "ImageScale")[0]["inputs"]
        self.assertEqual((960, 1280), (scale["width"], scale["height"]))

    def test_hires_size_rounding_matches_browser_preview_at_half_boundary(self):
        data = payload("waiIllustriousSDXL_v140.safetensors")
        data.update({"illustriousMode": "hires", "width": 720, "height": 1280,
                     "hiresScale": 1.25})
        nodes = self.build(data)
        scale = self.nodes_of(nodes, "ImageScale")[0]["inputs"]
        self.assertEqual((904, 1600), (scale["width"], scale["height"]))

    def test_milmu_keeps_v_prediction_node_with_new_sampler(self):
        data = payload("milmuAnimeIllustriousXL_vPred01.safetensors")
        data["sampler"] = "auto"
        data["scheduler"] = "auto"
        data["steps"] = 30
        data["cfg"] = 5.5
        nodes = self.build(data)
        model_sampling = self.nodes_of(nodes, "ModelSamplingDiscrete")
        self.assertEqual("v_prediction", model_sampling[0]["inputs"]["sampling"])
        self.assertTrue(model_sampling[0]["inputs"]["zsnr"])
        sampler = self.nodes_of(nodes, "KSampler")[0]["inputs"]
        self.assertEqual(("euler", "normal"),
                         (sampler["sampler_name"], sampler["scheduler"]))

    def test_tiled_vae_decode_is_a_real_workflow_option(self):
        data = payload("waiIllustriousSDXL_v140.safetensors")
        data["vae"] = {"mode": "tiled", "tileSize": 512, "overlap": 64}
        nodes = self.build(data)
        tiled = self.nodes_of(nodes, "VAEDecodeTiled")
        self.assertEqual(1, len(tiled))
        self.assertEqual((512, 64),
                         (tiled[0]["inputs"]["tile_size"], tiled[0]["inputs"]["overlap"]))
        self.assertFalse(self.nodes_of(nodes, "VAEDecode"))

    def test_freeu_and_vpred_cfg_rescale_are_capability_guarded(self):
        freeu = payload("waiIllustriousSDXL_v140.safetensors")
        freeu["modelEnhancement"] = {"mode": "freeu_v2"}
        freeu_nodes = self.nodes_of(self.build(freeu), "FreeU_V2")
        self.assertEqual(1, len(freeu_nodes))
        self.assertEqual((1.3, 1.4, 0.9, 0.2),
                         tuple(freeu_nodes[0]["inputs"][key]
                               for key in ("b1", "b2", "s1", "s2")))

        configured = easy_panel.model_sampling_profile(
            "waiIllustriousSDXL_v140.safetensors")["freeu"]
        self.assertEqual("sdxl_official", configured["key"])
        self.assertEqual(2, len(configured["presets"]))

        gentle = payload("waiIllustriousSDXL_v140.safetensors")
        gentle["modelEnhancement"] = {
            "mode": "freeu_v2", "b1": 1.1, "b2": 1.2, "s1": 0.6, "s2": 0.4,
        }
        gentle_node = self.nodes_of(self.build(gentle), "FreeU_V2")[0]["inputs"]
        self.assertEqual((1.1, 1.2, 0.6, 0.4),
                         tuple(gentle_node[key] for key in ("b1", "b2", "s1", "s2")))

        krea = payload("krea2TurboOfficialComfy_krea2TurboFp8.safetensors")
        krea["modelEnhancement"] = {"mode": "freeu_v2"}
        with self.assertRaisesRegex(ValueError, "不支持 FreeU"):
            self.build(krea)

        milmu = payload("milmuAnimeIllustriousXL_vPred01.safetensors")
        milmu["modelEnhancement"] = {"mode": "cfg_rescale", "multiplier": 0.65}
        rescale = self.nodes_of(self.build(milmu), "RescaleCFG")
        self.assertEqual(0.65, rescale[0]["inputs"]["multiplier"])

        eps = payload("waiIllustriousSDXL_v140.safetensors")
        eps["modelEnhancement"] = {"mode": "cfg_rescale"}
        with self.assertRaisesRegex(ValueError, "仅对.*v-pred"):
            self.build(eps)

    def test_krea2_accepts_official_2k_aligned_resolution(self):
        data = payload("krea2TurboOfficialComfy_krea2TurboFp8.safetensors")
        data.update({"width": 2048, "height": 2048})
        nodes = self.build(data)
        latent = self.nodes_of(nodes, "EmptyLatentImage")[0]["inputs"]
        self.assertEqual((2048, 2048), (latent["width"], latent["height"]))

    def test_img2img_and_repair_build_the_expected_vae_paths(self):
        img2img = payload("waiIllustriousSDXL_v140.safetensors")
        img2img.update({
            "img2img": {"enabled": True, "image": "easy_panel/source.png", "denoise": 0.6},
            "vae": {"mode": "tiled", "tileSize": 512, "overlap": 64},
        })
        with patch.object(easy_panel, "prepare_generation_image",
                          return_value="easy_panel/source.png"):
            nodes = self.build(img2img)
        self.assertEqual(1, len(self.nodes_of(nodes, "LoadImage")))
        self.assertEqual(1, len(self.nodes_of(nodes, "VAEEncodeTiled")))
        self.assertEqual(1, len(self.nodes_of(nodes, "VAEDecodeTiled")))
        self.assertEqual(0.6, self.nodes_of(nodes, "KSampler")[0]["inputs"]["denoise"])

        repair = payload("waiIllustriousSDXL_v140.safetensors")
        repair.update({
            "illustriousMode": "repair",
            "repair": {"image": "easy_panel/source.png", "mask": "easy_panel/mask.png",
                       "grow": 6, "denoise": 0.5},
        })
        with patch.object(easy_panel, "validate_input_image", side_effect=lambda name: name):
            nodes = self.build(repair)
        encode = self.nodes_of(nodes, "VAEEncodeForInpaint")[0]["inputs"]
        self.assertEqual(6, encode["grow_mask_by"])
        self.assertEqual(0.5, self.nodes_of(nodes, "KSampler")[0]["inputs"]["denoise"])

    def test_edited_pose_and_color_correction_create_real_nodes(self):
        pose = payload("waiIllustriousSDXL_v140.safetensors")
        pose["pose"] = {
            "enabled": True,
            "poseJson": '[{"people":[]}]',
            "controlnet": "openpose.safetensors",
            "strength": 0.82,
            "end": 0.75,
        }
        nodes = self.build(pose)
        self.assertEqual(1, len(self.nodes_of(nodes, "huchenlei.LoadOpenposeJSON")))
        self.assertEqual(1, len(self.nodes_of(nodes, "EasyPanelRenderPoseXinsir")))
        control = self.nodes_of(nodes, "ControlNetApplyAdvanced")[0]["inputs"]
        self.assertEqual((0.82, 0.75), (control["strength"], control["end_percent"]))

        color = payload("waiIllustriousSDXL_v140.safetensors")
        color["colorCorrection"] = {
            "enabled": True, "brightness": 1.05, "contrast": 1.05,
            "saturation": 1.05, "gamma": 1, "red": 0, "green": 0, "blue": 0,
            "hue": 0, "hsvSaturation": 0, "value": 0,
            "blackPoint": 0, "whitePoint": 255, "grayPoint": 1,
        }
        nodes = self.build(color)
        for class_type in ("LayerColor: Brightness & Contrast", "LayerColor: RGB",
                           "LayerColor: HSV", "LayerColor: Gamma", "LayerColor: Levels"):
            self.assertEqual(1, len(self.nodes_of(nodes, class_type)))


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
