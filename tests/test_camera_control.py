"""相机机位控制（BSK 语义）的契约测试。

面板滑杆值经 easy_panel_app/camera_control.py 折算成加权相机词，由 compile_prompt 并入正向词。
它与 BSK_相机控制 节点同语义（方位 2D 比例分配 / 高度互斥单档 / 距离档位 / 翻滚死区），
但由面板直接计算，不依赖外部插件；真正的机位效果来自配套的机位 LoRA。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app import camera_control
from easy_panel_app.camera_control import (
    compute_camera_prompt,
    compute_camera_terms,
    normalize_camera_control,
    preview_response,
    prompt_terms,
)

SPEC = importlib.util.spec_from_file_location("easy_panel_camera_control_test", PROJECT_DIR / "easy_panel.py")
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


class PromptMathTests(unittest.TestCase):
    def test_rest_position_defaults(self):
        prompt = compute_camera_prompt(0.0, 0.0, 0.0, 0.0)
        self.assertIn("(from front:10.00)", prompt)
        self.assertIn("(eye-level:3.00)", prompt)
        self.assertIn("(medium shot:1.00)", prompt)
        self.assertTrue(prompt.endswith(","))

    def test_azimuth_direction_labels_follow_bsk(self):
        # BSK 的映射：x=+0.5 是 right 分量但输出 from left；±1 才是背面。
        self.assertIn("(from left:10.00)", compute_camera_prompt(0.5, 0.0, 0.0, 0.0))
        self.assertIn("(from right:10.00)", compute_camera_prompt(-0.5, 0.0, 0.0, 0.0))
        self.assertIn("(from behind:10.00)", compute_camera_prompt(1.0, 0.0, 0.0, 0.0))

    def test_azimuth_splits_budget_between_two_directions(self):
        terms = compute_camera_terms(0.25, 0.0, 0.0, 0.0)
        self.assertIn("(from front:5.00)", terms)
        self.assertIn("(from left:5.00)", terms)

    def test_azimuth_deadzone_drops_minor_directions(self):
        # 占比折算后低于死区 0.2 的方向不输出：x=0.004 时次要方向权重仅 0.12，只留主导方向。
        terms = compute_camera_terms(0.004, 0.0, 0.0, 0.0)
        azimuth = [item for item in terms if any(flag in item for flag in
                                                 ("from front", "from behind", "from left", "from right"))]
        self.assertEqual(1, len(azimuth))
        self.assertIn("from front", azimuth[0])

    def test_elevation_single_exclusive_category(self):
        # 档位的多个 tag 会各自输出同权重（与 BSK 节点一致），但整个高度轴只出一个档位。
        high = compute_camera_terms(0.0, 0.4, 0.0, 0.0)
        self.assertIn("(high angle:4.40)", high)
        self.assertIn("(from above:4.40)", high)
        low = compute_camera_terms(0.0, -0.4, 0.0, 0.0)
        self.assertIn("(low angle:4.40)", low)
        self.assertIn("(from below:4.40)", low)
        bird = compute_camera_terms(0.0, 0.85, 0.0, 0.0)
        self.assertIn("(aerial view:9.35)", bird)
        self.assertNotIn("(high angle", ", ".join(bird))

    def test_pole_gate_silences_azimuth(self):
        prompt = compute_camera_prompt(0.0, 1.0, 0.0, 0.0)
        self.assertNotIn("from front", prompt)

    def test_distance_categories(self):
        self.assertIn("(extreme close-up:1.00)", compute_camera_prompt(0.0, 0.0, 0.9, 0.0))
        self.assertIn("(close-up:1.00)", compute_camera_prompt(0.0, 0.0, 0.5, 0.0))
        self.assertIn("(full body:1.00)", compute_camera_prompt(0.0, 0.0, -0.5, 0.0))
        self.assertIn("(wide shot:1.00)", compute_camera_prompt(0.0, 0.0, -0.9, 0.0))

    def test_tilt_deadzone(self):
        self.assertIn("(dutch angle:1.00)", compute_camera_prompt(0.0, 0.0, 0.0, 0.2))
        self.assertNotIn("dutch angle", compute_camera_prompt(0.0, 0.0, 0.0, 0.1))

    def test_extras_default_off(self):
        prompt = compute_camera_prompt(0.0, 0.0, 0.0, 0.0)
        self.assertNotIn("cinematic", prompt)
        self.assertNotIn("depth of field", prompt)


class RequestShapeTests(unittest.TestCase):
    def test_normalize_requires_enabled_flag(self):
        self.assertIsNone(normalize_camera_control(None))
        self.assertIsNone(normalize_camera_control({"enabled": False, "x": 0.5}))
        self.assertIsNone(normalize_camera_control("x=0.5"))

    def test_normalize_clamps_and_coerces(self):
        state = normalize_camera_control({"enabled": True, "x": 5, "y": "abc", "z": -3, "roll": 0.2})
        self.assertEqual(1.0, state["x"])
        self.assertEqual(0.0, state["y"])
        self.assertEqual(-1.0, state["z"])
        self.assertAlmostEqual(0.2, state["roll"])

    def test_prompt_terms_disabled_is_empty(self):
        self.assertEqual([], prompt_terms({"cameraControl": {"enabled": False}}))
        self.assertEqual([], prompt_terms({}))
        self.assertTrue(prompt_terms({"cameraControl": {"enabled": True, "x": 0.5}}))

    def test_preview_response_accepts_flat_sliders(self):
        data = preview_response({"x": 0.5, "y": 0.0, "z": 0.0, "roll": 0.0})
        self.assertIn("from left", data["prompt"])
        self.assertTrue(data["weighted"])


class CompileIntegrationTests(unittest.TestCase):
    def compiled(self, camera):
        return easy_panel.compile_prompt({
            "model": "illustriousTest.safetensors",
            "promptSections": {"subject": "1girl, solo", "scene": "simple background"},
            "negative": "",
            "cameraControl": camera,
        })

    def test_enabled_terms_flow_into_positive(self):
        result = self.compiled({"enabled": True, "x": 0.5, "y": 0.0, "z": 0.9, "roll": 0.0})
        self.assertIn("from left", result["positive"])
        self.assertIn("extreme close-up", result["positive"])
        self.assertIn("cameraControl", [item["key"] for item in result["sources"]])

    def test_disabled_terms_are_absent(self):
        result = self.compiled({"enabled": False, "x": 0.5, "y": 0.0, "z": 0.9, "roll": 0.0})
        self.assertNotIn("from left", result["positive"])
        self.assertNotIn("cameraControl", [item["key"] for item in result["sources"]])

    def test_manual_override_stays_untouched(self):
        data = {
            "model": "illustriousTest.safetensors",
            "promptSections": {"subject": "1girl"},
            "negative": "",
            "cameraControl": {"enabled": True, "x": 0.5, "y": 0.0, "z": 0.0, "roll": 0.0},
            "promptOverride": {"enabled": True, "positive": "1girl, custom text", "negative": ""},
        }
        result = easy_panel.compile_prompt(data)
        self.assertEqual("1girl, custom text", result["positive"])


class FrontendWiringTests(unittest.TestCase):
    def test_index_loads_camera_script(self):
        html = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("camera-control.js", html)

    def test_script_covers_payload_restore_and_preview(self):
        script = (PROJECT_DIR / "web" / "assets" / "js" / "camera-control.js").read_text(encoding="utf-8")
        for needle in ("cameraControl", "/api/camera-prompt", "restorePayloadToPanel",
                       "promptCompilePayload", "相机机位控制"):
            self.assertIn(needle, script)

    def test_backend_registers_endpoint_and_hook(self):
        source = (PROJECT_DIR / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn('"/api/camera-prompt"', source)
        self.assertIn("camera_control.prompt_terms(data)", source)

    def test_mobile_passthrough(self):
        api = (PROJECT_DIR / "easy_panel_app" / "rpg_api.py").read_text(encoding="utf-8")
        self.assertIn('"animaHighres", "cameraControl"', api)
        ts = (PROJECT_DIR / "android-client" / "src" / "services" / "easyPanelVisual.ts").read_text(encoding="utf-8")
        self.assertIn("cameraControl?: Record<string, unknown>", ts)
        controller = (PROJECT_DIR / "android-client" / "src" / "lib" / "easyPanelController.ts").read_text(encoding="utf-8")
        self.assertIn("'animaHighres', 'cameraControl'", controller)


if __name__ == "__main__":
    unittest.main()
