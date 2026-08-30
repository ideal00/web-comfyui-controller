import json
import unittest
from pathlib import Path


class UserPromptPresetTests(unittest.TestCase):
    def test_personal_prompt_presets_are_saved_categorized_and_applied(self):
        html = Path("index.html").read_text(encoding="utf-8")
        script = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        css = Path("web/assets/css/panel.css").read_text(encoding="utf-8")

        for marker in (
            'id="userPromptPresetPanel"', 'id="userPresetName"',
            'id="userPresetCategory"', 'id="userPresetContent"',
            'id="userPresetList"', '>姿势串<', '>画师 / 画风串<',
            'id="userPresetComboMode"', 'id="userPresetComboPicker"',
            'id="userPresetComboFields"', '>组合保存<',
        ):
            self.assertIn(marker, html)
        for marker in (
            "USER_PROMPT_PRESET_KEY", "easyPanelPromptPresetsV1",
            "function loadUserPromptPresets", "function saveUserPromptPreset",
            "function applyUserPromptPreset", "function editUserPromptPreset",
            "function deleteUserPromptPreset", "localStorage.setItem",
            "artist:{label:'画师 / 画风串',target:'promptStyle'}",
            "pose:{label:'姿势串',target:'promptPose'}",
            "function setUserPromptPresetMode", "function toggleUserPromptComboCategory",
            "function captureUserPromptComboCategory", "function userPromptComboSections",
            "item.category==='combo'", "Object.entries(item.sections||{})",
            "function userPromptComboBackgroundTerm",
            "function userPromptComboBackgroundIssues",
            "function reviewUserPromptComboBackgrounds",
            "function moveUserPromptComboBackgroundsToScene",
            "一键移到场景分区", "检测到错放背景词",
            "setUserPromptPresetMode('combo',true)",
            "USER_PROMPT_PNG_RECOVERY_MARKER",
            "USER_PROMPT_BEFORE_PNG_RECOVERY_BACKUP",
            "USER_PROMPT_PNG_RECOVERY_URL",
            "function applyPngMetadataComboRecoveryOnce",
            "recovered_combo_presets_20260828.json",
            "recoveryByName.get(item.name)",
            "已依据原始 PNG 内嵌参数恢复",
        ):
            self.assertIn(marker, script)
        self.assertNotIn("needsInlineBackgroundCleanup", script)
        self.assertNotIn("cleanUserPromptComboValue", script)
        self.assertNotIn("prepareEarliestUserPromptPresetRestore", script)
        self.assertNotIn("initUserPromptPresetRecovery", script)
        self.assertIn(".user-preset-panel", css)
        self.assertIn(".user-preset-item", css)
        self.assertIn(".user-preset-combo-picker", css)
        self.assertIn(".user-preset-combo-fields", css)

    def test_png_metadata_recovery_table_is_complete_and_distinct(self):
        path = Path("web/assets/data/recovered_combo_presets_20260828.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data["items"]
        self.assertEqual(len(items), 13)
        by_name = {item["name"]: item for item in items}
        self.assertEqual(len(by_name), 13)
        for item in items:
            self.assertTrue(item["evidence"])
            self.assertTrue(item["sections"]["pose"])
            self.assertTrue(item["sections"]["clothing"])
        self.assertNotEqual(by_name["花田连衣裙"]["sections"], by_name["毛衣喝咖啡"]["sections"])
        self.assertNotEqual(by_name["露胸告白"]["sections"], by_name["露胸比心"]["sections"])
        self.assertNotEqual(by_name["裸体揉乳"]["sections"], by_name["湿润巫女服捆绑"]["sections"])


if __name__ == "__main__":
    unittest.main()
