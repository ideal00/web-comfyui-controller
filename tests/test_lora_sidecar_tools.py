from __future__ import annotations

import json
import struct
import tempfile
import unittest
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app.lora_sidecars import (
    SIDECAR_MARKER,
    atomic_write_notes,
    infer_base_model,
    load_notes,
    merge_note,
    read_safetensors_metadata,
    read_text_smart,
    render_sidecar,
    sidecar_from_safetensors,
    smart_parse_lora_sidecar,
)
from easy_panel_app.tag_classifier import classify_tag_list
from lora_txt_to_json import note_key


class TagClassifierTests(unittest.TestCase):
    def test_unlabelled_tags_are_split_by_semantics(self):
        result = classify_tag_list([
            "alice_(series)", "blue hair", "red dress", "standing", "full body",
            "classroom", "sunlight", "anime screencap", "sparkles",
        ])
        self.assertEqual(["alice_(series)"], result["subject"])
        self.assertEqual(["blue hair"], result["appearance"])
        self.assertEqual(["red dress"], result["clothing"])
        self.assertEqual(["standing"], result["pose"])
        self.assertEqual(["full body"], result["composition"])
        self.assertEqual(["classroom"], result["scene"])
        self.assertEqual(["sunlight"], result["lighting"])
        self.assertEqual(["anime screencap"], result["style"])
        self.assertEqual(["sparkles"], result["other"])


class SmartSidecarParserTests(unittest.TestCase):
    def test_explicit_metadata_and_multiple_presets(self):
        parsed = smart_parse_lora_sidecar(
            """名称：Alice 测试
适用底模：Illustrious
推荐权重：0.75
触发词：alice_trigger
[基础角色]
角色外貌：blue hair, green eyes
服装：red dress
[校服]
服装：school uniform, white shirt
姿势：standing
场景：classroom
""",
            "characters/Alice.txt",
        )
        self.assertEqual("Alice 测试", parsed["title"])
        self.assertEqual("Illustrious", parsed["base_model"])
        self.assertEqual("0.75", parsed["weight"])
        self.assertEqual("alice_trigger", parsed["trigger"])
        by_name = {item["name"]: item for item in parsed["outfits"]}
        self.assertEqual("blue hair, green eyes", by_name["基础角色"]["appearance"])
        self.assertEqual("red dress", by_name["基础角色"]["clothing"])
        self.assertEqual("school uniform, white shirt", by_name["校服"]["clothing"])
        self.assertEqual("standing", by_name["校服"]["pose"])
        self.assertEqual("classroom", by_name["校服"]["scene"])

    def test_compact_multicharacter_lines_do_not_merge_people(self):
        parsed = smart_parse_lora_sidecar(
            """角色Yoruno Sakura,long hair, red dress
服装
school uniform, white shirt
列车Kuro Syasyou,long hair, blue eyes, standing
""",
            "01_角色/test.txt",
        )
        by_name = {item["name"]: item for item in parsed["outfits"]}
        self.assertIn("Yoruno Sakura", by_name)
        self.assertIn("默认服装", by_name)
        self.assertIn("列车 Kuro Syasyou", by_name)
        self.assertIn("Yoruno Sakura", by_name["Yoruno Sakura"]["subject"])
        self.assertIn("Kuro Syasyou", by_name["列车 Kuro Syasyou"]["subject"])
        self.assertEqual("school uniform, white shirt", by_name["默认服装"]["clothing"])

    def test_single_line_is_content_not_an_empty_header(self):
        parsed = smart_parse_lora_sidecar("x micro bikini", "03_服装/x.txt")
        self.assertEqual(1, len(parsed["outfits"]))
        self.assertEqual("x micro bikini", parsed["outfits"][0]["clothing"])

    def test_one_tag_per_line_keeps_every_semantic_tag(self):
        parsed = smart_parse_lora_sidecar(
            "black hair\nblue eyes\nwhite dress\nstanding\nclassroom",
            "01_角色/line-list.txt",
        )
        self.assertEqual(1, len(parsed["outfits"]))
        outfit = parsed["outfits"][0]
        self.assertEqual("black hair, blue eyes", outfit["appearance"])
        self.assertEqual("white dress", outfit["clothing"])
        self.assertEqual("standing", outfit["pose"])
        self.assertEqual("classroom", outfit["scene"])

    def test_bare_trigger_heading_and_folder_hint(self):
        parsed = smart_parse_lora_sidecar("触发词\nHGK", "02_画风/HGK.txt")
        self.assertEqual("HGK", parsed["trigger"])
        self.assertEqual("HGK", parsed["outfits"][0]["style"])
        self.assertNotEqual("触发词", parsed["outfits"][0]["name"])

    def test_artist_handle_and_title_case_character(self):
        artist = smart_parse_lora_sidecar("@k4nz4r1n", "02_画风/artist.txt")
        character = smart_parse_lora_sidecar("Mamako Oosuki", "01_角色/mamako.txt")
        self.assertEqual("@k4nz4r1n", artist["outfits"][0]["style"])
        self.assertEqual("Mamako Oosuki", character["outfits"][0]["subject"])


class SafetensorsSidecarTests(unittest.TestCase):
    def write_fixture(self, path: Path) -> None:
        metadata = {
            "modelspec.title": "Alice Outfit",
            "modelspec.trigger_phrase": "alice_trigger",
            "ss_base_model_version": "illustriousXL_v1",
            "ss_tag_frequency": json.dumps({
                "set": {"alice_(series)": 20, "blue hair": 18, "red dress": 15,
                        "standing": 12, "classroom": 10},
            }),
        }
        header = json.dumps({"__metadata__": metadata}, ensure_ascii=False).encode("utf-8")
        path.write_bytes(struct.pack("<Q", len(header)) + header)

    def test_only_header_is_needed_to_generate_structured_txt(self):
        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary) / "alice.safetensors"
            self.write_fixture(model)
            metadata = read_safetensors_metadata(model)
            self.assertEqual("Illustrious", infer_base_model(metadata, model))
            document = sidecar_from_safetensors(model)
            self.assertEqual("alice_trigger", document["trigger"])
            rendered = render_sidecar(document, model.name)
            self.assertTrue(rendered.startswith(SIDECAR_MARKER))
            self.assertIn("角色外貌：blue hair", rendered)
            self.assertIn("服装与配饰：red dress", rendered)


class NotesSafetyTests(unittest.TestCase):
    def test_duplicate_lora_basenames_use_relative_json_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lora = root / "styles" / "same.safetensors"
            key = note_key(
                {"same.safetensors": {"title": "legacy"}},
                lora,
                root,
                {"same.safetensors"},
            )
            self.assertEqual("styles/same.safetensors", key)

    def test_merge_preserves_manual_fields_and_understands_legacy_aliases(self):
        old = {
            "trigger": "hand_written",
            "outfits": [{"name": "默认服装", "prompt": "old dress", "manual": "keep me"}],
        }
        parsed = {
            "trigger": "automatic",
            "base_model": "Illustrious",
            "outfits": [{
                "name": "默认服装", "appearance": "blue hair",
                "clothing": "new dress", "other": "replace me",
            }],
        }
        merged, changed = merge_note(old, parsed)
        self.assertTrue(changed)
        self.assertEqual("hand_written", merged["trigger"])
        self.assertEqual("Illustrious", merged["base_model"])
        outfit = merged["outfits"][0]
        self.assertEqual("old dress", outfit["clothing"])
        self.assertEqual("keep me", outfit["other"])
        self.assertEqual("blue hair", outfit["appearance"])

    def test_atomic_json_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "lora_notes.json"
            payload = {"角色.safetensors": {"title": "测试"}}
            atomic_write_notes(target, payload)
            self.assertEqual(payload, load_notes(target))

    def test_gb18030_txt_is_decoded_without_mojibake(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "legacy.txt"
            expected = "角色外貌：黑色长发，蓝色眼睛"
            target.write_bytes(expected.encode("gb18030"))
            self.assertEqual(expected, read_text_smart(target))

    def test_cp932_txt_is_decoded_without_mojibake(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "japanese.txt"
            expected = "キャラクター：黒髪、青い目"
            target.write_bytes(expected.encode("cp932"))
            self.assertEqual(expected, read_text_smart(target))


if __name__ == "__main__":
    unittest.main()
