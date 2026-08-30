import unittest
from pathlib import Path


class PromptLibraryTests(unittest.TestCase):
    def test_expanded_library_and_compact_ui_are_wired(self):
        html = Path("index.html").read_text(encoding="utf-8")
        panel = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        library = Path("web/assets/js/prompt-library.js").read_text(encoding="utf-8")
        css = Path("web/assets/css/panel.css").read_text(encoding="utf-8")

        self.assertLess(html.index("prompt-library.js?v=5"), html.index("panel.js?v=55"))
        for marker in ('id="tokenSearch"', 'id="tokenCategoryTabs"', "filterTokenLibrary()"):
            self.assertIn(marker, html)
        for marker in ("selectTokenGroup", "activeTokenGroup", "EASY_PANEL_PROMPT_LIBRARY"):
            self.assertIn(marker, panel)
        for marker in (
            "写真·站立倚靠", "写真·坐跪蹲", "写真·躺卧支撑",
            "写真·手势动作", "写真·组合预设", "standing, contrapposto",
            "sitting on edge of bed", "lying on stomach", "dappled sunlight",
            "window shadow", "train interior", "spacecraft", "hair intakes",
            "solo focus",
            "cinematic color grading", "gouache (medium)", "retro anime",
            "volumetric lighting", "golden hour", "dreamy atmosphere",
            "光辉·质量与画风", "光辉·光线与氛围", "rim lighting",
            "painting (medium)", "different shadow", "milky way",
            "光辉·表情标签", "nervous smile", "watery eyes", "jitome",
            "光辉·成人主体（仅成年）", "光辉·成人反应（仅成年）",
            "光辉·成人裸露与遮挡（仅成年）", "光辉·成人互动（仅成年自愿）",
            "光辉·成人体液（仅成年）", "mature female", "implied sex",
        ):
            self.assertIn(marker, library)
        self.assertGreater(library.count("|"), 750)
        self.assertIn("max-height:268px", css)
        self.assertIn("overflow-x:auto", css)


if __name__ == "__main__":
    unittest.main()
