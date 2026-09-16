"""能力契约（capabilities / components / match priority / hires 继承）与 artifact_role 测试。

背景：模型族判断、UI 开关、preflight、workflow 门控必须只读
``model_profiles`` 的 profile（capabilities/components），不再散落 ``if anima or krea2``。
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import easy_panel
from easy_panel_app import creative_index as ci
from easy_panel_app import model_profiles as mp
from easy_panel_app.creative_index import CreativeIndex

ROOT = Path(__file__).resolve().parent.parent


def combo(steps: int = 30, cfg: float = 4.8, sampler: str = "er_sde",
          scheduler: str = "simple") -> list[dict]:
    return [{"key": "recommended", "label": "推荐", "steps": steps, "cfg": cfg,
             "sampler": sampler, "scheduler": scheduler, "guidance": "off", "note": ""}]


def fake_catalog(**profiles) -> dict:
    return {"schema_version": 1, "profiles": list(profiles.get("profiles") or [])}


def payload(model: str, **overrides) -> dict:
    data = {
        "model": model,
        "promptSections": {"subject": "1girl, solo"},
        "negative": "blurry",
        "width": 832,
        "height": 1216,
        "seed": 12345,
        "steps": 30,
        "cfg": 4.8,
    }
    data.update(overrides)
    return data


def build_nodes(data: dict) -> dict:
    return easy_panel.build_workflow(data)["prompt"]


def nodes_of(nodes: dict, class_type: str) -> list[dict]:
    return [node for node in nodes.values() if node.get("class_type") == class_type]


def snapshot(snapshot_id: str, *, outputs=None) -> dict:
    body = {
        "model": "anima-base-v1.0.safetensors",
        "quality": "balanced",
        "prompt": "1girl, quiet cafe",
        "negative": "",
        "seed": "1",
        "width": 832,
        "height": 1216,
        "loras": [],
    }
    return {
        "id": snapshot_id,
        "createdAt": 1,
        "schemaVersion": 2,
        "promptId": "prompt-" + snapshot_id[:8],
        "payload": body,
        "source": {"checkpoint": body["model"], "generation": {"seed": "1", "width": 832, "height": 1216}, "loras": []},
        "compiled": {"positive": body["prompt"], "negative": body["negative"]},
        "workflow": {"operation": "panel.generate", "version": "test"},
        "environment": {"panelVersion": "test-panel"},
        "status": "completed",
        "outputs": list(outputs or []),
    }


class CapabilityContractTests(unittest.TestCase):
    def test_family_capabilities_come_from_the_profile(self):
        anima = mp.model_sampling_profile("anima-base-v1.0.safetensors")
        caps = anima["capabilities"]
        self.assertEqual("anima", anima["family"])
        self.assertFalse(caps["controlnet_pose"])
        self.assertFalse(caps["controlnet_depth"])
        self.assertTrue(caps["detail_refine"])
        self.assertTrue(caps["highres_reconstruction"])
        self.assertTrue(caps["anima_highres"])
        self.assertEqual("model_only", caps["lora_loader"])
        self.assertEqual("unet", anima["components"]["loader"])
        self.assertIn("qwen_3_06b_base", anima["components"]["text_encoder"])

        krea = mp.model_sampling_profile("krea2TurboFp8.safetensors")
        self.assertEqual("krea2", krea["family"])
        self.assertFalse(krea["capabilities"]["negative_prompt"])
        self.assertFalse(krea["capabilities"]["hires_fix"])
        self.assertFalse(krea["capabilities"]["face_detailer"])
        self.assertEqual("krea2", krea["components"]["clip_type"])

        sdxl = mp.model_sampling_profile("waiIllustriousSDXL_v170.safetensors")
        self.assertTrue(sdxl["capabilities"]["controlnet_pose"])
        self.assertTrue(sdxl["capabilities"]["ultimate_upscale"])
        self.assertEqual("checkpoint", sdxl["components"]["loader"])
        self.assertEqual("full", sdxl["capabilities"]["lora_loader"])

    def test_cfg_rescale_prefers_the_explicit_declaration(self):
        milmu = mp.model_sampling_profile("milmuAnimeIllustriousXL_vPred01.safetensors")
        self.assertTrue(milmu["capabilities"]["cfg_rescale"])
        eps = mp.model_sampling_profile("waiIllustriousSDXL_v170.safetensors")
        self.assertFalse(eps["capabilities"]["cfg_rescale"])

        profile = {"id": "t-one", "match": ["waiillustrioussdxl_v170"], "family": "illustrious",
                   "prediction": "v_prediction", "capabilities": {"cfg_rescale": False},
                   "combos": combo(steps=20, cfg=5.0, sampler="euler_ancestral", scheduler="normal")}
        with patch.object(mp, "load_model_catalog", return_value=fake_catalog(profiles=[profile])):
            off = mp.model_sampling_profile("waiIllustriousSDXL_v170.safetensors")
        self.assertFalse(off["capabilities"]["cfg_rescale"])

        profile["capabilities"] = {"cfg_rescale": True}
        profile["prediction"] = "eps"
        with patch.object(mp, "load_model_catalog", return_value=fake_catalog(profiles=[profile])):
            on = mp.model_sampling_profile("waiIllustriousSDXL_v170.safetensors")
        self.assertTrue(on["capabilities"]["cfg_rescale"])

    def test_match_priority_beats_a_broader_token(self):
        broad = {"id": "broad", "match": ["anima"], "family": "anima", "combos": combo()}
        specific = {"id": "specific", "match": ["hosekilustrousmixanima"], "family": "anima",
                    "match_priority": 5, "combos": combo(steps=24, cfg=4.5)}
        with patch.object(mp, "load_model_catalog", return_value=fake_catalog(profiles=[broad, specific])):
            profile = mp.model_sampling_profile("hosekiLustrousmixAnima_animaV10.safetensors")
        self.assertEqual("specific", profile["id"])

    def test_partial_profile_hires_keeps_family_limits(self):
        profile = {"id": "anima-partial", "match": ["anima-base"], "family": "anima",
                   "hires": {"scale": 1.4}, "combos": combo(steps=34, cfg=4.8)}
        with patch.object(mp, "load_model_catalog", return_value=fake_catalog(profiles=[profile])):
            hires = mp.model_sampling_profile("anima-base-v1.0.safetensors")["hires"]
        self.assertEqual(1.4, hires["scale"])
        self.assertEqual(2.0, hires["max_scale"])
        self.assertEqual(0.2, hires["min_denoise"])
        self.assertEqual(2560, hires["max_long_edge"])
        self.assertEqual("RealESRGAN_x4plus_anime_6B.pth", hires["upscaler"])

    def test_constraints_are_the_single_source_for_ui_ranges(self):
        anima = mp.model_sampling_profile("anima-base-v1.0.safetensors")
        highres = mp.capability_constraints(anima, "highres_reconstruction")
        self.assertTrue(highres["enabled"])
        self.assertEqual([1.15, 2.0], highres["scale"])
        self.assertEqual([0.2, 0.35], highres["denoise"])
        self.assertEqual(2560, highres["max_long_edge"])
        self.assertEqual(["RealESRGAN_x4plus_anime_6B.pth"], highres["allowed_upscalers"])
        self.assertEqual([0.05, 0.2], mp.capability_constraints(anima, "detail_refine")["denoise"])

        sdxl = mp.model_sampling_profile("waiIllustriousSDXL_v170.safetensors")
        sdxl_highres = mp.capability_constraints(sdxl, "highres_reconstruction")
        self.assertEqual([1.1, 1.5], sdxl_highres["scale"])
        self.assertEqual([], sdxl_highres["allowed_upscalers"])
        self.assertEqual({}, mp.capability_constraints(sdxl, "not_a_capability"))

        script = (ROOT / "web/assets/js/anima-highres.js").read_text(encoding="utf-8")
        self.assertIn("constraints.highres_reconstruction", script)
        self.assertIn("allowed_upscalers", script)
        self.assertIn("applyConstraintRanges", script)

    def test_profile_components_override_encoder_and_vae(self):
        profile = {"id": "anima-custom", "match": ["anima-base"], "family": "anima",
                   "components": {"text_encoder": "custom_te.safetensors",
                                  "vae": "custom_vae.safetensors"},
                   "combos": combo(steps=34, cfg=4.8)}
        with patch.object(mp, "load_model_catalog", return_value=fake_catalog(profiles=[profile])):
            nodes = build_nodes(payload("anima-base-v1.0.safetensors"))
        clip = nodes_of(nodes, "CLIPLoader")[0]["inputs"]
        self.assertEqual("custom_te.safetensors", clip["clip_name"])
        self.assertEqual("stable_diffusion", clip["type"])
        self.assertEqual("custom_vae.safetensors", nodes_of(nodes, "VAELoader")[0]["inputs"]["vae_name"])


class CapabilityWorkflowTests(unittest.TestCase):
    def test_krea2_skips_negative_and_blocks_unsupported_features(self):
        data = payload("krea2TurboFp8.safetensors", steps=8, cfg=1.0)
        encodes = nodes_of(build_nodes(data), "CLIPTextEncode")
        self.assertEqual("", encodes[1]["inputs"]["text"])

        cases = {
            "regional": {"regions": [{"prompt": "left girl", "preset": "left"},
                                     {"prompt": "right girl", "preset": "right"}]},
            "pose": {"pose": {"enabled": True, "controlnet": "xinsir_openpose_sdxl.safetensors"}},
            "depth": {"depth": {"enabled": True, "image": "easy_panel/bg.png",
                                "controlnet": "xinsir_depth_sdxl.safetensors"}},
            "ultimate": {"outputEnhancement": {"mode": "ultimate"}},
            "face": {"outputEnhancement": {"mode": "off", "faceDetailer": {"enabled": True}}},
            "refine": {"animaDetailRefine": {"enabled": True, "mode": "balanced"}},
        }
        for label, extra in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    build_nodes({**data, **extra})

    def test_anima_blocks_controlnet_and_ultimate_but_allows_face_detailer(self):
        data = payload("anima-base-v1.0.safetensors")
        with self.assertRaisesRegex(ValueError, "OpenPose"):
            build_nodes({**data, "pose": {"enabled": True, "controlnet": "x.safetensors"}})
        with self.assertRaisesRegex(ValueError, "Depth ControlNet"):
            build_nodes({**data, "depth": {"enabled": True, "image": "a.png", "controlnet": "x.safetensors"}})
        with self.assertRaisesRegex(ValueError, "Ultimate SD Upscale"):
            build_nodes({**data, "outputEnhancement": {"mode": "ultimate"}})
        nodes = build_nodes({**data, "outputEnhancement": {"mode": "off",
                                                           "faceDetailer": {"enabled": True}}})
        self.assertEqual(1, len(nodes_of(nodes, "FaceDetailer")))

    def test_detail_refine_is_capability_gated(self):
        with self.assertRaisesRegex(ValueError, "只对 Anima 模型开放"):
            build_nodes({**payload("waiIllustriousSDXL_v170.safetensors"),
                         "animaDetailRefine": {"enabled": True, "mode": "balanced"}})
        nodes = build_nodes({**payload("anima-base-v1.0.safetensors"),
                             "animaDetailRefine": {"enabled": True, "mode": "balanced"}})
        self.assertEqual(2, len(nodes_of(nodes, "KSampler")))

    def test_illustrious_keeps_controlnet_and_ultimate(self):
        wai = "waiIllustriousSDXL_v170.safetensors"
        with patch.object(easy_panel, "validate_input_image", side_effect=lambda name: name):
            pose_nodes = build_nodes(payload(wai, pose={"enabled": True,
                                                        "controlnet": "xinsir_openpose_sdxl.safetensors"}))
        self.assertEqual(1, len(nodes_of(pose_nodes, "ControlNetLoader")))
        ultimate_nodes = build_nodes(payload(wai, outputEnhancement={"mode": "ultimate"}))
        self.assertEqual(1, len(nodes_of(ultimate_nodes, "UltimateSDUpscale")))

    def test_backend_has_no_family_special_cases_left(self):
        source = (ROOT / "easy_panel.py").read_text(encoding="utf-8")
        self.assertNotIn("if anima or krea2:", source)
        self.assertNotIn("if not anima and not krea2:", source)
        self.assertNotIn("regional_mode = bool(regions and not anima and not krea2)", source)


class SnapshotHighresTests(unittest.TestCase):
    def test_snapshot_records_effective_highres_parameters(self):
        data = payload("anima-base-v1.0.safetensors", width=1216, height=1824,
                       animaHighres={"enabled": True, "scale": 2.0, "denoise": 0.25, "steps": 20})
        executed = easy_panel.build_snapshot_source(data)["enhancements"]["animaHighres"]
        self.assertTrue(executed["enabled"])
        self.assertEqual(2.0, executed["requestedScale"])
        self.assertLessEqual(max(executed["targetWidth"], executed["targetHeight"]), 2560)
        self.assertAlmostEqual(executed["effectiveScale"], executed["targetWidth"] / 1216, places=3)
        self.assertTrue(str(executed["upscaler"]).endswith(".pth"))
        self.assertEqual(2560, executed["maxLongEdge"])

    def test_snapshot_keeps_requested_scale_when_no_clamp_is_needed(self):
        data = payload("anima-base-v1.0.safetensors", width=864, height=1152,
                       animaHighres={"enabled": True, "scale": 1.5, "denoise": 0.25, "steps": 20})
        executed = easy_panel.build_snapshot_source(data)["enhancements"]["animaHighres"]
        self.assertEqual(1.5, executed["requestedScale"])
        self.assertEqual(1.5, executed["effectiveScale"])
        self.assertEqual((1296, 1728), (executed["targetWidth"], executed["targetHeight"]))


class ArtifactRoleTests(unittest.TestCase):
    def test_normalize_artifact_ref_derives_roles(self):
        self.assertEqual("comparison", ci.normalize_artifact_ref("EasyPanel_base_00001_.png")[0]["artifact_role"])
        self.assertEqual("final", ci.normalize_artifact_ref("EasyPanel_00001_.png")[0]["artifact_role"])
        explicit = ci.normalize_artifact_ref({"filename": "x.png", "artifact_role": "comparison"})[0]
        self.assertEqual("comparison", explicit["artifact_role"])
        unknown = ci.normalize_artifact_ref({"filename": "y.png", "artifact_role": "nonsense"})[0]
        self.assertEqual("final", unknown["artifact_role"])

    def test_hires_base_is_not_the_preview_and_roles_are_exposed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "EasyPanel_base_00001_.png").write_bytes(b"base")
            (root / "EasyPanel_00001_.png").write_bytes(b"final")
            index = CreativeIndex(root / "creative.sqlite3")
            result = index.upsert_snapshot(
                snapshot("b" * 32, outputs=[{"filename": "EasyPanel_00001_.png", "type": "output"}]),
                output_root=root,
                status="queued",
            )
            index.update_snapshot_status(
                "b" * 32,
                status="completed",
                images=[{"filename": "EasyPanel_00001_.png", "type": "output"}],
                comparison_images=[{"filename": "EasyPanel_base_00001_.png", "type": "output"}],
                output_root=root,
            )
            detail = index.get_generation(result["generation_id"], include_hires_base=True)
            roles = {item["filename"]: item["role"] for item in detail["artifacts"]}
            self.assertEqual("comparison", roles["EasyPanel_base_00001_.png"])
            self.assertEqual("final", roles["EasyPanel_00001_.png"])
            final_id = next(item["artifact_id"] for item in detail["artifacts"]
                            if item["filename"] == "EasyPanel_00001_.png")
            self.assertEqual(final_id, detail["primary_artifact_id"])

            default_detail = index.get_generation(result["generation_id"])
            self.assertEqual(["EasyPanel_00001_.png"],
                             [item["filename"] for item in default_detail["artifacts"]])
            self.assertEqual(1, default_detail["hires_base_count"])
            self.assertEqual(final_id, default_detail["primary_artifact_id"])

    def test_import_records_completed_and_marks_base_as_comparison(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "EasyPanel_base_00007_.png").write_bytes(b"x")
            (root / "EasyPanel_00007_.png").write_bytes(b"y")
            index = CreativeIndex(root / "creative.sqlite3")
            record = {"positive": "1girl", "negative": "", "loras": [], "model": "m",
                      "seed": 7, "width": 832, "height": 1216}
            with patch.object(ci, "_comfy_record_from_png", return_value=record):
                outcome = index.import_output_images(root)
            self.assertEqual(2, outcome["imported"])
            connection = sqlite3.connect(root / "creative.sqlite3")
            try:
                statuses = [row[0] for row in connection.execute("SELECT status FROM generations")]
                roles = {row[0]: row[1] for row in connection.execute(
                    "SELECT filename, artifact_role FROM artifacts")}
            finally:
                connection.close()
            self.assertEqual(["completed", "completed"], sorted(statuses))
            self.assertEqual("comparison", roles["EasyPanel_base_00007_.png"])
            self.assertEqual("final", roles["EasyPanel_00007_.png"])


class FrontendFamilySourceTests(unittest.TestCase):
    def test_frontend_reads_family_from_the_backend_profile(self):
        panel = (ROOT / "web/assets/js/panel.js").read_text(encoding="utf-8")
        self.assertIn("function modelFamilyClient()", panel)
        self.assertIn("profile.family", panel)
        self.assertIn("function promptFamilyClient(){return modelFamilyClient()}", panel)
        self.assertIn("capabilities?.highres_reconstruction", panel)

        highres = (ROOT / "web/assets/js/anima-highres.js").read_text(encoding="utf-8")
        self.assertIn("profile.family", highres)
        self.assertIn("highres_reconstruction", highres)
        self.assertIn("easyPanelHiresStashV1", highres)
        self.assertIn("lastKnownFamily", highres)
        self.assertIn("实际约", highres)

        refine = (ROOT / "web/assets/js/anima-refine.js").read_text(encoding="utf-8")
        self.assertIn("profile.family", refine)
        self.assertIn("detail_refine", refine)

    def test_script_versions_are_bumped(self):
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertRegex(index_html, r"panel\.js\?v=\d+")
        self.assertIn("anima-refine.js?v=3", index_html)
        self.assertIn("anima-highres.js?v=8", index_html)


if __name__ == "__main__":
    unittest.main()
