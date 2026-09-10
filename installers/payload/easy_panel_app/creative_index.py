"""Backward-compatible SQLite index for Easy Panel creative state.

The JSON snapshot and job files remain the source of truth for replay.  This
module adds a deliberately one-way, query-oriented index around them.  Every
write is best-effort at the caller boundary, while the individual SQLite
operations use transactions so a failed row cannot leave a half-written
generation behind.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import secrets
import sqlite3
import time
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlencode


SCHEMA_VERSION = 1
MAX_PAGE_SIZE = 100
MAX_OFFSET = 1_000_000
MAX_LINEAGE_NODES = 100
MAX_SNAPSHOT_TEXT = 2_000_000

SUPPORTED_OPERATIONS = frozenset({
    "txt2img",
    "seed_variant",
    "img2img",
    "inpaint",
    "face_fix",
    "hand_fix",
    "upscale",
    "outfit_change",
    "scene_change",
    "style_change",
    "section_change",
})
KNOWN_STATUSES = frozenset({"queued", "running", "completed", "error", "cancelled", "unknown"})
_STATUS_ALIASES = {
    "complete": "completed",
    "done": "completed",
    "failed": "error",
    "failure": "error",
    "success": "completed",
    "succeeded": "completed",
    "canceled": "cancelled",
    "cancel": "cancelled",
    "pending": "queued",
    "processing": "running",
}
_TERMINAL_STATUSES = frozenset({"completed", "error", "cancelled"})
_LEGACY_ARTIFACT_KEYS = ("outputs", "images", "artifacts")
_LEGACY_IDENTIFIER_KEYS = ("promptId", "prompt_id", "requestId", "request_id")
SORT_FIELDS = {
    "created_at": "g.created_at",
    "updated_at": "g.updated_at",
    "status": "g.status",
    "operation": "g.operation",
    "model": "g.model",
}

_SECRET_KEY_MARKERS = (
    "token",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "secret",
)


class CreativeIndexError(ValueError):
    """Raised for invalid index input or an incompatible database."""


def now_ms() -> int:
    return int(time.time() * 1000)


def normalize_operation(value: Any, default: str = "unknown") -> str:
    raw = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if raw in SUPPORTED_OPERATIONS:
        return raw
    return default if default in SUPPORTED_OPERATIONS or default == "unknown" else "unknown"


def normalize_status(value: Any, default: str = "unknown") -> str:
    if isinstance(value, Mapping):
        value = value.get("status") or value.get("status_str") or value.get("state")
    raw = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    raw = _STATUS_ALIASES.get(raw, raw)
    if raw in KNOWN_STATUSES:
        return raw
    return default if default in KNOWN_STATUSES else "unknown"


def _status_priority(value: str) -> int:
    return {
        "unknown": 0,
        "queued": 1,
        "running": 2,
        "cancelled": 3,
        "error": 4,
        "completed": 5,
    }.get(value, 0)


def _merged_status(old: Any, new: Any) -> str:
    before = normalize_status(old)
    after = normalize_status(new)
    if before in _TERMINAL_STATUSES:
        return before
    if after in _TERMINAL_STATUSES:
        return after
    if _status_priority(after) >= _status_priority(before):
        return after
    return before


def _has_legacy_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, Sequence)):
        return bool(value)
    return bool(value)


def _legacy_status_value(record: Mapping[str, Any]) -> str | None:
    if "status" not in record or not _has_legacy_value(record.get("status")):
        return None
    normalized = normalize_status(record.get("status"))
    return normalized if normalized != "unknown" else None


def _legacy_has_outputs(record: Mapping[str, Any]) -> bool:
    return any(_has_legacy_value(record.get(key)) for key in _LEGACY_ARTIFACT_KEYS)


def _legacy_has_error(record: Mapping[str, Any]) -> bool:
    return any(_has_legacy_value(record.get(key)) for key in ("error", "error_json"))


def _legacy_artifacts(record: Mapping[str, Any]) -> list[Any]:
    for key in _LEGACY_ARTIFACT_KEYS:
        value = record.get(key)
        if isinstance(value, list) and value:
            return value
    return []


def infer_legacy_status(record: Mapping[str, Any]) -> str:
    """Infer a status for old snapshot/job rows without an explicit status.

    Explicit terminal states remain authoritative.  Error markers win over
    output-shaped fields so a failed job with partial images is not presented
    as completed.  The remaining evidence is intentionally conservative:
    outputs imply completion, identifiers without outputs imply queued, and
    everything else remains unknown.
    """

    if not isinstance(record, Mapping):
        return "unknown"
    explicit = _legacy_status_value(record)
    if explicit in _TERMINAL_STATUSES:
        return explicit
    if _legacy_has_error(record):
        return "error"
    if _legacy_has_outputs(record):
        return "completed"
    if explicit in {"queued", "running"}:
        return explicit
    if any(_has_legacy_value(record.get(key)) for key in _LEGACY_IDENTIFIER_KEYS):
        return "queued"
    return "unknown"


def _safe_text(value: Any, limit: int = 4096) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _safe_int(value: Any, fallback: int | None = None) -> int | None:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def sanitize_json_value(value: Any, depth: int = 0) -> Any:
    """Copy JSON-like data while removing credential-shaped keys.

    Snapshots are already allow-listed by the existing compiler.  The extra
    pass here protects the new database if an older caller supplies a raw
    request or a future field with a credential-looking key.
    """

    if depth > 8:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:MAX_SNAPSHOT_TEXT]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:512]:
            key = str(raw_key)[:256]
            lowered = key.casefold().replace("-", "_")
            if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
                continue
            cleaned = sanitize_json_value(raw_value, depth + 1)
            if cleaned is not None:
                result[key] = cleaned
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        result_list: list[Any] = []
        for item in list(value)[:512]:
            cleaned = sanitize_json_value(item, depth + 1)
            if cleaned is not None:
                result_list.append(cleaned)
        return result_list
    return None


def _json_text(value: Any) -> str:
    cleaned = sanitize_json_value(value)
    if cleaned is None:
        cleaned = {}
    text = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_SNAPSHOT_TEXT:
        return json.dumps({"truncated": True}, ensure_ascii=False)
    return text


def _json_value(text: Any) -> Any:
    try:
        value = json.loads(str(text or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, (dict, list)) else {}


def _safe_generation_id(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{32}", text):
        raise CreativeIndexError("generation_id 无效。")
    return text


def _new_id() -> str:
    return secrets.token_hex(16)


def _flag_value(value: Any) -> bool:
    """Coerce the review flags accepted from web, mobile and JSON stores."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().casefold() in {
        "1", "true", "yes", "on", "star", "favorite", "favourite", "入选", "最佳",
    }


def _note_text(value: Any, limit: int = 2000) -> str:
    return str(value or "").strip()[:limit]


def _row_flag(row: sqlite3.Row, name: str) -> bool:
    """Read a 0/1 column that may be absent from a not-yet-migrated row."""

    try:
        return bool(row[name])
    except (IndexError, KeyError):
        return False


def _row_int(row: sqlite3.Row, name: str) -> int:
    try:
        return int(row[name] or 0)
    except (IndexError, KeyError, TypeError, ValueError):
        return 0


def _row_text(row: sqlite3.Row, name: str, limit: int = 2000) -> str:
    try:
        return str(row[name] or "")[:limit]
    except (IndexError, KeyError):
        return ""


_STABLE_ID_NAMESPACE = "easy-panel:creative-index:stable-id:v1"


def _stable_id(namespace: str, value: Any) -> str:
    """Return a rebuildable, namespaced 128-bit hexadecimal identifier."""

    canonical = json.dumps(
        sanitize_json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    material = f"{_STABLE_ID_NAMESPACE}:{namespace}:{canonical}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:32]


def _stable_generation_id(
    snapshot: Mapping[str, Any],
    *,
    snapshot_id: str | None = None,
    prompt_id: str = "",
    request_id: str = "",
) -> str:
    """Derive a stable generation ID without using secrets or timestamps.

    Source identifiers are intentionally ordered from the strongest native
    identity to a sanitized complete-record fingerprint.  The explicit kind
    in the digest input prevents the same text used by two source systems from
    collapsing into one namespace.
    """

    for kind, value in (
        ("snapshot_id", snapshot_id),
        ("prompt_id", prompt_id),
        ("request_id", request_id),
    ):
        clean = _safe_text(value, 4096)
        if clean:
            return _stable_id("generation", {"kind": kind, "value": clean})
    return _stable_id("generation", {"kind": "record", "value": sanitize_json_value(snapshot)})


def _stable_artifact_id(generation_id: str, artifact: Mapping[str, Any]) -> str:
    """Derive an artifact ID from its owning generation and safe reference."""

    return _stable_id(
        "artifact",
        {
            "generation_id": generation_id,
            "filename": _safe_text(artifact.get("filename"), 512),
            "subfolder": _safe_text(artifact.get("subfolder"), 512),
            "type": _safe_text(artifact.get("image_type"), 32),
            "kind": _safe_text(artifact.get("artifact_kind"), 32),
        },
    )


def _stable_key(prefix: str, value: Any) -> str:
    canonical = json.dumps(sanitize_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:32]}"


def _normalise_subfolder(value: Any) -> str:
    raw = str(value or "").replace("\\", "/").strip("/")
    if not raw:
        return ""
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CreativeIndexError("artifact subfolder 无效。")
    return "/".join(path.parts)[:512]


def normalize_artifact_ref(raw: Any, output_root: Path | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Validate a ComfyUI image reference and optionally verify its file."""

    if isinstance(raw, Mapping):
        filename = str(raw.get("filename") or raw.get("name") or "").strip()
        subfolder = str(raw.get("subfolder") or "")
        image_type = str(raw.get("type") or raw.get("image_type") or "output").strip()
        kind = str(raw.get("artifact_kind") or raw.get("kind") or "output").strip().casefold()
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), Mapping) else {}
    else:
        filename = str(raw or "").strip()
        subfolder = ""
        image_type = "output"
        kind = "output"
        metadata = {}
    filename = filename.replace("\\", "/")
    if not filename or Path(filename).name != filename or filename in {".", ".."}:
        return None, "图片文件名包含路径或为空，已跳过。"
    if ".." in PurePosixPath(filename).parts:
        return None, "图片文件名包含路径穿越片段，已跳过。"
    try:
        subfolder = _normalise_subfolder(subfolder)
    except CreativeIndexError as exc:
        return None, str(exc)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", image_type):
        image_type = "output"
    if kind not in {"output", "intermediate"}:
        kind = "output"
    safe_metadata = sanitize_json_value(metadata)
    if not isinstance(safe_metadata, dict):
        safe_metadata = {}
    exists: bool | None = True
    if output_root is not None:
        root = Path(output_root).resolve()
        candidate = (root / Path(subfolder) / filename).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None, "图片路径超出输出目录，已跳过。"
        exists = candidate.is_file()
        if not exists:
            return {
                "filename": filename,
                "subfolder": subfolder,
                "image_type": image_type,
                "artifact_kind": kind,
                "metadata": {**safe_metadata, "exists": False},
            }, f"图片不存在，已保留记录：{filename}"
    safe_metadata["exists"] = exists
    return {
        "filename": filename,
        "subfolder": subfolder,
        "image_type": image_type,
        "artifact_kind": kind,
        "metadata": safe_metadata,
    }, None


def artifact_url(filename: str, subfolder: str = "", image_type: str = "output") -> str:
    query = {"name": filename, "type": image_type or "output"}
    if subfolder:
        query["subfolder"] = subfolder
    return "/api/rpg/image?" + urlencode(query)


class CreativeIndex:
    """Transactional SQLite index with safe legacy import helpers."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            current = _safe_int(row[0], 0) if row else 0
            if current is None:
                current = 0
            if current > SCHEMA_VERSION:
                raise CreativeIndexError(
                    f"创作索引版本 {current} 高于当前支持版本 {SCHEMA_VERSION}。"
                )
            # Version 0 was the pre-index state.  The CREATE IF NOT EXISTS
            # calls make an empty database upgradeable, while the column pass
            # below also repairs a partially-created v0 database without
            # rewriting any legacy JSON source file.
            self._create_schema_v1(connection)
            self._ensure_schema_v1_columns(connection)
            self._create_schema_v1_indexes(connection)
            connection.execute(
                # INSERT OR REPLACE works with the older SQLite builds that
                # ship in some desktop Python distributions as well as new
                # SQLite, and this tiny metadata table has no dependent FK.
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @staticmethod
    def _ensure_schema_v1_columns(connection: sqlite3.Connection) -> None:
        """Apply additive v1 migrations to a database made by an older build.

        SQLite cannot add a primary key or foreign-key constraint with ALTER
        TABLE.  Such a malformed legacy table is rejected explicitly; normal
        v0 databases (which had no index tables) are created by
        ``_create_schema_v1`` above.  All v1 fields that can be added safely
        are declared with defaults so an interrupted migration remains
        retryable.
        """

        expected: dict[str, dict[str, str]] = {
            "generations": {
                "snapshot_id": "TEXT",
                "prompt_id": "TEXT NOT NULL DEFAULT ''",
                "request_id": "TEXT NOT NULL DEFAULT ''",
                "operation": "TEXT NOT NULL DEFAULT 'unknown'",
                "status": "TEXT NOT NULL DEFAULT 'unknown'",
                "created_at": "INTEGER NOT NULL DEFAULT 0",
                "updated_at": "INTEGER NOT NULL DEFAULT 0",
                "schema_version": "INTEGER NOT NULL DEFAULT 0",
                "panel_version": "TEXT NOT NULL DEFAULT ''",
                "workflow_version": "TEXT NOT NULL DEFAULT ''",
                "inference_version": "TEXT NOT NULL DEFAULT ''",
                "model": "TEXT NOT NULL DEFAULT ''",
                "seed": "TEXT",
                "width": "INTEGER",
                "height": "INTEGER",
                "quality": "TEXT NOT NULL DEFAULT ''",
                "input_json": "TEXT NOT NULL DEFAULT '{}'",
                "compiled_json": "TEXT NOT NULL DEFAULT '{}'",
                "inference_json": "TEXT NOT NULL DEFAULT '{}'",
                "workflow_json": "TEXT NOT NULL DEFAULT '{}'",
                "snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "error_json": "TEXT NOT NULL DEFAULT '{}'",
                # Review fields are additive and default-valued, so an older
                # database keeps working and the migration stays retryable.
                "favorite": "INTEGER NOT NULL DEFAULT 0",
                "rating": "INTEGER NOT NULL DEFAULT 0",
                "note": "TEXT NOT NULL DEFAULT ''",
            },
            "artifacts": {
                "generation_id": "TEXT",
                "filename": "TEXT NOT NULL DEFAULT ''",
                "subfolder": "TEXT NOT NULL DEFAULT ''",
                "image_type": "TEXT NOT NULL DEFAULT 'output'",
                "artifact_kind": "TEXT NOT NULL DEFAULT 'output'",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
                "created_at": "INTEGER NOT NULL DEFAULT 0",
            },
            "derivations": {
                "parent_generation_id": "TEXT",
                "child_generation_id": "TEXT",
                "parent_artifact_id": "TEXT",
                "child_artifact_id": "TEXT",
                "operation": "TEXT NOT NULL DEFAULT 'unknown'",
                "created_at": "INTEGER NOT NULL DEFAULT 0",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            },
            "generation_loras": {
                "generation_id": "TEXT",
                "position": "INTEGER NOT NULL DEFAULT 0",
                "name": "TEXT NOT NULL DEFAULT ''",
                "weight": "TEXT",
                "trigger": "TEXT NOT NULL DEFAULT ''",
                "role": "TEXT NOT NULL DEFAULT 'other'",
                "source": "TEXT NOT NULL DEFAULT ''",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        }
        for table, columns in expected.items():
            actual = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not actual:
                continue
            if table == "generations" and "generation_id" not in actual:
                raise CreativeIndexError("旧创作索引缺少 generations.generation_id，无法安全迁移。")
            if table == "artifacts" and "artifact_id" not in actual:
                raise CreativeIndexError("旧创作索引缺少 artifacts.artifact_id，无法安全迁移。")
            if table == "derivations" and "derivation_id" not in actual:
                raise CreativeIndexError("旧创作索引缺少 derivations.derivation_id，无法安全迁移。")
            for name, declaration in columns.items():
                if name not in actual:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    @staticmethod
    def _create_schema_v1(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS generations (
                generation_id TEXT PRIMARY KEY,
                snapshot_id TEXT UNIQUE,
                prompt_id TEXT NOT NULL DEFAULT '',
                request_id TEXT NOT NULL DEFAULT '',
                operation TEXT NOT NULL DEFAULT 'unknown',
                status TEXT NOT NULL DEFAULT 'unknown',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 0,
                panel_version TEXT NOT NULL DEFAULT '',
                workflow_version TEXT NOT NULL DEFAULT '',
                inference_version TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                seed TEXT,
                width INTEGER,
                height INTEGER,
                quality TEXT NOT NULL DEFAULT '',
                input_json TEXT NOT NULL DEFAULT '{}',
                compiled_json TEXT NOT NULL DEFAULT '{}',
                inference_json TEXT NOT NULL DEFAULT '{}',
                workflow_json TEXT NOT NULL DEFAULT '{}',
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                error_json TEXT NOT NULL DEFAULT '{}',
                favorite INTEGER NOT NULL DEFAULT 0,
                rating INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                generation_id TEXT REFERENCES generations(generation_id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                subfolder TEXT NOT NULL DEFAULT '',
                image_type TEXT NOT NULL DEFAULT 'output',
                artifact_kind TEXT NOT NULL DEFAULT 'output',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                UNIQUE(generation_id, filename, subfolder, image_type, artifact_kind)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS derivations (
                derivation_id TEXT PRIMARY KEY,
                parent_generation_id TEXT REFERENCES generations(generation_id) ON DELETE CASCADE,
                child_generation_id TEXT REFERENCES generations(generation_id) ON DELETE CASCADE,
                parent_artifact_id TEXT REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
                child_artifact_id TEXT REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
                operation TEXT NOT NULL DEFAULT 'unknown',
                created_at INTEGER NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                CHECK(parent_generation_id IS NOT NULL OR parent_artifact_id IS NOT NULL),
                CHECK(child_generation_id IS NOT NULL OR child_artifact_id IS NOT NULL)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS generation_loras (
                generation_id TEXT NOT NULL REFERENCES generations(generation_id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                name TEXT NOT NULL,
                weight TEXT,
                trigger TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'other',
                source TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(generation_id, position)
            )
            """
        )

    @staticmethod
    def _create_schema_v1_indexes(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE INDEX IF NOT EXISTS idx_generations_created ON generations(created_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_generations_updated ON generations(updated_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_generations_prompt ON generations(prompt_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_generations_request ON generations(request_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_generation ON artifacts(generation_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_derivations_parent ON derivations(parent_generation_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_derivations_child ON derivations(child_generation_id)")

    @contextlib.contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            self._ensure_schema(connection)
            yield connection
        finally:
            connection.close()

    @contextlib.contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def initialize(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            return _safe_int(row[0], SCHEMA_VERSION) if row else SCHEMA_VERSION

    @staticmethod
    def _snapshot_parts(snapshot: Mapping[str, Any]) -> tuple[dict, dict, dict, dict, dict]:
        payload = snapshot.get("payload") if isinstance(snapshot.get("payload"), Mapping) else {}
        source = snapshot.get("source") if isinstance(snapshot.get("source"), Mapping) else {}
        compiled = snapshot.get("compiled") if isinstance(snapshot.get("compiled"), Mapping) else {}
        workflow = snapshot.get("workflow") if isinstance(snapshot.get("workflow"), Mapping) else {}
        environment = snapshot.get("environment") if isinstance(snapshot.get("environment"), Mapping) else {}
        return dict(payload), dict(source), dict(compiled), dict(workflow), dict(environment)

    @staticmethod
    def _snapshot_operation(snapshot: Mapping[str, Any], explicit: Any = "") -> str:
        explicit_raw = str(explicit or "").strip().casefold()
        chosen = normalize_operation(explicit, "unknown")
        if chosen != "unknown":
            return chosen
        if explicit_raw == "unknown" or (explicit_raw and explicit_raw not in {"panel.generate", "rpg.generate"}):
            return "unknown"
        workflow = snapshot.get("workflow") if isinstance(snapshot.get("workflow"), Mapping) else {}
        raw = str(workflow.get("operation") or snapshot.get("operation") or "").casefold()
        if "upscale" in raw:
            return "upscale"
        if "inpaint" in raw or "repair" in raw:
            return "inpaint"
        if "img2img" in raw:
            return "img2img"
        return "txt2img" if raw in {"", "panel.generate", "rpg.generate"} else "unknown"

    @classmethod
    def _snapshot_record_values(
        cls,
        snapshot: Mapping[str, Any],
        *,
        operation: Any = "",
        status: Any = "unknown",
        prompt_id: Any = "",
        request_id: Any = "",
    ) -> dict[str, Any]:
        payload, source, compiled, workflow, environment = cls._snapshot_parts(snapshot)
        source_generation = source.get("generation") if isinstance(source.get("generation"), Mapping) else {}
        payload_generation = payload.get("generation") if isinstance(payload.get("generation"), Mapping) else {}
        generation = {**dict(payload_generation), **dict(source_generation)}
        client = payload.get("client") if isinstance(payload.get("client"), Mapping) else {}
        snapshot_id = _safe_text(snapshot.get("id") or snapshot.get("snapshot_id"), 128) or None
        prompt = _safe_text(prompt_id or snapshot.get("promptId") or snapshot.get("prompt_id"), 128)
        request = _safe_text(request_id or snapshot.get("requestId") or snapshot.get("request_id"), 128)
        if not request:
            request = _safe_text(client.get("requestId") or client.get("request_id"), 128)
        model = _safe_text(source.get("checkpoint") or payload.get("model") or generation.get("model"), 800)
        seed = generation.get("seed") if generation.get("seed") is not None else payload.get("seed")
        if seed is not None:
            seed = _safe_text(seed, 128)
        width = _safe_int(generation.get("width") or payload.get("width"))
        height = _safe_int(generation.get("height") or payload.get("height"))
        quality = _safe_text(generation.get("quality") or payload.get("quality"), 80)
        created = _safe_int(snapshot.get("createdAt") or snapshot.get("created_at"), now_ms()) or now_ms()
        schema_version = _safe_int(snapshot.get("schemaVersion") or snapshot.get("schema_version"), 0) or 0
        panel_version = _safe_text(environment.get("panelVersion") or snapshot.get("panelVersion"), 80)
        workflow_version = _safe_text(
            workflow.get("version") or workflow.get("workflowVersion") or panel_version,
            80,
        )
        inference_version = _safe_text(
            environment.get("inferenceVersion") or environment.get("panelVersion") or panel_version,
            80,
        )
        inference = {
            "generation": generation,
            "environment": environment,
            "modelStrategy": source.get("modelStrategy", {}),
        }
        return {
            "snapshot_id": snapshot_id,
            "prompt_id": prompt,
            "request_id": request,
            "operation": cls._snapshot_operation(snapshot, operation),
            "status": normalize_status(status, "unknown"),
            "created_at": created,
            "schema_version": schema_version,
            "panel_version": panel_version,
            "workflow_version": workflow_version,
            "inference_version": inference_version,
            "model": model,
            "seed": seed,
            "width": width,
            "height": height,
            "quality": quality,
            "input_json": _json_text(payload or source),
            "compiled_json": _json_text(compiled),
            "inference_json": _json_text(inference),
            "workflow_json": _json_text(workflow),
            "snapshot_json": _json_text(snapshot),
            "error_json": _json_text(snapshot.get("error") or {}),
        }

    @staticmethod
    def _extract_loras(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
        payload, source, _compiled, _workflow, _environment = CreativeIndex._snapshot_parts(snapshot)
        raw = source.get("loras")
        if not isinstance(raw, list) or not raw:
            raw = payload.get("loras")
        if not isinstance(raw, list) or not raw:
            raw = list(payload.get("characterLoras") or []) + list(payload.get("styleLoras") or [])
        result: list[dict[str, Any]] = []
        for item in raw[:128]:
            if isinstance(item, str):
                item = {"name": item}
            if not isinstance(item, Mapping):
                continue
            name = _safe_text(item.get("name"), 800)
            if not name:
                continue
            role = _safe_text(item.get("role"), 40).casefold() or "other"
            if role not in {"character", "style", "other"}:
                role = "other"
            weight = item.get("weight")
            if weight is not None:
                weight = _safe_text(weight, 80)
            result.append({
                "name": name,
                "weight": weight,
                "trigger": _safe_text(item.get("trigger"), 2400),
                "role": role,
                "source": _safe_text(item.get("source") or item.get("sourceKind"), 80),
                "metadata": sanitize_json_value(item),
            })
        return result

    @staticmethod
    def _snapshot_artifacts(snapshot: Mapping[str, Any]) -> list[Any]:
        return _legacy_artifacts(snapshot)

    @staticmethod
    def _find_existing(
        connection: sqlite3.Connection,
        snapshot_id: str | None,
        prompt_id: str,
        request_id: str,
    ) -> sqlite3.Row | None:
        if snapshot_id:
            row = connection.execute(
                "SELECT * FROM generations WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
            if row:
                return row
        if prompt_id:
            row = connection.execute(
                "SELECT * FROM generations WHERE prompt_id = ? ORDER BY updated_at DESC LIMIT 1",
                (prompt_id,),
            ).fetchone()
            if row:
                return row
        if request_id:
            return connection.execute(
                "SELECT * FROM generations WHERE request_id = ? ORDER BY updated_at DESC LIMIT 1",
                (request_id,),
            ).fetchone()
        return None

    def _upsert_artifacts(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
        outputs: Sequence[Any],
        output_root: Path | None,
        *,
        warnings: list[str],
    ) -> list[str]:
        artifact_ids: list[str] = []
        for raw in list(outputs)[:128]:
            ref, warning = normalize_artifact_ref(raw, output_root)
            if warning:
                warnings.append(warning)
            if not ref:
                continue
            metadata_json = _json_text(ref["metadata"])
            existing = connection.execute(
                """SELECT artifact_id FROM artifacts
                   WHERE generation_id = ? AND filename = ? AND subfolder = ?
                     AND image_type = ? AND artifact_kind = ?""",
                (
                    generation_id,
                    ref["filename"],
                    ref["subfolder"],
                    ref["image_type"],
                    ref["artifact_kind"],
                ),
            ).fetchone()
            if existing:
                artifact_id = str(existing[0])
                connection.execute(
                    "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
                    (metadata_json, artifact_id),
                )
            else:
                artifact_id = _stable_artifact_id(generation_id, ref)
                collision = connection.execute(
                    """SELECT generation_id, filename, subfolder, image_type, artifact_kind
                       FROM artifacts WHERE artifact_id = ?""",
                    (artifact_id,),
                ).fetchone()
                if collision:
                    identity = (generation_id, ref["filename"], ref["subfolder"], ref["image_type"], ref["artifact_kind"])
                    existing_identity = tuple(collision[column] for column in (
                        "generation_id", "filename", "subfolder", "image_type", "artifact_kind",
                    ))
                    if existing_identity != identity:
                        raise CreativeIndexError("artifact_id 稳定哈希冲突，已拒绝写入。")
                connection.execute(
                    """INSERT INTO artifacts(
                           artifact_id, generation_id, filename, subfolder, image_type,
                           artifact_kind, metadata_json, created_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        artifact_id,
                        generation_id,
                        ref["filename"],
                        ref["subfolder"],
                        ref["image_type"],
                        ref["artifact_kind"],
                        metadata_json,
                        now_ms(),
                    ),
                )
            artifact_ids.append(artifact_id)
        return artifact_ids

    @staticmethod
    def _insert_derivation(
        connection: sqlite3.Connection,
        *,
        parent_generation_id: str = "",
        child_generation_id: str = "",
        parent_artifact_id: str = "",
        child_artifact_id: str = "",
        operation: Any = "unknown",
        metadata: Any = None,
    ) -> bool:
        parent_generation_id = str(parent_generation_id or "")
        child_generation_id = str(child_generation_id or "")
        parent_artifact_id = str(parent_artifact_id or "")
        child_artifact_id = str(child_artifact_id or "")
        if not (parent_generation_id or parent_artifact_id) or not (child_generation_id or child_artifact_id):
            return False
        if parent_generation_id and not connection.execute(
            "SELECT 1 FROM generations WHERE generation_id = ?", (parent_generation_id,)
        ).fetchone():
            return False
        if child_generation_id and not connection.execute(
            "SELECT 1 FROM generations WHERE generation_id = ?", (child_generation_id,)
        ).fetchone():
            return False
        if parent_artifact_id and not connection.execute(
            "SELECT 1 FROM artifacts WHERE artifact_id = ?", (parent_artifact_id,)
        ).fetchone():
            return False
        if child_artifact_id and not connection.execute(
            "SELECT 1 FROM artifacts WHERE artifact_id = ?", (child_artifact_id,)
        ).fetchone():
            return False
        op = normalize_operation(operation)
        existing = connection.execute(
            """SELECT derivation_id FROM derivations
               WHERE COALESCE(parent_generation_id, '') = ?
                 AND COALESCE(child_generation_id, '') = ?
                 AND COALESCE(parent_artifact_id, '') = ?
                 AND COALESCE(child_artifact_id, '') = ?
                 AND operation = ? LIMIT 1""",
            (parent_generation_id, child_generation_id, parent_artifact_id, child_artifact_id, op),
        ).fetchone()
        if existing:
            return False
        connection.execute(
            """INSERT INTO derivations(
                   derivation_id, parent_generation_id, child_generation_id,
                   parent_artifact_id, child_artifact_id, operation, created_at, metadata_json
               ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _new_id(),
                parent_generation_id or None,
                child_generation_id or None,
                parent_artifact_id or None,
                child_artifact_id or None,
                op,
                now_ms(),
                _json_text(metadata or {}),
            ),
        )
        return True

    def add_derivation(
        self,
        *,
        parent_generation_id: Any = "",
        child_generation_id: Any = "",
        parent_artifact_id: Any = "",
        child_artifact_id: Any = "",
        operation: Any = "unknown",
        metadata: Any = None,
    ) -> bool:
        """Add one lineage edge, or return False when either side is unknown.

        This is intentionally a narrow index-only operation.  It never edits
        the source snapshot/job JSON and is idempotent for the same endpoints
        and operation.
        """

        with self._write_transaction() as connection:
            return self._insert_derivation(
                connection,
                parent_generation_id=_safe_text(parent_generation_id, 128),
                child_generation_id=_safe_text(child_generation_id, 128),
                parent_artifact_id=_safe_text(parent_artifact_id, 128),
                child_artifact_id=_safe_text(child_artifact_id, 128),
                operation=operation,
                metadata=metadata,
            )

    def upsert_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        operation: Any = "",
        status: Any = "queued",
        prompt_id: Any = "",
        request_id: Any = "",
        output_root: str | Path | None = None,
        parent_generation_id: Any = "",
        parent_artifact_id: Any = "",
    ) -> dict[str, Any]:
        if not isinstance(snapshot, Mapping):
            raise CreativeIndexError("snapshot 必须是 JSON 对象。")
        values = self._snapshot_record_values(
            snapshot,
            operation=operation,
            status=status,
            prompt_id=prompt_id,
            request_id=request_id,
        )
        output_path = Path(output_root).expanduser() if output_root is not None else None
        warnings: list[str] = []
        with self._write_transaction() as connection:
            existing = self._find_existing(
                connection,
                values["snapshot_id"],
                values["prompt_id"],
                values["request_id"],
            )
            created = existing is None
            generation_id = str(existing["generation_id"]) if existing else _stable_generation_id(
                snapshot,
                snapshot_id=values["snapshot_id"],
                prompt_id=values["prompt_id"],
                request_id=values["request_id"],
            )
            merged_status = _merged_status(existing["status"], values["status"]) if existing else values["status"]
            created_at = int(existing["created_at"]) if existing else values["created_at"]
            row_values = {**values, "status": merged_status, "created_at": created_at, "updated_at": now_ms()}
            columns = (
                "generation_id", "snapshot_id", "prompt_id", "request_id", "operation", "status",
                "created_at", "updated_at", "schema_version", "panel_version", "workflow_version",
                "inference_version", "model", "seed", "width", "height", "quality", "input_json",
                "compiled_json", "inference_json", "workflow_json", "snapshot_json", "error_json",
            )
            if created:
                connection.execute(
                    f"INSERT INTO generations({', '.join(columns)}) VALUES({', '.join('?' for _ in columns)})",
                    tuple(generation_id if column == "generation_id" else row_values[column] for column in columns),
                )
            else:
                assignments = ", ".join(f"{column} = ?" for column in columns if column != "generation_id")
                connection.execute(
                    f"UPDATE generations SET {assignments} WHERE generation_id = ?",
                    tuple(row_values[column] for column in columns if column != "generation_id") + (generation_id,),
                )
            connection.execute("DELETE FROM generation_loras WHERE generation_id = ?", (generation_id,))
            for position, lora in enumerate(self._extract_loras(snapshot)):
                connection.execute(
                    """INSERT INTO generation_loras(
                           generation_id, position, name, weight, trigger, role, source, metadata_json
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        generation_id,
                        position,
                        lora["name"],
                        lora["weight"],
                        lora["trigger"],
                        lora["role"],
                        lora["source"],
                        _json_text(lora["metadata"]),
                    ),
                )
            artifact_ids = self._upsert_artifacts(
                connection,
                generation_id,
                self._snapshot_artifacts(snapshot),
                output_path,
                warnings=warnings,
            )
            parent_generation = _safe_text(parent_generation_id, 64)
            parent_artifact = _safe_text(parent_artifact_id, 64)
            if not parent_generation and isinstance(snapshot.get("derivation"), Mapping):
                derivation = snapshot["derivation"]
                parent_generation = _safe_text(derivation.get("parentGenerationId") or derivation.get("parent_generation_id"), 64)
                parent_artifact = _safe_text(derivation.get("parentArtifactId") or derivation.get("parent_artifact_id"), 64)
            if parent_generation or parent_artifact:
                self._insert_derivation(
                    connection,
                    parent_generation_id=parent_generation,
                    child_generation_id=generation_id,
                    parent_artifact_id=parent_artifact,
                    child_artifact_id=artifact_ids[0] if artifact_ids else "",
                    operation=row_values["operation"],
                    metadata={"source": "snapshot"},
                )
            row = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?", (generation_id,)
            ).fetchone()
            return {
                "generation_id": generation_id,
                "created": created,
                "warnings": warnings,
                "generation": self._summary_from_row(connection, row),
            }

    def update_snapshot_status(
        self,
        snapshot_id: Any,
        *,
        status: Any,
        images: Sequence[Any] = (),
        output_root: str | Path | None = None,
    ) -> dict[str, Any] | None:
        wanted = _safe_text(snapshot_id, 128)
        if not wanted:
            return None
        output_path = Path(output_root).expanduser() if output_root is not None else None
        warnings: list[str] = []
        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM generations WHERE snapshot_id = ?", (wanted,)
            ).fetchone()
            if not row:
                return None
            next_status = _merged_status(row["status"], status)
            connection.execute(
                "UPDATE generations SET status = ?, updated_at = ? WHERE generation_id = ?",
                (next_status, now_ms(), row["generation_id"]),
            )
            self._upsert_artifacts(
                connection,
                str(row["generation_id"]),
                list(images),
                output_path,
                warnings=warnings,
            )
            latest = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?", (row["generation_id"],)
            ).fetchone()
            return {
                "generation_id": str(row["generation_id"]),
                "warnings": warnings,
                "generation": self._summary_from_row(connection, latest),
            }

    def update_job(
        self,
        *,
        prompt_id: Any = "",
        request_id: Any = "",
        snapshot_id: Any = "",
        status: Any = "unknown",
        images: Sequence[Any] = (),
        output_root: str | Path | None = None,
    ) -> dict[str, Any] | None:
        wanted_snapshot = _safe_text(snapshot_id, 128)
        wanted_prompt = _safe_text(prompt_id, 128)
        wanted_request = _safe_text(request_id, 128)
        output_path = Path(output_root).expanduser() if output_root is not None else None
        warnings: list[str] = []
        with self._write_transaction() as connection:
            row = self._find_existing(connection, wanted_snapshot or None, wanted_prompt, wanted_request)
            if not row:
                return None
            next_status = _merged_status(row["status"], status)
            connection.execute(
                """UPDATE generations
                   SET prompt_id = CASE WHEN ? <> '' THEN ? ELSE prompt_id END,
                       request_id = CASE WHEN ? <> '' THEN ? ELSE request_id END,
                       status = ?, updated_at = ?
                   WHERE generation_id = ?""",
                (
                    wanted_prompt,
                    wanted_prompt,
                    wanted_request,
                    wanted_request,
                    next_status,
                    now_ms(),
                    row["generation_id"],
                ),
            )
            self._upsert_artifacts(
                connection,
                str(row["generation_id"]),
                list(images),
                output_path,
                warnings=warnings,
            )
            latest = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?", (row["generation_id"],)
            ).fetchone()
            return {
                "generation_id": str(row["generation_id"]),
                "warnings": warnings,
                "generation": self._summary_from_row(connection, latest),
            }

    def list_unfinished_jobs(self, *, limit: Any = 1000) -> list[dict[str, Any]]:
        """Return indexed jobs that still need ComfyUI status reconciliation.

        The creative index is intentionally a query-oriented projection.  A
        server-side reconciler needs only stable identifiers, not the full
        snapshot payload, so keep this result narrow and cheap to read.
        """

        page_limit = max(1, min(1000, _safe_int(limit, 1000) or 1000))
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT generation_id, snapshot_id, prompt_id, request_id, status,
                          created_at, updated_at
                   FROM generations
                   WHERE status IN ('queued', 'running') AND prompt_id <> ''
                   ORDER BY updated_at ASC, generation_id ASC
                   LIMIT ?""",
                (page_limit,),
            ).fetchall()
        return [
            {
                "generation_id": str(row["generation_id"]),
                "snapshot_id": str(row["snapshot_id"] or ""),
                "prompt_id": str(row["prompt_id"] or ""),
                "request_id": str(row["request_id"] or ""),
                "status": normalize_status(row["status"]),
                "created_at": int(row["created_at"] or 0),
                "updated_at": int(row["updated_at"] or 0),
            }
            for row in rows
        ]

    @staticmethod
    def _summary_from_row(connection: sqlite3.Connection, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {}
        generation_id = str(row["generation_id"])
        artifact_count = connection.execute(
            "SELECT COUNT(*) FROM artifacts WHERE generation_id = ?", (generation_id,)
        ).fetchone()[0]
        parent_count = connection.execute(
            "SELECT COUNT(*) FROM derivations WHERE child_generation_id = ?", (generation_id,)
        ).fetchone()[0]
        child_count = connection.execute(
            "SELECT COUNT(*) FROM derivations WHERE parent_generation_id = ?", (generation_id,)
        ).fetchone()[0]
        lora_count = connection.execute(
            "SELECT COUNT(*) FROM generation_loras WHERE generation_id = ?", (generation_id,)
        ).fetchone()[0]
        thumbnail_url = None
        # Prefer the first output whose file still exists so a deleted leading
        # image does not leave the record without a usable thumbnail.  The
        # "exists" flag is refreshed by prune_missing_outputs before listing.
        thumbnails = connection.execute(
            """SELECT filename, subfolder, image_type, metadata_json FROM artifacts
               WHERE generation_id = ? ORDER BY created_at ASC, artifact_id ASC""",
            (generation_id,),
        ).fetchall()
        for thumbnail in thumbnails:
            metadata = _json_value(thumbnail["metadata_json"])
            if isinstance(metadata, Mapping) and metadata.get("exists") is False:
                continue
            thumbnail_url = artifact_url(
                str(thumbnail["filename"]),
                str(thumbnail["subfolder"]),
                str(thumbnail["image_type"]),
            )
            break
        return {
            "generation_id": generation_id,
            "snapshot_id": row["snapshot_id"] or None,
            "prompt_id": row["prompt_id"] or None,
            "request_id": row["request_id"] or None,
            "operation": normalize_operation(row["operation"]),
            "status": normalize_status(row["status"]),
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
            "schema_version": int(row["schema_version"]),
            "panel_version": row["panel_version"] or "",
            "workflow_version": row["workflow_version"] or "",
            "inference_version": row["inference_version"] or "",
            "model": row["model"] or "",
            "seed": row["seed"],
            "width": row["width"],
            "height": row["height"],
            "quality": row["quality"] or "",
            "favorite": _row_flag(row, "favorite"),
            "rating": _row_int(row, "rating"),
            "note": _row_text(row, "note"),
            "lora_count": int(lora_count),
            "artifact_count": int(artifact_count),
            "parent_count": int(parent_count),
            "child_count": int(child_count),
            "thumbnail_url": thumbnail_url,
        }

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> dict[str, Any]:
        metadata = _json_value(row["metadata_json"])
        if not isinstance(metadata, dict):
            metadata = {}
        exists = metadata.get("exists")
        return {
            "artifact_id": str(row["artifact_id"]),
            "generation_id": row["generation_id"],
            "filename": str(row["filename"]),
            "subfolder": str(row["subfolder"] or ""),
            "type": str(row["image_type"] or "output"),
            "kind": str(row["artifact_kind"] or "output"),
            "exists": exists,
            "metadata": metadata,
            "url": artifact_url(str(row["filename"]), str(row["subfolder"] or ""), str(row["image_type"] or "output"))
            if exists is not False else None,
            "created_at": int(row["created_at"]),
        }

    def _loras_for_generation(self, connection: sqlite3.Connection, generation_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM generation_loras WHERE generation_id = ? ORDER BY position ASC",
            (generation_id,),
        ).fetchall()
        return [
            {
                "position": int(row["position"]),
                "name": row["name"],
                "weight": row["weight"],
                "trigger": row["trigger"],
                "role": row["role"],
                "source": row["source"],
                "metadata": _json_value(row["metadata_json"]),
            }
            for row in rows
        ]

    def get_generation(self, generation_id: Any) -> dict[str, Any] | None:
        wanted = _safe_generation_id(generation_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?", (wanted,)
            ).fetchone()
            if not row:
                return None
            summary = self._summary_from_row(connection, row)
            artifacts = connection.execute(
                "SELECT * FROM artifacts WHERE generation_id = ? ORDER BY created_at ASC, artifact_id ASC",
                (wanted,),
            ).fetchall()
            snapshot = _json_value(row["snapshot_json"])
            input_value = _json_value(row["input_json"])
            compiled = _json_value(row["compiled_json"])
            inference = _json_value(row["inference_json"])
            workflow = _json_value(row["workflow_json"])
            return {
                **summary,
                "input": input_value,
                "compiled": compiled,
                "inference": inference,
                "workflow": workflow,
                "snapshot": snapshot,
                "error": _json_value(row["error_json"]),
                "loras": self._loras_for_generation(connection, wanted),
                "artifacts": [self._artifact_from_row(item) for item in artifacts],
                "replay": {
                    "can_submit": False,
                    "action": "restore_to_form",
                    "payload": input_value,
                    "operation": normalize_operation(row["operation"]),
                    "seed": row["seed"],
                    "note": "仅恢复到现有编辑/生成表单；必须由用户显式点击生成。",
                },
                "variation": {
                    "can_submit": False,
                    "action": "restore_to_form",
                    "payload": input_value,
                    "operation": normalize_operation(row["operation"]),
                    "seed": None,
                    "note": "变化版只预览恢复参数；换 Seed 后仍必须由用户显式点击生成。",
                },
            }

    def prune_missing_outputs(self, output_root: Any, *, limit: int = 400) -> dict[str, int]:
        """Delete generations whose recorded output images no longer exist on disk.

        Works in place over a bounded number of terminal generations that already
        have at least one recorded output artifact.  For every scanned generation
        each output artifact is re-checked against ``output_root``; artifact
        ``metadata.exists`` is refreshed to the current on-disk state.  A
        generation is only deleted when none of its output files survive, which
        removes its artifacts, derivations and LoRA rows through ON DELETE
        CASCADE.  Queued/running rows (which usually have no artifacts yet) are
        never touched.  Returns counts of scanned/pruned/refreshed items.
        """

        root = Path(str(output_root)).resolve()
        scan_limit = max(1, min(4000, int(limit)))
        pruned: list[str] = []
        scanned = 0
        refreshed = 0
        with self._write_transaction() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT g.generation_id
                FROM generations g
                JOIN artifacts a ON a.generation_id = g.generation_id
                WHERE g.status IN ('completed', 'error', 'cancelled', 'unknown')
                  AND a.image_type = 'output'
                ORDER BY g.updated_at DESC, g.generation_id ASC
                LIMIT ?
                """,
                (scan_limit,),
            ).fetchall()
            for row in rows:
                scanned += 1
                generation_id = str(row["generation_id"])
                artifacts = connection.execute(
                    """SELECT artifact_id, filename, subfolder, image_type, metadata_json
                       FROM artifacts
                       WHERE generation_id = ? AND image_type = 'output'
                       ORDER BY created_at ASC, artifact_id ASC""",
                    (generation_id,),
                ).fetchall()
                exists_any = False
                for artifact in artifacts:
                    filename = str(artifact["filename"] or "")
                    subfolder = str(artifact["subfolder"] or "").replace("\\", "/").strip("/")
                    candidate = (root / Path(subfolder) / Path(filename).name).resolve()
                    try:
                        candidate.relative_to(root)
                    except ValueError:
                        candidate = root
                    exists = candidate.is_file()
                    exists_any = exists_any or exists
                    metadata = _json_value(artifact["metadata_json"])
                    if not isinstance(metadata, Mapping):
                        metadata = {}
                    else:
                        metadata = dict(metadata)
                    if bool(metadata.get("exists")) != exists:
                        metadata["exists"] = exists
                        connection.execute(
                            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
                            (json.dumps(metadata, ensure_ascii=False), artifact["artifact_id"]),
                        )
                        refreshed += 1
                if not exists_any:
                    pruned.append(generation_id)
            for generation_id in pruned:
                connection.execute("DELETE FROM generations WHERE generation_id = ?", (generation_id,))
        return {
            "scanned_generations": scanned,
            "pruned_generations": len(pruned),
            "refreshed_artifacts": refreshed,
        }

    def delete_generation(self, generation_id: Any, output_root: Any = None) -> dict[str, Any] | None:
        """Delete one generation record together with its recorded output files.

        Returns ``None`` when the generation does not exist.  Only
        ``image_type == 'output'`` artifacts are unlinked on disk, and only
        when ``output_root`` is provided.  Every candidate path is resolved and
        must stay inside ``output_root``; anything that escapes the root is
        skipped (never followed).  The database row plus its artifacts,
        derivations and LoRA rows are removed through ON DELETE CASCADE in a
        second write transaction.  File deletion is best-effort: a file that is
        already missing is reported in ``missing_files``, never raised.
        """
        wanted = _safe_generation_id(generation_id)
        root = Path(str(output_root)).resolve() if output_root else None
        targets: list[tuple[str, str, str, str]] = []
        with self._connection() as connection:
            row = connection.execute(
                "SELECT generation_id FROM generations WHERE generation_id = ?", (wanted,)
            ).fetchone()
            if row is None:
                return None
            artifacts = connection.execute(
                "SELECT artifact_id, filename, subfolder, image_type FROM artifacts "
                "WHERE generation_id = ?",
                (wanted,),
            ).fetchall()
            for artifact in artifacts:
                targets.append((
                    str(artifact["artifact_id"]),
                    str(artifact["image_type"] or "output"),
                    str(artifact["filename"] or ""),
                    str(artifact["subfolder"] or "").replace("\\", "/").strip("/"),
                ))
        removed_files: list[str] = []
        missing_files: list[str] = []
        if root is not None:
            for _artifact_id, image_type, filename, subfolder in targets:
                if image_type != "output" or not filename:
                    continue
                if filename in (".", ".."):
                    continue
                candidate = (root / Path(subfolder) / Path(filename).name).resolve()
                try:
                    candidate.relative_to(root)
                except ValueError:
                    # Path traversal outside the output root is never followed.
                    continue
                try:
                    candidate.unlink()
                    removed_files.append(filename)
                except FileNotFoundError:
                    missing_files.append(filename)
                except OSError:
                    pass
        with self._write_transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM generations WHERE generation_id = ?", (wanted,)
            )
            deleted_rows = max(0, cursor.rowcount)
        return {
            "deleted_generation": wanted,
            "deleted": deleted_rows > 0,
            "removed_files": removed_files,
            "missing_files": missing_files,
            "artifact_count": len(targets),
        }

    def set_generation_flags(
        self,
        generation_id: Any,
        *,
        favorite: Any = None,
        rating: Any = None,
        note: Any = None,
    ) -> dict[str, Any] | None:
        """Save the human review state (入选 / 评分 / 备注) of one generation.

        These fields never change the recipe: the snapshot payload stays the
        same, so 收藏 marks a version instead of creating a new one.
        """

        wanted = _safe_generation_id(generation_id)
        assignments: list[str] = []
        params: list[Any] = []
        if favorite is not None:
            assignments.append("favorite = ?")
            params.append(1 if _flag_value(favorite) else 0)
        if rating is not None:
            assignments.append("rating = ?")
            params.append(max(0, min(5, _safe_int(rating, 0) or 0)))
        if note is not None:
            assignments.append("note = ?")
            params.append(_note_text(note))
        if not assignments:
            raise CreativeIndexError("没有需要保存的收藏字段。")
        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?", (wanted,)
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                f"UPDATE generations SET {', '.join(assignments)} WHERE generation_id = ?",
                tuple(params) + (wanted,),
            )
            updated = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?", (wanted,)
            ).fetchone()
            return self._summary_from_row(connection, updated) if updated else None

    def list_generations(
        self,
        *,
        limit: Any = 20,
        offset: Any = 0,
        operation: Any = "",
        status: Any = "",
        model: Any = "",
        favorite: Any = None,
        sort: Any = "created_at",
        order: Any = "desc",
    ) -> dict[str, Any]:
        page_limit = max(1, min(MAX_PAGE_SIZE, _safe_int(limit, 20) or 20))
        page_offset = max(0, min(MAX_OFFSET, _safe_int(offset, 0) or 0))
        op = str(operation or "").strip().casefold()
        op = normalize_operation(op) if op else ""
        state = str(status or "").strip().casefold()
        state = normalize_status(state) if state else ""
        model_filter = _safe_text(model, 800)
        sort_sql = SORT_FIELDS.get(str(sort or "created_at").strip().casefold(), SORT_FIELDS["created_at"])
        direction = "ASC" if str(order or "").strip().casefold() == "asc" else "DESC"
        where: list[str] = []
        params: list[Any] = []
        if op:
            where.append("g.operation = ?")
            params.append(op)
        if state:
            where.append("g.status = ?")
            params.append(state)
        favorite_filter = str(favorite or "").strip().casefold()
        if favorite_filter in {"1", "true", "yes", "favorite", "favourite", "star", "入选"}:
            where.append("g.favorite = 1")
        elif favorite_filter in {"0", "false", "no", "unfavorite", "unfavourite", "未入选"}:
            where.append("g.favorite = 0")
        if model_filter:
            where.append("LOWER(g.model) LIKE LOWER(?)")
            params.append(f"%{model_filter}%")
        if _flag_value(favorite):
            where.append("g.favorite = 1")
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        with self._connection() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM generations g{where_sql}", tuple(params)).fetchone()[0])
            rows = connection.execute(
                f"SELECT g.* FROM generations g{where_sql} ORDER BY {sort_sql} {direction}, g.generation_id ASC LIMIT ? OFFSET ?",
                tuple(params) + (page_limit, page_offset),
            ).fetchall()
            items = [self._summary_from_row(connection, row) for row in rows]
            return {
                "items": items,
                "total": total,
                "limit": page_limit,
                "offset": page_offset,
                "has_more": page_offset + len(items) < total,
                "schema_version": SCHEMA_VERSION,
            }

    def _lineage_walk(
        self,
        connection: sqlite3.Connection,
        start: str,
        direction: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        queue: list[tuple[str, int]] = [(start, 0)]
        visited = {start}
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        while queue and len(nodes) < MAX_LINEAGE_NODES:
            current, depth = queue.pop(0)
            if direction == "parents":
                rows = connection.execute(
                    "SELECT * FROM derivations WHERE child_generation_id = ? ORDER BY created_at ASC",
                    (current,),
                ).fetchall()
                related_key = "parent_generation_id"
                edge_parent = "parent_generation_id"
                edge_child = "child_generation_id"
            else:
                rows = connection.execute(
                    "SELECT * FROM derivations WHERE parent_generation_id = ? ORDER BY created_at ASC",
                    (current,),
                ).fetchall()
                related_key = "child_generation_id"
                edge_parent = "parent_generation_id"
                edge_child = "child_generation_id"
            for row in rows:
                related = str(row[related_key] or "")
                edges.append({
                    "derivation_id": str(row["derivation_id"]),
                    "parent_generation_id": row[edge_parent],
                    "child_generation_id": row[edge_child],
                    "parent_artifact_id": row["parent_artifact_id"],
                    "child_artifact_id": row["child_artifact_id"],
                    "operation": normalize_operation(row["operation"]),
                    "created_at": int(row["created_at"]),
                    "metadata": _json_value(row["metadata_json"]),
                })
                if not related or related in visited:
                    continue
                visited.add(related)
                related_row = connection.execute(
                    "SELECT * FROM generations WHERE generation_id = ?", (related,)
                ).fetchone()
                if not related_row:
                    continue
                nodes.append({"depth": depth + 1, **self._summary_from_row(connection, related_row)})
                if depth < MAX_LINEAGE_NODES:
                    queue.append((related, depth + 1))
                if len(nodes) >= MAX_LINEAGE_NODES:
                    break
        return nodes, edges

    def get_lineage(self, generation_id: Any) -> dict[str, Any] | None:
        wanted = _safe_generation_id(generation_id)
        with self._connection() as connection:
            root = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?", (wanted,)
            ).fetchone()
            if not root:
                return None
            ancestors, parent_edges = self._lineage_walk(connection, wanted, "parents")
            descendants, child_edges = self._lineage_walk(connection, wanted, "children")
            return {
                "generation_id": wanted,
                "ancestors": ancestors,
                "descendants": descendants,
                "edges": parent_edges + [edge for edge in child_edges if edge not in parent_edges],
                "schema_version": SCHEMA_VERSION,
            }

    def import_legacy_files(
        self,
        snapshots_source: str | Path | Sequence[Any] | None,
        jobs_source: str | Path | Sequence[Any] | None,
        *,
        output_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Import old JSON rows without rewriting either source file."""

        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "warnings": [],
            "errors": [],
        }

        def load_source(source: Any, label: str) -> list[Any]:
            if source is None:
                return []
            if isinstance(source, (str, Path)):
                try:
                    parsed = json.loads(Path(source).read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    report["errors"].append(f"{label} 文件无法读取：{type(exc).__name__}")
                    return []
            else:
                parsed = source
            if not isinstance(parsed, list):
                report["errors"].append(f"{label} 必须是 JSON 数组，已跳过整份文件。")
                return []
            return parsed

        snapshots = load_source(snapshots_source, "generation_snapshots.json")
        jobs = load_source(jobs_source, "rpg_jobs.json")
        for index, item in enumerate(snapshots):
            if not isinstance(item, Mapping):
                report["skipped"] += 1
                report["warnings"].append(f"snapshot[{index}] 不是对象，已跳过。")
                continue
            try:
                result = self.upsert_snapshot(
                    item,
                    operation=self._snapshot_operation(item),
                    status=infer_legacy_status(item),
                    output_root=output_root,
                )
                report["inserted" if result["created"] else "updated"] += 1
                report["warnings"].extend(result.get("warnings") or [])
            except Exception as exc:
                report["skipped"] += 1
                report["errors"].append(f"snapshot[{index}] 导入失败：{type(exc).__name__}")

        for index, item in enumerate(jobs):
            if not isinstance(item, Mapping):
                report["skipped"] += 1
                report["warnings"].append(f"job[{index}] 不是对象，已跳过。")
                continue
            prompt_id = _safe_text(item.get("prompt_id") or item.get("promptId"), 128)
            request_id = _safe_text(item.get("request_id") or item.get("requestId"), 128)
            snapshot_id = _safe_text(item.get("snapshot_id") or item.get("snapshotId"), 128)
            legacy_status = infer_legacy_status(item)
            legacy_artifacts = _legacy_artifacts(item)
            if snapshot_id or prompt_id or request_id:
                updated = self.update_job(
                    prompt_id=prompt_id,
                    request_id=request_id,
                    snapshot_id=snapshot_id,
                    status=legacy_status,
                    images=legacy_artifacts,
                    output_root=output_root,
                )
                if updated:
                    report["updated"] += 1
                    report["warnings"].extend(updated.get("warnings") or [])
                    continue
            try:
                synthetic_id = snapshot_id or _stable_key("legacy-job", item)
                client = item.get("client") if isinstance(item.get("client"), Mapping) else {}
                loras = list(item.get("character_loras") or []) + list(item.get("style_loras") or [])
                synthetic = {
                    "id": synthetic_id,
                    "createdAt": _safe_int(item.get("created_at") or item.get("createdAt"), now_ms()),
                    "schemaVersion": 0,
                    "promptId": prompt_id,
                    "payload": {
                        "client": sanitize_json_value(client),
                        "model": _safe_text(item.get("model"), 800),
                        "loras": sanitize_json_value(loras),
                    },
                    "source": {
                        "checkpoint": _safe_text(item.get("model"), 800),
                        "loras": sanitize_json_value(loras),
                    },
                    "workflow": {"kind": "legacy-job", "operation": "legacy.job"},
                    "outputs": legacy_artifacts,
                }
                result = self.upsert_snapshot(
                    synthetic,
                    operation="txt2img",
                    status=legacy_status,
                    request_id=request_id,
                    output_root=output_root,
                )
                report["inserted" if result["created"] else "updated"] += 1
                report["warnings"].extend(result.get("warnings") or [])
            except Exception as exc:
                report["skipped"] += 1
                report["errors"].append(f"job[{index}] 导入失败：{type(exc).__name__}")
        report["warnings"] = report["warnings"][:200]
        report["errors"] = report["errors"][:200]
        return report


__all__ = [
    "CreativeIndex",
    "CreativeIndexError",
    "KNOWN_STATUSES",
    "MAX_LINEAGE_NODES",
    "MAX_OFFSET",
    "MAX_PAGE_SIZE",
    "SCHEMA_VERSION",
    "SUPPORTED_OPERATIONS",
    "artifact_url",
    "infer_legacy_status",
    "normalize_artifact_ref",
    "normalize_operation",
    "normalize_status",
    "sanitize_json_value",
]
