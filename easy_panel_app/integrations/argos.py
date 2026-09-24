"""离线翻译（Argos Translate）：调用本机已经装好的 Argos venv，不联网、不需要 API Key。

为什么用子进程而不是 import：
  * 面板跑在 `python_embeded`，Argos 装在用户自己的 venv 里（ctranslate2 + sentencepiece
    + 语言包），把这套依赖再装一遍到面板环境既浪费空间、也容易和 ComfyUI 抢版本；
  * 子进程只需要按需启动，翻译完就退出，不常驻内存。

工具目录探测顺序：
  1. 环境变量 ``EASY_PANEL_ARGOS_HOME``（指向含 ``venv/`` 与 ``data/`` 的 argos-translate 目录）
  2. 下面 :data:`DEFAULT_HOMES` 里逐个存在的目录（当前用户机器上的已知位置）

语言包目录沿用 Argos 的 XDG 约定：``<home>/data/argos-translate/packages/translate-zh_en-1_9``，
所以子进程会带上 XDG_DATA_HOME / XDG_CONFIG_HOME / XDG_CACHE_HOME（与工具的启动 bat 一致），
保证模型与缓存都留在 G 盘、不写 C 盘。
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

ENV_HOME = "EASY_PANEL_ARGOS_HOME"
DEFAULT_HOMES = (
    r"G:\edge download\webp_to_png_converter_v2\argos-translate",
    r"G:\ComfyUI\argos-translate",
    r"G:\argos-translate",
)
VENV_PYTHONS = ("venv/Scripts/python.exe", "venv/bin/python")
PACKAGE_DIR = "data/argos-translate/packages"
DEFAULT_FROM = "zh"
DEFAULT_TO = "en"

MAX_TEXTS = 32
MAX_TEXT_CHARS = 4000
DEFAULT_TIMEOUT = 240.0
CACHE_LIMIT = 512
MARKER = "ARGOSJSON:"

#: 子进程里跑的最小翻译脚本：读一份 JSON，逐条翻译，按标记行输出结果。
WORKER = (
    "import json, sys\n"
    "from argostranslate import translate as _translate\n"
    "request = json.loads(sys.stdin.read() or '{}')\n"
    "out = []\n"
    "for item in request.get('texts') or []:\n"
    "    text = (item or '').strip()\n"
    "    out.append(_translate.translate(text, request.get('from', 'zh'), request.get('to', 'en'))\n"
    "               if text else '')\n"
    "print('ARGOSJSON:' + json.dumps({'texts': out}, ensure_ascii=False))\n"
)

_cache: dict[tuple[str, str, str, str], str] = {}
_cache_lock = threading.Lock()


def candidate_homes() -> list[Path]:
    homes: list[Path] = []
    override = os.environ.get(ENV_HOME, "").strip()
    if override:
        homes.append(Path(override).expanduser())
    for item in DEFAULT_HOMES:
        path = Path(item).expanduser()
        if path not in homes:
            homes.append(path)
    return homes


def python_executable(home: Path) -> Path | None:
    for relative in VENV_PYTHONS:
        candidate = home / relative
        if candidate.is_file():
            return candidate
    return None


def argos_home() -> Path | None:
    """返回第一个「有 venv python」的 Argos 目录。"""

    for home in candidate_homes():
        if python_executable(home):
            return home
    return None


def installed_pairs(home: Path) -> list[dict[str, str]]:
    """扫描语言包目录：``translate-zh_en-1_9`` → ``{from: zh, to: en, version: 1_9}``。"""

    folder = home / PACKAGE_DIR
    pairs: list[dict[str, str]] = []
    if not folder.is_dir():
        return pairs
    for entry in sorted(folder.iterdir()):
        name = entry.name
        if not entry.is_dir() or not name.startswith("translate-"):
            continue
        body = name[len("translate-"):]
        version = ""
        if "-" in body:
            body, version = body.rsplit("-", 1)
        if "_" not in body:
            continue
        source, target = body.split("_", 1)
        pairs.append({"from": source, "to": target, "version": version.replace("_", ".")})
    return pairs


def status(*, home: Path | None = None) -> dict:
    """给前端用的能力探测：能不能用、装在哪、有哪些语言对。"""

    resolved = home or argos_home()
    if resolved is None:
        return {
            "available": False,
            "engine": "argos",
            "home": "",
            "python": "",
            "pairs": [],
            "reason": ("未找到离线翻译器（Argos）：请把 argos-translate 目录放在 "
                       "G:\\edge download\\webp_to_png_converter_v2\\ 下，或用环境变量 "
                       "EASY_PANEL_ARGOS_HOME 指定它的位置。"),
        }
    pairs = installed_pairs(resolved)
    available = any(item["from"] == DEFAULT_FROM and item["to"] == DEFAULT_TO for item in pairs)
    reason = ""
    if not pairs:
        reason = f"离线翻译器缺少语言包：请在 {resolved / PACKAGE_DIR} 里安装 zh→en / en→zh 包。"
    elif not available:
        reason = "离线翻译器没有 zh→en 语言包（已装：" + "、".join(
            f"{item['from']}→{item['to']}" for item in pairs) + "）。"
    return {
        "available": available,
        "engine": "argos",
        "home": str(resolved),
        "python": str(python_executable(resolved) or ""),
        "pairs": [f"{item['from']}→{item['to']}" for item in pairs],
        "reason": reason,
    }


def _cache_get(key: tuple[str, str, str, str]) -> str | None:
    with _cache_lock:
        return _cache.get(key)


def _cache_put(key: tuple[str, str, str, str], value: str) -> None:
    with _cache_lock:
        if len(_cache) >= CACHE_LIMIT:
            for stale in list(_cache)[: CACHE_LIMIT // 4]:
                _cache.pop(stale, None)
        _cache[key] = value


def _run_worker(home: Path, payload: dict, timeout: float) -> list[str]:
    python = python_executable(home)
    if python is None:
        raise ValueError("离线翻译器缺少 venv（venv\\Scripts\\python.exe）。")
    env = dict(os.environ)
    env.update({
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_CACHE_HOME": str(home / "cache"),
    })
    try:
        completed = subprocess.run(
            [str(python), "-c", WORKER],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=env, cwd=str(home),
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"离线翻译超时（>{int(timeout)} 秒）；可以先把描述拆短一些。") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = " / ".join(detail[-3:])[:400] or "进程退出码 " + str(completed.returncode)
        raise ValueError("离线翻译执行失败：" + tail)
    for line in reversed((completed.stdout or "").splitlines()):
        if line.startswith(MARKER):
            try:
                parsed = json.loads(line[len(MARKER):])
            except json.JSONDecodeError as exc:
                raise ValueError("离线翻译返回了无法解析的结果。") from exc
            texts = parsed.get("texts")
            if not isinstance(texts, list):
                raise ValueError("离线翻译没有返回文本。")
            return [str(item or "") for item in texts]
    raise ValueError("离线翻译没有返回结果（请检查语言包是否完整）。")


def translate_texts(texts, *, from_code: str = DEFAULT_FROM, to_code: str = DEFAULT_TO,
                    home: Path | None = None, timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    """批量离线翻译；同一段文字走缓存，不会重复启动子进程。"""

    items = [str(item or "") for item in (texts or [])]
    if not items:
        raise ValueError("请先填写要翻译的中文。")
    if len(items) > MAX_TEXTS:
        raise ValueError(f"一次最多翻译 {MAX_TEXTS} 段文字。")
    for item in items:
        if len(item) > MAX_TEXT_CHARS:
            raise ValueError(f"单段文字过长（上限 {MAX_TEXT_CHARS} 字）。")
    resolved = home or argos_home()
    if resolved is None:
        raise ValueError(status()["reason"])
    pairs = installed_pairs(resolved)
    if not any(item["from"] == from_code and item["to"] == to_code for item in pairs):
        raise ValueError(status(home=resolved)["reason"] or
                         f"离线翻译器没有 {from_code}→{to_code} 语言包。")

    key_prefix = (str(resolved), from_code, to_code)
    results: list[str] = []
    pending: list[str] = []
    pending_index: list[int] = []
    for index, item in enumerate(items):
        if not item.strip():
            results.append("")
            continue
        cached = _cache_get((*key_prefix, item))
        if cached is None:
            results.append("")
            pending.append(item)
            pending_index.append(index)
        else:
            results.append(cached)
    if pending:
        translated = _run_worker(
            resolved,
            {"texts": pending, "from": from_code, "to": to_code},
            timeout,
        )
        if len(translated) != len(pending):
            raise ValueError("离线翻译返回的段数与请求不一致。")
        for slot, value in zip(pending_index, translated):
            results[slot] = value
            _cache_put((*key_prefix, items[slot]), value)
    return results


def argos_translate(data: dict) -> dict:
    """``POST /api/argos-translate`` 的入口。

    * ``{"status": true}`` → 只返回能力探测结果（前端用来决定按钮可用性）
    * ``{"text": "..."}`` → 单段翻译，返回与 Google 直译同形状的结果（正面 + 自然语言分区）
    * ``{"texts": [...]}`` → 批量翻译（分区中→英用），原样返回 ``texts``
    """

    payload = data if isinstance(data, dict) else {}
    if payload.get("status"):
        return {"engine": "argos", "engineLabel": "离线翻译（Argos）", "status": status()}
    raw_texts = payload.get("texts")
    if isinstance(raw_texts, list):
        source_texts = [str(item or "") for item in raw_texts]
    else:
        source_texts = [str(payload.get("text") or "")]
    if not any(item.strip() for item in source_texts):
        raise ValueError("请先填写中文描述。")
    from_code = str(payload.get("from") or DEFAULT_FROM).strip().lower() or DEFAULT_FROM
    to_code = str(payload.get("to") or DEFAULT_TO).strip().lower() or DEFAULT_TO
    translated = translate_texts(source_texts, from_code=from_code, to_code=to_code)
    result = {
        "engine": "argos",
        "engineLabel": "离线翻译（Argos）",
        "from": from_code,
        "to": to_code,
        "texts": translated,
    }
    if not isinstance(raw_texts, list):
        positive = (translated[0] if translated else "").strip()
        result.update({
            "positive": positive,
            "negative": "",
            # 与 Google 直译一致：整段直译写进「自然语言」分区，避免把句子塞进标签分区。
            "sections": {"naturalLanguage": positive},
        })
    return result


__all__ = [
    "DEFAULT_FROM",
    "DEFAULT_TO",
    "ENV_HOME",
    "MAX_TEXTS",
    "argos_home",
    "argos_translate",
    "candidate_homes",
    "installed_pairs",
    "python_executable",
    "status",
    "translate_texts",
]
