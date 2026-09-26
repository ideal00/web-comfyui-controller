"""左侧「快捷工具」抽屉折叠层（rail-fold.js）契约测试。

需求（2026-09-23）：透明背景角色 PNG 移进左侧抽屉并折叠；抽屉里原本不能折叠的
（输入框字号 / 我的功能 / 中文描述转换 / 读图还原）也统一改成可折叠。

契约：
  - 每块折叠面板都是 details[data-rail-fold]（默认折叠、状态记 localStorage）；
  - 透明背景面板由 model-advanced.js 动态移进 #railTransparentMount，并保留旧版回退；
  - 结果类操作（读 DeepSeek 回答 / 读图还原 / 打开透明蒙版编辑）会自动展开对应面板；
  - 主面板与 installers/payload 的脚本、样式、页面逐字节一致。
"""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGES = [ROOT / "index.html", ROOT / "installers/payload/index.html"]
SCRIPT = ROOT / "web/assets/js/rail-fold.js"
PAYLOAD_SCRIPT = ROOT / "installers/payload/web/assets/js/rail-fold.js"
CSS = ROOT / "web/assets/css/panel.css"
PAYLOAD_CSS = ROOT / "installers/payload/web/assets/css/panel.css"
ADVANCED = ROOT / "web/assets/js/model-advanced.js"
PAYLOAD_ADVANCED = ROOT / "installers/payload/web/assets/js/model-advanced.js"

FOLD_IDS = ["customFeatureCard", "taskQueueFold", "translationCard", "imageReadCard"]


class RailFoldMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = [page.read_text(encoding="utf-8") for page in PAGES]
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")
        cls.advanced = ADVANCED.read_text(encoding="utf-8")

    def test_both_pages_install_the_fold_layer(self):
        for page in self.pages:
            self.assertIn('<script src="/assets/js/rail-fold.js?v=3"></script>', page)
            self.assertIn('id="railTransparentMount"', page)
            self.assertIn('id="railTransparentLauncher"', page)

    def test_every_rail_block_is_a_collapsible_details(self):
        for page in self.pages:
            tags = list(re.finditer(r"<details[^>]*data-rail-fold[^>]*>", page))
            self.assertEqual(4, len(tags), "左侧抽屉应有 4 块静态可折叠面板（透明背景由脚本移入）")
            found = []
            for tag in tags:
                block = tag.group(0)
                identifier = re.search(r'id="([^"]+)"', block)
                self.assertIsNotNone(identifier, f"折叠块缺少 id：{block}")
                found.append(identifier.group(1))
                self.assertNotIn(" open", block, f"折叠块不应默认展开：{block}")
                self.assertRegex(
                    page[tag.end():tag.end() + 40],
                    r"^\s*<summary>",
                    f"{identifier.group(1)} 的 details 里应该是 summary",
                )
            for fold_id in FOLD_IDS:
                self.assertIn(fold_id, found)
            self.assertIn("railTransparentMount", page)

    def test_transparent_panel_moves_into_the_rail(self):
        for marker in (
            '<details id="transparentOutputPanel" class="transparent-output-panel rail-fold" data-rail-fold>',
            'id="transparentOutputState"',
            "透明背景角色 PNG",
            'const railMount = byId("railTransparentMount")',
            "railMount.appendChild(transparentPanel)",
            'byId("studioSettingsView").prepend(transparentPanel)',
        ):
            self.assertIn(marker, self.advanced)
        # 旧的独立标题块已经被折叠摘要取代
        self.assertNotIn('class="transparent-output-heading"', self.advanced)

    def test_task_toolbar_moved_into_the_rail(self):
        for page in self.pages:
            fold_start = page.index('id="taskQueueFold"')
            fold = page[fold_start : page.index("</details>", fold_start)]
            for marker in (
                'id="taskQueueToolbar"',
                'id="taskQueueServerCounts"',
                'id="taskRunBtn"', 'id="taskPauseBtn"', 'id="taskCancelCurrentBtn"',
                'id="taskCancelPendingBtn"', 'id="taskCleanFailedBtn"', 'id="taskCleanFinishedBtn"',
                'id="taskAutoSkip"', 'id="taskSelectOnly"',
                'id="taskQueueNotice"', 'id="taskQueueServerList"',
            ):
                self.assertIn(marker, fold, f"{marker} 应该在任务批处理折叠块里")
            self.assertIn('id="taskQueueSummary"', fold)
            # 生成列里不再有任务工具栏（避免两处各一份）
            generation = page[page.index('id="generationSection"') : page.index('id="studioToolDrawer"')]
            self.assertNotIn('id="taskQueueToolbar"', generation)

    def test_fold_layer_behaviour(self):
        for marker in (
            'const FOLD_STORAGE_KEY = "easyPanelRailFoldV1"',
            'details[data-rail-fold]',
            "function readFoldState()",
            "function writeFoldState(state)",
            "function rememberFold(node, open)",
            "function reveal(target)",
            "function ensureRailVisible(node)",
            "toggleLeftRail(false)",
            "const preserveOpen = wasCollapsed && node.open",
            "if (preserveOpen) event.preventDefault()",
            "if (preserveOpen) node.open = true",
            "function summarizeTaskCounts(text)",
            "function updateTaskQueueState()",
            "function observeTaskCounts()",
            'node.open = false; // 默认折叠',
            "window.easyPanelRevealRail = reveal;",
        ):
            self.assertIn(marker, self.source)
        for wrapped in (
            'wrapGlobal("readDeepSeekClipboard"',
            'wrapGlobal("openDeepSeekWeb"',
            'wrapGlobal("readImageInfo"',
            'wrapGlobal("readOutputImage"',
            'wrapGlobal("openTransparentMaskEditor"',
        ):
            self.assertIn(wrapped, self.source)

    def test_styles_and_payload_copies(self):
        for marker in (
            ".studio-left>.rail-fold{margin:7px 0}",
            ".rail-fold>summary{",
            ".rail-fold[open]>summary{",
            ".rail-fold-state{",
            ".rail-mount{margin:7px 0}",
            ".studio-left .transparent-output-panel{",
        ):
            self.assertIn(marker, self.css)
        self.assertEqual(SCRIPT.read_bytes(), PAYLOAD_SCRIPT.read_bytes())
        self.assertEqual(CSS.read_bytes(), PAYLOAD_CSS.read_bytes())
        self.assertEqual(ADVANCED.read_bytes(), PAYLOAD_ADVANCED.read_bytes())
        self.assertEqual(PAGES[0].read_bytes(), PAGES[1].read_bytes())


if __name__ == "__main__":
    unittest.main()
