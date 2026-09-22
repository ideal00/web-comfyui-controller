"""Prompt 方言层：数据库统一存 Danbooru canonical tag，输出时按模型方言转换。

背景（用户 2026-09-22 定的底层标准）：

* 词条库 / 云端 / TagComplete 一律保存 **Danbooru 原形**（``long_hair``），不存空格版。
* 插入 Prompt 时才按当前模型族决定写法：
   - **Anima**：小写 + **下划线转空格**（``long hair``），但 ``score_*`` 保留下划线、
     画师标签用 ``@name`` 形式（Anima 模型卡与 ``integrations/ai.py`` 的翻译提示词同规则）。
   - **Illustrious / 光辉**：默认按用户实测工作流保持 Danbooru 原形（``long_hair``），
     可手动切到空格方言做对照。
   - **Krea 2**：自然语言优先，空格方言。
* **LoRA 触发词永不自动转换**（``protect=True`` / kind=trigger）：有些触发词本身就是
  ``some_custom_trigger_v2``，机械转空格会直接让 LoRA 失效。

已有代码里 AI 转换路径是"靠提示词约束"实现的；本模块负责**确定性插入路径**
（标签搜索、可视化词条库、云端卡片点击）的统一格式，两端（Python / 前端）同规则。
"""

from __future__ import annotations

import re

#: 方言键 → 中文说明（前端下拉与此保持一致）。
DIALECTS = {
    "auto": "跟随模型（Anima 空格 / 其他原样）",
    "space": "空格方言（下划线换空格）",
    "canonical": "Danbooru 原样（保留下划线）",
}
DEFAULT_DIALECT = "auto"

#: 需要空格方言的模型族（Anima 模型卡明确要求；Krea 2 走自然语言）。
SPACE_FAMILIES = {"anima", "krea2"}

#: Danbooru tag 类别编号 → 语义类别（category 字段来自 vendor/tagcomplete 的 danbooru.csv）。
DANBOORU_CATEGORY_KINDS = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta",
}
KIND_LABELS = {
    "general": "通用标签",
    "character": "角色",
    "copyright": "作品",
    "artist": "画师",
    "meta": "元标签",
    "score": "分数标签",
    "trigger": "LoRA 触发词",
    "unknown": "未知",
}

_ARTIST_PREFIX = "@"
_SCORE_RE = re.compile(r"^score_\d+(?:_up)?$", re.I)


def resolve_dialect(family: str = "", override: str = "auto") -> str:
    """把"模型族 + 用户选择"解析成 ``space`` 或 ``canonical``。"""
    choice = str(override or DEFAULT_DIALECT).strip().lower()
    if choice in {"space", "canonical"}:
        return choice
    family_key = str(family or "").strip().lower()
    return "space" if family_key in SPACE_FAMILIES else "canonical"


def classify_tag(tag: str, categories: dict[str, int] | None = None) -> str:
    """判断 tag 语义类别：``score`` / ``artist`` / ``trigger`` / 通用等。

    ``categories`` 是 ``{规范化 tag: Danbooru category}``，由调用方注入（避免本模块
    依赖 3.4MB 的标签表）；缺失时只按形状判断。
    """
    value = str(tag or "").strip()
    if not value:
        return "unknown"
    if _SCORE_RE.match(value):
        return "score"
    if value.startswith(_ARTIST_PREFIX):
        return "artist"
    if categories:
        category = categories.get(value.lower())
        if category is not None:
            return DANBOORU_CATEGORY_KINDS.get(int(category), "general")
    return "general"


def format_tag(tag: str, dialect: str, kind: str = "", protect: bool = False) -> str:
    """按方言输出单个 tag；``protect``（触发词）与 ``score`` 永远原样。"""
    value = str(tag or "").strip()
    if not value:
        return ""
    resolved = "space" if str(dialect or "").lower() == "space" else "canonical"
    if protect:
        return value
    if resolved == "canonical":
        return value
    if _SCORE_RE.match(value):
        return value
    if kind == "trigger":
        return value
    if kind == "artist" or value.startswith(_ARTIST_PREFIX):
        body = value[1:] if value.startswith(_ARTIST_PREFIX) else value
        return f"{_ARTIST_PREFIX}{body.replace('_', ' ')}".strip()
    return value.replace("_", " ")


def format_tags(tags, dialect: str, kinds: dict[str, str] | None = None,
                protect: bool = False) -> list[str]:
    """批量格式化；``kinds`` 可选 ``{tag: kind}``。"""
    lookup = kinds or {}
    return [format_tag(tag, dialect, lookup.get(str(tag).strip(), ""), protect) for tag in (tags or [])]


def describe(dialect: str, family: str = "") -> str:
    """给 UI 用的一句话说明。"""
    resolved = resolve_dialect(family, dialect)
    if str(dialect or "").lower() in {"space", "canonical"}:
        return f"{DIALECTS[resolved]}（手动指定）"
    family_key = str(family or "").strip().lower()
    suffix = f"：{family_key}" if family_key else ""
    return f"{DIALECTS[resolved]}（按当前模型{suffix}）"


def convert(tags, family: str = "", dialect: str = DEFAULT_DIALECT,
            categories: dict[str, int] | None = None) -> dict:
    """给接口/前端的统一入口：返回每一条的输入、类别与最终写法。"""
    resolved = resolve_dialect(family, dialect)
    results = []
    for tag in tags or []:
        kind = classify_tag(tag, categories)
        results.append({
            "input": str(tag),
            "tag": str(tag).strip(),
            "kind": kind,
            "kind_label": KIND_LABELS.get(kind, kind),
            "formatted": format_tag(tag, resolved, kind),
        })
    return {
        "family": str(family or ""),
        "dialect": str(dialect or DEFAULT_DIALECT),
        "resolved": resolved,
        "description": describe(dialect, family),
        "dialects": DIALECTS,
        "results": results,
    }
