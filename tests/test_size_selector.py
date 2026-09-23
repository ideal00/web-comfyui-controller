"""尺寸选择器（图片比例 + 长边滑块 + 推荐档位 + 尺寸信息）契约测试。

设计契约（2026-09-23 用户方案）：
  - 隐藏的原生 ``<select id="size">`` 仍是尺寸唯一真相源（``payload()`` / ``effectiveOutputSize()`` /
    ``model-advanced.js`` 都读它），新面板只负责把选择写回去，避免第二套尺寸状态；
  - 「比例」是严格数学比例（短边按比例计算后向下对齐 8 的倍数）；「推荐档位」保留 index.html 现有档位
    （≈ 表示像素只是近似比例，例如 1216×832 实际 1.46:1、768×1344 实际 4:7）；
  - 每个比例用 localStorage 记忆上次用的尺寸；
  - 主面板与 installers/payload 的脚本、样式必须逐字节一致。
"""

from __future__ import annotations

import math
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGES = [ROOT / "index.html", ROOT / "installers/payload/index.html"]
SCRIPT = ROOT / "web/assets/js/size-selector.js"
PAYLOAD_SCRIPT = ROOT / "installers/payload/web/assets/js/size-selector.js"
CSS = ROOT / "web/assets/css/panel.css"
PAYLOAD_CSS = ROOT / "installers/payload/web/assets/css/panel.css"
PANEL_JS = ROOT / "web/assets/js/panel.js"

RATIO_ORDER = ["1:1", "2:3", "3:4", "9:16", "1:2", "9:21", "3:2", "4:3", "16:9", "2:1", "21:9"]
OPTION_RE = re.compile(r'<option value="(\d{2,5})x(\d{2,5})"[^>]*>([^<]*)</option>')
RATIO_LABEL_RE = re.compile(r"[（(]\s*(\d+)\s*[:：]\s*(\d+)\s*[)）]")


def nearest_ratio(width: int, height: int) -> str:
    """与前端 nearestRatioKey 同一套算法（对数距离里找最接近的主比例）。"""
    target = math.log(width / height)
    best, gap = "", float("inf")
    for key in RATIO_ORDER:
        w, h = (int(part) for part in key.split(":"))
        delta = abs(math.log(w / h) - target)
        if delta < gap - 1e-9:
            best, gap = key, delta
    return best


def parse_presets(html: str) -> list[tuple[int, int, str]]:
    return [
        (int(match.group(1)), int(match.group(2)), match.group(3))
        for match in OPTION_RE.finditer(html)
    ]


class SizeSelectorWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")
        cls.pages = [page.read_text(encoding="utf-8") for page in PAGES]
        cls.panel_js = PANEL_JS.read_text(encoding="utf-8")

    def test_both_pages_load_the_selector(self):
        for page in self.pages:
            self.assertIn('<script src="/assets/js/size-selector.js?v=1"></script>', page)
            self.assertIn('href="/assets/css/panel.css?v=47"', page)

    def test_payload_copies_are_byte_identical(self):
        self.assertEqual(SCRIPT.read_bytes(), PAYLOAD_SCRIPT.read_bytes())
        self.assertEqual(CSS.read_bytes(), PAYLOAD_CSS.read_bytes())

    def test_native_select_remains_the_single_source_of_truth(self):
        for page in self.pages:
            self.assertIn('<select id="size" onchange="updateSizeInfo()">', page)
        # 面板继续读原生 select（编译器 / 预检 / 队列都靠它）
        self.assertIn("String($('size')?.value||'864x1152')", self.panel_js)
        self.assertIn("$('size').value.split('x')", self.panel_js)
        # 新模块只写回，不引入第二套尺寸状态
        self.assertIn('const select = byId("size")', self.source)
        self.assertIn("elements.select.value !== value", self.source)
        self.assertNotIn("function payload(", self.source)

    def test_selector_wraps_panel_hooks(self):
        for hook in ('wrapGlobal("updateSizeInfo"', 'wrapGlobal("modelChanged"', 'wrapGlobal("modelAdvancedChanged"'):
            self.assertIn(hook, self.source)
        # 包装必须幂等，不能重复包出无限递归
        self.assertIn("__sizeSelectorWrapped", self.source)

    def test_ratio_table_matches_the_agreed_spec(self):
        order = re.search(r"const RATIO_ORDER = \[(.*?)\];", self.source, re.S)
        self.assertIsNotNone(order)
        self.assertEqual(
            RATIO_ORDER,
            re.findall(r'"(\d+:\d+)"', order.group(1)),
        )
        for key in RATIO_ORDER:
            width, height = (int(part) for part in key.split(":"))
            self.assertIn(f'"{key}": {{ w: {width}, h: {height} }},', self.source)

    def test_memory_and_display_contract(self):
        self.assertIn('const MEMORY_KEY = "easyPanelSizeByRatioV1"', self.source)
        self.assertIn("easyPanelSizeByRatioV1", self.source)
        for marker in ("图片比例", "推荐档位", "预计显存负载", "自定义", "长边", "对齐 8 的倍数"):
            self.assertIn(marker, self.source)
        # 短边向下对齐（1664×1104 之类的值），不要越过数学比例多占显存
        self.assertIn("Math.floor(number / unit) * unit", self.source)
        self.assertIn("alignDown(exact, unit)", self.source)

    def test_module_is_dom_guarded_and_exported(self):
        self.assertIn('typeof document === "undefined"', self.source)
        self.assertIn("window.EasyPanelSizeSelector = testApi;", self.source)
        self.assertIn("module.exports = testApi;", self.source)

    def test_styles_are_installed(self):
        for marker in (
            ".three>.size-field-wide{grid-column:1/-1}",
            ".size-ratio-chip",
            ".size-preset-chip",
            ".size-preset-approx",
            ".size-picker-range input[type=range]",
        ):
            self.assertIn(marker, self.css)


class SizePresetRatioTests(unittest.TestCase):
    """档位 → 比例的分组契约：现有档位一个都不能掉，也不能被硬改成数学精确值。"""

    @classmethod
    def setUpClass(cls):
        cls.pages = [parse_presets(page.read_text(encoding="utf-8")) for page in PAGES]

    def test_every_preset_maps_to_a_primary_ratio(self):
        for presets in self.pages:
            self.assertGreaterEqual(len(presets), 24)
            for width, height, label in presets:
                match = RATIO_LABEL_RE.search(label)
                key = f"{int(match.group(1))}:{int(match.group(2))}" if match else ""
                if key not in RATIO_ORDER:
                    key = nearest_ratio(width, height)
                self.assertIn(key, RATIO_ORDER, f"{width}×{height} 没有归入任何比例")
                target_w, target_h = (int(part) for part in key.split(":"))
                drift = abs(width / height - target_w / target_h) / (target_w / target_h)
                self.assertLess(drift, 0.05, f"{width}×{height} 与 {key} 相差 {drift:.1%}")

    def test_approximate_presets_keep_their_labels(self):
        presets = dict(((w, h), label) for w, h, label in self.pages[0])
        # 这些档位的像素不是严格数学比例，标签必须写明实际比例（滑块会用严格比例）
        self.assertIn("（4:7）", presets[(768, 1344)])
        self.assertIn("（7:4）", presets[(1344, 768)])
        self.assertIn("（3:2）", presets[(1216, 832)])
        self.assertEqual("3:2", nearest_ratio(1216, 832))

    def test_presets_stay_8_aligned_within_backend_limits(self):
        for presets in self.pages:
            for width, height, _label in presets:
                self.assertEqual(0, width % 8, f"{width}×{height} 宽度不是 8 的倍数")
                self.assertEqual(0, height % 8, f"{width}×{height} 高度不是 8 的倍数")
                self.assertLessEqual(max(width, height), 2560, f"{width}×{height} 超过后端上限")

    def test_default_size_is_still_864x1152(self):
        panel_js = PANEL_JS.read_text(encoding="utf-8")
        self.assertIn("preferred='864x1152'", panel_js)
        self.assertEqual("3:4", nearest_ratio(864, 1152))


if __name__ == "__main__":
    unittest.main()
