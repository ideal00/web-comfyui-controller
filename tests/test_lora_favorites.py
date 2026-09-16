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
        aliases = module.load_lora_rename_aliases()
        import json

        alias_files = Path("lora_imports").glob("*_chinese_filenames.json")
        total = sum(len(json.loads(path.read_text(encoding="utf-8"))) for path in alias_files)
        # Every entry yields three keys: the shared Illustrious path, the path as
        # recorded (Anima folders keep their own top-level folder) and the bare name.
        self.assertEqual(len(aliases), 3 * total)
        self.assertEqual(
            aliases["Illustrious_Hosiery_Test/01_服装/maidify.safetensors"],
            "Illustrious_Hosiery_Test/01_服装/女仆化服装（Maidify）.safetensors",
        )
        self.assertEqual(
            aliases["Illustrious_Hosiery_Test/02_人物模板/Odette.safetensors"],
            "Illustrious_Hosiery_Test/02_人物模板/奥黛塔（原神）.safetensors",
        )
        self.assertEqual(
            aliases["Anima_Soft_Illustration/01_NSFW_人物/honoka.safetensors"],
            "Anima_Soft_Illustration/01_NSFW_人物/穗乃果（Honoka·Anima自训）.safetensors",
        )


if __name__ == "__main__":
    unittest.main()
