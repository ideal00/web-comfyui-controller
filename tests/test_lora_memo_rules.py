import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "lora_imports" / "2026-08-26_civitai_downloads.json"
RENAME_MANIFEST = ROOT / "lora_imports" / "2026-08-26_illustrious_chinese_filenames.json"
NEW_MANIFEST = ROOT / "lora_imports" / "2026-08-27_civitai_downloads.json"
NEW_RENAME_MANIFEST = ROOT / "lora_imports" / "2026-08-27_illustrious_chinese_filenames.json"
BATCH_MANIFESTS = sorted((ROOT / "lora_imports").glob("2026-08-27_batch*_civitai_downloads.json"))
NOTES = ROOT / "lora_notes.json"
RULES = ROOT / "LORA_MEMO_RULES.md"
SIDECAR_SYNC = ROOT / "tools" / "Sync-LoRASidecars.ps1"
ALLOWED_CLASSES = {
    "character", "appearance", "clothing", "pose", "composition", "scene",
    "lighting", "style", "coloring", "negative", "other",
}
CLASS_FIELDS = {
    "character": "subject",
    "appearance": "appearance",
    "clothing": "clothing",
    "pose": "pose",
    "composition": "composition",
    "scene": "scene",
    "lighting": "lighting",
    "style": "style",
    "coloring": "coloring",
    "negative": "negative",
    "other": "other",
}


class LoraMemoRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.imports = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.renames = json.loads(RENAME_MANIFEST.read_text(encoding="utf-8"))
        cls.notes = json.loads(NOTES.read_text(encoding="utf-8"))

    @classmethod
    def installed_filename(cls, filename, item):
        destination = item["destination"]
        prefix = "Illustrious_Hosiery_Test/"
        if destination.startswith(prefix):
            destination = destination[len(prefix):]
        relative = destination + "/" + filename
        return Path(cls.renames.get(relative, relative)).name

    def test_rule_and_manifest_files_exist(self):
        self.assertTrue(RULES.is_file())
        self.assertEqual(len(self.imports), 16)

    def test_manifest_is_safe_and_prompt_values_are_english(self):
        for filename, item in self.imports.items():
            self.assertTrue(filename.endswith(".safetensors"))
            self.assertRegex(item["sha256"], r"^[0-9A-F]{64}$")
            self.assertRegex(
                item["destination"],
                r"^(Illustrious_Hosiery_Test/(01_服装|02_人物模板)|Anima_Soft_Illustration/01_NSFW_人物)$",
            )
            note = item["note"]
            self.assertEqual(note["trigger"], "")
            self.assertTrue(note["url"].startswith("https://civitai.red/models/"))
            for preset in note["presets"]:
                self.assertIn(preset["class"], ALLOWED_CLASSES)
                self.assertNotRegex(preset["value"], r"[\u3400-\u9fff]")

    def test_imported_panel_notes_keep_classes_separate(self):
        for filename, item in self.imports.items():
            note = self.notes[self.installed_filename(filename, item)]
            self.assertEqual(note["trigger"], "")
            self.assertEqual(len(note["outfits"]), len(item["note"]["presets"]))
            for outfit in note["outfits"]:
                main_class = outfit["main_class"]
                self.assertIn(main_class, ALLOWED_CLASSES)
                populated = [field for field in CLASS_FIELDS.values() if outfit.get(field)]
                self.assertEqual(populated, [CLASS_FIELDS[main_class]])
                self.assertNotRegex(outfit[CLASS_FIELDS[main_class]], r"[\u3400-\u9fff]")

    def test_illustrious_installed_names_are_chinese_and_notes_follow_renames(self):
        self.assertEqual(len(self.renames), 59)
        self.assertEqual(len(set(self.renames.values())), len(self.renames))
        for old_relative, new_relative in self.renames.items():
            self.assertRegex(Path(new_relative).name, r"[\u3400-\u9fff]")
            old_name = Path(old_relative).name
            new_name = Path(new_relative).name
            self.assertNotIn(old_name, self.notes)
            self.assertIn(new_name, self.notes)
            self.assertRegex(self.notes[new_name]["title"], r"[\u3400-\u9fff]")

    def test_installer_scripts_ship_the_rules(self):
        for filename in ("Build-Packages.ps1", "Install-EasyPanelModule.ps1"):
            text = (ROOT / "installers" / filename).read_text(encoding="utf-8-sig")
            self.assertIn("LORA_MEMO_RULES.md", text)

    def test_rules_require_nonempty_same_name_utf8_sidecars(self):
        rules = RULES.read_text(encoding="utf-8")
        self.assertIn("必须存在严格同名的 UTF-8 `.txt`", rules)
        self.assertIn("缺失数必须为 0", rules)
        self.assertIn("默认执行移动，不保留下载目录", rules)
        self.assertTrue(SIDECAR_SYNC.is_file())

    def test_august_27_import_is_localized_and_classified(self):
        imports = json.loads(NEW_MANIFEST.read_text(encoding="utf-8"))
        renames = json.loads(NEW_RENAME_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(len(imports), 17)
        self.assertEqual(len(renames), 17)
        for filename, item in imports.items():
            self.assertEqual(item["note"]["trigger"], "")
            self.assertRegex(item["installed_name"], r"[\u3400-\u9fff]")
            relative = item["destination"].removeprefix("Illustrious_Hosiery_Test/") + "/" + filename
            self.assertEqual(Path(renames[relative]).name, item["installed_name"])
            note = self.notes[item["installed_name"]]
            self.assertEqual(note["trigger"], "")
            self.assertEqual(len(note["outfits"]), len(item["note"]["presets"]))
            for outfit in note["outfits"]:
                main_class = outfit["main_class"]
                populated = [field for field in CLASS_FIELDS.values() if outfit.get(field)]
                self.assertEqual(populated, [CLASS_FIELDS[main_class]])
                self.assertNotRegex(outfit[CLASS_FIELDS[main_class]], r"[\u3400-\u9fff]")

    def test_august_27_moved_batches_are_localized_and_classified(self):
        self.assertGreaterEqual(len(BATCH_MANIFESTS), 1)
        for manifest_path in BATCH_MANIFESTS:
            imports = json.loads(manifest_path.read_text(encoding="utf-8"))
            rename_path = Path(str(manifest_path).replace(
                "_civitai_downloads.json", "_illustrious_chinese_filenames.json"
            ))
            renames = json.loads(rename_path.read_text(encoding="utf-8"))
            self.assertEqual(len(imports), len(renames))
            for filename, item in imports.items():
                self.assertEqual(item["note"]["trigger"], "")
                self.assertRegex(item["installed_name"], r"[\u3400-\u9fff]")
                old_relative = item["destination"] + "/" + filename
                new_relative = item["destination"] + "/" + item["installed_name"]
                self.assertEqual(renames[old_relative], new_relative)
                note = self.notes[item["installed_name"]]
                self.assertEqual(note["trigger"], "")
                self.assertEqual(len(note["outfits"]), len(item["note"]["presets"]))
                for outfit in note["outfits"]:
                    main_class = outfit["main_class"]
                    populated = [field for field in CLASS_FIELDS.values() if outfit.get(field)]
                    self.assertEqual(populated, [CLASS_FIELDS[main_class]])
                    self.assertNotRegex(outfit[CLASS_FIELDS[main_class]], r"[\u3400-\u9fff]")

    def test_all_prompt_fields_contain_no_chinese(self):
        for filename, note in self.notes.items():
            self.assertNotRegex(str(note.get("trigger", "")), r"[\u3400-\u9fff]", filename)
            for outfit in note.get("outfits", []):
                for field in CLASS_FIELDS.values():
                    self.assertNotRegex(
                        str(outfit.get(field, "")),
                        r"[\u3400-\u9fff]",
                        f"{filename} / {outfit.get('name', '')} / {field}",
                    )


if __name__ == "__main__":
    unittest.main()
