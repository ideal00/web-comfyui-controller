import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeepSeekWebTranslationTests(unittest.TestCase):
    def test_translation_ui_uses_deepseek_web_without_api_credentials(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "assets" / "js" / "panel.js").read_text(encoding="utf-8")

        for marker in (
            "DeepSeek 网页版",
            "不用 API / 不保存密钥",
            'onclick="openDeepSeekWeb()"',
            'id="deepSeekManualCopy"',
            'onclick="copyDeepSeekInstructionManually()"',
            'id="deepSeekManualInstruction"',
            'id="deepSeekManualHelp"',
            'readonly',
            'onclick="readDeepSeekClipboard()"',
        ):
            self.assertIn(marker, html)
        for removed_id in ('id="aiKey"', 'id="aiEndpoint"', 'id="googleKey"'):
            self.assertNotIn(removed_id, html)
        for marker in (
            "function deepSeekWebInstruction",
            "function openDeepSeekWeb",
            "function copyDeepSeekInstructionManually",
            "function showDeepSeekManualInstruction",
            "function hideDeepSeekManualInstruction",
            "function readDeepSeekClipboard",
            "https://chat.deepseek.com/",
            "POSITIVE:",
            "NEGATIVE:",
            "window.EasyPanelClipboard.copyText",
            "document.execCommand('copy')",
        ):
            self.assertIn(marker, script)
        open_function = script[script.index("async function openDeepSeekWeb"):]
        self.assertLess(
            open_function.index("await copyDeepSeekInstruction(instruction)"),
            open_function.index("window.open('https://chat.deepseek.com/'"),
        )
        self.assertIn("DeepSeek 尚未打开", script)
        self.assertIn("完整转换指令", script)
        self.assertNotIn("RPG Token", script[script.index("function deepSeekWebInstruction"):script.index("function readDeepSeekClipboard")])

    def test_android_clipboard_bridge_is_minimal_and_origin_checked(self):
        activity = (ROOT / "android-client" / "android" / "app" / "src" / "main" / "java" /
                    "app" / "rpgbox" / "mobile" / "AdvancedPanelActivity.java").read_text(encoding="utf-8")
        self.assertIn('addJavascriptInterface(new ClipboardBridge(), "EasyPanelClipboard")', activity)
        self.assertIn("public boolean copyText(String text)", activity)
        self.assertIn("isTrustedBridgePage()", activity)
        self.assertIn("MAX_CLIPBOARD_TEXT_LENGTH", activity)
        self.assertNotIn('addJavascriptInterface(new ClipboardBridge(), "*"', activity)

    def test_installer_payload_matches_runtime_files(self):
        self.assertEqual(
            (ROOT / "index.html").read_bytes(),
            (ROOT / "installers" / "payload" / "index.html").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "web" / "assets" / "js" / "panel.js").read_bytes(),
            (ROOT / "installers" / "payload" / "web" / "assets" / "js" / "panel.js").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "web" / "assets" / "css" / "panel.css").read_bytes(),
            (ROOT / "installers" / "payload" / "web" / "assets" / "css" / "panel.css").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
