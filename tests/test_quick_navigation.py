import unittest
from html.parser import HTMLParser
from pathlib import Path


class _IdAncestorParser(HTMLParser):
    """Track the DOM ancestors of elements with ids without needing a browser."""

    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.ancestors = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        identifier = attrs.get("id")
        if identifier:
            self.ancestors[identifier] = tuple(item[1] or item[0] for item in self.stack)
        if tag not in self.VOID_TAGS:
            self.stack.append((tag, identifier))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID_TAGS and self.stack:
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


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
            'src="/assets/js/panel.js?v='
        ):
            self.assertIn(marker, html)
        self.assertIn("function jumpToPanelSection", script)
        self.assertIn("function jumpToPanelBottom", script)
        self.assertIn("function panelBottomTarget", script)
        self.assertIn("'jobQueueList'", script)
        self.assertIn("scrollPanelTargetIntoSafeView(target)", script)
        self.assertNotIn("const target=$('generate')", script)
        self.assertIn("toggleStudioToolDrawer(false)", script)
        self.assertIn("id==='loraSection'", script)
        self.assertIn("function quickGenerateImage", script)
        self.assertIn("quickBtn.disabled=true", script)
        self.assertIn("function updatePanelQuickJumpPosition", script)
        self.assertIn("getBoundingClientRect()", script)
        self.assertIn("nav.style.left", script)
        self.assertIn("PANEL_QUICK_JUMP_STORAGE", script)
        self.assertIn("initPanelQuickJumpDrag", script)
        self.assertIn("loadPanelQuickJumpPosition", script)
        self.assertIn("app?.classList.toggle('left-rail-collapsed',collapsed)", script)
        self.assertIn("preferredLeft=rect.right+24", script)
        self.assertIn("minimumLeft=collapsed?96:8", script)
        self.assertIn("moved:false,captured:false", script)
        self.assertIn("state.captured&&state.nav.hasPointerCapture", script)
        self.assertIn(".panel-quick-jumps", css)
        self.assertIn("left:0;top:50%;bottom:auto;transform:translateY(-50%)", css)
        self.assertIn(".quick-jump-highlight", css)
        self.assertIn(".panel-quick-jumps .quick-generate", css)
        self.assertIn("--studio-dock-reserve", css)

    def test_low_motion_dock_exposes_queue_without_scrolling(self):
        html = Path("index.html").read_text(encoding="utf-8")
        script = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        css = Path("web/assets/css/panel.css").read_text(encoding="utf-8")

        self.assertIn('id="studioActionDock" class="studio-action-dock"', html)
        self.assertIn('class="dock-enqueue" type="button" onclick="enqueueJob()"', html)
        self.assertIn('id="jobQueueDockCount"', html)
        self.assertIn("$('jobQueueDockCount')", script)
        self.assertIn(".studio-action-dock{position:relative", css)
        self.assertIn("min-height:46px", css)
        self.assertIn("生成面板快速跳转（按住可拖动）", html)

    def test_dock_has_an_independent_layout_row_and_scroll_helper_uses_viewport(self):
        html = Path("index.html").read_text(encoding="utf-8")
        script = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        css = Path("web/assets/css/panel.css").read_text(encoding="utf-8")

        parser = _IdAncestorParser()
        parser.feed(html)
        self.assertIn("studioContentViewport", parser.ancestors["studioLayout"])
        self.assertNotIn("studioContentViewport", parser.ancestors["studioActionDock"])
        self.assertIn("html,body{height:100%;overflow:hidden}", css)
        self.assertIn(".studio-content-viewport{flex:1 1 auto", css)
        self.assertIn(".studio-action-dock{position:relative", css)
        self.assertIn("scroller=document.querySelector('.studio-content-viewport')", script)
        self.assertIn("(scroller||window).scrollBy", script)
        self.assertIn("function scrollStudioContentToTop", script)
        self.assertIn("function initStudioViewportScroll", script)
        self.assertIn(".app{display:grid;grid-template-rows:auto minmax(0,1fr) auto", css)
        self.assertIn(".app{position:fixed;inset:0;width:100%;height:100vh;height:100dvh", css)
        self.assertIn(".panel-quick-jumps{touch-action:none;cursor:grab}", css)
        self.assertIn(".studio-action-dock{position:fixed!important;top:auto!important", css)
        self.assertIn(".studio-content-viewport{padding-bottom:calc(var(--studio-dock-reserve) + 14px)", css)


if __name__ == "__main__":
    unittest.main()
