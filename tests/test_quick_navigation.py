import unittest
from pathlib import Path


class QuickNavigationTests(unittest.TestCase):
    def test_lora_and_bottom_floating_buttons_are_wired(self):
        html = Path("index.html").read_text(encoding="utf-8")
        script = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        css = Path("web/assets/css/panel.css").read_text(encoding="utf-8")

        for marker in (
            'id="loraSection"',
            'class="panel-quick-jumps"',
            "jumpToPanelSection('loraSection')",
            'onclick="jumpToPanelBottom()"',
            'id="quickGenerate"',
            'onclick="quickGenerateImage()"',
            'src="/assets/js/panel.js?v=56"',
        ):
            self.assertIn(marker, html)
        self.assertIn("function jumpToPanelSection", script)
        self.assertIn("function jumpToPanelBottom", script)
        self.assertIn("const target=$('generate')", script)
        self.assertIn("toggleStudioToolDrawer(false)", script)
        self.assertIn("id==='loraSection'", script)
        self.assertIn("function quickGenerateImage", script)
        self.assertIn("quickBtn.disabled=true", script)
        self.assertIn(".panel-quick-jumps", css)
        self.assertIn("left:0;top:50%;bottom:auto;transform:translateY(-50%)", css)
        self.assertIn(".quick-jump-highlight", css)
        self.assertIn(".panel-quick-jumps .quick-generate", css)

    def test_low_motion_dock_exposes_queue_without_scrolling(self):
        html = Path("index.html").read_text(encoding="utf-8")
        script = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        css = Path("web/assets/css/panel.css").read_text(encoding="utf-8")

        self.assertIn('class="studio-action-dock"', html)
        self.assertIn('class="dock-enqueue" type="button" onclick="enqueueJob()"', html)
        self.assertIn('id="jobQueueDockCount"', html)
        self.assertIn("$('jobQueueDockCount')", script)
        self.assertIn(".studio-action-dock{position:fixed", css)
        self.assertIn("min-height:46px", css)


if __name__ == "__main__":
    unittest.main()
