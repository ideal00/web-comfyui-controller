from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.fingerprint import fingerprint_parts, generation_fingerprint  # noqa: E402


def recipe(**overrides) -> dict:
    data = {
        "model": "wai-illustrious.safetensors",
        "seed": "1234",
        "width": 832,
        "height": 1216,
        "steps": 28,
        "cfg": 5.0,
        "sampler": "euler_ancestral",
        "scheduler": "normal",
        "prompt": "1girl, silver hair, red dress",
        "negative": "bad anatomy",
        "loras": [{"name": "服装/红裙.safetensors", "weight": 0.7}],
        "hiresScale": 1.5,
        "hiresDenoise": 0.4,
    }
    data.update(overrides)
    return data


class GenerationFingerprintTests(unittest.TestCase):
    """同模型 + 同 LoRA + 同提示词 + 同 seed + 同参数 = 同一个任务指纹。"""

    def test_same_recipe_has_same_fingerprint(self):
        first = generation_fingerprint(recipe())
        second = generation_fingerprint(recipe())
        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertEqual(64, len(first))

    def test_volatile_fields_do_not_change_fingerprint(self):
        base = generation_fingerprint(recipe())
        noisy = generation_fingerprint(recipe(
            requestId="abc", clientId="desktop", batchCount=8, label="实验 3",
            experiment={"variable": "cfg"}, generatedAt=1730000000000,
        ))
        self.assertEqual(base, noisy)

    def test_recipe_changes_are_detected(self):
        base = generation_fingerprint(recipe())
        for overrides in ({"seed": "1235"}, {"model": "anima.safetensors"},
                          {"prompt": "1girl, silver hair, blue dress"},
                          {"hiresScale": 2.0}, {"steps": 30},
                          {"loras": [{"name": "服装/红裙.safetensors", "weight": 0.9}]},
                          {"loras": [{"name": "服装/蓝裙.safetensors", "weight": 0.7}]}):
            with self.subTest(overrides=overrides):
                self.assertNotEqual(base, generation_fingerprint(recipe(**overrides)))

    def test_lora_order_and_case_do_not_matter(self):
        first = generation_fingerprint(recipe(loras=[
            {"name": "A.safetensors", "weight": 0.8}, {"name": "B.safetensors", "weight": 0.5}]))
        second = generation_fingerprint(recipe(loras=[
            {"name": "b.safetensors", "weight": 0.5}, {"name": "a.safetensors", "weight": 0.8}]))
        self.assertEqual(first, second)

    def test_whitespace_is_normalized(self):
        first = generation_fingerprint(recipe(prompt="1girl,   silver hair,\n red dress"))
        second = generation_fingerprint(recipe(prompt=" 1girl, silver hair, red dress "))
        self.assertEqual(first, second)

    def test_uploaded_file_names_are_ignored(self):
        base = generation_fingerprint(recipe(img2img={"image": "tmp_a.png", "denoise": 0.5}))
        other = generation_fingerprint(recipe(img2img={"image": "tmp_b.png", "denoise": 0.5}))
        changed = generation_fingerprint(recipe(img2img={"image": "tmp_a.png", "denoise": 0.7}))
        self.assertEqual(base, other)
        self.assertNotEqual(base, changed)

    def test_regions_are_part_of_the_recipe(self):
        first = generation_fingerprint(recipe(regions=[
            {"prompt": "girl A", "x": 0, "y": 0, "width": 0.5, "height": 1}]))
        second = generation_fingerprint(recipe(regions=[
            {"prompt": "girl B", "x": 0, "y": 0, "width": 0.5, "height": 1}]))
        self.assertNotEqual(first, second)

    def test_mobile_client_block_does_not_change_fingerprint(self):
        """移动端把本次请求编号放在 client.requestId / client.sceneId 里，不能影响指纹。"""

        first = generation_fingerprint(recipe(client={
            "gameId": "easy-panel-mobile", "sceneId": "prompt_1_abc", "requestId": "prompt_1_abc",
        }))
        second = generation_fingerprint(recipe(client={
            "gameId": "easy-panel-mobile", "sceneId": "prompt_2_xyz", "requestId": "prompt_2_xyz",
        }))
        self.assertEqual(first, second)
        # gameId 是固定值（区分手机 / 电脑来源），仍然保留在指纹里。
        self.assertNotEqual(first, generation_fingerprint(recipe()))

    def test_empty_payload_has_no_fingerprint(self):
        self.assertEqual("", generation_fingerprint({}))
        self.assertEqual({}, fingerprint_parts(None))

    def test_parts_expose_what_is_compared(self):
        parts = fingerprint_parts(recipe())
        self.assertEqual("1234", parts["seed"])
        self.assertEqual(1, len(parts["loras"]))
        self.assertNotIn("requestId", fingerprint_parts(recipe(requestId="x")))


if __name__ == "__main__":
    unittest.main()
