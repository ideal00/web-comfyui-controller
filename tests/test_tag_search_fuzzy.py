"""Fuzzy fallback keeps exact tags first while accepting loose keywords."""

import unittest
from unittest import mock

import easy_panel


class TagSearchFuzzyTests(unittest.TestCase):
    def setUp(self):
        self.sample = [
            {"tag": "blue_hair", "search": "blue hair", "translation": "蓝发", "aliases": [], "count": 100, "category": 0},
            {"tag": "long_blue_hair", "search": "long blue hair", "translation": "蓝色长发", "aliases": [], "count": 40, "category": 0},
            {"tag": "blue_eyes", "search": "blue eyes", "translation": "蓝眼睛", "aliases": [], "count": 200, "category": 0},
            {"tag": "high_heels", "search": "high heels", "translation": "高跟鞋", "aliases": [], "count": 80, "category": 0},
        ]
        self.patch = mock.patch.object(easy_panel, "TAG_INDEX", self.sample)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_reordered_keywords_match_and_exact_stays_first(self):
        self.assertEqual("blue_hair", easy_panel.search_tags("hair blue", limit=1)[0]["tag"].replace(" ", "_"))
        results = easy_panel.search_tags("blue hair", limit=4)
        self.assertEqual("blue hair", results[0]["tag"])

    def test_partial_keyword_and_chinese_character_overlap(self):
        self.assertIn("blue eyes", [row["tag"] for row in easy_panel.search_tags("blue unclear", limit=4)])
        self.assertEqual("blue hair", easy_panel.search_tags("蓝色头发", limit=1)[0]["tag"])


if __name__ == "__main__":
    unittest.main()
