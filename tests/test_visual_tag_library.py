"""本地视觉词条库（G:\\QK download → SQLite 索引）的契约测试。

全部用临时合成目录，绝不依赖真实词条库；覆盖四套字段命名体系、BOM、
水平线分隔符、组合词条、未匹配参考图、越界路径防护与缩略图缓存。
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from easy_panel_app import visual_tag_library as vtl

# 体系一：鞋子类（Danbooru tag / 中文释义 / 详细释义 / 分类），带 BOM 且用 div 分隔
DOC_CHILD = """# 示例展示

## 1. shoes — 鞋子

<img src="./筛选/0001_shoes.jpg" alt="shoes" style="zoom:60%" />

| 字段 | 内容 |
| --- | --- |
| Danbooru tag | shoes |
| 中文释义 | 鞋子 |
| 详细释义 | 覆盖足部、通常有坚固鞋底的通用鞋类标签。 |
| 分类 | 基础大类 |

<div style="page-break-after:always"></div>

## 2. high_heels — 高跟鞋

<img src="./筛选/0002_high_heels.jpg" alt="high_heels" style="zoom:60%" />

| 字段 | 内容 |
| --- | --- |
| Danbooru tag | high_heels |
| 中文释义 | 高跟鞋 |
| 详细释义 | 让脚后跟明显高于脚趾的鞋类。 |
| 分类 | 鞋跟结构 |
"""

# 体系二：上衣类（tag / tag中文名 / tag中文含义 / tag所属的子类（简单分类即可））
DOC_TAG_PREFIX = """## 1. tank_top — 背心 / 坦克背心

<img src="./images/0001_tank_top.jpg" alt="tank_top" style="zoom:50%" />

| 字段 | 内容 |
| --- | --- |
| 序号 | 0001 |
| tag | tank_top |
| tag中文名 | 背心 / 坦克背心 |
| tag中文含义 | 无袖、肩部为较宽肩带的基础背心。 |
| tag所属的子类（简单分类即可） | 背心 / 短上衣 |
| 角色 | erika_(blue_archive) |
"""

# 体系三：套装类（Danbooru Tag / 中文含义=短名 / 详细解释 / 所属子类）
DOC_COSTUME = """## 1. santa_costume — 圣诞老人装

<img src="./images/0001_santa_costume.jpg" alt="santa_costume" style="zoom:55%" />

| 字段 | 内容 |
| --- | --- |
| Danbooru Tag | santa_costume |
| 中文含义 | 圣诞老人装 |
| 详细解释 | 圣诞老人主题完整服装，常见红白配色。 |
| 所属子类 | 主题套装 |
"""

# 体系四：配饰类（Danbooru Tag / 中文名 / 中文含义=长释义 / 子类 / 模特），用 --- 分隔
DOC_ACCESSORY = """## 1. necklace — 项链

<img src="./images/0001_necklace.jpg" alt="necklace" style="zoom:50%" />

| 字段 | 内容 |
| --- | --- |
| Danbooru Tag | necklace |
| 中文名 | 项链 |
| 中文含义 | 泛指戴在颈部的项链。 |
| 子类 | 项链/吊坠 |
| 模特 | 1girl,hikawa_hina |
| 序号 | 0001 |

---

## 2. chain_necklace — 链条项链

<img src="./images/0002_chain_necklace.jpg" alt="chain_necklace" style="zoom:50%" />

| 字段 | 内容 |
| --- | --- |
| Danbooru Tag | chain_necklace |
| 中文名 | 链条项链 |
| 中文含义 | 以金属链条为主体的项链。 |
| 子类 | 项链/吊坠 |
| 模特 | 1girl,kaname_raana |
| 序号 | 0002 |
"""

# 组合词条 + 未匹配参考图
DOC_COMBO = """## 1. honkai:star_rail,official_art,game_cg — 星穹铁道画风

<img src="./images/0001_honkai_star_rail,official_art,game_cg.jpg" alt="combo" style="zoom:50%" />

| 字段 | 内容 |
| --- | --- |
| 序号 | 0001 |
| tag | honkai:star_rail,official_art,game_cg |
| tag中文名 | 星穹铁道画风 |
| tag中文含义 | 第一个 tag 为星铁名字。 |
| tag所属的子类 | up喜欢 |

<div style="page-break-after:always"></div>

## 2. oxfords — 牛津鞋

<img src="./筛选/0008_oxfords__未匹配.jpg" alt="oxfords" style="zoom:60%" />

| 字段 | 内容 |
| --- | --- |
| Danbooru tag | oxfords |
| 中文释义 | 牛津鞋 |
| 详细释义 | 系带低帮皮鞋。 |
| 分类 | 基础大类 |
"""

# 体系五：衬衫类（Tag / 中文含义=短名 / 中文介绍=长释义，没有子类列）
DOC_SHIRT = """## 1. shirt — 衬衫 / 上衣

<img src="./images/1 (1).jpg" alt="shirt" style="zoom:60%" />

| 字段 | 内容 |
| --- | --- |
| Tag | shirt |
| 中文含义 | 衬衫 / 上衣 |
| 中文介绍 | 泛指穿在上半身的衬衫或类似上衣。 |
"""

UNRELATED_DOC = """# 插件说明

这里没有词条，只有解读文档，不应该进入索引。
"""


def write_tree(root: Path) -> None:
    """构造合成词条库：5 个分类目录（含 5 套字段命名体系）+ 1 个无关目录 + 假图片。"""
    (root / "26-8-26 鞋子展示" / "筛选").mkdir(parents=True)
    (root / "26-8-26 鞋子展示" / "鞋子tag展示.md").write_text(
        "\ufeff" + DOC_CHILD, encoding="utf-8")  # BOM：首条标题匹配不到，只能靠字段表
    for name in ("0001_shoes.jpg", "0002_high_heels.jpg", "0008_oxfords__未匹配.jpg"):
        (root / "26-8-26 鞋子展示" / "筛选" / name).write_bytes(b"fake")

    (root / "26-9-11 上衣" / "images").mkdir(parents=True)
    (root / "26-9-11 上衣" / "上衣.md").write_text(DOC_TAG_PREFIX, encoding="utf-8")
    (root / "26-9-11 上衣" / "images" / "0001_tank_top.jpg").write_bytes(b"fake")

    (root / "26-8-28 套装展示" / "images").mkdir(parents=True)
    (root / "26-8-28 套装展示" / "套装tag展示.md").write_text(DOC_COSTUME, encoding="utf-8")
    (root / "26-8-28 套装展示" / "images" / "0001_santa_costume.jpg").write_bytes(b"fake")

    (root / "26-9-19 颈部配饰" / "images").mkdir(parents=True)
    (root / "26-9-19 颈部配饰" / "颈部配饰.md").write_text(DOC_ACCESSORY, encoding="utf-8")
    for name in ("0001_necklace.jpg", "0002_chain_necklace.jpg"):
        (root / "26-9-19 颈部配饰" / "images" / name).write_bytes(b"fake")

    # 体系五：衬衫类（中文介绍=长释义，且没有子类列）
    (root / "26-8-24 衬衫展示" / "images").mkdir(parents=True)
    (root / "26-8-24 衬衫展示" / "衬衫tag展示.md").write_text(DOC_SHIRT, encoding="utf-8")
    (root / "26-8-24 衬衫展示" / "images" / "1 (1).jpg").write_bytes(b"fake")

    (root / "26-9-14 画风" / "images").mkdir(parents=True)
    (root / "26-9-14 画风" / "画风.md").write_text(DOC_COMBO, encoding="utf-8")
    (root / "26-9-14 画风" / "images" / "0001_honkai_star_rail,official_art,game_cg.jpg").write_bytes(b"fake")

    (root / "插件目录" / "说明.md").parent.mkdir(parents=True)
    (root / "插件目录" / "说明.md").write_text(UNRELATED_DOC, encoding="utf-8")
    # 一张可真正解码的图片，用于缩略图测试
    from PIL import Image

    image = Image.new("RGB", (900, 1200), (60, 90, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    (root / "26-8-26 鞋子展示" / "筛选" / "0001_shoes.jpg").write_bytes(buffer.getvalue())


class LibraryTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "library"
        write_tree(self.root)
        self.patchers = [
            mock.patch.dict(os.environ, {vtl.ROOT_ENV_KEYS[0]: str(self.root)}),
            mock.patch.object(vtl, "INDEX_FILE", Path(self.temp.name) / "idx.sqlite"),
            mock.patch.object(vtl, "THUMB_DIR", Path(self.temp.name) / "thumbs"),
        ]
        for patcher in self.patchers:
            patcher.start()
        vtl._ROWS_CACHE["signature"] = None
        vtl._ROWS_CACHE["rows"] = None
        vtl._SIGNATURE_CACHE.update({"key": None, "ts": 0.0, "value": None})
        vtl._INDEX_STATE.update({"key": None, "ts": 0.0, "value": None})
        # 预热是运行时优化：测试里关掉，否则后台线程会拿着临时目录的图片句柄，
        # 让 TemporaryDirectory 在 Windows 上报 PermissionError。
        vtl._WARM_STATE["started"] = True

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()


class ParseTests(LibraryTestCase):
    def test_index_build_counts(self):
        result = vtl.build_index()
        # 鞋 2 + 上衣 1 + 套装 1 + 配饰 2 + 画风 2 + 衬衫 1 = 9（无关 MD 不计）
        self.assertEqual(9, result["entries"])
        self.assertEqual({"鞋子展示", "上衣", "套装展示", "颈部配饰", "画风", "衬衫展示"},
                         set(result["categories"]))

    def test_all_four_field_schemes_resolve(self):
        rows = {(row["category"], row["tag"]): row for row in vtl._rows()}
        shoes = rows[("鞋子展示", "shoes")]
        self.assertEqual("鞋子", shoes["name_zh"])           # 中文释义 = 短名
        self.assertIn("覆盖足部", shoes["description"])       # 详细释义
        self.assertEqual("基础大类", shoes["group_name"])     # 分类

        top = rows[("上衣", "tank_top")]
        self.assertEqual("背心 / 坦克背心", top["name_zh"])    # tag中文名
        self.assertIn("无袖", top["description"])             # tag中文含义
        self.assertEqual("背心 / 短上衣", top["group_name"])   # 括号说明被剥掉
        self.assertEqual("erika_(blue_archive)", top["sample"])

        costume = rows[("套装展示", "santa_costume")]
        self.assertEqual("圣诞老人装", costume["name_zh"])     # 中文含义当短名
        self.assertIn("红白配色", costume["description"])      # 详细解释
        self.assertEqual("主题套装", costume["group_name"])

        necklace = rows[("颈部配饰", "chain_necklace")]
        self.assertEqual("链条项链", necklace["name_zh"])      # 中文名
        self.assertIn("金属链条", necklace["description"])     # 中文含义当长释义
        self.assertEqual("项链/吊坠", necklace["group_name"])

        shirt = rows[("衬衫展示", "shirt")]
        self.assertEqual("衬衫 / 上衣", shirt["name_zh"])      # 中文含义当短名
        self.assertIn("上半身", shirt["description"])          # 中文介绍 = 长释义（新别名）
        self.assertEqual("", shirt["group_name"])              # 该文档没有子类列
        self.assertTrue(shirt["image_path"].endswith("1 (1).jpg"), shirt["image_path"])

    def test_bom_first_entry_is_kept(self):
        tagged = [row for row in vtl._rows() if row["tag"] == "shoes"]
        self.assertEqual(1, len(tagged), "BOM 导致首条丢失时这里会为空")

    def test_combo_tag_splits_into_members(self):
        combo = next(row for row in vtl._rows() if row["tag"].startswith("honkai"))
        self.assertEqual(["honkai:star_rail", "official_art", "game_cg"],
                         vtl._split_tags(combo["tags"]))

    def test_unmatched_image_status(self):
        oxfords = next(row for row in vtl._rows() if row["tag"] == "oxfords")
        self.assertEqual("unmatched", oxfords["image_status"])

    def test_unrelated_documents_are_skipped(self):
        self.assertNotIn("插件目录", vtl.categories())

    def test_image_path_outside_root_is_rejected(self):
        entry = dict(next(iter(vtl._rows())))
        entry["image_path"] = "../outside.jpg"
        self.assertIsNone(vtl.image_path(entry))
        entry["image_path"] = "鞋子展示/筛选/不存在.jpg"
        self.assertIsNone(vtl.image_path(entry))


class SearchTests(LibraryTestCase):
    def test_tag_and_chinese_search(self):
        self.assertEqual("shoes", vtl.search("shoes", limit=1)["results"][0]["tag"])
        top = vtl.search("高跟鞋", limit=1)["results"][0]
        self.assertEqual("high_heels", top["tag"])
        self.assertGreaterEqual(top["score"], 100)

    def test_category_filter_and_categories(self):
        filtered = vtl.search("", limit=10, category="鞋子展示")
        self.assertEqual(2, filtered["matched"])
        self.assertEqual("鞋子展示", filtered["results"][0]["category"])

    def test_pagination_slices_without_overlap(self):
        shoes = vtl.search("", limit=3, category="鞋子展示", offset=0)
        self.assertEqual(2, shoes["shown"])          # 合成库里鞋子类共 2 条
        self.assertFalse(shoes["has_more"])
        beyond = vtl.search("", limit=3, category="鞋子展示", offset=3)
        self.assertEqual(0, len(beyond["results"]))
        self.assertFalse(beyond["has_more"])

        # 用全部 9 条验证跨页不重复、不丢失
        page1 = vtl.search("", limit=5, offset=0)
        page2 = vtl.search("", limit=5, offset=5)
        self.assertEqual(5, page1["shown"])
        self.assertEqual(4, page2["shown"])
        self.assertTrue(page1["has_more"])
        self.assertFalse(page2["has_more"])
        ids = [item["id"] for item in page1["results"] + page2["results"]]
        self.assertEqual(len(ids), len(set(ids)), "分页结果不应重复")
        self.assertEqual(9, len(ids), "分页应覆盖全部词条")

    def test_pagination_meta_fields(self):
        payload = vtl.search("shoes", limit=2, offset=1)
        self.assertEqual(1, payload["offset"])
        self.assertEqual(2, payload["limit"])
        self.assertIn("shown", payload)
        self.assertIn("has_more", payload)

    def test_lookup_chinese_prefers_exact_name(self):
        self.assertEqual(["high_heels"], vtl.lookup_chinese("高跟鞋"))

    def test_has_cjk(self):
        self.assertTrue(vtl.has_cjk("高跟鞋"))
        self.assertFalse(vtl.has_cjk("high_heels"))

    def test_stats_shape(self):
        stats = vtl.stats()
        self.assertTrue(stats["available"])
        self.assertEqual(9, stats["entries"])
        self.assertEqual(1, stats["unmatched_images"])


class IndexTests(LibraryTestCase):
    def test_sqlite_round_trip_and_freshness(self):
        first = vtl.ensure_index()
        self.assertEqual(9, first["entries"])
        generated = first["generated_at"]
        second = vtl.ensure_index()          # 源文档没变 → 不重建
        self.assertEqual(generated, second["generated_at"])
        with vtl._connection() as connection:
            rows = connection.execute("SELECT COUNT(*) AS total FROM visual_tags").fetchone()
        self.assertEqual(9, rows["total"])

    def test_document_change_triggers_rebuild(self):
        vtl.ensure_index()
        doc = self.root / "26-8-26 鞋子展示" / "鞋子tag展示.md"
        doc.write_text(doc.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        refreshed = vtl.ensure_index()
        self.assertTrue(refreshed["generated_at"])


class ThumbnailTests(LibraryTestCase):
    def test_thumbnail_resizes_and_caches(self):
        vtl.ensure_index()
        entry = next(row for row in vtl._rows() if row["tag"] == "shoes")
        path = vtl.image_path(entry)
        self.assertIsNotNone(path)
        thumb = vtl.thumbnail_bytes(path)
        self.assertTrue(thumb and thumb.startswith(b"\xff\xd8"))
        self.assertLess(len(thumb), path.stat().st_size)
        from PIL import Image

        with Image.open(io.BytesIO(thumb)) as image:
            self.assertLessEqual(max(image.size), vtl.DEFAULT_THUMB_SIZE)
        self.assertEqual(thumb, vtl.thumbnail_bytes(path), "第二次应直接命中缓存")
        self.assertEqual(1, len(list(vtl.THUMB_DIR.glob("*.jpg"))))

    def test_broken_image_returns_none(self):
        broken = self.root / "26-9-11 上衣" / "images" / "0001_tank_top.jpg"
        self.assertIsNone(vtl.thumbnail_bytes(broken))

    def test_memory_cache_serves_without_disk(self):
        vtl.ensure_index()
        entry = next(row for row in vtl._rows() if row["tag"] == "shoes")
        path = vtl.image_path(entry)
        first = vtl.thumbnail_bytes(path)
        self.assertTrue(first)
        self.assertTrue(vtl._THUMB_MEMORY, "缩略图应进入内存缓存")
        for cache_file in vtl.THUMB_DIR.glob("*.jpg"):
            cache_file.unlink()          # 删掉磁盘缓存，内存仍应能直接返回
        self.assertEqual(first, vtl.thumbnail_bytes(path))

    def test_prewarm_generates_once_and_skips_cached(self):
        vtl.ensure_index()
        self.assertGreaterEqual(vtl.prewarm_thumbnails(3), 1)
        self.assertEqual(0, vtl.prewarm_thumbnails(3), "已缓存的缩略图不该重复生成")


class DanbooruClientTests(unittest.TestCase):
    """云端客户端的关键约束（不联网：全部注入 fetcher）。"""

    def setUp(self):
        from easy_panel_app import danbooru_client

        self.client = danbooru_client
        self.client.clear_cache()

    def tearDown(self):
        self.client.clear_cache()

    def test_user_agent_avoids_blocked_keyword(self):
        # 实测：UA 含 comfyui 会被 Danbooru 直接 403，同形但不含该词的 UA 正常。
        self.assertNotIn("comfyui", self.client.USER_AGENT.lower())

    def test_normalize_filters_deleted_and_maps_fields(self):
        card = self.client.normalize_post({
            "id": 11, "rating": "g", "score": 3, "preview_file_url": "https://cdn/p.jpg",
            "large_file_url": "https://cdn/l.jpg", "file_url": "https://cdn/f.jpg",
            "image_width": 900, "image_height": 1200, "tag_string": "1girl high_heels",
            "tag_string_general": "1girl high_heels", "tag_string_artist": "somebody",
            "tag_count": 3,
        })
        self.assertEqual("post:11", card["id"])
        self.assertEqual(["1girl", "high_heels"], card["tags"])
        self.assertEqual(["somebody"], card["groups"]["artist"])
        self.assertEqual("https://cdn/l.jpg", card["sample_url"])
        self.assertIsNone(self.client.normalize_post({"id": 12, "is_deleted": True}))
        self.assertIsNone(self.client.normalize_post({"preview_file_url": "x"}))

    def test_cache_prevents_second_request(self):
        calls = []

        def fetcher(url):
            calls.append(url)
            return [{"id": 1, "preview_file_url": "https://cdn/p.jpg", "tag_string": "x"}]

        self.client.search_posts("high_heels", fetcher=fetcher)
        cached = self.client.search_posts("high_heels", fetcher=fetcher)
        self.assertEqual(1, len(calls))
        self.assertTrue(cached["cached"])

    def test_query_builder_clamps_and_composes(self):
        seen = []

        def fetcher(url):
            seen.append(url)
            return []

        self.client.search_posts("thighhighs", limit=999, page=999, rating="explicit",
                                 sort="oldest", fetcher=fetcher)
        query = urllib.parse.unquote(seen[0])
        self.assertIn("rating:e", query)
        self.assertIn("order:id", query)
        self.assertIn("limit=20", query)
        self.assertIn("page=100", query)

    def test_failures_degrade_without_raising(self):
        def failing(_url):
            raise urllib.error.HTTPError("https://x", 500, "boom", {}, None)

        payload = self.client.search_posts("shoes", fetcher=failing)
        self.assertEqual([], payload["results"])
        self.assertIn("500", payload["error"])

        def throttled(_url):
            raise urllib.error.HTTPError("https://x", 429, "slow", {}, None)

        self.client.clear_cache()
        payload = self.client.search_posts("shoes", fetcher=throttled)
        self.assertIn("限流", payload["error"])
        blocked = self.client.search_posts("shoes", fetcher=failing)
        self.assertIn("秒后可重试", blocked["error"])

    def test_empty_query_returns_hint(self):
        payload = self.client.search_posts("   ", fetcher=lambda url: [])
        self.assertTrue(payload["error"])
        self.assertEqual([], payload["results"])

    def test_post_image_index_and_proxy_cache(self):
        fetcher_calls = []

        def search_fetcher(url):
            return [{"id": 77, "preview_file_url": "https://cdn/p77.jpg",
                     "large_file_url": "https://cdn/s77.jpg", "tag_string": "x"}]

        def image_fetcher(url):
            fetcher_calls.append(url)
            return b"JPEGDATA"

        self.client.search_posts("thighhighs", fetcher=search_fetcher)
        self.assertEqual("https://cdn/p77.jpg", self.client.resolve_post_image("77"))
        self.assertEqual("https://cdn/s77.jpg", self.client.resolve_post_image("77", "sample"))
        self.assertEqual("", self.client.resolve_post_image("999"))
        self.assertEqual("", self.client.resolve_post_image(""))

        self.assertEqual(b"JPEGDATA", self.client.fetch_image("https://cdn/p77.jpg", fetcher=image_fetcher))
        self.assertEqual(b"JPEGDATA", self.client.fetch_image("https://cdn/p77.jpg", fetcher=image_fetcher))
        self.assertEqual(1, len(fetcher_calls), "第二次应该命中内存缓存")

    def test_image_fetch_failures_are_swallowed(self):
        def broken(url):
            raise urllib.error.HTTPError(url, 404, "gone", {}, None)

        self.assertIsNone(self.client.fetch_image("https://cdn/missing.jpg", fetcher=broken))
        self.assertIsNone(self.client.fetch_image(""))
        oversized = lambda url: b"x" * (self.client.IMAGE_MAX_BYTES + 10)  # noqa: E731
        self.assertIsNone(self.client.fetch_image("https://cdn/huge.jpg", fetcher=oversized))

    def test_proxy_resolves_only_known_posts(self):
        # 代理只认“搜到过的帖子”：未知编号拿不到 URL，非法 kind 回退 preview
        self.client.search_posts("shoes", fetcher=lambda url: [
            {"id": 5, "preview_file_url": "https://cdn/p5.jpg",
             "large_file_url": "https://cdn/s5.jpg", "tag_string": "x"}])
        self.assertEqual("https://cdn/p5.jpg", self.client.resolve_post_image("5", "preview"))
        self.assertEqual("https://cdn/p5.jpg", self.client.resolve_post_image("5", "evil"))
        self.assertEqual("https://cdn/s5.jpg", self.client.resolve_post_image("5", "sample"))
        self.assertEqual("", self.client.resolve_post_image("404"))


class PerformanceGuardTests(LibraryTestCase):
    """防回归：源目录扫描必须被缓存，否则并发请求（缩略图网格）会把面板拖死。

    真实事故：48 张缩略图并发 → 每个请求都递归遍历源目录计算签名 → 面板级联超时。
    """

    def test_repeated_searches_do_not_rescan_sources(self):
        vtl.ensure_index()
        calls = []
        original = vtl._document_paths

        def counting(root):
            calls.append(str(root))
            return original(root)

        with mock.patch.object(vtl, "_document_paths", counting):
            for _ in range(6):
                vtl.search("high_heels", limit=5)
                vtl.stats()
        self.assertLessEqual(len(calls), 1, f"每个请求都重扫源目录：{len(calls)} 次")

    def test_document_scan_avoids_recursive_glob(self):
        import inspect

        source = inspect.getsource(vtl._document_paths)
        self.assertNotIn('"**"', source, "文档扫描不能用 ** 递归（源目录含 2000+ 图片与插件目录）")


class ApiWiringTests(unittest.TestCase):
    """面板接线契约：端点、白名单、前端脚本与版本号。"""

    @classmethod
    def setUpClass(cls):
        cls.panel_source = (PROJECT_DIR / "easy_panel.py").read_text(encoding="utf-8")
        cls.index_html = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")
        cls.payload_html = (PROJECT_DIR / "installers" / "payload" / "index.html").read_text(encoding="utf-8")
        cls.library_js = (PROJECT_DIR / "web" / "assets" / "js" / "visual-tag-library.js").read_text(encoding="utf-8")

    def test_get_endpoints_registered(self):
        for endpoint in ('"/api/visual-tags"', '"/api/visual-tags/image"', '"/api/danbooru/posts"',
                         '"/api/danbooru/image"', '"/api/tag-dialect"'):
            self.assertIn(endpoint, self.panel_source, endpoint)
        self.assertIn("def serve_visual_tag_image", self.panel_source)
        self.assertIn("def serve_danbooru_posts", self.panel_source)
        self.assertIn("def serve_danbooru_image", self.panel_source)

    def test_cloud_cards_use_local_proxy_and_fixed_thumb_height(self):
        # 云端图必须走本机代理（CDN 直连在国内很慢），且缩略图高度必须是确定值
        self.assertIn('src="${CLOUD_IMAGE_API}?post=', self.library_js)
        self.assertNotIn('src="${esc(card.preview_url)}"', self.library_js)
        self.assertIn("height:232px;flex:0 0 auto", self.library_js)
        self.assertNotIn("aspect-ratio:3/4;display:flex;align-items:center", self.library_js)

    def test_rebuild_endpoint_is_whitelisted(self):
        self.assertIn('"/api/visual-tags/rebuild"', self.panel_source)
        marker = 'elif self.path == "/api/visual-tags/rebuild":'
        self.assertIn(marker, self.panel_source)

    def test_visual_tags_results_carry_dialect_fields(self):
        self.assertIn('kind = prompt_dialect.classify_tag(item["tag"], dialect_categories())',
                      self.panel_source)
        self.assertIn('item["kind"] = kind', self.panel_source)
        self.assertIn('item["formatted"] = prompt_dialect.format_tag', self.panel_source)

    def test_frontend_scripts_loaded_in_both_panels(self):
        for page in (self.index_html, self.payload_html):
            self.assertIn("/assets/js/prompt-dialect.js?v=1", page)
            self.assertIn("/assets/js/visual-tag-library.js?v=", page)
            self.assertLess(page.index("prompt-dialect.js"), page.index("panel.js?v="))

    def test_visual_tags_endpoint_supports_paging(self):
        self.assertIn('offset=bounded(query.get("offset", ["0"])[0], 0, 0, 20000)', self.panel_source)
        # 前端本地分页：把页码换成 offset，并统一用同一个翻页控件
        self.assertIn('offset: String(Math.max(0, state.page - 1) * LOCAL_LIMIT)', self.library_js)
        self.assertIn('function pageChanged()', self.library_js)
        self.assertIn('if (pager) pager.hidden = false;', self.library_js)

    def test_library_js_uses_dialect_layer(self):
        self.assertIn("EasyPanelDialect", self.library_js)
        self.assertIn("window.EasyPanelVisualTags", self.library_js)
        self.assertIn("/api/visual-tags/image", self.library_js)
        # 排序只提供最新 / 最旧：order:score 实测在热门标签上会 500，
        # 因此源码里只允许出现在那句解释文案中。
        self.assertEqual(1, self.library_js.count("order:score"))
        self.assertIn('SORTS = { newest: "最新", oldest: "最旧" }', self.library_js)


if __name__ == "__main__":
    unittest.main()
