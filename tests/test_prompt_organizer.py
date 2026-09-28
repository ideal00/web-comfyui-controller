from __future__ import annotations

import easy_panel


def test_only_known_confident_tags_leave_manual_section():
    result = easy_panel.classify_known_tags(
        ["1girl", "long hair", "white dress", "sitting", "bedroom", "invented scene thing"]
    )
    assert [item["section"] for item in result] == [
        "subject", "appearance", "clothing", "pose", "scene", "manual"
    ]


def test_danbooru_character_and_artist_categories_override_generic_classifier():
    known = easy_panel.tag_category_map()
    characters = [tag for tag, category in known.items() if category == 4]
    artists = [tag for tag, category in known.items() if category == 1]
    if characters:
        assert easy_panel.classify_known_tags([characters[0]])[0]["section"] == "subject"
    if artists:
        assert easy_panel.classify_known_tags([artists[0]])[0]["section"] == "style"
