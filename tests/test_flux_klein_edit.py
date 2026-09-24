"""FLUX.2 Klein 智能修图：官方节点链移植 + 局部裁剪修复的契约测试。

节点链来自 ComfyUI 官方模板 ``image_flux2_klein_image_edit_4b_distilled.json``，
所以这里既查“结构对不对”，也查“有没有被写成 SD 式 img2img”（denoise / KSampler）。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easy_panel_app import creative_index  # noqa: E402
from easy_panel_app import flux_klein_edit as fx  # noqa: E402

import easy_panel  # noqa: E402


def nodes_of(workflow: dict) -> dict:
    return workflow["prompt"]


def class_types(workflow: dict) -> set[str]:
    return {node["class_type"] for node in nodes_of(workflow).values()}


def find(workflow: dict, class_type: str) -> dict:
    for node in nodes_of(workflow).values():
        if node["class_type"] == class_type:
            return node
    raise AssertionError(f"工作流里缺少 {class_type}")


class FluxEditNormalizeTests(unittest.TestCase):
    def test_defaults_match_the_official_distilled_model(self):
        edit = fx.normalize_flux_edit({"fluxEdit": {"enabled": True, "source": "a.png",
                                                   "instruction": "refine"}})
        self.assertEqual("full", edit["mode"])
        self.assertEqual("standard", edit["strategy"])
        self.assertEqual(4, edit["steps"])          # 4 步蒸馏
        self.assertEqual(1.0, edit["megapixels"])   # 官方参考图归一到 1MP
        self.assertEqual(fx.DEFAULT_UNET, edit["unet"])
        self.assertEqual("qwen_3_4b.safetensors", edit["text_encoder"])
        self.assertEqual("flux2-vae.safetensors", edit["vae"])
        self.assertEqual(list(fx.DEFAULT_PRESERVE), edit["preserve"])
        self.assertGreater(edit["seed"], 0)

    def test_unknown_values_fall_back_instead_of_crashing(self):
        edit = fx.normalize_flux_edit({"fluxEdit": {
            "enabled": True, "mode": "??", "strategy": "???", "preserve": ["face", "nope"],
            "steps": "abc", "megapixels": 99, "seed": "x", "references": ["r1", "r2", "r3"],
        }})
        self.assertEqual("full", edit["mode"])
        self.assertEqual("standard", edit["strategy"])
        self.assertEqual(["face"], edit["preserve"])
        self.assertEqual(4, edit["steps"])
        self.assertEqual(1.5, edit["megapixels"])           # 上限夹取
        self.assertEqual(2, len(edit["references"]))        # 最多 2 张参考图

    def test_missing_preserve_uses_defaults_but_empty_list_means_none(self):
        default_edit = fx.normalize_flux_edit({"fluxEdit": {"enabled": True}})
        self.assertEqual(list(fx.DEFAULT_PRESERVE), default_edit["preserve"])
        cleared = fx.normalize_flux_edit({"fluxEdit": {"enabled": True, "preserve": []}})
        self.assertEqual([], cleared["preserve"])

    def test_validation_reports_actionable_errors(self):
        edit = fx.normalize_flux_edit({"fluxEdit": {"enabled": True, "mode": "regional"}})
        errors = fx.validate_flux_edit(edit)
        self.assertTrue(any("原图" in item for item in errors))
        self.assertTrue(any("修改描述" in item for item in errors))
        self.assertTrue(any("蒙版" in item for item in errors))
        self.assertEqual([], fx.validate_flux_edit(
            fx.normalize_flux_edit({"fluxEdit": {"enabled": True, "source": "a.png",
                                                 "instruction": "refine"}})))

    def test_strategy_texts_drive_the_final_instruction(self):
        base = {"enabled": True, "source": "a.png", "instruction": "refine hair strands"}
        conservative = fx.compose_flux_instruction(
            fx.normalize_flux_edit({"fluxEdit": {**base, "strategy": "conservative"}}))
        restructure = fx.compose_flux_instruction(
            fx.normalize_flux_edit({"fluxEdit": {**base, "strategy": "restructure"}}))
        self.assertIn("Conservative refinement", conservative)
        self.assertIn("Do not redesign the character", conservative)
        self.assertIn("refine hair strands.", conservative)
        self.assertIn("Restructuring is allowed", restructure)
        self.assertNotIn("Do not redesign the character", restructure)

    def test_preserve_checkboxes_become_explicit_clauses(self):
        edit = fx.normalize_flux_edit({"fluxEdit": {
            "enabled": True, "source": "a.png", "instruction": "refine",
            "preserve": ["identity", "composition"]}})
        text = fx.compose_flux_instruction(edit)
        self.assertIn("the original character identity", text)
        self.assertIn("the original camera framing and composition", text)
        self.assertNotIn("facial features", text)


class FluxEditWorkflowTests(unittest.TestCase):
    def build(self, request: dict) -> dict:
        edit = fx.normalize_flux_edit({"fluxEdit": {
            "enabled": True, "source": "easy_panel/source.png", **request}})
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            _write_image(source, (768, 1024))
            with patch.object(fx, "resolve_source_image",
                              return_value=("easy_panel/source.png", source, "input")):
                return fx.build_flux_klein_edit_workflow(edit, filename_prefix="EasyPanel")

    def test_chain_matches_the_official_distilled_template(self):
        workflow = self.build({"instruction": "refine hair strands"})
        expected = {
            "UNETLoader", "CLIPLoader", "VAELoader", "LoadImage",
            "ImageScaleToTotalPixels", "GetImageSize", "EmptyFlux2LatentImage",
            "Flux2Scheduler", "CLIPTextEncode", "ConditioningZeroOut", "VAEEncode",
            "ReferenceLatent", "CFGGuider", "KSamplerSelect", "RandomNoise",
            "SamplerCustomAdvanced", "VAEDecode", "SaveImage",
        }
        self.assertEqual(expected, class_types(workflow))

        self.assertEqual(fx.DEFAULT_UNET, find(workflow, "UNETLoader")["inputs"]["unet_name"])
        clip = find(workflow, "CLIPLoader")["inputs"]
        self.assertEqual("qwen_3_4b.safetensors", clip["clip_name"])
        self.assertEqual("flux2", clip["type"])
        self.assertEqual("flux2-vae.safetensors", find(workflow, "VAELoader")["inputs"]["vae_name"])

        scale = find(workflow, "ImageScaleToTotalPixels")["inputs"]
        self.assertEqual("nearest-exact", scale["upscale_method"])
        self.assertEqual(1.0, scale["megapixels"])
        # 官方 UI 模板里 resolution_steps 是折叠的高级输入，转 API 必须显式给值。
        self.assertEqual(fx.RESOLUTION_STEPS, scale["resolution_steps"])

        scheduler = find(workflow, "Flux2Scheduler")["inputs"]
        self.assertEqual(4, scheduler["steps"])
        self.assertEqual(["15", 0], scheduler["width"])
        self.assertEqual(["15", 1], scheduler["height"])

        guider = find(workflow, "CFGGuider")["inputs"]
        self.assertEqual(1.0, guider["cfg"])                 # Klein 免引导
        self.assertEqual("euler", find(workflow, "KSamplerSelect")["inputs"]["sampler_name"])
        self.assertEqual(2, len([node for node in nodes_of(workflow).values()
                                 if node["class_type"] == "ReferenceLatent"]))
        self.assertEqual(["16", 0], find(workflow, "SamplerCustomAdvanced")["inputs"]["latent_image"])

    def test_not_written_as_sd_style_img2img(self):
        workflow = self.build({"instruction": "refine"})
        for node in nodes_of(workflow).values():
            self.assertNotIn(node["class_type"], {"KSampler", "KSamplerAdvanced", "VAEEncodeForInpaint"})
            self.assertNotIn("denoise", node["inputs"])
        text = find(workflow, "CLIPTextEncode")["inputs"]["text"]
        self.assertIn("refine", text)

    def test_plan_describes_a_single_klein_sampling_stage(self):
        workflow = self.build({"instruction": "refine"})
        plan = workflow["plan"]
        self.assertEqual(1, plan["samplerCount"])
        self.assertEqual(4, plan["samplers"]["26"])
        self.assertIn("FLUX 智能修图", plan["stages"]["26"])
        self.assertEqual("base", plan["outputStage"])
        self.assertEqual(list(fx._scaled_size(768, 1024, 1.0)), plan["output"])

    def test_reference_images_add_extra_reference_latents(self):
        workflow = self.build({"instruction": "match the style", "references": ["ref1.png", "ref2.png"]})
        latents = [node for node in nodes_of(workflow).values()
                   if node["class_type"] == "ReferenceLatent"]
        self.assertEqual(6, len(latents))  # 原图 2 条 + 每张参考图 2 条
        self.assertEqual(2, workflow["plan"]["fluxEdit"]["references"])

    def test_instruction_is_ignored_for_validation_of_other_modes(self):
        with self.assertRaises(ValueError):
            fx.build_flux_klein_edit_workflow(
                fx.normalize_flux_edit({"fluxEdit": {"enabled": True, "mode": "regional"}}))


class FluxEditRegionalTests(unittest.TestCase):
    def test_roi_box_snaps_to_alignment_and_keeps_a_workable_size(self):
        from PIL import Image, ImageDraw

        mask = Image.new("L", (1024, 1024), 0)
        ImageDraw.Draw(mask).rectangle([500, 500, 540, 540], fill=255)
        box = fx.roi_box(mask, grow=0, pad=0)
        x, y, width, height = box
        self.assertEqual(0, x % 8)
        self.assertEqual(0, y % 8)
        self.assertEqual(0, width % 8)
        self.assertEqual(0, height % 8)
        self.assertGreaterEqual(min(width, height), fx.MIN_ROI_SIDE)

        big = Image.new("L", (4096, 4096), 255)
        box = fx.roi_box(big, grow=0, pad=0)
        self.assertLessEqual(max(box[2], box[3]), fx.MAX_ROI_SIDE)

    def test_empty_mask_is_rejected_with_a_clear_message(self):
        from PIL import Image

        with self.assertRaisesRegex(ValueError, "蒙版是空的"):
            fx.roi_box(Image.new("L", (512, 512), 0), grow=0, pad=0)

    def test_regional_mode_crops_the_roi_and_pastes_it_back(self):
        from PIL import Image, ImageDraw

        mask = Image.new("L", (1024, 1024), 0)
        ImageDraw.Draw(mask).rectangle([400, 500, 600, 700], fill=255)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            crop_dir = Path(folder)
            _write_image(source, (1024, 1024))
            edit = fx.normalize_flux_edit({"fluxEdit": {
                "enabled": True, "mode": "regional", "source": "easy_panel/source.png",
                "mask": "easy_panel/flux_mask_1.png", "instruction": "fix the hand"}})
            with patch.object(fx, "resolve_source_image",
                              return_value=("easy_panel/source.png", source, "input")), \
                    patch.object(fx, "load_mask_layers", return_value=mask), \
                    patch.object(fx, "_input_dir", return_value=crop_dir):
                workflow = fx.build_flux_klein_edit_workflow(edit, filename_prefix="EasyPanel")
                prepared = fx.prepare_regional_inputs(source, "easy_panel/flux_mask_1.png")

            nodes = nodes_of(workflow)
            self.assertIn("ImageCompositeMasked", class_types(workflow))
            composite = find(workflow, "ImageCompositeMasked")["inputs"]
            self.assertFalse(composite["resize_source"])
            self.assertEqual(0, composite["x"] % 8)
            self.assertEqual(0, composite["y"] % 8)
            self.assertEqual(["28", 0], composite["destination"])
            # 模型把 ROI 归一到 1MP：贴回前必须缩回 ROI 尺寸，否则硬贴会错位。
            scale = find(workflow, "ImageScale")["inputs"]
            self.assertEqual(composite["source"], ["32", 0])
            self.assertEqual(prepared["roi"]["width"], scale["width"])
            self.assertEqual(prepared["roi"]["height"], scale["height"])
            self.assertTrue(Path(crop_dir / Path(prepared["crop"]).name).is_file())
            self.assertTrue(Path(crop_dir / Path(prepared["mask"]).name).is_file())
            self.assertEqual([1024, 1024], workflow["plan"]["output"])

    def test_crop_files_are_named_by_content_hash(self):
        from PIL import Image, ImageDraw

        mask = Image.new("L", (512, 512), 0)
        ImageDraw.Draw(mask).rectangle([100, 100, 300, 300], fill=255)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            crop_dir = Path(folder)
            _write_image(source, (512, 512))
            with patch.object(fx, "load_mask_layers", return_value=mask), \
                    patch.object(fx, "_input_dir", return_value=crop_dir):
                first = fx.prepare_regional_inputs(source, "easy_panel/m.png")
                second = fx.prepare_regional_inputs(source, "easy_panel/m.png")
            self.assertEqual(first["crop"], second["crop"])
            self.assertEqual(2, len(list(crop_dir.glob("flux_*"))))


class FluxEditWiringTests(unittest.TestCase):
    def test_backend_routes_flux_requests_to_the_klein_builder(self):
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")
        for marker in ("from easy_panel_app.flux_klein_edit import",
                       "if flux_edit_enabled(data):", "build_flux_klein_edit_workflow(",
                       '"/api/upload-flux-mask"', "save_flux_mask_upload",
                       "index_generation_for_output", "snapshot_flux_edit"):
            with self.subTest(marker=marker):
                self.assertIn(marker, backend)

    def test_operation_vocabulary_has_flux_edit(self):
        self.assertIn("flux_edit", creative_index.SUPPORTED_OPERATIONS)
        self.assertEqual("flux_edit", easy_panel.infer_creative_operation(
            {"fluxEdit": {"enabled": True, "source": "a.png"}}))
        self.assertEqual("txt2img", easy_panel.infer_creative_operation({"model": "x"}))

    def test_snapshot_declared_operation_is_not_downgraded(self):
        """回归：新操作码（flux_edit）不能被索引的旧列表降级成 unknown。"""

        snapshot = {"workflow": {"operation": "flux_edit"}, "payload": {}}
        self.assertEqual("flux_edit", creative_index.CreativeIndex._snapshot_operation(snapshot))
        self.assertEqual("flux_edit", creative_index.CreativeIndex._snapshot_operation(
            snapshot, "flux_edit"))
        # 老路径不受影响。
        self.assertEqual("txt2img", creative_index.CreativeIndex._snapshot_operation(
            {"workflow": {"operation": "panel.generate"}}))
        self.assertEqual("upscale", creative_index.CreativeIndex._snapshot_operation(
            {"operation": "panel.upscale"}))

    def test_build_workflow_ignores_the_main_model_for_flux_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            _write_image(source, (768, 768))
            payload = {"fluxEdit": {"enabled": True, "source": source.name,
                                    "instruction": "refine the fabric"},
                       "model": "", "filenamePrefix": "EasyPanel"}
            with patch.object(fx, "resolve_source_image",
                              return_value=("easy_panel/source.png", source, "input")):
                workflow = easy_panel.build_workflow(payload)
        self.assertIn("SamplerCustomAdvanced", class_types(workflow))

    def test_payload_copy_stays_byte_identical(self):
        for relative in ("easy_panel_app/flux_klein_edit.py", "easy_panel.py",
                         "easy_panel_app/media_storage.py", "easy_panel_app/creative_index.py"):
            with self.subTest(relative=relative):
                self.assertEqual((ROOT / relative).read_bytes(),
                                 (ROOT / "installers" / "payload" / relative).read_bytes())

    def test_frontend_wiring(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("/assets/js/flux-edit.js?v=", page)
        self.assertIn("handSendToFlux()", page)
        self.assertIn('value="flux_edit"', page)
        workbench = (ROOT / "web/assets/js/result-workbench.js").read_text(encoding="utf-8")
        self.assertIn('data-workbench="flux"', workbench)
        self.assertIn("easyPanelOpenFluxEdit", workbench)
        hand = (ROOT / "web/assets/js/hand-workbench.js").read_text(encoding="utf-8")
        self.assertIn("window.handExportMask", hand)
        self.assertIn("window.handSendToFlux", hand)
        editor = (ROOT / "web/assets/js/flux-edit.js").read_text(encoding="utf-8")
        for marker in ("/api/upload-flux-mask", "/api/generate", "fluxEdit", "operation: \"flux_edit\"",
                       "easyPanelFluxUseHandMask", "easyPanelOpenFluxEdit"):
            with self.subTest(marker=marker):
                self.assertIn(marker, editor)


def _write_image(path: Path, size: tuple[int, int]) -> None:
    from PIL import Image

    Image.new("RGB", size, (32, 48, 64)).save(path, format="PNG")


if __name__ == "__main__":
    unittest.main()
