from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GenerationProgressUiTests(unittest.TestCase):
    def test_progress_bar_is_present_and_connected_to_comfy_progress_stream(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")

        self.assertIn('id="generationProgressBar"', html)
        preview_start = html.index('class="card preview-card"')
        preview_end = html.index('</aside>', preview_start)
        progress_position = html.index('id="generationProgress"')
        controls_position = html.index('class="preview-controls"', preview_start)
        self.assertGreater(progress_position, preview_start)
        self.assertLess(progress_position, controls_position)
        self.assertLess(progress_position, preview_end)
        self.assertIn("new EventSource(url)", javascript)
        self.assertIn("dataset.connection='connected'", javascript)
        self.assertIn("type==='progress'", javascript)
        self.assertIn("当前节点进度", javascript)
        self.assertNotIn("当前采样 ${cached.value}", javascript)
        self.assertIn("markGenerationPromptComplete(id)", javascript)
        self.assertIn('parsed.path == "/api/progress-stream"', backend)
        self.assertIn('"progress_stream": "/api/progress-stream"', backend)
        self.assertIn('client_id = "easy-panel"', backend)

    def test_installers_ship_the_unified_service_controller(self):
        builder = (ROOT / "installers" / "Build-Packages.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "installers" / "Install-EasyPanelModule.ps1").read_text(encoding="utf-8")
        controller = (ROOT / "tools" / "EasyPanel-Service.ps1").read_text(encoding="utf-8")
        launcher_installer = (ROOT / "tools" / "Install-OneClickLaunchers.ps1").read_text(encoding="utf-8")

        self.assertNotIn('Copy-CleanDirectory (Join-Path $repositoryRoot "launchers")', builder)
        self.assertIn('EasyPanel-Service.ps1', builder)
        self.assertIn('Install-OneClickLaunchers.ps1', installer)
        self.assertIn('EasyPanel-Service.ps1', launcher_installer)
        self.assertIn('EasyPanel_一键启动.bat', installer)
        self.assertIn('EasyPanel_一键关闭.bat', installer)
        for marker in (
            '[ValidateSet("Start", "Stop", "Status")]',
            'Start-Process -FilePath $Config.Python',
            '--windows-standalone-build',
            'EASY_PANEL_HOST = "0.0.0.0"',
            'EASY_PANEL_RPG_TOKEN = $Token',
            'RandomNumberGenerator',
            'Stop-Process -Id ([int]$processId)',
            'if ($DryRun)',
            'NoBrowser',
        ):
            self.assertIn(marker, controller)
        self.assertIn('ASCIIEncoding', launcher_installer)

    def test_single_and_batch_generation_both_start_progress_tracking(self):
        javascript = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")

        self.assertIn("beginGenerationProgress(count)", javascript)
        self.assertIn("beginGenerationProgress(expected,'队列生成进度')", javascript)
        self.assertGreaterEqual(javascript.count("registerGenerationPrompt("), 3)

    def test_large_seeds_and_hires_metadata_are_restored_without_precision_loss(self):
        javascript = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")

        self.assertIn("BigInt(seed)+BigInt(index)", javascript)
        self.assertNotIn("Number.isSafeInteger(Number(seed))", javascript)
        self.assertIn("String(data.seed)", javascript)
        self.assertIn("data.hires?.enabled&&supportsHiresClient()", javascript)
        self.assertIn("data.hires.sampler&&$('hiresSampler')", javascript)
        self.assertIn('self.path == "/api/read-output"', backend)
        self.assertIn("self.send_json(parse_generation_info(file.read_bytes()))\n                return", backend)

    def test_compatible_models_default_to_requested_hires_configuration(self):
        javascript = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(
            encoding="utf-8")
        for marker in (
            "DEFAULT_HIRES_GENERATION_CONFIG",
            "scale:'1.3'", "denoise:'0.25'", "steps:'20'", "cfg:'5'",
            "sampler:'euler_ancestral'", "scheduler:'normal'",
            "function applyDefaultHiresGenerationConfig",
            "$('illustriousMode').value='hires'",
            "guidanceChanged(true);applyDefaultHiresGenerationConfig()",
        ):
            self.assertIn(marker, javascript)

    def test_output_enhancement_ui_is_capability_gated_and_payload_backed(self):
        advanced = (ROOT / "web" / "assets" / "js" / "model-advanced.js").read_text(
            encoding="utf-8")
        panel = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")

        for token in ("anime6b", "seedvr2", "ultimate", "faceDetailerEnabled",
                      "handDetailerEnabled", "footDetailerEnabled",
                      "limbDetailer", "autoColorMatchEnabled", "workflowFeatures"):
            self.assertIn(token, advanced)
        self.assertIn("data.outputEnhancement", advanced)
        self.assertIn("data.hand_detailer", panel)
        self.assertIn("data.foot_detailer", panel)
        self.assertIn("hiresSampler", panel)
        self.assertIn("hiresScheduler", panel)

    def test_standard_generation_can_use_a_depth_background_reference(self):
        panel = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(
            encoding="utf-8")
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")
        for marker in (
            "背景空间控制（Depth）", "用参考图锁定背景空间",
            "function uploadDepthReference", "function depthPayload",
            "depth:depthPayload()", "xinsir_depth", "function setDepthPreset",
            "轻控制", "标准控制", "强控制", "抑制简陋背景",
            "背景 LoRA 建议 0.4–0.6", "二采 0.25–0.32",
        ):
            self.assertIn(marker, panel)
        for marker in (
            'depth = data.get("depth")', "DepthAnythingV2Preprocessor",
            '"resolution": 1024', '"strength": depth_strength',
            '"depthBackgroundNegative"', 'and not depth_enabled',
        ):
            self.assertIn(marker, backend)

    def test_route1_can_use_main_pose_prompt_without_openpose(self):
        panel = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(
            encoding="utf-8")
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")
        for marker in (
            "function initRoute1PromptPoseMode", "仅使用主界面姿势提示词",
            "function route1PoseModeChanged", "value!=='prompt'",
        ):
            self.assertIn(marker, panel)
        self.assertIn('pose_mode not in {"prompt", "extract", "skeleton"}', backend)
        self.assertIn('if pose_mode != "prompt":', backend)

    def test_route1_smart_fusion_uses_soft_trimap_and_ring_only_redraw(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        panel = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(
            encoding="utf-8")
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")
        for marker in (
            "RMBG精确轮廓 + 自适应窄环重绘", "光照方向覆盖",
            "自动：近环 + 中环连续拟合", "route1FusionProfile",
            "route1FusionDenoise", "route1EnvironmentLightStrength", "照片颗粒",
            "route1SharpenStrength", "平坦皮肤区域基本不处理",
        ):
            self.assertIn(marker, html)
        for marker in (
            "function applyRoute1FusionPreset", "smartFusion:", "lightDirection:",
            "colorMatchStrength:", "environmentLightStrength:", "grainStrength:",
            "sharpenStrength:",
        ):
            self.assertIn(marker, panel)
        for marker in (
            '"LayerUtility: CropByMask"', '"LayerMask: RmBgUltra V2"',
            '"LayerUtility: RestoreCropBox"', '"ColorTransfer"',
            '"ImageBlend"', '"LayerFilter: AddGrain"', '"ImageSharpen"',
            '"Canny"', '"ImageToMask"', '"operation": "multiply"',
            '"operation": "subtract"', "ring_radius", "inner_radius",
            "prepare_route1_environment_light", "near_radius", "middle_radius",
            "np.linalg.lstsq",
        ):
            self.assertIn(marker, backend)

    def test_all_final_and_limb_prompts_are_editable_and_payload_backed(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(
            encoding="utf-8")
        advanced = (ROOT / "web" / "assets" / "js" / "model-advanced.js").read_text(
            encoding="utf-8")
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")

        self.assertIn('<textarea id="compiledPositive"', html)
        self.assertIn('<textarea id="compiledNegative"', html)
        self.assertIn('oninput="finalPromptChanged()"', html)
        self.assertIn('onclick="rebuildFinalPrompt()"', html)
        self.assertIn('onclick="clearFinalPrompt()"', html)
        self.assertIn("promptOverride:finalPromptOverride()", javascript)
        self.assertIn("data.promptOverride=finalPromptOverride()", javascript)
        self.assertIn("手动原样提交", javascript)
        self.assertIn("最终正负向已按图片原文恢复", javascript)
        self.assertIn('id="handDetailerPositive"', advanced)
        self.assertIn('id="handDetailerNegative"', advanced)
        self.assertIn('id="footDetailerPositive"', advanced)
        self.assertIn('id="footDetailerNegative"', advanced)
        self.assertIn('handPositive: byId("handDetailerPositive")', advanced)
        self.assertIn('override.get("positive", "")', backend)
        self.assertIn('"overridden": overridden', backend)

    def test_advanced_functions_have_matching_help_and_recommended_defaults(self):
        advanced = (ROOT / "web" / "assets" / "js" / "model-advanced.js").read_text(
            encoding="utf-8")

        self.assertIn('class="small" title=', advanced)
        for phrase in ("默认推荐", "推荐 1.5×", "推荐 1.25×", "推荐 512",
                       "推荐 0.70", "推荐 12"):
            self.assertIn(phrase, advanced)
        self.assertIn('anime6b: { scale: 1.5', advanced)
        self.assertIn('seedvr2: { scale: 1.25', advanced)
        self.assertIn('ultimate: { scale: 1.5', advanced)
        self.assertIn('value="1.5"', advanced)
        self.assertIn('id="handDetailerEnabled" type="checkbox" onchange=', advanced)
        self.assertIn('id="footDetailerEnabled" type="checkbox" onchange=', advanced)
        self.assertNotIn('id="handDetailerEnabled" type="checkbox" checked', advanced)
        self.assertNotIn('id="footDetailerEnabled" type="checkbox" checked', advanced)
        self.assertIn('id="limbDetailerDenoise"', advanced)
        self.assertIn('id="limbDetailerDenoise" type="number" min="0.15" max="0.6" step="0.05" value="0.35"', advanced)
        self.assertIn("features.hand_detailer === false", advanced)
        self.assertIn("features.foot_detailer === false", advanced)

    def test_lora_rows_support_buttons_and_drag_reordering(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(
            encoding="utf-8")
        css = (ROOT / "web" / "assets" / "css" / "panel.css").read_text(
            encoding="utf-8")

        self.assertIn("可拖动“↕序号”", html)
        self.assertIn("function moveLoraRow(row,direction)", javascript)
        self.assertIn("handle.draggable=true", javascript)
        self.assertIn("handle.ondragstart", javascript)
        self.assertIn("row.ondragover", javascript)
        self.assertIn("commitLoraOrder", javascript)
        self.assertIn("saveLoraState();renderRegions();promptEditorChanged()", javascript)
        self.assertIn("querySelectorAll('.lora-row')", javascript)
        self.assertIn(".lora-drag-handle", css)
        self.assertIn(".lora-row.dragging", css)


if __name__ == "__main__":
    unittest.main()
