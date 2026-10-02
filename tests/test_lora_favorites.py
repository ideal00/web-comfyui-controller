import unittest
from pathlib import Path


class LoraFavoritesTests(unittest.TestCase):
    def test_favorites_are_persistent_filterable_and_categorized(self):
        html = Path("index.html").read_text(encoding="utf-8")
        script = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        css = Path("web/assets/css/panel.css").read_text(encoding="utf-8")

        for marker in (
            'id="loraFavoritesQuick"',
            'id="loraFavoriteCount"',
            'onclick="showFavoriteLoras()"',
            'src="/assets/js/panel.js?v=',
            'id="loraSearch"',
            'onclick="clearLoraSearch()"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "easyPanelLoraFavoritesV1",
            "function migrateStoredLoraNames",
            "function reconcileStoredLoraNamesWithCatalog",
            "if(!renamed)return original",
            "actualByNormalized",
            "function loadLoraRenameAliases",
            "fetch('/api/lora-aliases')",
            "name:renamedLoraName(item.name)",
            "function toggleLoraFavorite",
            "function showFavoriteLoras",
            "function loraFavoriteFolder",
            "__favorite_folder__:",
            "localStorage.setItem(LORA_FAVORITES_STORAGE",
            "favorite.className='lora-favorite'",
            "function loraSearchTerms",
            "function loraMatchesSearch",
            "terms.every(term=>searchable.includes(term))",
            "function clearLoraSearch",
            "function loraFamilyVisible(family){return String(family||'general').toLocaleLowerCase()===promptFamilyClient()}",
            "function visibleFavoriteLoras",
            "return loraFamilyVisible(m.family)",
            "const favorites=visibleFavoriteLoras()",
            "仅当前模型族",
            "当前模型族没有收藏的 LoRA",
            "当前模型族 LoRA 分类",
            "renderLoraFolderOptions();refreshLoraSelects()",
        ):
            self.assertIn(marker, script)
        self.assertIn(".lora-favorite.active", css)
        self.assertIn(".lora-favorites-quick.active", css)
        self.assertIn(".lora-search", css)

    def test_backend_exposes_all_filename_aliases(self):
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location("easy_panel_favorite_alias_test", "easy_panel.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        import json
        import tempfile
        from unittest.mock import patch

        entries = {
            "01_clothing/old.safetensors": "01_clothing/new.safetensors",
            "Anima/old-character.safetensors": "Anima/new-character.safetensors",
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "lora_rename_aliases.json").write_text(json.dumps(entries), encoding="utf-8")
            with patch.object(module, "PROJECT_DIR", root):
                aliases = module.load_lora_rename_aliases()
            for old, new in entries.items():
                self.assertEqual(aliases[old], new)
                self.assertEqual(aliases["Illustrious_Hosiery_Test/" + old], "Illustrious_Hosiery_Test/" + new)
                self.assertEqual(aliases[Path(old).name], Path(new).name)
            with patch.object(module, "PROJECT_DIR", root / "missing"):
                self.assertEqual(module.load_lora_rename_aliases(), {})



if __name__ == "__main__":
    unittest.main()
