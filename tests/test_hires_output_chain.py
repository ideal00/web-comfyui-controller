"""高清输出链的数据行为测试：_base_ 对照图与成品图的分离、上限约束与快照落盘。"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.media_storage import (
    HIRES_BASE_MARKER,
    is_hires_base_filename,
    split_hires_outputs,
)


SPEC = importlib.util.spec_from_file_location("easy_panel_hires_chain_test", PROJECT_DIR / "easy_panel.py")
easy_panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = easy_panel
SPEC.loader.exec_module(easy_panel)


class SplitHiresOutputsTests(unittest.TestCase):
    """一次高清任务的输出必须能拆成 final / base 两份。"""

    def test_split_hires_outputs(self):
        images = [
            {"filename": "EasyPanel_001_base_00001_.png"},
            {"filename": "EasyPanel_001_00001_.png"},
        ]
        result = split_hires_outputs(images)
        self.assertEqual(1, len(result["base"]))
        self.assertEqual(1, len(result["final"]))
        self.assertTrue(result["final"][0]["filename"].endswith("_00001_.png"))
        self.assertNotIn(HIRES_BASE_MARKER, result["final"][0]["filename"])

    def test_split_hires_outputs_batch(self):
        images = [
            {"filename": "x_base_00001_.png"},
            {"filename": "x_00001_.png"},
            {"filename": "x_base_00002_.png"},
            {"filename": "x_00002_.png"},
        ]
        result = split_hires_outputs(images)
        self.assertEqual(2, len(result["base"]))
        self.assertEqual(2, len(result["final"]))

    def test_normal_generation_has_no_base_outputs(self):
        result = split_hires_outputs([{"filename": "EasyPanel_001_00001_.png"}])
        self.assertEqual([], result["base"])
        self.assertEqual(1, len(result["final"]))

    def test_missing_base_does_not_break_final_output(self):
        # 首采对照图被删掉时，成品仍必须正常返回。
        result = split_hires_outputs([{"filename": "EasyPanel_001_00001_.png"}])
        self.assertEqual(1, len(result["final"]))
        self.assertEqual([], result["base"])

    def test_only_base_reports_empty_final(self):
        result = split_hires_outputs([{"filename": "EasyPanel_001_base_00001_.png"}])
        self.assertEqual(1, len(result["base"]))
        self.assertEqual([], result["final"])

    def test_accepts_plain_filename_strings(self):
        result = split_hires_outputs(["a_base_00001_.png", "a_00001_.png"])
        self.assertEqual(1, len(result["base"]))
        self.assertEqual(1, len(result["final"]))
        self.assertTrue(is_hires_base_filename("a_base_00001_.png"))
        self.assertFalse(is_hires_base_filename("a_00001_.png"))
        self.assertFalse(is_hires_base_filename(None))
        self.assertFalse(is_hires_base_filename({"filename": ""}))

    def test_empty_input_is_safe(self):
        for value in (None, [], "not-a-list", 0):
            with self.subTest(value=value):
                self.assertEqual({"all": [], "final": [], "base": []}, split_hires_outputs(value))


class HiresPurposeCapTests(unittest.TestCase):
    """二采目的决定 denoise 上限，网页 / API / 手机端共用同一套数字。"""

    def test_purpose_caps_match_the_documented_ranges(self):
        self.assertEqual(0.23, easy_panel.HIRES_PURPOSE_CAPS["preserve"])
        self.assertEqual(0.26, easy_panel.HIRES_PURPOSE_CAPS["enhance"])
        self.assertEqual(0.35, easy_panel.HIRES_PURPOSE_CAPS["redraw"])

    def test_preserve_caps_denoise(self):
        data = {"hiresPurpose": "preserve", "hiresDenoise": 0.35}
        self.assertEqual(0.23, easy_panel.hires_purpose_cap(data))

    def test_enhance_is_the_default(self):
        self.assertEqual("enhance", easy_panel.normalized_hires_purpose({}))
        self.assertEqual(0.26, easy_panel.hires_purpose_cap({}))

    def test_redraw_allows_the_retouch_ceiling(self):
        self.assertEqual(0.35, easy_panel.hires_purpose_cap({"hiresPurpose": "redraw"}))

    def test_unknown_purpose_falls_back_to_enhance(self):
        self.assertEqual("enhance", easy_panel.normalized_hires_purpose({"hiresPurpose": "nope"}))

    def hires_denoise(self, workflow) -> float:
        samplers = [node for node in workflow["prompt"].values()
                    if node.get("class_type") == "KSampler"]
        return samplers[-1]["inputs"]["denoise"]

    def build(self, purpose: str, denoise: float):
        data = {
            "model": "waiIllustriousSDXL_v140.safetensors",
            "illustriousMode": "hires",
            "hiresScale": 1.2,
            "hiresPurpose": purpose,
            "hiresDenoise": denoise,
            "promptSections": {"subject": "1girl", "scene": "studio"},
            "negative": "",
        }
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            return easy_panel.build_workflow(data)

    def test_build_workflow_clamps_denoise_by_purpose(self):
        # 直接 POST 一个超标的 denoise 也必须被目的上限压住。
        self.assertEqual(0.23, self.hires_denoise(self.build("preserve", 0.35)))
        self.assertEqual(0.26, self.hires_denoise(self.build("enhance", 0.35)))
        self.assertEqual(0.35, self.hires_denoise(self.build("redraw", 0.35)))

    def test_build_workflow_keeps_values_inside_the_cap(self):
        self.assertEqual(0.18, self.hires_denoise(self.build("preserve", 0.18)))
        self.assertEqual(0.30, self.hires_denoise(self.build("redraw", 0.30)))

    def test_composition_lock_no_longer_raises_the_ceiling(self):
        # 构图锁过去会把 0.35 当成上限；现在上限只由目的决定。
        data = {
            "model": "waiIllustriousSDXL_v140.safetensors",
            "illustriousMode": "hires",
            "hiresScale": 1.2,
            "hiresCompositionLock": True,
            "hiresDenoise": 0.35,
            "promptSections": {"subject": "1girl", "scene": "studio"},
            "negative": "",
        }
        with patch.object(easy_panel, "checkpoint_issue", return_value=None):
            workflow = easy_panel.build_workflow(data)
        self.assertEqual(0.26, self.hires_denoise(workflow))


class SnapshotComparisonOutputsTests(unittest.TestCase):
    """快照只把成品写进 outputs，首采对照图单独放 comparisonOutputs。"""

    def test_attach_snapshot_outputs_splits_base(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot_file = Path(folder) / "generation_snapshots.json"
            with patch.object(easy_panel, "SNAPSHOT_FILE", snapshot_file), \
                 patch.object(easy_panel, "update_creative_index_status_best_effort", lambda *a, **k: {}):
                easy_panel.write_snapshots([{"id": "snap-1", "outputs": [], "createdAt": 0}])
                easy_panel.attach_snapshot_outputs(
                    "snap-1",
                    ["EasyPanel_001_00001_.png"],
                    base_outputs=["EasyPanel_001_base_00001_.png"],
                )
                saved = easy_panel.load_snapshots()[0]
        self.assertEqual(["EasyPanel_001_00001_.png"], saved["outputs"])
        self.assertEqual(["EasyPanel_001_base_00001_.png"], saved["comparisonOutputs"])

    def test_task_queue_outputs_only_writes_final_images(self):
        captured = {}

        def fake_attach(snapshot_id, outputs, base_outputs=None):
            captured["snapshot_id"] = snapshot_id
            captured["outputs"] = list(outputs)
            captured["base_outputs"] = list(base_outputs or [])
            return {}

        payload = {"images": [
            {"filename": "EasyPanel_001_base_00001_.png"},
            {"filename": "EasyPanel_001_00001_.png"},
        ]}
        with patch.object(easy_panel, "attach_snapshot_outputs", fake_attach):
            easy_panel.task_queue_outputs({"snapshot_id": "snap-9"}, "completed", payload)
        self.assertEqual("snap-9", captured["snapshot_id"])
        self.assertEqual(["EasyPanel_001_00001_.png"], captured["outputs"])
        self.assertEqual(["EasyPanel_001_base_00001_.png"], captured["base_outputs"])

    def test_task_queue_outputs_without_base_writes_only_final(self):
        captured = {}

        def fake_attach(snapshot_id, outputs, base_outputs=None):
            captured["outputs"] = list(outputs)
            captured["base_outputs"] = list(base_outputs or [])
            return {}

        payload = {"images": [{"filename": "EasyPanel_001_00001_.png"}]}
        with patch.object(easy_panel, "attach_snapshot_outputs", fake_attach):
            easy_panel.task_queue_outputs({"snapshot_id": "snap-1"}, "completed", payload)
        self.assertEqual(["EasyPanel_001_00001_.png"], captured["outputs"])
        self.assertEqual([], captured["base_outputs"])


class HiresPairingContractTests(unittest.TestCase):
    """前端必须按批次序号配对，而不是依赖数组位置。"""

    def setUp(self):
        self.script = (PROJECT_DIR / "web/assets/js/result-workbench.js").read_text(encoding="utf-8")

    def test_pairs_by_batch_index(self):
        for marker in ("outputBatchIndex", "pairHiresOutputs", r"_(\d{5})_",
                       "不依赖数组位置", "没有找到与这张成品对应的首采对照图"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)

    def test_mobile_backend_uses_the_shared_helper(self):
        mobile = (PROJECT_DIR / "easy_panel_app/rpg_api.py").read_text(encoding="utf-8")
        self.assertIn("is_hires_base_filename", mobile)
        backend = (PROJECT_DIR / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn("split_hires_outputs", backend)


if __name__ == "__main__":
    unittest.main()
