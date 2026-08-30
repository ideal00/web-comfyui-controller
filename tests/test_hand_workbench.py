import unittest
from pathlib import Path


class HandWorkbenchTests(unittest.TestCase):
    def test_workbench_ui_and_assets_are_wired(self):
        html = Path("index.html").read_text(encoding="utf-8")
        script = Path("web/assets/js/hand-workbench.js").read_text(encoding="utf-8")
        css = Path("web/assets/css/panel.css").read_text(encoding="utf-8")

        for marker in (
            'id="handWorkbench"', 'id="handCanvas"', 'id="handToolMagnetic"',
            'id="handToolAnchor"', 'id="handToolWand"', 'id="handSendMaskButton"',
            'id="handMiniPaint"', 'id="handCompareCanvas"',
            'id="handPaintFullscreen"',
            'src="/assets/js/hand-workbench.js?v=6"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "function magneticPath", "function magicWand", "function morphMask",
            "function featherMask", "handSendMaskToRepair", "export-image",
            "destination-in", "maskTint",
            "toggleHandPaintFullscreen", "setHandPaintExpanded", "scheduleMiniPaintResize",
            "resize-editor", "resize-complete", "ResizeObserver",
        ):
            self.assertIn(marker, script)
        self.assertIn(".hand-workbench", css)
        self.assertIn(".hand-send-mask", css)
        self.assertIn(".hand-workbench.paint-expanded", css)
        self.assertIn(".hand-workbench.paint-resizing", css)
        self.assertIn("width:min(98vw,1800px)", css)
        self.assertIn("选区完成：发送蒙版到局部修复", html)

    def test_local_minipaint_bundle_keeps_license_and_bridge(self):
        vendor = Path("web/assets/vendor/minipaint")
        self.assertTrue((vendor / "MIT-LICENSE.txt").is_file())
        self.assertTrue((vendor / "dist/bundle.js").is_file())
        bridge = (vendor / "index.html").read_text(encoding="utf-8")
        self.assertIn("easy-panel-minipaint", bridge)
        self.assertIn("easy-panel-hand-workbench", bridge)
        self.assertIn('lang="zh-CN"', bridge)
        self.assertIn("?lang=zh&amp;ep=5", Path("index.html").read_text(encoding="utf-8"))
        self.assertIn("localizeMiniPaint", bridge)
        self.assertIn("resize-editor", bridge)
        self.assertIn("'Pressure': '压感'", bridge)
        self.assertIn("'Clone Tool': '仿制图章'", bridge)


if __name__ == "__main__":
    unittest.main()
