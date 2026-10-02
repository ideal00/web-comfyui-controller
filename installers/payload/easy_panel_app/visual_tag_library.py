"""本地精选视觉词条库：把 ComfyUI 目录中的 ``visual_tag_library`` 读成可搜索索引。

数据形态（每个分类一个文件夹，源数据**只读**）::

    26-8-26 鞋子展示/
        鞋子tag展示.md          # 人读文档，每条 = 标题 + <img> + 字段表
        筛选/0001_shoes.jpg     # 精选参考图（文件名以序号开头）
        ...

文档内部结构::

    ## 1. shoes — 鞋子
    <img src="./筛选/0001_shoes.jpg" ... />
    | 字段 | 内容 |
    | Danbooru tag | shoes |
    | 中文释义 | 鞋子 |
    | 详细释义 | 覆盖足部…… |

解析必须容忍的三种真实情况：

* 文件带 UTF-8 BOM，首条标题的 ``^##`` 匹配不到 → 以字段表为准，标题只当兜底。
* 字段名有 4 套命名体系（见 ``NAME_FIELDS`` / ``MEANING_FIELDS``），且 ``中文含义``
  在不同文档里既可能是短名（套装类）也可能是长释义（面部配饰类）→ 按同文档里出现的别名判定。
* ``tag`` 可能是逗号连接的标签组合（画风类，如 ``honkai:star_rail,official_art,game_cg``）。

索引落在 ``visual_tag_index.sqlite``（派生数据，可随时重建），缩略图落在
``cache/visual_tag_thumbs``。源目录位置用 ``EASY_PANEL_VISUAL_TAG_ROOT`` 覆盖。
面板新增的图片与标签独立保存在 ``visual_tag_uploads``，合并进派生索引；
作品库引用保留来源编号并复制图片，因此重建索引或删除源输出不会丢失参考图。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]

#: 源数据默认位置；``EASY_PANEL_VISUAL_TAG_ROOT`` 优先，旧的别名变量也认。
DEFAULT_LIBRARY_ROOT = PROJECT_DIR.parent / "visual_tag_library"
ROOT_ENV_KEYS = ("EASY_PANEL_VISUAL_TAG_ROOT", "EASY_PANEL_VISUAL_LIBRARY")

INDEX_FILE = PROJECT_DIR / "visual_tag_index.sqlite"
THUMB_DIR = PROJECT_DIR / "cache" / "visual_tag_thumbs"
USER_LIBRARY_DIR = PROJECT_DIR / "visual_tag_uploads"
MAX_UPLOAD_BYTES = 20_000_000

SCHEMA_VERSION = 3
SOURCE_NAME = "qk"
DEFAULT_THUMB_SIZE = 320
MIN_THUMB_SIZE = 64
MAX_THUMB_SIZE = 512
MAX_SEARCH_LIMIT = 200

NAME_FIELDS = ("tag中文名", "中文名", "中文释义", "中文tag", "职业/身份原型", "二次元属性的中文名")
MEANING_FIELDS = ("详细解释", "详细释义", "tag中文含义", "中文介绍", "组合思路", "中文属性解释", "含义")
AMBIGUOUS_FIELD = "中文含义"
TAG_FIELDS = ("danboorutag", "tag", "tag串", "novelai/danboorutag串", "danboorutag/novelaitag串")
SUBCLASS_FIELDS = ("分类", "tag所属的子类", "tag所属子类", "所属子类", "子类", "世界细分")
SAMPLE_FIELDS = ("角色", "模特")
INDEX_FIELDS = ("序号",)

_IMG_RE = re.compile(r'<img[^>]*src="([^"]+)"')
_HEAD_RE = re.compile(r"^#{1,3}\s*\d+\.\s*(?P<body>.+?)\s*$", re.M)
_TABLE_ROW_RE = re.compile(r"^\|\s*(?P<key>[^|]+?)\s*\|\s*(?P<value>[^|]*?)\s*\|\s*$", re.M)
#: 词条分隔符有两种：多数文档用 page-break div，颈部配饰用 Markdown 水平线 ``---``。
_SPLIT_BLOCK_RE = re.compile(r'<div style="page-break-after:always"></div>|^[ \t]*---+[ \t]*$', re.M)
_DATE_PREFIX_RE = re.compile(r"^\d{2,4}-\d{1,2}-\d{1,2}\s*")
_NAME_SUFFIX_RE = re.compile(r"\s*[—–]\s*|\s+-\s+")
_PAREN_SUFFIX_RE = re.compile(r"[（(][^）)]*[）)]\s*$")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS visual_tags (
    id TEXT PRIMARY KEY,
    tag TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    name_zh TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    category_dir TEXT NOT NULL DEFAULT '',
    group_name TEXT NOT NULL DEFAULT '',
    sample TEXT NOT NULL DEFAULT '',
    seq TEXT NOT NULL DEFAULT '',
    image_path TEXT NOT NULL DEFAULT '',
    image_status TEXT NOT NULL DEFAULT 'ready',
    source TEXT NOT NULL DEFAULT 'qk',
    generation_id TEXT NOT NULL DEFAULT '',
    artifact_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_visual_tags_tag ON visual_tags(tag COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_visual_tags_category ON visual_tags(category);
CREATE TABLE IF NOT EXISTS visual_tag_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""

_LOCK = threading.RLock()
_ROWS_CACHE: dict = {"signature": None, "rows": None}


# --------------------------------------------------------------------------- #
# 源目录
# --------------------------------------------------------------------------- #
def library_root() -> Path:
    """源数据根目录（环境变量优先）。"""
    for key in ROOT_ENV_KEYS:
        override = os.environ.get(key, "").strip()
        if override:
            return Path(override)
    return DEFAULT_LIBRARY_ROOT


def library_available() -> bool:
    return library_root().is_dir()


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def _field_key(raw: str) -> str:
    text = _PAREN_SUFFIX_RE.sub("", str(raw or "").strip())
    text = re.sub(r"[\s_]+", "", text)
    return text.replace("：", "").replace(":", "").lower()


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _split_tags(tag: str) -> list[str]:
    return [item.strip() for item in str(tag or "").split(",") if item.strip()]


def _category_label(folder: str) -> str:
    return _DATE_PREFIX_RE.sub("", str(folder or "").strip()) or str(folder or "")


def _entry_id(category_dir: str, seq: str, tag: str) -> str:
    digest = hashlib.sha1(f"{category_dir}|{seq}|{tag}".encode("utf-8")).hexdigest()[:12]
    return f"vt{digest}"


def _resolve_fields(rows: dict[str, str]) -> dict[str, str]:
    """把文档里出现的别名解析成 name / description / group / sample。

    ``中文含义`` 是歧义键：与 ``详细解释`` 同时出现时它是短名（套装类文档），
    与 ``中文名`` 同时出现时它是长释义（面部配饰类文档）。
    """
    name = next((rows[key] for key in NAME_FIELDS if rows.get(key)), "")
    description = next((rows[key] for key in MEANING_FIELDS if rows.get(key)), "")
    ambiguous = rows.get(AMBIGUOUS_FIELD, "")
    if not name and not description:
        name, description = ambiguous, ""
    elif not name:
        name = ambiguous
    elif not description:
        description = ambiguous
    group = next((rows[key] for key in SUBCLASS_FIELDS if rows.get(key)), "")
    sample = next((rows[key] for key in SAMPLE_FIELDS if rows.get(key)), "")
    return {"name_zh": name, "description": description, "group_name": group, "sample": sample}


def _heading_parts(heading: str) -> tuple[str, str]:
    body = _clean(heading)
    if not body:
        return "", ""
    parts = _NAME_SUFFIX_RE.split(body, maxsplit=1)
    tag = parts[0].strip().strip("`")
    name = parts[1].strip() if len(parts) > 1 else ""
    return tag, name


def _relative_image(category_dir: str, image_ref: str) -> str:
    """把 ``./筛选/0001_shoes.jpg`` 归一成相对源数据根目录的 POSIX 路径。"""
    ref = str(image_ref or "").strip().replace("\\", "/")
    while ref.startswith("./"):
        ref = ref[2:]
    ref = ref.lstrip("/")
    if ref.startswith("../"):
        ref = ref[3:]
    if category_dir and not ref.startswith(f"{category_dir}/"):
        return f"{category_dir}/{ref}"
    return ref


def parse_document(path: Path, category_dir: str) -> list[dict]:
    """把一个展示文档解析成词条列表（按文档顺序）。"""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    entries: list[dict] = []
    for block in _SPLIT_BLOCK_RE.split(text):
        match = _IMG_RE.search(block)
        if not match:
            continue
        image_ref = match.group(1).strip()
        rows: dict[str, str] = {}
        for row in _TABLE_ROW_RE.finditer(block):
            key = _field_key(row.group("key"))
            value = _clean(row.group("value"))
            if not value or key in {"字段", "---"}:
                continue
            rows.setdefault(key, value)
        head_match = _HEAD_RE.search(block)
        heading = head_match.group("body") if head_match else ""
        head_tag, head_name = _heading_parts(heading)
        tag = next((rows[key] for key in TAG_FIELDS if rows.get(key)), "") or head_tag
        tag = _clean(tag).strip("`")
        if not tag:
            continue
        fields = _resolve_fields(rows)
        seq = next((rows[key] for key in INDEX_FIELDS if rows.get(key)), "")
        image_rel = _relative_image(category_dir, image_ref)
        matched = "未匹配" not in Path(image_ref).name
        entries.append({
            "id": _entry_id(category_dir, seq or image_ref, tag),
            "tag": tag,
            "tags": ", ".join(_split_tags(tag)),
            "name_zh": fields["name_zh"] or head_name or tag,
            "description": fields["description"],
            "category": _category_label(category_dir),
            "category_dir": category_dir,
            "group_name": fields["group_name"],
            "sample": fields["sample"],
            "seq": seq,
            "image_path": image_rel,
            "image_status": "ready" if matched else "unmatched",
            "source": SOURCE_NAME,
        })
    return entries


def _document_paths(root: Path) -> list[tuple[str, Path]]:
    """列出真正的展示文档（含 ``<img>`` 的 MD）。

    ⚠️ 只用**浅层匹配**（``分类/文档.md`` 与 ``分类/子目录/文档.md``），不要用 ``**``：
    源目录下还有 2000+ 张图片与插件目录，递归遍历会把每个请求拖慢（实测 48 张缩略图
    并发请求 → 每个都扫一遍全树 → 面板级联卡死）。
    """
    found: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for pattern in ("*/*.md", "*/*/*.md"):
        for path in sorted(root.glob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            parts = path.relative_to(root).parts
            if any(part.startswith(".") for part in parts):
                continue
            try:
                if "<img" not in path.read_text(encoding="utf-8-sig", errors="replace"):
                    continue
            except OSError:
                continue
            found.append((parts[0], path))
    return found


#: 签名缓存：源目录扫描（列文档 + 读内容判断是否为展示文档）不便宜，
#: 短时间内重复请求直接复用，避免每个 HTTP 请求都扫一遍源目录。
_SIGNATURE_CACHE: dict = {"key": None, "ts": 0.0, "value": None}
SIGNATURE_TTL_SECONDS = 20.0
#: ensure_index 结果的短期记忆（与签名同 TTL），避免每个 HTTP 请求都开一次 SQLite。
_INDEX_STATE: dict = {"key": None, "ts": 0.0, "value": None}


def _signature(root: Path, force: bool = False) -> list[list]:
    key = (str(root), str(USER_LIBRARY_DIR))
    now = time.monotonic()
    cached = _SIGNATURE_CACHE
    if (not force and cached["key"] == key and cached["value"] is not None
            and now - cached["ts"] < SIGNATURE_TTL_SECONDS):
        return cached["value"]
    items: list[list] = []
    custom = USER_LIBRARY_DIR / "entries"
    if custom.is_dir():
        items.append(["user", str(custom), custom.stat().st_mtime_ns])
    for category_dir, path in _document_paths(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append([category_dir, path.name, int(stat.st_mtime_ns), stat.st_size])
    _SIGNATURE_CACHE.update({"key": key, "ts": now, "value": items})
    return items


# --------------------------------------------------------------------------- #
# SQLite 索引
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def _connection(db_path: Path | None = None):
    """打开索引连接并保证关闭（Windows 上不关闭会让临时目录/备份删除失败）。"""
    target = db_path or INDEX_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(target), timeout=15.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(_SCHEMA_SQL)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(visual_tags)")}
        for name in ("generation_id", "artifact_id"):
            if name not in columns:
                connection.execute(f"ALTER TABLE visual_tags ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        yield connection
        connection.commit()
    finally:
        connection.close()


def _read_meta(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = connection.execute("SELECT key, value FROM visual_tag_meta").fetchall()
    except sqlite3.Error:
        return {}
    return {row["key"]: row["value"] for row in rows}


def _custom_entries() -> list[dict]:
    entries = []
    for path in sorted((USER_LIBRARY_DIR / "entries").glob("vu*.json"), reverse=True):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(entry, dict) and entry.get("source") == "user" and entry.get("id") == path.stem:
            entries.append(entry)
    return entries


def add_entry(content: bytes, metadata: dict, *, generation_id: str = "", artifact_id: str = "") -> dict:
    """Save an independent image copy and durable tag metadata; never change source documents."""
    from PIL import Image

    if not isinstance(metadata, dict):
        raise ValueError("图库词条必须是对象。")
    raw_tags = metadata.get("tags", "")
    if isinstance(raw_tags, list):
        raw_tags = ",".join(str(tag) for tag in raw_tags)
    if not isinstance(raw_tags, str) or len(raw_tags) > 4000:
        raise ValueError("Tag 最长 4000 字符。")
    tags = []
    for value in re.split(r"[,，\n]+", raw_tags):
        tag = " ".join(value.strip().split())
        if not tag:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_@][A-Za-z0-9_ .()':@+/-]*", tag):
            raise ValueError("Tag 只填写英文标签；中文名称与说明请填写在各自栏位。")
        tag = tag.replace(" ", "_")
        if tag not in tags:
            tags.append(tag)
    if not tags or len(tags) > 100:
        raise ValueError("请填写 1–100 个英文 Tag，用逗号或换行分隔。")
    fields = {}
    for key, maximum in (("name_zh", 100), ("category", 60), ("description", 2000)):
        value = metadata.get(key, "")
        if not isinstance(value, str) or len(value.strip()) > maximum:
            raise ValueError("名称、分类或说明过长。")
        fields[key] = value.strip()
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("图片不能为空，且不能超过 20 MB。")
    try:
        with Image.open(io.BytesIO(content)) as image:
            extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(image.format)
            if not extension or image.width * image.height > 40_000_000:
                raise ValueError("仅支持不超过 4000 万像素的 PNG、JPEG、WebP 图片。")
            image.verify()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("无法读取该图片，请选择有效的 PNG、JPEG 或 WebP。") from exc
    entry_id = "vu" + uuid.uuid4().hex
    entry = dict(id=entry_id, tag=", ".join(tags), tags=", ".join(tags),
                 name_zh=fields["name_zh"] or tags[0], category=fields["category"] or "我的图库",
                 description=fields["description"], category_dir="", group_name="", sample="",
                 seq=str(time.time_ns()), image_path="images/"+entry_id+extension,
                 image_status="ready", source="user", generation_id=generation_id, artifact_id=artifact_id)
    with _LOCK:
        images = USER_LIBRARY_DIR / "images"
        documents = USER_LIBRARY_DIR / "entries"
        images.mkdir(parents=True, exist_ok=True)
        documents.mkdir(parents=True, exist_ok=True)
        image_path = USER_LIBRARY_DIR / entry["image_path"]
        document = documents / (entry_id+".json")
        image_path.write_bytes(content)
        pending = document.with_suffix(".tmp")
        try:
            pending.write_text(json.dumps(entry, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            os.replace(pending, document)
        except Exception:
            image_path.unlink(missing_ok=True)
            pending.unlink(missing_ok=True)
            raise
        _INDEX_STATE.update({"key": None, "ts": 0.0, "value": None})
        _SIGNATURE_CACHE.update({"key": None, "ts": 0.0, "value": None})
        _ROWS_CACHE.update({"signature": None, "rows": None})
        ensure_index(force=True)
    return _public(entry)


def build_index(root: Path | None = None, db_path: Path | None = None) -> dict:
    """重新解析全部展示文档并写入 SQLite；返回统计信息。"""
    base = Path(root) if root else library_root()
    signature = _signature(base, force=True)
    entries: list[dict] = []
    for category_dir, path in _document_paths(base):
        entries.extend(parse_document(path, category_dir))
    with _LOCK:
        entries.extend(_custom_entries())
        for entry in entries:
            entry.setdefault("generation_id", "")
            entry.setdefault("artifact_id", "")
        signature = _signature(base, force=True)
        with _connection(db_path) as connection:
            connection.execute("DELETE FROM visual_tags")
            connection.executemany(
                "INSERT OR REPLACE INTO visual_tags (id, tag, tags, name_zh, description, category,"
                " category_dir, group_name, sample, seq, image_path, image_status, source, generation_id, artifact_id)"
                " VALUES (:id, :tag, :tags, :name_zh, :description, :category, :category_dir,"
                " :group_name, :sample, :seq, :image_path, :image_status, :source, :generation_id, :artifact_id)",
                entries,
            )
            meta = {
                "schema": str(SCHEMA_VERSION),
                "root": str(base),
                "signature": json.dumps(signature, ensure_ascii=False),
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "entries": str(len(entries)),
            }
            connection.executemany(
                "INSERT OR REPLACE INTO visual_tag_meta (key, value) VALUES (?, ?)",
                list(meta.items()),
            )
    _ROWS_CACHE["signature"] = None
    _ROWS_CACHE["rows"] = None
    return {"root": str(base), "entries": len(entries),
            "categories": sorted({item["category"] for item in entries})}

def ensure_index(force: bool = False) -> dict:
    """索引不存在/源文档变化时重建；返回元信息（结果带 TTL 记忆，避免逐请求开库）。"""
    root = library_root()
    if not root.is_dir() and not (USER_LIBRARY_DIR / "entries").is_dir():
        return {"available": False, "root": str(root), "entries": 0, "categories": [],
                "generated_at": "", "signature": []}
    now = time.monotonic()
    memo = _INDEX_STATE
    index_key = (str(root), str(USER_LIBRARY_DIR), str(INDEX_FILE))
    if (not force and memo["key"] == index_key and memo["value"] is not None
            and now - memo["ts"] < SIGNATURE_TTL_SECONDS):
        return memo["value"]
    try:
        signature = _signature(root)
    except OSError:
        signature = []
    meta = _read_meta_safe()
    fresh = (meta.get("schema") == str(SCHEMA_VERSION)
             and meta.get("root") == str(root)
             and meta.get("signature") == json.dumps(signature, ensure_ascii=False)
             and INDEX_FILE.is_file())
    if force or not fresh:
        build_index(root)
        meta = _read_meta_safe()
    state = {
        "available": True,
        "root": meta.get("root", str(root)),
        "entries": int(meta.get("entries") or 0),
        "generated_at": meta.get("generated_at", ""),
        "signature": signature,
    }
    _INDEX_STATE.update({"key": index_key, "ts": now, "value": state})
    warm_thumbnails_async()
    return state


def _read_meta_safe() -> dict[str, str]:
    if not INDEX_FILE.is_file():
        return {}
    try:
        with _connection() as connection:
            return _read_meta(connection)
    except sqlite3.Error:
        return {}


def _rows() -> list[dict]:
    """读取全部词条（内存缓存，按签名失效）。"""
    root = library_root()
    try:
        signature = json.dumps(_signature(root), ensure_ascii=False)
    except OSError:
        signature = ""
    cache_key = (str(root), str(INDEX_FILE), signature)
    if _ROWS_CACHE["signature"] == cache_key and _ROWS_CACHE["rows"] is not None:
        return _ROWS_CACHE["rows"]
    ensure_index()
    rows: list[dict] = []
    if INDEX_FILE.is_file():
        try:
            with _connection() as connection:
                for row in connection.execute("SELECT * FROM visual_tags"):
                    rows.append(dict(row))
        except sqlite3.Error:
            rows = []
    _ROWS_CACHE["signature"] = cache_key
    _ROWS_CACHE["rows"] = rows
    return rows


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def _normalize(text: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(text or "")).lower().replace("_", " ").split())


def _score(entry: dict, needle: str) -> int:
    best = 0
    for tag in _split_tags(entry.get("tags") or entry.get("tag") or ""):
        lowered = _normalize(tag)
        if not lowered:
            continue
        if lowered == needle:
            best = max(best, 120)
        elif lowered.startswith(needle):
            best = max(best, 90)
        elif needle in lowered:
            best = max(best, 70)
    name = _normalize(entry.get("name_zh"))
    if name:
        if name == needle:
            best = max(best, 110)
        elif needle in name:
            best = max(best, 80)
    description = _normalize(entry.get("description"))
    if description and needle in description:
        best = max(best, 40)
    group = _normalize(entry.get("group_name"))
    if group and needle in group:
        best = max(best, 30)
    if _normalize(entry.get("category")) == needle:
        best = max(best, 25)
    if best:
        return best
    tag_text = _normalize(entry.get("tags") or entry.get("tag"))
    fields = " ".join((tag_text, name,
                       description, group, _normalize(entry.get("category"))))
    parts = [part for part in re.split(r"[\s,，、/]+", needle) if part]
    if len(parts) > 1:
        if all(part in tag_text for part in parts):
            return 38
        if all(part in name for part in parts):
            return 34
        hits = sum(part in fields for part in parts)
        if hits == len(parts):
            return 22
        if hits:
            return 10 + hits
    return best


def _public(entry: dict, score: int = 0) -> dict:
    return {
        "source": "local",
        "id": entry.get("id", ""),
        "tag": entry.get("tag", ""),
        "tags": _split_tags(entry.get("tags") or entry.get("tag") or ""),
        "name_zh": entry.get("name_zh", ""),
        "description": entry.get("description", ""),
        "category": entry.get("category", ""),
        "group": entry.get("group_name", ""),
        "sample": entry.get("sample", ""),
        "image": entry.get("image_path", ""),
        "image_status": entry.get("image_status", "ready"),
        "custom": entry.get("source") == "user",
        "generation_id": entry.get("generation_id", ""),
        "artifact_id": entry.get("artifact_id", ""),
        "score": score,
    }


def categories() -> list[str]:
    return sorted({str(row.get("category") or "") for row in _rows() if row.get("category")})


def search(query: str, limit: int = 48, category: str = "", offset: int = 0, section: str = "") -> dict:
    """按 tag / 中文名 / 释义 搜索词条；空查询返回全部（分页由 limit/offset 控制）。"""
    info = ensure_index()
    rows = _rows()
    catalog = section_presets()
    routed = {}
    for component in catalog['results']:
        routed.setdefault(component['visualId'], []).append(component)
    if section:
        rows = [row for row in rows if any(c['section'] == section for c in routed.get(row['id'], []))]
    needle = _normalize(query)
    wanted = _normalize(category)
    if wanted:
        rows = [row for row in rows if _normalize(row.get("category")) == wanted]
    if not needle:
        matched = [_public(row, 1) for row in rows]
    else:
        scored = []
        for row in rows:
            score = _score(row, needle)
            if score:
                scored.append(_public(row, score))
        scored.sort(key=lambda item: (-item["score"], item["category"], item["tag"]))
        matched = scored
    max_items = max(1, min(int(limit or 48), MAX_SEARCH_LIMIT))
    start = max(0, int(offset or 0))
    page_rows = matched[start:start + max_items]
    for row in page_rows:
        row['compiler_sections'] = [dict(section=c['section'], label=catalog['labels'][c['section']], tags=c['tags']) for c in routed.get(row['id'], [])]
    return {
        "available": bool(info.get("available")),
        "root": info.get("root", ""),
        "total": len(_rows()),
        "matched": len(matched),
        "offset": start,
        "limit": max_items,
        "shown": len(page_rows),
        "has_more": start + len(page_rows) < len(matched),
        "categories": categories(),
        "generated_at": info.get("generated_at", ""),
        "query": query,
        "section": section,
        "section_labels": catalog["labels"],
        "results": page_rows,
    }


def stats() -> dict:
    info = ensure_index()
    rows = _rows()
    return {
        "available": bool(info.get("available")),
        "root": info.get("root", ""),
        "entries": len(rows),
        "categories": categories(),
        "unmatched_images": sum(1 for row in rows if row.get("image_status") != "ready"),
        "generated_at": info.get("generated_at", ""),
    }


def find_entry(entry_id: str) -> dict | None:
    wanted = str(entry_id or "").strip()
    if not wanted:
        return None
    for row in _rows():
        if row.get("id") == wanted:
            return row
    return None


def lookup_chinese(text: str, limit: int = 1) -> list[str]:
    """中文查询 → 英文 tag（先用词条短名精确匹配，再退回模糊匹配）。"""
    needle = _normalize(text)
    if not needle:
        return []
    exact = [_public(row, 100)["tag"] for row in _rows()
             if _normalize(row.get("name_zh")) == needle]
    if exact:
        return exact[:limit]
    return [item["tag"] for item in search(text, limit=limit)["results"]]


# --------------------------------------------------------------------------- #
# 图片
# --------------------------------------------------------------------------- #
def image_path(entry: dict | str) -> Path | None:
    """词条参考图绝对路径（越界或不存在时返回 None）。"""
    relative = entry.get("image_path", "") if isinstance(entry, dict) else str(entry or "")
    relative = str(relative or "").strip()
    if not relative:
        return None
    root = (USER_LIBRARY_DIR if isinstance(entry, dict) and entry.get("source") == "user" else library_root()).resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _thumb_key(path: Path, size: int) -> str:
    try:
        stamp = int(path.stat().st_mtime_ns)
    except OSError:
        stamp = 0
    return hashlib.sha1(f"{path}|{stamp}|{size}".encode("utf-8")).hexdigest()


_THUMB_MEMORY: dict[str, bytes] = {}
_THUMB_MEMORY_LIMIT = 512
_WARM_STATE: dict = {"started": False}
#: 后台预热张数：冷缓存单张约 15ms（JPEG draft 降采样），400 张约 6 秒跑完。
#: ⚠️ 必须节流 + 延时启动：PIL 缩放在 GIL 下是 CPU 密集的，猛跑会让正在打开的
#: 对话框请求被挤慢（实测不节流时 48 张缩略图 6 秒只出 24 张）。
THUMB_WARM_LIMIT = 400
THUMB_WARM_DELAY = 3.0
THUMB_WARM_PAUSE = 0.04


def _remember_thumb(key: str, data: bytes) -> None:
    if len(_THUMB_MEMORY) >= _THUMB_MEMORY_LIMIT:
        for stale in list(_THUMB_MEMORY)[: _THUMB_MEMORY_LIMIT // 4]:
            _THUMB_MEMORY.pop(stale, None)
    _THUMB_MEMORY[key] = data


def thumbnail_bytes(path: Path, size: int = DEFAULT_THUMB_SIZE) -> bytes | None:
    """生成/读取缩略图 JPEG；Pillow 不可用时返回 None（调用方回退原图）。

    三级读取：内存缓存 → 磁盘缓存 → 现生成（JPEG 先 draft 降采样，解码快很多）。
    """
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - 缺 Pillow 时优雅降级
        return None
    target = max(MIN_THUMB_SIZE, min(int(size or DEFAULT_THUMB_SIZE), MAX_THUMB_SIZE))
    key = _thumb_key(path, target)
    cached = _THUMB_MEMORY.get(key)
    if cached:
        return cached
    cache_file = THUMB_DIR / f"{key}.jpg"
    if cache_file.is_file():
        try:
            data = cache_file.read_bytes()
        except OSError:
            data = b""
        if data:
            _remember_thumb(key, data)
            return data
    try:
        with Image.open(path) as image:
            if image.format == "JPEG":
                # draft 让 JPEG 直接以 1/2^n 比例解码，大图缩略快一个数量级。
                image.draft("RGB", (target, target))
            image.load()
            if image.mode in {"RGBA", "LA", "P"}:
                background = Image.new("RGB", image.size, (255, 255, 255))
                converted = image.convert("RGBA")
                background.paste(converted, mask=converted.split()[-1])
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            image.thumbnail((target, target), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85, optimize=True)
        data = buffer.getvalue()
    except Exception:  # noqa: BLE001 - 单张坏图不影响面板
        return None
    _remember_thumb(key, data)
    try:
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(data)
    except OSError:
        pass
    return data


def prewarm_thumbnails(limit: int = THUMB_WARM_LIMIT, size: int = DEFAULT_THUMB_SIZE,
                       pause: float = THUMB_WARM_PAUSE) -> int:
    """同步预热前 ``limit`` 条词条的缩略图（已缓存的不重做）；返回新生成数量。

    每生成一张让出 ``pause`` 秒（参见 ``THUMB_WARM_PAUSE``）；源目录在预热期间变化
    （切库/测试换临时目录）时立即停手。
    """
    expected_root = str(library_root())
    generated = 0
    for row in _rows()[: max(0, int(limit))]:
        if str(library_root()) != expected_root:
            break
        path = image_path(row)
        if not path:
            continue
        key = _thumb_key(path, size)
        if key in _THUMB_MEMORY or (THUMB_DIR / f"{key}.jpg").is_file():
            continue
        if thumbnail_bytes(path, size):
            generated += 1
            if pause > 0:
                time.sleep(pause)
    return generated


def warm_thumbnails_async(limit: int = THUMB_WARM_LIMIT,
                          delay: float = THUMB_WARM_DELAY) -> bool:
    """后台线程预热缩略图（每进程只跑一次），避免首次打开对话框时逐张现生成。

    先等 ``delay`` 秒再开工，避开“面板刚启动 / 刚打开对话框”的高峰。
    ⚠️ 测试里要把 ``_WARM_STATE["started"]`` 置为 True：否则后台线程会拿着临时
    源目录的图片句柄，让 TemporaryDirectory 删除时在 Windows 上报 PermissionError。
    """
    if _WARM_STATE.get("started"):
        return False
    _WARM_STATE["started"] = True

    def worker() -> None:
        try:
            if delay > 0:
                time.sleep(delay)
            prewarm_thumbnails(limit)
        except Exception:  # noqa: BLE001 - 预热失败不影响按需生成
            pass

    threading.Thread(target=worker, name="visual-tag-thumb-warm", daemon=True).start()
    return True


_SECTION_CATALOG_CACHE = {}

def section_presets() -> dict:
    """All locally indexed images as separate compiler components."""
    from .visual_tag_sections import build_catalog
    ensure_index()
    rows = _rows()
    with _LOCK:
        if _SECTION_CATALOG_CACHE.get('rows') is not rows:
            _SECTION_CATALOG_CACHE.update(rows=rows, catalog=build_catalog(rows))
        return _SECTION_CATALOG_CACHE['catalog']
