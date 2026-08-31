"""Plan, apply, or roll back a Creative Library ID migration.

The default mode is read-only.  It computes deterministic generation and
artifact IDs from an existing v1 SQLite index, emits the complete old-to-new
mapping, and refuses to apply when references or identity conflicts are found.
Applying is deliberately explicit because the normal Easy Panel process must
be stopped before the database file is replaced.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from easy_panel_app.config import CREATIVE_INDEX_FILE  # noqa: E402
from easy_panel_app.creative_index import (  # noqa: E402
    SCHEMA_VERSION,
    _stable_artifact_id,
    _stable_generation_id,
    normalize_artifact_ref,
    sanitize_json_value,
)


TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "schema_meta": ("key", "value"),
    "generations": (
        "generation_id", "snapshot_id", "prompt_id", "request_id", "operation", "status",
        "created_at", "updated_at", "schema_version", "panel_version", "workflow_version",
        "inference_version", "model", "seed", "width", "height", "quality", "input_json",
        "compiled_json", "inference_json", "workflow_json", "snapshot_json", "error_json",
    ),
    "artifacts": (
        "artifact_id", "generation_id", "filename", "subfolder", "image_type",
        "artifact_kind", "metadata_json", "created_at",
    ),
    "derivations": (
        "derivation_id", "parent_generation_id", "child_generation_id", "parent_artifact_id",
        "child_artifact_id", "operation", "created_at", "metadata_json",
    ),
    "generation_loras": (
        "generation_id", "position", "name", "weight", "trigger", "role", "source",
        "metadata_json",
    ),
}

REQUIRED_TABLES = frozenset(TABLE_COLUMNS)


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _parse_snapshot(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _fallback_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build a safe fingerprint source for a malformed old snapshot JSON."""

    return {
        "legacy_index_record": sanitize_json_value({
            key: row.get(key)
            for key in (
                "snapshot_id", "prompt_id", "request_id", "operation", "status", "created_at",
                "updated_at", "schema_version", "panel_version", "workflow_version",
                "inference_version", "model", "seed", "width", "height", "quality",
                "input_json", "compiled_json", "inference_json", "workflow_json", "snapshot_json",
                "error_json",
            )
        }),
    }


def _connect(path: Path, *, read_only: bool = True) -> sqlite3.Connection:
    path = path.resolve()
    if read_only:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _sidecar_paths(path: Path) -> list[Path]:
    return [Path(str(path) + suffix) for suffix in ("-wal", "-shm") if Path(str(path) + suffix).exists()]


def _read_tables(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    names = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    missing = sorted(REQUIRED_TABLES - names)
    if missing:
        raise ValueError(f"创作索引缺少必要表：{', '.join(missing)}")
    tables: dict[str, list[dict[str, Any]]] = {}
    for table, columns in TABLE_COLUMNS.items():
        actual = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
        missing_columns = sorted(set(columns) - actual)
        if missing_columns:
            raise ValueError(f"创作索引表 {table} 缺少字段：{', '.join(missing_columns)}")
        selected = ", ".join(columns)
        tables[table] = [
            _row_dict(row)
            for row in connection.execute(f"SELECT {selected} FROM {table}")
        ]
    return tables


def _conflict(conflicts: list[dict[str, Any]], kind: str, message: str, **details: Any) -> None:
    conflicts.append({"kind": kind, "message": message, **details})


def build_migration_plan(path: str | Path) -> dict[str, Any]:
    """Read an index without writing it and return a migration plan."""

    database = Path(path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(f"找不到 SQLite 创作索引：{database}")
    sidecars = _sidecar_paths(database)
    conflicts: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    with _connect(database) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_errors = [
            list(row) for row in connection.execute("PRAGMA foreign_key_check")
        ]
        if integrity != "ok":
            _conflict(conflicts, "integrity", "SQLite integrity_check 未通过。", result=integrity)
        if foreign_key_errors:
            _conflict(
                conflicts,
                "foreign_key",
                "源数据库存在外键错误。",
                rows=foreign_key_errors[:100],
            )
        try:
            tables = _read_tables(connection)
        except ValueError as exc:
            _conflict(conflicts, "schema", str(exc))
            tables = {table: [] for table in TABLE_COLUMNS}

    generation_mapping: dict[str, str] = {}
    generation_reverse: dict[str, list[str]] = {}
    generation_rows = tables["generations"]
    for row in generation_rows:
        old_id = str(row.get("generation_id") or "")
        snapshot = _parse_snapshot(row.get("snapshot_json")) or _fallback_snapshot(row)
        new_id = _stable_generation_id(
            snapshot,
            snapshot_id=str(row.get("snapshot_id") or "") or None,
            prompt_id=str(row.get("prompt_id") or ""),
            request_id=str(row.get("request_id") or ""),
        )
        generation_mapping[old_id] = new_id
        generation_reverse.setdefault(new_id, []).append(old_id)
    for new_id, old_ids in generation_reverse.items():
        if len(old_ids) > 1:
            _conflict(
                conflicts,
                "generation_id_collision",
                "多个旧作品映射到同一个稳定 generation_id。",
                new_id=new_id,
                old_ids=old_ids,
            )

    artifact_mapping: dict[str, str] = {}
    artifact_reverse: dict[str, list[str]] = {}
    artifact_rows = tables["artifacts"]
    for row in artifact_rows:
        old_id = str(row.get("artifact_id") or "")
        old_generation = row.get("generation_id")
        new_generation = generation_mapping.get(str(old_generation)) if old_generation is not None else None
        raw_ref = {
            "filename": row.get("filename"),
            "subfolder": row.get("subfolder"),
            "type": row.get("image_type"),
            "kind": row.get("artifact_kind"),
        }
        safe_ref, warning = normalize_artifact_ref(raw_ref)
        if not safe_ref:
            _conflict(
                conflicts,
                "unsafe_artifact",
                warning or "artifact 引用不安全。",
                artifact_id=old_id,
            )
            continue
        canonical = (
            str(row.get("filename") or ""),
            str(row.get("subfolder") or ""),
            str(row.get("image_type") or "output"),
            str(row.get("artifact_kind") or "output"),
        )
        normalized = (
            safe_ref["filename"], safe_ref["subfolder"], safe_ref["image_type"], safe_ref["artifact_kind"],
        )
        if canonical != normalized:
            _conflict(
                conflicts,
                "noncanonical_artifact",
                "artifact 引用不是当前安全规范化形式。",
                artifact_id=old_id,
                source=canonical,
                normalized=normalized,
            )
            continue
        if new_generation is None:
            _conflict(
                conflicts,
                "orphan_artifact",
                "artifact 没有关联有效 generation，无法生成确定的稳定 ID。",
                artifact_id=old_id,
                generation_id=old_generation,
            )
            continue
        new_id = _stable_artifact_id(new_generation, safe_ref)
        artifact_mapping[old_id] = new_id
        artifact_reverse.setdefault(new_id, []).append(old_id)
        if warning:
            warnings.append({"kind": "artifact", "artifact_id": old_id, "message": warning})
    for new_id, old_ids in artifact_reverse.items():
        if len(old_ids) > 1:
            _conflict(
                conflicts,
                "artifact_id_collision",
                "多个旧输出映射到同一个稳定 artifact_id。",
                new_id=new_id,
                old_ids=old_ids,
            )

    generation_ids = set(generation_mapping)
    artifact_ids = set(artifact_mapping)
    for row in tables["derivations"]:
        for field, known in (
            ("parent_generation_id", generation_ids),
            ("child_generation_id", generation_ids),
            ("parent_artifact_id", artifact_ids),
            ("child_artifact_id", artifact_ids),
        ):
            value = row.get(field)
            if value is not None and str(value) not in known:
                _conflict(
                    conflicts,
                    "derivation_reference",
                    "derivation 引用的旧 ID 没有可用映射。",
                    derivation_id=row.get("derivation_id"),
                    field=field,
                    value=value,
                )
    for row in tables["generation_loras"]:
        value = row.get("generation_id")
        if value is not None and str(value) not in generation_ids:
            _conflict(
                conflicts,
                "lora_reference",
                "generation_loras 引用的旧 generation_id 没有可用映射。",
                generation_id=value,
            )

    plan = {
        "database": str(database),
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "sidecars": [str(item) for item in sidecars],
        "counts": {table: len(rows) for table, rows in tables.items()},
        "generation_mapping": [
            {"old": old_id, "new": generation_mapping[old_id]}
            for old_id in sorted(generation_mapping)
        ],
        "artifact_mapping": [
            {"old": old_id, "new": artifact_mapping[old_id]}
            for old_id in sorted(artifact_mapping)
        ],
        "warnings": warnings[:200],
        "conflicts": conflicts[:200],
        "safe_to_apply": not conflicts and not sidecars,
        "tables": tables,
        "generation_map": generation_mapping,
        "artifact_map": artifact_mapping,
    }
    return plan


def _insert_rows(connection: sqlite3.Connection, table: str, rows: Iterable[Mapping[str, Any]]) -> None:
    columns = TABLE_COLUMNS[table]
    placeholders = ", ".join("?" for _ in columns)
    names = ", ".join(columns)
    values = [tuple(row.get(column) for column in columns) for row in rows]
    if values:
        connection.executemany(f"INSERT INTO {table}({names}) VALUES({placeholders})", values)


def _make_temp_path(database: Path) -> Path:
    handle, raw = tempfile.mkstemp(
        prefix=f".{database.name}.creative-migration-",
        suffix=".sqlite3",
        dir=str(database.parent),
    )
    os.close(handle)
    return Path(raw)


def _backup_database(database: Path, backup: Path) -> None:
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        raise FileExistsError(f"备份目标已存在，为避免覆盖未执行迁移：{backup}")
    with _connect(database) as source:
        target = sqlite3.connect(str(backup))
        try:
            source.backup(target)
        finally:
            target.close()


def _validate_database(database: Path) -> None:
    with _connect(database) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise ValueError(f"迁移后 integrity_check 失败：{integrity}")
        foreign_key_errors = list(connection.execute("PRAGMA foreign_key_check"))
        if foreign_key_errors:
            raise ValueError(f"迁移后存在 {len(foreign_key_errors)} 条外键错误。")


def default_backup_path(database: Path, backup_dir: str | Path | None = None) -> Path:
    root = Path(backup_dir).expanduser() if backup_dir else database.parent / "creative-index-backups"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / f"{database.stem}-{stamp}.sqlite3"


def apply_migration(
    path: str | Path,
    *,
    backup_path: str | Path | None = None,
) -> dict[str, Any]:
    """Apply a previously validated plan with backup and atomic replacement."""

    database = Path(path).expanduser().resolve()
    plan = build_migration_plan(database)
    if not plan["safe_to_apply"]:
        raise ValueError("迁移计划存在冲突或 SQLite sidecar；请先处理 plan 中的 conflicts。")
    backup = Path(backup_path).expanduser().resolve() if backup_path else default_backup_path(database)
    if backup == database:
        raise ValueError("备份路径不能与数据库路径相同。")
    temp = _make_temp_path(database)
    replaced = False
    try:
        from easy_panel_app.creative_index import CreativeIndex

        CreativeIndex(temp).initialize()
        target = sqlite3.connect(str(temp))
        try:
            target.execute("PRAGMA foreign_keys = ON")
            tables = plan["tables"]
            generation_map = plan["generation_map"]
            artifact_map = plan["artifact_map"]
            schema_meta = tables["schema_meta"]
            target.execute("DELETE FROM schema_meta")
            _insert_rows(target, "schema_meta", schema_meta)

            generations = []
            for row in tables["generations"]:
                copied = dict(row)
                copied["generation_id"] = generation_map[str(row["generation_id"])]
                generations.append(copied)
            _insert_rows(target, "generations", generations)

            artifacts = []
            for row in tables["artifacts"]:
                copied = dict(row)
                copied["artifact_id"] = artifact_map[str(row["artifact_id"])]
                copied["generation_id"] = generation_map[str(row["generation_id"])]
                artifacts.append(copied)
            _insert_rows(target, "artifacts", artifacts)

            derivations = []
            for row in tables["derivations"]:
                copied = dict(row)
                for field in ("parent_generation_id", "child_generation_id"):
                    if copied[field] is not None:
                        copied[field] = generation_map[str(copied[field])]
                for field in ("parent_artifact_id", "child_artifact_id"):
                    if copied[field] is not None:
                        copied[field] = artifact_map[str(copied[field])]
                derivations.append(copied)
            _insert_rows(target, "derivations", derivations)

            loras = []
            for row in tables["generation_loras"]:
                copied = dict(row)
                copied["generation_id"] = generation_map[str(row["generation_id"])]
                loras.append(copied)
            _insert_rows(target, "generation_loras", loras)
            target.commit()
        finally:
            target.close()
        _validate_database(temp)

        _backup_database(database, backup)
        os.replace(str(temp), str(database))
        replaced = True
        try:
            _validate_database(database)
        except Exception:
            rollback_temp = _make_temp_path(database)
            try:
                shutil.copy2(backup, rollback_temp)
                os.replace(str(rollback_temp), str(database))
            finally:
                if rollback_temp.exists():
                    rollback_temp.unlink()
            raise
        return {
            "database": str(database),
            "mode": "apply",
            "backup": str(backup),
            "safe_to_apply": True,
            "counts": plan["counts"],
            "generation_mapping": plan["generation_mapping"],
            "artifact_mapping": plan["artifact_mapping"],
        }
    finally:
        if temp.exists():
            temp.unlink()
        if replaced and backup.exists():
            # The backup is intentionally retained for manual rollback.
            pass


def rollback_database(path: str | Path, backup_path: str | Path) -> dict[str, Any]:
    """Atomically restore a previously retained SQLite backup."""

    database = Path(path).expanduser().resolve()
    backup = Path(backup_path).expanduser().resolve()
    if not backup.is_file():
        raise FileNotFoundError(f"找不到回滚备份：{backup}")
    _validate_database(backup)
    temp = _make_temp_path(database)
    try:
        shutil.copy2(backup, temp)
        os.replace(str(temp), str(database))
        _validate_database(database)
        return {"database": str(database), "mode": "rollback", "backup": str(backup)}
    finally:
        if temp.exists():
            temp.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查或迁移 Easy Panel Creative Library SQLite ID。")
    parser.add_argument("--db", type=Path, default=CREATIVE_INDEX_FILE, help="SQLite 索引路径")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="备份后原子迁移；默认只读")
    action.add_argument("--rollback", type=Path, metavar="BACKUP", help="从指定备份原子恢复")
    parser.add_argument("--backup", type=Path, help="--apply 使用的备份文件路径")
    parser.add_argument("--backup-dir", type=Path, help="--apply 自动备份目录")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.rollback:
            report = rollback_database(args.db, args.rollback)
        elif args.apply:
            backup = args.backup or default_backup_path(args.db.resolve(), args.backup_dir)
            report = apply_migration(args.db, backup_path=backup)
        else:
            report = build_migration_plan(args.db)
            report.pop("tables", None)
            report.pop("generation_map", None)
            report.pop("artifact_map", None)
            report["mode"] = "dry-run"
    except Exception as exc:
        print(json.dumps({"mode": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("mode") == "dry-run" and not report.get("safe_to_apply", False):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
