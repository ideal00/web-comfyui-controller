import unittest
from pathlib import Path


class PromptSectionClearTests(unittest.TestCase):
    def test_each_main_prompt_section_has_its_own_clear_button(self):
        html = Path("index.html").read_text(encoding="utf-8")
        script = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        css = Path("web/assets/css/panel.css").read_text(encoding="utf-8")

        expected = (
            ("promptSubject", "人物与角色"),
            ("promptAppearance", "外貌"),
            ("promptExpression", "表情"),
            ("promptClothing", "服装与材质"),
            ("promptPose", "姿势"),
            ("promptComposition", "构图与镜头"),
            ("promptScene", "场景"),
            ("promptLighting", "光线"),
            ("promptStyle", "画风与上色"),
            ("promptNaturalLanguage", "自然语言"),
            ("prompt", "其他补充"),
            ("negative", "额外负面词"),
        )
        for field_id, label in expected:
            self.assertIn(
                f"clearPromptSection('{field_id}','{label}')",
                html,
            )
            self.assertIn(
                f"pastePromptSection('{field_id}','{label}')",
                html,
            )
        self.assertEqual(html.count('class="prompt-section-clear"'), len(expected))
        self.assertEqual(html.count('class="prompt-section-paste"'), len(expected))
        self.assertIn("function clearPromptSection", script)
        self.assertIn("async function pastePromptSection", script)
        self.assertIn("navigator.clipboard?.readText", script)
        self.assertIn("tokenHistory.filter(item=>item.field!==id)", script)
        self.assertIn(".prompt-section-label", css)
        self.assertIn(".prompt-section-clear", css)
        self.assertIn(".prompt-section-paste", css)


if __name__ == "__main__":
    unittest.main()
