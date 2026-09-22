"""Danbooru 云端查询（只读）：小请求 + 限速 + 缓存 + 失败降级。

设计约束（实测与官方文档确认）：

* 读请求全局 10 req/s 且**按 IP 共享**，官方建议长期会话 ~1 req/s → 这里串行 + 最小间隔。
* ``order:score``（按热度）在热门标签上会 HTTP 500 → **不提供**热门排序，只用最新 / 最旧。
* 突发请求会成批 500/超时 → 必须有缓存与退避，任何失败都降级为"本地结果 + 云端不可用"提示。
* 匿名只读无需 API key；``/posts.json`` 单页最多 200 条，这里按方案每次只取 20 条。

本模块不直接读磁盘，缓存放内存（进程级）；所有网络调用都可注入 ``fetcher`` 便于测试。
"""

from __future__ import annotations

import concurrent.futures
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_ENV = "EASY_PANEL_DANBOORU_BASE"
DEFAULT_BASE = "https://danbooru.donmai.us"
#: ⚠️ UA 里**不能出现 comfyui**：实测 ``easy-panel/1.0 (local ComfyUI panel)`` 直接 403，
#: 同形但不含该词的 UA 正常 200（站点按关键词拦机器人）。改 UA 前先看 UA 断言测试。
USER_AGENT = "easy-panel-visual-tag-library/1.0"

DEFAULT_LIMIT = 20
MAX_LIMIT = 20
MAX_PAGE = 100
CACHE_TTL_SECONDS = 600.0
MIN_INTERVAL_SECONDS = 1.0
BACKOFF_SECONDS = 45.0
REQUEST_TIMEOUT = 20.0
MAX_TAGS_PER_POST = 160

#: UI 用的分级名 → Danbooru 单字母分级。
RATING_CODES = {
    "general": "g",
    "sensitive": "s",
    "questionable": "q",
    "explicit": "e",
}
RATING_LABELS = {
    "general": "General（全年龄）",
    "sensitive": "Sensitive（敏感）",
    "questionable": "Questionable（暗示）",
    "explicit": "Explicit（明确）",
}
#: 只保留两种稳定排序：最新（默认）与最旧。热门排序实测会 500，不提供。
SORT_TAGS = {
    "newest": "",
    "oldest": "order:id",
}
SORT_LABELS = {"newest": "最新", "oldest": "最旧"}

_LOCK = threading.RLock()
_CACHE: dict[tuple, tuple[float, dict]] = {}
_LAST_CALL = {"ts": 0.0}
_BACKOFF_UNTIL = {"ts": 0.0}

#: 帖图索引：搜索/缓存过的帖子的预览图与原图 URL，供 /api/danbooru/image 代理使用
#: （代理不能用任意 URL（SSRF），只能解析“我们确实搜索到过的帖子”的图片）。
_POST_INDEX: dict[str, dict] = {}
_POST_INDEX_LIMIT = 4000

#: 图片字节缓存（仅内存）：预览图约 5–15KB，300 张 ≈ 3MB；重复打开对话框直接命中。
IMAGE_CACHE: dict[str, tuple[float, bytes]] = {}
IMAGE_CACHE_LIMIT = 300
IMAGE_CACHE_TTL = 1800.0
IMAGE_KINDS = {"preview": "preview_url", "sample": "sample_url"}
IMAGE_MIN_INTERVAL = 0.05
IMAGE_MAX_BYTES = 4_000_000
_IMAGE_LAST_CALL = {"ts": 0.0}


def base_url() -> str:
    import os

    return os.environ.get(BASE_ENV, "").strip() or DEFAULT_BASE


def _default_fetcher(url: str, timeout: float = REQUEST_TIMEOUT):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _wait_for_slot() -> None:
    """串行 + 最小间隔，避免触发站点限流。"""
    with _LOCK:
        gap = time.monotonic() - _LAST_CALL["ts"]
        if gap < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - gap)
        _LAST_CALL["ts"] = time.monotonic()


def _cached(key: tuple) -> dict | None:
    with _LOCK:
        item = _CACHE.get(key)
    if not item:
        return None
    if time.monotonic() - item[0] > CACHE_TTL_SECONDS:
        return None
    payload = dict(item[1])
    payload["cached"] = True
    return payload


def _store(key: tuple, payload: dict) -> dict:
    with _LOCK:
        _CACHE[key] = (time.monotonic(), payload)
        if len(_CACHE) > 200:
            oldest = sorted(_CACHE.items(), key=lambda pair: pair[1][0])[:50]
            for stale_key, _ in oldest:
                _CACHE.pop(stale_key, None)
    return payload


def _build_query(tags: str, rating: str, sort: str) -> str:
    parts = [tags.strip()]
    code = RATING_CODES.get(str(rating or "").strip().lower())
    if code:
        parts.append(f"rating:{code}")
    order = SORT_TAGS.get(str(sort or "").strip().lower(), "")
    if order:
        parts.append(order)
    return " ".join(part for part in parts if part)


def _split_tag_string(value: object, cap: int = MAX_TAGS_PER_POST) -> list[str]:
    return [item for item in str(value or "").split(" ") if item][:cap]


#: 不可用于提示词的标签：Danbooru 的颜文字/表情符号类（用户拿它们写 prompt 无意义）。
NON_PROMPT_TAGS = frozenset({
    ":d", ":p", ":3", ":o", ":q", ";d", ";p", ";3", ":|", ":)", ":(", ":>", ":<",
    "xd", "^_^", ">_<", "@_@", "t_t", "><", "o_o", "0_0", "-_", "=_=", "^^;", "orz",
})


def is_promptable_tag(tag: str) -> bool:
    """颜文字类标签不适合写进 Prompt（前缀冒号/分号的是 Danbooru 颜文字）。"""
    value = str(tag or "").strip()
    if not value:
        return False
    if value.lower() in NON_PROMPT_TAGS:
        return False
    return value[0] not in {":", ";"}


def normalize_post(post: dict) -> dict | None:
    """Danbooru post → 统一卡片（与本地卡片同形，前端一套渲染逻辑）。"""
    if not isinstance(post, dict):
        return None
    if post.get("is_deleted") or post.get("is_banned"):
        return None
    preview = str(post.get("preview_file_url") or "")
    post_id = post.get("id")
    if not post_id:
        return None
    groups = {
        "general": [tag for tag in _split_tag_string(post.get("tag_string_general")) if is_promptable_tag(tag)],
        "character": _split_tag_string(post.get("tag_string_character")),
        "copyright": _split_tag_string(post.get("tag_string_copyright")),
        "artist": _split_tag_string(post.get("tag_string_artist")),
    }
    all_tags = [tag for tag in _split_tag_string(post.get("tag_string")) if is_promptable_tag(tag)]
    return {
        "source": "danbooru",
        "id": f"post:{post_id}",
        "post_id": post_id,
        "preview_url": preview,
        "sample_url": str(post.get("large_file_url") or post.get("file_url") or preview),
        "file_url": str(post.get("file_url") or ""),
        "post_url": f"{base_url()}/posts/{post_id}",
        "width": int(post.get("image_width") or 0),
        "height": int(post.get("image_height") or 0),
        "rating": str(post.get("rating") or ""),
        "score": int(post.get("score") or 0),
        "tag_count": int(post.get("tag_count") or len(all_tags)),
        "tags": all_tags,
        "groups": groups,
    }


def _index_posts(cards: list[dict]) -> None:
    """记住搜到的帖子，供图片代理解析（不信任外部传入的 URL）。"""
    with _LOCK:
        for card in cards:
            post_id = str(card.get("post_id") or "")
            if not post_id:
                continue
            _POST_INDEX[post_id] = {
                "preview_url": card.get("preview_url") or "",
                "sample_url": card.get("sample_url") or "",
                "ts": time.monotonic(),
            }
        if len(_POST_INDEX) > _POST_INDEX_LIMIT:
            oldest = sorted(_POST_INDEX.items(), key=lambda pair: pair[1].get("ts", 0.0))
            for stale_id, _ in oldest[: _POST_INDEX_LIMIT // 4]:
                _POST_INDEX.pop(stale_id, None)


def resolve_post_image(post_id: str, kind: str = "preview") -> str:
    """帖子编号 → 图片 URL（仅限本次进程搜到过的帖子；未知则返回空）。"""
    key = str(post_id or "").strip()
    field = IMAGE_KINDS.get(str(kind or "preview").strip().lower(), "preview_url")
    if not key:
        return ""
    with _LOCK:
        entry = _POST_INDEX.get(key)
    return str(entry.get(field) or "") if entry else ""


def _image_get(url: str, timeout: float = REQUEST_TIMEOUT):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(IMAGE_MAX_BYTES + 1)


def fetch_image(url: str, fetcher=None, use_cache: bool = True) -> bytes | None:
    """抓取帖图字节（带内存缓存与轻量限速）；失败返回 None，绝不抛错给上层。"""
    target = str(url or "").strip()
    if not target:
        return None
    now = time.monotonic()
    if use_cache:
        with _LOCK:
            cached = IMAGE_CACHE.get(target)
        if cached and now - cached[0] <= IMAGE_CACHE_TTL:
            return cached[1]
    fetch = fetcher or _image_get
    with _LOCK:
        gap = now - _IMAGE_LAST_CALL["ts"]
    if gap < IMAGE_MIN_INTERVAL:
        time.sleep(IMAGE_MIN_INTERVAL - gap)
    with _LOCK:
        _IMAGE_LAST_CALL["ts"] = time.monotonic()
    try:
        data = fetch(target)
    except Exception:  # noqa: BLE001 - 图片拿不到就当没有（前端回退占位符）
        return None
    if not data or len(data) > IMAGE_MAX_BYTES:
        return None
    with _LOCK:
        if len(IMAGE_CACHE) >= IMAGE_CACHE_LIMIT:
            oldest = sorted(IMAGE_CACHE.items(), key=lambda pair: pair[1][0])
            for stale_key, _ in oldest[: IMAGE_CACHE_LIMIT // 4]:
                IMAGE_CACHE.pop(stale_key, None)
        IMAGE_CACHE[target] = (time.monotonic(), data)
    return data


def prefetch_images(cards: list[dict], workers: int = 6, kind: str = "preview") -> bool:
    """搜索返回后后台预取预览图：浏览器同源并发只有 6，且 CDN 单张约 1–2 秒，
    后台先抓一轮可以让首屏尾部与再次打开都接近瞬时。"""
    urls = []
    for card in cards:
        url = str(card.get("preview_url") or "") if kind == "preview" else str(card.get("sample_url") or "")
        if not url:
            continue
        with _LOCK:
            cached = IMAGE_CACHE.get(url)
        if cached and time.monotonic() - cached[0] <= IMAGE_CACHE_TTL:
            continue
        urls.append(url)
    if not urls:
        return False

    def worker() -> None:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
                list(pool.map(lambda item: fetch_image(item), urls))
        except Exception:  # noqa: BLE001 - 预取失败不影响按需加载
            pass

    threading.Thread(target=worker, name="danbooru-image-prefetch", daemon=True).start()
    return True


def search_posts(tags: str, limit: int = DEFAULT_LIMIT, page: int = 1,
                 rating: str = "general", sort: str = "newest",
                 fetcher=None, use_cache: bool = True) -> dict:
    """查询 Danbooru 帖子；任何异常都转成带 ``error`` 的降级结果，不抛错。"""
    query_tags = str(tags or "").strip()
    try:
        safe_limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    except (TypeError, ValueError):
        safe_limit = DEFAULT_LIMIT
    try:
        safe_page = max(1, min(int(page or 1), MAX_PAGE))
    except (TypeError, ValueError):
        safe_page = 1
    rating_key = str(rating or "").strip().lower()
    rating_key = rating_key if rating_key in RATING_CODES else "general"
    sort_key = str(sort or "").strip().lower()
    sort_key = sort_key if sort_key in SORT_TAGS else "newest"

    payload = {
        "source": "danbooru",
        "query": query_tags,
        "composed_query": "",
        "page": safe_page,
        "limit": safe_limit,
        "rating": rating_key,
        "sort": sort_key,
        "cached": False,
        "results": [],
        "error": "",
        "base": base_url(),
    }
    if not query_tags:
        payload["error"] = "请输入要查询的标签。"
        return payload

    composed = _build_query(query_tags, rating_key, sort_key)
    payload["composed_query"] = composed
    key = (composed, safe_limit, safe_page)
    if use_cache:
        cached = _cached(key)
        if cached:
            return cached

    now = time.monotonic()
    with _LOCK:
        backoff_left = _BACKOFF_UNTIL["ts"] - now
    if backoff_left > 0:
        payload["error"] = f"云端刚被限流，{int(backoff_left) + 1} 秒后可重试。"
        payload["retry_after"] = int(backoff_left) + 1
        return payload

    params = urllib.parse.urlencode({
        "tags": composed,
        "limit": safe_limit,
        "page": safe_page,
    })
    url = f"{base_url()}/posts.json?{params}"
    fetch = fetcher or _default_fetcher
    _wait_for_slot()
    try:
        raw = fetch(url)
    except urllib.error.HTTPError as exc:  # 429/500/403…
        code = getattr(exc, "code", 0)
        with _LOCK:
            _BACKOFF_UNTIL["ts"] = time.monotonic() + (BACKOFF_SECONDS if code in {429, 503} else 15.0)
        payload["error"] = {
            429: "云端限流（429），请稍后再试。",
            500: "云端查询超时/繁忙（500），已降级为本地结果。",
            403: "云端拒绝了这次请求（403）。",
            404: "云端没有这个地址（404）。",
        }.get(code, f"云端返回错误（HTTP {code}）。")
        return payload
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        payload["error"] = f"无法连接 Danbooru：{exc}"
        return payload
    except (ValueError, json.JSONDecodeError):
        payload["error"] = "云端返回内容无法解析。"
        return payload

    if not isinstance(raw, list):
        payload["error"] = "云端返回了意外的数据结构。"
        return payload

    cards = []
    for post in raw:
        card = normalize_post(post)
        if card:
            cards.append(card)
    payload["results"] = cards
    payload["received"] = len(cards)
    _index_posts(cards)
    prefetch_images(cards)
    return _store(key, payload)


def cache_stats() -> dict:
    with _LOCK:
        return {"entries": len(_CACHE), "min_interval": MIN_INTERVAL_SECONDS,
                "cache_ttl": CACHE_TTL_SECONDS, "backoff_left": max(0.0, _BACKOFF_UNTIL["ts"] - time.monotonic())}


def clear_cache() -> None:
    """清空云端缓存与退避（测试与手动重试用）。"""
    with _LOCK:
        _CACHE.clear()
        _POST_INDEX.clear()
        IMAGE_CACHE.clear()
        _BACKOFF_UNTIL["ts"] = 0.0
