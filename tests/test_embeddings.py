import unittest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EmbeddingPanelTests(unittest.TestCase):
    def test_embedding_picker_is_wired_to_prompt_sections(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web/assets/js/panel.js").read_text(encoding="utf-8")
        server = (ROOT / "easy_panel.py").read_text(encoding="utf-8")

        for marker in (
            'id="embeddingSection"',
            'id="embeddingFolder"',
            'id="embeddingSelect"',
            'onclick="applySelectedEmbedding()"',
            'onclick="removeSelectedEmbedding()"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "function filteredEmbeddings",
            "function embeddingPromptToken",
            "function applySelectedEmbedding",
            "function removeSelectedEmbedding",
            "return item.prompt||'embedding:'",
            "splitClientTerms(embeddingPromptToken(name)).map(normalizedClientTerm)",
            "section==='negative'?appendNegative(token):appendEnglish(token,section)",
        ):
            self.assertIn(marker, script)
        for marker in (
            "def embedding_catalog",
            '"embeddings": embeddings',
            '"embeddingMeta": embedding_meta',
        ):
            self.assertIn(marker, server)

    def test_embedding_manifest_separates_display_labels_from_real_prompts(self):
        notes = json.loads((ROOT / "embedding_notes.json").read_text(encoding="utf-8"))
        self.assertEqual(47, len(notes))
        self.assertEqual("embedding:lazypos", notes["lazypos.safetensors"]["prompt"])
        cheek = notes["FFF_cheek_poking.safetensors"]
        self.assertEqual("FFF_cheek_poking, penis to face", cheek["trigger"])
        self.assertEqual("embedding:FFF_cheek_poking, penis to face", cheek["prompt"])
        self.assertNotIn("中文", cheek["prompt"])
        self.assertEqual(
            "embedding:HTRP_God_Abstral, HTRP God Abstral",
            notes["HTRP_God_Abstral.safetensors"]["prompt"],
        )
        self.assertEqual([], [name for name in notes if any("\u4e00" <= ch <= "\u9fff" for ch in name)])
        for note in notes.values():
            self.assertFalse(any("\u4e00" <= ch <= "\u9fff" for ch in note["prompt"]), note["prompt"])
            self.assertTrue(note["prompt"].startswith("embedding:"), note["prompt"])

    def test_installer_payload_matches_runtime(self):
        pairs = (
            (ROOT / "easy_panel.py", ROOT / "installers/payload/easy_panel.py"),
            (ROOT / "index.html", ROOT / "installers/payload/index.html"),
            (ROOT / "web/assets/js/panel.js", ROOT / "installers/payload/web/assets/js/panel.js"),
            (ROOT / "embedding_notes.json", ROOT / "installers/payload/embedding_notes.json"),
        )
        for runtime, payload in pairs:
            self.assertEqual(runtime.read_bytes(), payload.read_bytes(), runtime.name)


if __name__ == "__main__":
    unittest.main()
