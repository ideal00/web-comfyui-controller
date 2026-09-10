import unittest
from pathlib import Path


class ImageViewerTests(unittest.TestCase):
    def test_generated_images_open_in_navigable_viewer(self):
        html = Path("index.html").read_text(encoding="utf-8")
        script = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        css = Path("web/assets/css/panel.css").read_text(encoding="utf-8")

        for marker in (
            'id="panelImageViewer"',
            'id="panelImageViewerPrev"',
            'id="panelImageViewerNext"',
            'id="panelImageViewerImage"',
            'id="panelImageViewerStage"',
            'id="panelImageViewerCanvas"',
            'id="panelImageViewerCount"',
            'id="panelImageViewerZoom"',
            'id="panelImageViewerZoomValue"',
            'src="/assets/js/panel.js?v='
        ):
            self.assertIn(marker, html)
        for marker in (
            "function openGeneratedViewer",
            "function openLinkedImageViewer",
            "function stepPanelImageViewer",
            "function panelImageViewerKeydown",
            "function panelImageViewerPointerUp",
            "function setPanelImageViewerZoom",
            "function stepPanelImageViewerZoom",
            "function panelImageViewerWheel",
            "function measurePanelImageViewer",
            "function layoutPanelImageViewer",
            "if(!event.altKey)return",
            "Math.min(400",
            "event.key==='ArrowLeft'",
            "event.key==='ArrowRight'",
            "onclick=\"return openGeneratedViewer(event,",
            "onclick=\"return openLinkedImageViewer(event,this)",
            'class="snapshot-output"',
        ):
            self.assertIn(marker, script)
        self.assertIn(".panel-image-viewer", css)
        self.assertIn(".panel-image-viewer-nav.previous", css)
        self.assertIn(".panel-image-viewer-zoom", css)
        self.assertIn(".panel-image-viewer-close{top:18px;left:20px;right:auto", css)
        self.assertIn("overflow:auto", css)
        self.assertIn("overscroll-behavior:contain", css)
        self.assertIn("touch-action:pan-y", css)


if __name__ == "__main__":
    unittest.main()
