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
            'onclick="readDeepSeekClipboard()"',
        ):
            self.assertIn(marker, html)
        for removed_id in ('id="aiKey"', 'id="aiEndpoint"', 'id="googleKey"'):
            self.assertNotIn(removed_id, html)
        for marker in (
            "function deepSeekWebInstruction",
            "function openDeepSeekWeb",
            "function readDeepSeekClipboard",
            "https://chat.deepseek.com/",
            "POSITIVE:",
            "NEGATIVE:",
        ):
            self.assertIn(marker, script)

    def test_installer_payload_matches_runtime_files(self):
        self.assertEqual(
            (ROOT / "index.html").read_bytes(),
            (ROOT / "installers" / "payload" / "index.html").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "web" / "assets" / "js" / "panel.js").read_bytes(),
            (ROOT / "installers" / "payload" / "web" / "assets" / "js" / "panel.js").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
