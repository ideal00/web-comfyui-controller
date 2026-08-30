"""Safe, device-shared browser state for Easy Panel.

Only the two browser collections that already exist in the Easy Panel web UI
are stored here: user prompt presets and the LoRA/character favourites list.
The file is deliberately separate from ``lora_notes.json`` and is never
addressed by a path supplied by an HTTP client.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Mapping
from http import HTTPStatus
from pathlib import Path
from typing import Any


SHARED_STATE_SCHEMA = 1
SHARED_STATE_FILENAME = "easy_panel_shared_state.json"
SHARED_STATE_BACKUP_SUFFIX = ".bak"
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_STATE_BYTES
MAX_PROMPT_PRESETS = 300
MAX_CHARACTER_FAVORITES = 500
MAX_PRESET_NAME_CHARS = 80
MAX_PRESET_TEXT_CHARS = 12000
MAX_PRESET_SECTIONS = 10
MAX_PRESET_ITEM_BYTES = 160 * 1024
MAX_FAVORITE_CHARS = 512
PROMPT_PRESET_CATEGORIES = {
    "combo",
    "pose",
    "artist",
    "composition",
    "lighting",
    "scene",
    "clothing",
    "appearance",
    "subject",
    "negative",
    "manual",
}
PROMPT_SECTION_CATEGORIES = PROMPT_PRESET_CATEGORIES - {"combo"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


class SharedStateError(ValueError):
    """A client or on-disk shared-state document failed validation."""

    status = HTTPStatus.BAD_REQUEST


class SharedStateStore:
    """Read and merge shared state with atomic, process-local serialization."""

    def __init__(self, path: str | os.PathLike[str]):
        raw_path = os.fspath(path)
        if not raw_path or "\x00" in raw_path:
            raise ValueError("共享数据文件路径无效。")
        self.path = Path(raw_path).resolve()
        self.backup_path = self.path.with_name(self.path.name + SHARED_STATE_BACKUP_SUFFIX)
        self._lock = threading.RLock()

    @staticmethod
    def empty_state() -> dict[str, Any]:
        return {
            "schema": SHARED_STATE_SCHEMA,
            "revision": 0,
            "updatedAt": 0,
            "promptPresets": [],
            "characterFavorites": [],
        }

    def read(self) -> dict[str, Any]:
        state, _ = self.read_with_metadata()
        return state

    def read_with_metadata(self) -> tuple[dict[str, Any], bool]:
        with self._lock:
            return self._load_locked()

    def merge(self, client_state: Mapping[str, Any] | None, base_revision: Any = None) -> dict[str, Any]:
        """Merge a browser snapshot without allowing stale clients to replace data.

        A revision mismatch is intentionally a safe merge: new records from the
        client may be added, but records that already exist on the server are
        kept.  A client with the current revision may update an existing preset
        using its ``updatedAt`` timestamp.  Empty client collections are never a
        deletion request.
        """

        if base_revision is not None:
            if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision < 0:
                raise SharedStateError("共享数据 revision 无效。")
        incoming = self.normalize_client_state(client_state)
        with self._lock:
            current, recovered = self._load_locked()
            conflict = base_revision is not None and base_revision != current["revision"]
            if not incoming["promptPresets"] and not incoming["characterFavorites"]:
                return {
                    "ok": True,
                    "state": current,
                    "changed": False,
                    "conflict": conflict,
                    "reason": "empty_client",
                    "recovered": recovered,
                }

            merged_presets = _merge_prompt_presets(
                current["promptPresets"],
                incoming["promptPresets"],
                allow_replacements=not conflict and base_revision is not None,
            )
            merged_favorites = _merge_favorites(
                current["characterFavorites"], incoming["characterFavorites"]
            )
            if len(merged_presets) > MAX_PROMPT_PRESETS:
                raise SharedStateError(f"提示词预设数量超过上限（{MAX_PROMPT_PRESETS}）。")
            if len(merged_favorites) > MAX_CHARACTER_FAVORITES:
                raise SharedStateError(f"角色收藏数量超过上限（{MAX_CHARACTER_FAVORITES}）。")

            changed = (
                merged_presets != current["promptPresets"]
                or merged_favorites != current["characterFavorites"]
            )
            if changed:
                now = max(_now_ms(), current["updatedAt"] + 1)
                next_state = {
                    "schema": SHARED_STATE_SCHEMA,
                    "revision": current["revision"] + 1,
                    "updatedAt": now,
                    "promptPresets": merged_presets,
                    "characterFavorites": merged_favorites,
                }
                self._write_locked(next_state)
            else:
                next_state = current
            return {
                "ok": True,
                "state": next_state,
                "changed": changed,
                "conflict": conflict,
                "reason": "revision_conflict" if conflict else "merged",
                "recovered": recovered,
            }

    @staticmethod
    def normalize_client_state(client_state: Mapping[str, Any] | None) -> dict[str, Any]:
        if client_state is None:
            client_state = {}
        if not isinstance(client_state, Mapping):
            raise SharedStateError("共享数据必须是 JSON 对象。")
        return {
            "promptPresets": _normalize_prompt_list(client_state.get("promptPresets", [])),
            "characterFavorites": _normalize_favorite_list(client_state.get("characterFavorites", [])),
        }

    def _load_locked(self) -> tuple[dict[str, Any], bool]:
        if self.path.is_file():
            try:
                return _decode_state(self.path.read_bytes()), False
            except (OSError, SharedStateError, json.JSONDecodeError, UnicodeError):
                pass
        if self.backup_path.is_file():
            try:
                state = _decode_state(self.backup_path.read_bytes())
                self._atomic_replace_bytes_locked(_encode_state(state), make_backup=False)
                return state, True
            except (OSError, SharedStateError, json.JSONDecodeError, UnicodeError):
                pass
        self._quarantine_corrupt_primary_locked()
        return self.empty_state(), False

    def _write_locked(self, state: Mapping[str, Any]) -> None:
        encoded = _encode_state(state)
        if len(encoded) > MAX_STATE_BYTES:
            raise SharedStateError("共享数据文件超过 4 MB 上限。")
        self._atomic_replace_bytes_locked(encoded, make_backup=True)

    def _atomic_replace_bytes_locked(self, encoded: bytes, *, make_backup: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        previous: bytes | None = None
        if make_backup and self.path.is_file():
            try:
                candidate = self.path.read_bytes()
                _decode_state(candidate)
                previous = candidate
            except (OSError, SharedStateError, json.JSONDecodeError, UnicodeError):
                previous = None

        temp_path = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with temp_path.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if previous is not None:
                backup_temp = self.backup_path.with_name(
                    f".{self.backup_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
                )
                try:
                    with backup_temp.open("wb") as handle:
                        handle.write(previous)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(backup_temp, self.backup_path)
                finally:
                    _unlink_quietly(backup_temp)
            os.replace(temp_path, self.path)
            _fsync_directory_quietly(self.path.parent)
        finally:
            _unlink_quietly(temp_path)

    def _quarantine_corrupt_primary_locked(self) -> None:
        if not self.path.is_file():
            return
        stamp = _now_ms()
        target = self.path.with_name(f"{self.path.name}.corrupt.{stamp}.json")
        counter = 0
        while target.exists():
            counter += 1
            target = self.path.with_name(f"{self.path.name}.corrupt.{stamp}.{counter}.json")
        try:
            os.replace(self.path, target)
        except OSError:
            pass


def _now_ms() -> int:
    return int(time.time() * 1000)


def _text(value: Any, maximum: int, field: str, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise SharedStateError(f"共享数据字段 {field} 必须是字符串。")
    value = value.strip()
    if required and not value:
        raise SharedStateError(f"共享数据字段 {field} 不能为空。")
    if len(value) > maximum:
        raise SharedStateError(f"共享数据字段 {field} 超过长度上限。")
    return value


def _normalize_prompt_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        raise SharedStateError("提示词预设必须是对象。")
    name = _text(item.get("name"), MAX_PRESET_NAME_CHARS, "name")
    if not name:
        return None
    category = item.get("category") if isinstance(item.get("category"), str) else "manual"
    if category not in PROMPT_PRESET_CATEGORIES:
        category = "manual"
    raw_sections = item.get("sections", {})
    if raw_sections is None:
        raw_sections = {}
    if not isinstance(raw_sections, Mapping):
        raise SharedStateError("提示词预设 sections 必须是对象。")
    if len(raw_sections) > MAX_PRESET_SECTIONS:
        raise SharedStateError("提示词预设分区数量超过上限。")
    sections: dict[str, str] = {}
    for key, value in raw_sections.items():
        if key not in PROMPT_SECTION_CATEGORIES:
            continue
        clean = _text(value, MAX_PRESET_TEXT_CHARS, f"sections.{key}")
        if clean:
            sections[key] = clean
    content_limit = MAX_PRESET_TEXT_CHARS * MAX_PRESET_SECTIONS if category == "combo" else MAX_PRESET_TEXT_CHARS
    content = _text(item.get("content"), content_limit, "content")
    if category == "combo" and not content and sections:
        content = "\n".join(sections.values())
    if not content:
        return None
    raw_id = item.get("id", "")
    if raw_id is not None and not isinstance(raw_id, str):
        raise SharedStateError("提示词预设 id 必须是字符串。")
    item_id = raw_id.strip() if isinstance(raw_id, str) else ""
    if not _SAFE_ID.fullmatch(item_id):
        item_id = "p_" + _prompt_fingerprint({
            "name": name,
            "category": category,
            "content": content,
            "sections": sections,
        })[:32]
    raw_updated = item.get("updatedAt", 0)
    if isinstance(raw_updated, bool) or not isinstance(raw_updated, (int, float)):
        raw_updated = 0
    updated_at = max(0, int(raw_updated))
    normalized = {
        "id": item_id,
        "name": name,
        "category": category,
        "content": content,
        "sections": sections,
        "updatedAt": updated_at,
    }
    if len(_encode_json(normalized)) > MAX_PRESET_ITEM_BYTES:
        raise SharedStateError("单个提示词预设超过大小上限。")
    return normalized


def _normalize_prompt_list(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SharedStateError("promptPresets 必须是数组。")
    if len(raw) > MAX_PROMPT_PRESETS:
        raise SharedStateError(f"提示词预设数量超过上限（{MAX_PROMPT_PRESETS}）。")
    output: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    for item in raw:
        normalized = _normalize_prompt_item(item)
        if normalized is None:
            continue
        fingerprint = _prompt_fingerprint(normalized)
        if normalized["id"] in seen_ids or fingerprint in seen_fingerprints:
            continue
        seen_ids.add(normalized["id"])
        seen_fingerprints.add(fingerprint)
        output.append(normalized)
    return output


def _normalize_favorite(value: Any) -> str | None:
    if not isinstance(value, str):
        raise SharedStateError("角色收藏必须是字符串路径。")
    value = value.strip().replace("\\", "/")
    if not value:
        return None
    if len(value) > MAX_FAVORITE_CHARS:
        raise SharedStateError("角色收藏名称超过长度上限。")
    if value.startswith("/") or value.startswith("//") or re.match(r"^[A-Za-z]:", value):
        raise SharedStateError("角色收藏必须是相对 LoRA 路径。")
    if "\x00" in value or any(part == ".." for part in value.split("/")):
        raise SharedStateError("角色收藏路径无效。")
    return value


def _normalize_favorite_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SharedStateError("characterFavorites 必须是数组。")
    if len(raw) > MAX_CHARACTER_FAVORITES:
        raise SharedStateError(f"角色收藏数量超过上限（{MAX_CHARACTER_FAVORITES}）。")
    output: list[str] = []
    seen: set[str] = set()
    for value in raw:
        normalized = _normalize_favorite(value)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return sorted(output, key=str.casefold)


def _prompt_fingerprint(item: Mapping[str, Any]) -> str:
    material = {
        "name": item.get("name", ""),
        "category": item.get("category", ""),
        "content": item.get("content", ""),
        "sections": item.get("sections", {}),
    }
    return hashlib.sha256(_encode_json(material)).hexdigest()


def _merge_prompt_presets(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    allow_replacements: bool,
) -> list[dict[str, Any]]:
    result = [dict(item, sections=dict(item.get("sections", {}))) for item in existing]
    by_id = {item["id"]: index for index, item in enumerate(result)}
    by_fingerprint = {_prompt_fingerprint(item): index for index, item in enumerate(result)}
    for item in incoming:
        item_copy = dict(item, sections=dict(item.get("sections", {})))
        index = by_id.get(item_copy["id"])
        matched_by_id = index is not None
        if index is None:
            index = by_fingerprint.get(_prompt_fingerprint(item_copy))
        if index is None:
            result.append(item_copy)
            index = len(result) - 1
            by_id[item_copy["id"]] = index
            by_fingerprint[_prompt_fingerprint(item_copy)] = index
            continue
        current = result[index]
        if matched_by_id and allow_replacements and item_copy["updatedAt"] > current["updatedAt"]:
            result[index] = item_copy
            by_id[item_copy["id"]] = index
            by_fingerprint[_prompt_fingerprint(item_copy)] = index
    return sorted(result, key=lambda item: (-int(item["updatedAt"]), item["id"]))


def _merge_favorites(existing: list[str], incoming: list[str]) -> list[str]:
    return sorted(set(existing).union(incoming), key=str.casefold)


def _encode_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_state(state: Mapping[str, Any]) -> bytes:
    normalized = _validate_document(state)
    encoded = json.dumps(normalized, ensure_ascii=False, indent=2).encode("utf-8")
    if len(encoded) > MAX_STATE_BYTES:
        raise SharedStateError("共享数据文件超过 4 MB 上限。")
    return encoded


def _decode_state(encoded: bytes) -> dict[str, Any]:
    if len(encoded) > MAX_STATE_BYTES:
        raise SharedStateError("共享数据文件超过 4 MB 上限。")
    parsed = json.loads(encoded.decode("utf-8"))
    return _validate_document(parsed)


def _validate_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise SharedStateError("共享数据文件根节点必须是对象。")
    if document.get("schema") != SHARED_STATE_SCHEMA:
        raise SharedStateError("共享数据 schema 版本不受支持。")
    revision = document.get("revision")
    updated_at = document.get("updatedAt")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise SharedStateError("共享数据 revision 无效。")
    if isinstance(updated_at, bool) or not isinstance(updated_at, int) or updated_at < 0:
        raise SharedStateError("共享数据 updatedAt 无效。")
    prompt_presets = _normalize_prompt_list(document.get("promptPresets"))
    favorites = _normalize_favorite_list(document.get("characterFavorites"))
    if len(_encode_json({"promptPresets": prompt_presets, "characterFavorites": favorites})) > MAX_STATE_BYTES:
        raise SharedStateError("共享数据内容超过大小上限。")
    return {
        "schema": SHARED_STATE_SCHEMA,
        "revision": revision,
        "updatedAt": updated_at,
        "promptPresets": prompt_presets,
        "characterFavorites": favorites,
    }


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _fsync_directory_quietly(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
