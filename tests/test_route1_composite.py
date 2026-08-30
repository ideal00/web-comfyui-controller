from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


MODULE_PATH = Path(__file__).resolve().parents[1] / "easy_panel.py"
SPEC = importlib.util.spec_from_file_location("easy_panel_route1_test", MODULE_PATH)
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


def route1_payload() -> dict:
    return {
        "model": "waiIllustriousSDXL_v140.safetensors",
        "promptSections": {"subject": "1girl", "scene": "realistic city street"},
        "negative": "bad anatomy",
        "width": 832,
        "height": 1216,
        "seed": 20260819,
        "guidance": {"mode": "off"},
        "regions": [],
        "route1": {
            "enabled": True,
            "image": "easy_panel/background.png",
            "mask": "easy_panel/mask.png",
            "poseImage": "easy_panel/pose.png",
            "poseMode": "extract",
            "openposeControlnet": "xinsir_openpose_sdxl.safetensors",
            "depthControlnet": "xinsir_depth_sdxl_1.0.safetensors",
            "grow": 8,
            "feather": 12,
            "poseStrength": 0.75,
            "poseEnd": 0.85,
            "depthStrength": 0.45,
            "depthEnd": 0.70,
            "pass1Denoise": 0.85,
            "pass1Steps": 28,
            "pass1Cfg": 6.5,
            "pass2Denoise": 0.25,
            "pass2Steps": 20,
            "pass2Cfg": 5.5,
            "smartFusion": True,
            "lightDirection": "upper_right",
            "fusionDenoise": 0.18,
            "fusionSteps": 12,
            "fusionCfg": 4.5,
            "colorMatchStrength": 0.28,
            "environmentLightStrength": 0.22,
            "grainStrength": 0.035,
            "sharpenStrength": 0.10,
            "blendPrompt": "matching perspective, consistent lighting",
            "negativePrompt": "cutout look, halo edge",
        },
    }


class Route1CompositeTests(unittest.TestCase):
    def build(self, data: dict) -> dict:
        with (
            patch.object(easy_panel, "checkpoint_issue", return_value=None),
            patch.object(easy_panel, "validate_input_image", side_effect=lambda value: str(value)),
            patch.object(
                easy_panel, "prepare_route1_working_assets",
                side_effect=lambda image, mask: (image, mask, (3264, 2448), (1712, 1280), True),
            ),
            patch.object(
                easy_panel, "prepare_route1_environment_light",
                return_value=("easy_panel/light.png", {
                    "prompt": "continuous measured light gradient vector (0.12, -0.08)",
                }),
            ),
            patch.object(
                easy_panel, "prepare_route1_generation_mask",
                return_value=("easy_panel/generation-mask.png", 27, 31),
            ),
        ):
            return easy_panel.build_workflow(data)["prompt"]

    @staticmethod
    def nodes_of(nodes: dict, class_type: str) -> list[dict]:
        return [node for node in nodes.values() if node["class_type"] == class_type]

    def test_route1_builds_trimap_color_match_and_ring_only_third_pass(self):
        nodes = self.build(route1_payload())
        self.assertEqual(2, len(self.nodes_of(nodes, "ControlNetLoader")))
        self.assertEqual(2, len(self.nodes_of(nodes, "ControlNetApplyAdvanced")))
        self.assertEqual(3, len(self.nodes_of(nodes, "InpaintModelConditioning")))
        self.assertEqual(3, len(self.nodes_of(nodes, "KSampler")))
        self.assertEqual(1, len(self.nodes_of(nodes, "DWPreprocessor")))
        self.assertEqual(1, len(self.nodes_of(nodes, "DepthAnythingV2Preprocessor")))
        self.assertEqual(4, len(self.nodes_of(nodes, "GrowMask")))
        self.assertEqual(3, len(self.nodes_of(nodes, "FeatherMask")))
        self.assertEqual(1, len(self.nodes_of(nodes, "EmptyImage")))
        self.assertEqual(4, len(self.nodes_of(nodes, "ImageCompositeMasked")))
        self.assertEqual(2, len(self.nodes_of(nodes, "MaskComposite")))
        self.assertEqual(1, len(self.nodes_of(nodes, "LayerMask: RmBgUltra V2")))
        self.assertEqual(3, len(self.nodes_of(nodes, "LayerUtility: CropByMask")))
        self.assertEqual(2, len(self.nodes_of(nodes, "LayerUtility: RestoreCropBox")))
        self.assertEqual(1, len(self.nodes_of(nodes, "ColorTransfer")))
        self.assertEqual(1, len(self.nodes_of(nodes, "ImageBlend")))
        self.assertEqual(1, len(self.nodes_of(nodes, "LayerFilter: AddGrain")))
        self.assertEqual(1, len(self.nodes_of(nodes, "ImageSharpen")))
        self.assertEqual(1, len(self.nodes_of(nodes, "Canny")))
        self.assertEqual(1, len(self.nodes_of(nodes, "ImageToMask")))
        self.assertEqual("EasyPanel_Route1", self.nodes_of(nodes, "SaveImage")[0]["inputs"]["filename_prefix"])

        depth = self.nodes_of(nodes, "DepthAnythingV2Preprocessor")[0]
        depth_source = nodes[depth["inputs"]["image"][0]]
        self.assertEqual("ImageCompositeMasked", depth_source["class_type"])
        self.assertEqual("LoadImage", nodes[depth_source["inputs"]["destination"][0]]["class_type"])
        self.assertEqual("EmptyImage", nodes[depth_source["inputs"]["source"][0]]["class_type"])
        final_composite = nodes[self.nodes_of(nodes, "SaveImage")[0]["inputs"]["images"][0]]
        self.assertEqual("ImageCompositeMasked", final_composite["class_type"])
        self.assertEqual("ImageCompositeMasked",
                         nodes[final_composite["inputs"]["destination"][0]]["class_type"])
        self.assertEqual("VAEDecode", nodes[final_composite["inputs"]["source"][0]]["class_type"])

        precise_masks = [node for node in self.nodes_of(nodes, "MaskComposite")
                         if node["inputs"]["operation"] == "multiply"]
        rings = [node for node in self.nodes_of(nodes, "MaskComposite")
                 if node["inputs"]["operation"] == "subtract"]
        self.assertEqual(1, len(precise_masks))
        self.assertEqual(1, len(rings))
        expands = sorted(node["inputs"]["expand"] for node in self.nodes_of(nodes, "GrowMask"))
        self.assertIn(8, expands)
        self.assertIn(27, expands)
        self.assertIn(-13, expands)
        encoded = " ".join(node["inputs"]["text"] for node in self.nodes_of(nodes, "CLIPTextEncode"))
        self.assertIn("directional sunlight from the upper right", encoded)
        self.assertIn("continuous measured light gradient vector", encoded)
        self.assertIn("exactly one character", encoded)
        self.assertIn("no foreground silhouette", encoded)
        self.assertIn("giant silhouette", encoded)
        color_match = self.nodes_of(nodes, "ColorTransfer")[0]
        self.assertEqual("LayerUtility: CropByMask",
                         nodes[color_match["inputs"]["image_target"][0]]["class_type"])
        self.assertEqual("LayerUtility: CropByMask",
                         nodes[color_match["inputs"]["image_ref"][0]]["class_type"])
        light_blend = self.nodes_of(nodes, "ImageBlend")[0]
        self.assertEqual(("soft_light", 0.22), (
            light_blend["inputs"]["blend_mode"], light_blend["inputs"]["blend_factor"],
        ))
        grain = self.nodes_of(nodes, "LayerFilter: AddGrain")[0]
        sharpen = self.nodes_of(nodes, "ImageSharpen")[0]
        self.assertEqual([next(node_id for node_id, node in nodes.items() if node is grain), 0],
                         sharpen["inputs"]["image"])
        self.assertEqual(0.10, sharpen["inputs"]["alpha"])

        samplers = self.nodes_of(nodes, "KSampler")
        self.assertEqual((28, 6.5, 0.85, "euler", "karras"), (
            samplers[0]["inputs"]["steps"], samplers[0]["inputs"]["cfg"],
            samplers[0]["inputs"]["denoise"], samplers[0]["inputs"]["sampler_name"],
            samplers[0]["inputs"]["scheduler"],
        ))
        self.assertEqual((20, 5.5, 0.25, "dpmpp_2m", "karras"), (
            samplers[1]["inputs"]["steps"], samplers[1]["inputs"]["cfg"],
            samplers[1]["inputs"]["denoise"], samplers[1]["inputs"]["sampler_name"],
            samplers[1]["inputs"]["scheduler"],
        ))
        self.assertEqual((12, 4.5, 0.18, "dpmpp_2m", "karras"), (
            samplers[2]["inputs"]["steps"], samplers[2]["inputs"]["cfg"],
            samplers[2]["inputs"]["denoise"], samplers[2]["inputs"]["sampler_name"],
            samplers[2]["inputs"]["scheduler"],
        ))

    def test_smart_fusion_can_be_disabled_for_legacy_two_pass_output(self):
        data = route1_payload()
        data["route1"]["smartFusion"] = False
        nodes = self.build(data)
        self.assertEqual(2, len(self.nodes_of(nodes, "KSampler")))
        self.assertFalse(self.nodes_of(nodes, "LayerMask: RmBgUltra V2"))
        self.assertFalse(self.nodes_of(nodes, "ColorTransfer"))

    def test_skeleton_mode_skips_pose_extraction(self):
        data = route1_payload()
        data["route1"]["poseMode"] = "skeleton"
        nodes = self.build(data)
        self.assertFalse(self.nodes_of(nodes, "DWPreprocessor"))

    def test_prompt_pose_mode_uses_main_prompt_without_openpose(self):
        data = route1_payload()
        data["route1"].update({
            "poseMode": "prompt", "poseImage": "", "openposeControlnet": "",
        })
        nodes = self.build(data)
        self.assertFalse(self.nodes_of(nodes, "DWPreprocessor"))
        self.assertEqual(1, len(self.nodes_of(nodes, "ControlNetLoader")))
        self.assertEqual(1, len(self.nodes_of(nodes, "ControlNetApplyAdvanced")))
        self.assertEqual("xinsir_depth_sdxl_1.0.safetensors",
                         self.nodes_of(nodes, "ControlNetLoader")[0]["inputs"]["control_net_name"])

    def test_route1_rejects_non_sdxl_family(self):
        data = route1_payload()
        data["model"] = "anima-base-v1.0.safetensors"
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            with self.assertRaisesRegex(ValueError, "仅支持 SDXL"):
                easy_panel.build_workflow(data)

    def test_large_camera_photo_gets_aligned_2_2mp_working_copies(self):
        self.assertEqual((1712, 1280), easy_panel.route1_working_dimensions(3264, 2448))
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir)
            source_name, mask_name = "photo.jpg", "mask.png"
            Image.new("RGB", (3264, 2448), "navy").save(input_dir / source_name)
            Image.new("L", (3264, 2448), 255).save(input_dir / mask_name)
            with patch.object(easy_panel, "COMFY_INPUT", input_dir):
                work_image, work_mask, original, working, resized = (
                    easy_panel.prepare_route1_working_assets(source_name, mask_name)
                )
            self.assertTrue(resized)
            self.assertEqual((3264, 2448), original)
            self.assertEqual((1712, 1280), working)
            self.assertLessEqual(working[0] * working[1], 2_200_000)
            with Image.open(input_dir / source_name) as original_image:
                self.assertEqual((3264, 2448), original_image.size)
            with Image.open(input_dir / work_image) as resized_image:
                self.assertEqual(working, resized_image.size)
            with Image.open(input_dir / work_mask) as resized_mask:
                self.assertEqual(working, resized_mask.size)

    def test_generation_mask_expands_only_the_head_region(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir)
            mask = Image.new("L", (256, 192), 0)
            for y in range(40, 190):
                for x in range(80, 176):
                    mask.putpixel((x, y), 255)
            mask.save(input_dir / "mask.png")
            with patch.object(easy_panel, "COMFY_INPUT", input_dir):
                generated_name, headroom, side_margin = easy_panel.prepare_route1_generation_mask(
                    "mask.png", (256, 192))
                generated = Image.open(input_dir / generated_name).convert("L")
            self.assertEqual(20, headroom)
            self.assertEqual(24, side_margin)
            original_bbox = mask.getbbox()
            generated_bbox = generated.getbbox()
            self.assertLess(generated_bbox[0], original_bbox[0])
            self.assertLess(generated_bbox[1], original_bbox[1])
            self.assertGreater(generated_bbox[2], original_bbox[2])
            self.assertEqual(original_bbox[3], generated_bbox[3])

    def test_environment_light_analysis_uses_continuous_gradient_and_two_rings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir)
            width, height = 256, 192
            gradient = Image.new("RGB", (width, height))
            pixels = gradient.load()
            for y in range(height):
                for x in range(width):
                    level = int(35 + 190 * x / (width - 1))
                    pixels[x, y] = (level, min(255, level + 8), min(255, level + 16))
            mask = Image.new("L", (width, height), 0)
            for y in range(56, 152):
                for x in range(96, 176):
                    mask.putpixel((x, y), 255)
            gradient.save(input_dir / "background.png")
            mask.save(input_dir / "mask.png")
            with patch.object(easy_panel, "COMFY_INPUT", input_dir):
                light_name, analysis = easy_panel.prepare_route1_environment_light(
                    "background.png", "mask.png")
            self.assertGreater(analysis["gradientX"], 0.1)
            self.assertLess(abs(analysis["gradientY"]), analysis["gradientX"])
            self.assertGreater(analysis["middleRadius"], analysis["nearRadius"])
            self.assertIn("continuous background-derived illumination field",
                          analysis["prompt"])
            with Image.open(input_dir / light_name) as light_map:
                self.assertEqual((width, height), light_map.size)


if __name__ == "__main__":
    unittest.main()
