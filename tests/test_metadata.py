from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from easy_panel_app.metadata import (
    parse_a1111_parameters,
    parse_comfyui_prompt,
    parse_generation_info,
    parse_novelai_comment,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "easy_panel.py"
SPEC = importlib.util.spec_from_file_location("easy_panel_metadata_test", MODULE_PATH)
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


BIG_SEED = "7121937610493606652"


def comfy_prompt(seed: int) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "1girl"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality"}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 768, "height": 1024}},
        "5": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 24, "cfg": 6.0,
            "sampler_name": "euler", "scheduler": "normal",
            "positive": ["2", 0], "negative": ["3", 0],
        }},
    }


def comfy_hires_prompt(seed: int) -> dict:
    prompt = comfy_prompt(seed)
    prompt.update({
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0]}},
        "7": {"class_type": "ImageScale", "inputs": {
            "image": ["6", 0], "upscale_method": "lanczos",
            "width": 904, "height": 1600, "crop": "disabled",
        }},
        "8": {"class_type": "VAEEncode", "inputs": {"pixels": ["7", 0]}},
        "9": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 20, "cfg": 4.5, "denoise": 0.35,
            "sampler_name": "euler", "scheduler": "normal",
            "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["8", 0],
        }},
    })
    prompt["4"]["inputs"].update({"width": 720, "height": 1280})
    return prompt


def png_with_prompt(prompt: dict) -> bytes:
    image = Image.new("RGB", (8, 8), "white")
    info = PngImagePlugin.PngInfo()
    info.add_text("prompt", json.dumps(prompt))
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=info)
    return output.getvalue()


class MetadataSeedTests(unittest.TestCase):
    def test_all_metadata_formats_preserve_64_bit_seed_as_text(self):
        self.assertEqual(BIG_SEED, parse_comfyui_prompt(comfy_prompt(int(BIG_SEED)))["seed"])
        self.assertEqual(BIG_SEED, parse_a1111_parameters(
            f"1girl\nNegative prompt: low quality\nSteps: 24, Seed: {BIG_SEED}"
        )["seed"])
        self.assertEqual(BIG_SEED, parse_novelai_comment(json.dumps({
            "prompt": "1girl", "parameters": {"seed": int(BIG_SEED)}
        }))["seed"])
        self.assertEqual(BIG_SEED, parse_generation_info(
            png_with_prompt(comfy_prompt(int(BIG_SEED)))
        )["seed"])

    def test_read_output_returns_after_sending_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / "sample.png").write_bytes(png_with_prompt(comfy_prompt(int(BIG_SEED))))
            request = json.dumps({"name": "sample.png"}).encode("utf-8")
            handler = object.__new__(easy_panel.Handler)
            handler.path = "/api/read-output"
            handler.headers = {"Content-Length": str(len(request))}
            handler.rfile = io.BytesIO(request)
            sent = []
            handler.send_json = lambda body, status=200: sent.append((body, status))
            with patch.object(easy_panel, "OUTPUT", output), patch.object(
                easy_panel, "comfy_json", side_effect=AssertionError("read-output fell through to generation")
            ):
                handler.do_POST()
            self.assertEqual(1, len(sent))
            self.assertEqual(BIG_SEED, sent[0][0]["seed"])

    def test_hires_metadata_keeps_base_size_and_refinement_settings(self):
        result = parse_comfyui_prompt(comfy_hires_prompt(int(BIG_SEED)))
        self.assertEqual((720, 1280), (result["base_width"], result["base_height"]))
        self.assertEqual((904, 1600), (result["width"], result["height"]))
        self.assertEqual({
            "enabled": True, "scale": 1.25, "denoise": 0.35,
            "steps": 20, "cfg": 4.5, "sampler": "euler",
            "scheduler": "normal", "upscale_method": "lanczos",
        }, result["hires"])

    def test_seedvr2_metadata_keeps_main_model_and_sampler(self):
        data = {
            "model": "anima-base-v1.0.safetensors",
            "promptSections": {"subject": "1girl"}, "negative": "",
            "width": 768, "height": 1024, "seed": BIG_SEED,
            "outputEnhancement": {"mode": "seedvr2", "scale": 2},
        }
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            prompt = easy_panel.build_workflow(data)["prompt"]
        result = parse_comfyui_prompt(prompt)
        self.assertEqual("anima-base-v1.0.safetensors", result["model"])
        self.assertEqual((34, 4.8, "er_sde", "simple"),
                         (result["steps"], result["cfg"],
                          result["sampler"], result["scheduler"]))
        self.assertEqual("seedvr2", result["output_enhancement"]["mode"])
        self.assertFalse(result["hires"]["enabled"])

    def test_post_upscale_detailer_and_color_match_metadata(self):
        data = {
            "model": "waiIllustriousSDXL_v140.safetensors",
            "promptSections": {"subject": "1girl"}, "negative": "",
            "width": 768, "height": 1024,
            "outputEnhancement": {
                "mode": "anime6b", "scale": 2,
                "faceDetailer": {"enabled": True},
                "colorMatch": {"enabled": True},
            },
        }
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            result = parse_comfyui_prompt(easy_panel.build_workflow(data)["prompt"])
        self.assertEqual("anime6b", result["output_enhancement"]["mode"])
        self.assertEqual(2.0, result["output_enhancement"]["scale"])
        self.assertTrue(result["face_detailer"])
        self.assertTrue(result["color_match"])

    def test_hand_and_foot_detailer_metadata_are_not_misreported_as_faces(self):
        data = {
            "model": "waiIllustriousSDXL_v140.safetensors",
            "promptSections": {"subject": "1girl, full body, barefoot"},
            "negative": "", "width": 768, "height": 1024,
            "outputEnhancement": {
                "mode": "off",
                "faceDetailer": {"enabled": True},
                "limbDetailer": {"hands": True, "feet": True},
            },
        }
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            result = parse_comfyui_prompt(easy_panel.build_workflow(data)["prompt"])
        self.assertTrue(result["face_detailer"])
        self.assertTrue(result["hand_detailer"])
        self.assertTrue(result["foot_detailer"])


if __name__ == "__main__":
    unittest.main()
