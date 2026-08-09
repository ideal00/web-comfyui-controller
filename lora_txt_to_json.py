"""Smartly classify same-name LoRA TXT files and merge them into lora_notes.json."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from easy_panel_app.config import LORA_DIR, LORA_NOTES, ROOT
from easy_panel_app.lora_sidecars import (
    NOTE_FIELDS,
    atomic_write_notes,
    backup_notes,
    load_notes,
    merge_note,
    read_text_smart,
    smart_parse_lora_sidecar,
)


def discover_sidecars(inputs: list[str], lora_dir: Path) -> list[Path]:
    roots = [Path(item).expanduser() for item in inputs] if inputs else [lora_dir]
    found: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.casefold() == ".txt":
            found.append(root.resolve())
        elif root.is_file() and root.suffix.casefold() in {".safetensors", ".pt", ".ckpt"}:
            text_file = root.with_suffix(".txt")
            if text_file.is_file():
                found.append(text_file.resolve())
        elif root.is_dir():
            found.extend(path.resolve() for path in root.rglob("*.txt") if path.is_file())
        else:
            print(f"[跳过] 路径不存在：{root}")
    return sorted(set(found), key=lambda path: str(path).casefold())


def companion_lora(text_file: Path) -> Path | None:
    for suffix in (".safetensors", ".pt", ".ckpt"):
        candidate = text_file.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def note_key(notes: dict, lora: Path, lora_dir: Path, duplicate_names: set[str]) -> str:
    try:
        relative = lora.resolve().relative_to(lora_dir).as_posix()
    except ValueError:
        relative = lora.name
    if relative in notes:
        return relative
    if lora.name.casefold() in duplicate_names:
        return relative
    if lora.name in notes:
        return lora.name
    return lora.name


def write_report(report: dict) -> Path:
    report_dir = ROOT / "backup"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = report_dir / f"lora-smart-import-report-{stamp}.json"
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="识别同名 TXT 中的人物、外貌、服装、姿势、构图、场景、光线、画风及其他标签并保存 JSON。",
    )
    parser.add_argument("paths", nargs="*", help="可拖入 TXT、LoRA 或文件夹；省略则扫描整个 LoRA 目录")
    parser.add_argument("--lora-dir", type=Path, default=LORA_DIR, help="LoRA 根目录")
    parser.add_argument("--notes", type=Path, default=LORA_NOTES, help="目标 lora_notes.json")
    parser.add_argument("--dry-run", action="store_true", help="只识别并显示统计，不写 JSON")
    parser.add_argument("--yes", action="store_true", help="无需交互确认")
    parser.add_argument("--replace", action="store_true", help="用 TXT 识别结果替换同名预设；默认只补空字段")
    args = parser.parse_args(argv)

    lora_dir = args.lora_dir.expanduser().resolve()
    notes_path = args.notes.expanduser().resolve()
    notes = load_notes(notes_path)
    sidecars = discover_sidecars(args.paths, lora_dir)
    valid_pairs: list[tuple[Path, Path]] = []
    skipped_without_lora: list[str] = []
    for text_file in sidecars:
        lora = companion_lora(text_file)
        if lora:
            valid_pairs.append((text_file, lora))
        else:
            skipped_without_lora.append(str(text_file))

    name_counts = Counter(lora.name.casefold() for _, lora in valid_pairs)
    duplicate_names = {name for name, count in name_counts.items() if count > 1}
    working = json.loads(json.dumps(notes, ensure_ascii=False))
    category_counts = Counter()
    parsed_files = 0
    changed_notes = 0
    empty_files: list[str] = []
    errors: list[dict] = []
    details: list[dict] = []

    for text_file, lora in valid_pairs:
        try:
            content = read_text_smart(text_file)
            try:
                source_label = text_file.relative_to(lora_dir).as_posix()
            except ValueError:
                source_label = str(text_file)
            parsed = smart_parse_lora_sidecar(content, source_label)
            has_useful = bool(parsed.get("outfits") or parsed.get("trigger") or
                              parsed.get("base_model") or parsed.get("weight"))
            if not has_useful:
                empty_files.append(str(text_file))
                continue
            key = note_key(working, lora, lora_dir, duplicate_names)
            existing_note = working.get(key)
            if not isinstance(existing_note, dict) and key != lora.name:
                # When upgrading old basename-only notes, give each duplicate
                # relative-path entry the same safe starting data rather than
                # silently hiding the user's manual fields.
                existing_note = working.get(lora.name, {})
            merged, changed = merge_note(existing_note or {}, parsed, replace=args.replace)
            working[key] = merged
            parsed_files += 1
            changed_notes += int(changed)
            for outfit in parsed.get("outfits", []):
                for field in NOTE_FIELDS:
                    if outfit.get(field):
                        category_counts[field] += 1
            details.append({
                "txt": str(text_file),
                "lora": str(lora),
                "note_key": key,
                "changed": changed,
                "title": parsed.get("title", ""),
                "base_model": parsed.get("base_model", ""),
                "weight": parsed.get("weight", ""),
                "trigger": parsed.get("trigger", ""),
                "presets": len(parsed.get("outfits", [])),
                "outfits": parsed.get("outfits", []),
                "unclassified": parsed.get("unclassified", []),
                "stats": parsed.get("stats", {}),
            })
        except Exception as exc:
            errors.append({"txt": str(text_file), "error": str(exc)})

    print("=" * 72)
    print("Easy Panel｜LoRA TXT 智能分区 JSON 导入器 v2")
    print(f"LoRA 根目录：{lora_dir}")
    print(f"目标 JSON：{notes_path}")
    print(f"找到 TXT：{len(sidecars)}；有同名 LoRA：{len(valid_pairs)}")
    print(f"成功识别：{parsed_files}；会改变 JSON 条目：{changed_notes}")
    print(f"无有效内容：{len(empty_files)}；无同名 LoRA：{len(skipped_without_lora)}；错误：{len(errors)}")
    for path in empty_files[:20]:
        print("  [空内容]", path)
    for path in skipped_without_lora[:20]:
        print("  [无同名 LoRA]", path)
    for item in errors[:20]:
        print("  [错误]", item["txt"], "-", item["error"])
    print("分区预设计数：")
    for field in NOTE_FIELDS:
        print(f"  {field:12} {category_counts[field]}")
    print("默认合并策略：保留手写非空字段，只自动补空字段和新增预设。")
    if args.replace:
        print("警告：已选择 --replace，同名预设将以 TXT 识别结果为准。")

    if args.dry_run:
        print("DRY-RUN：未备份、未写入 lora_notes.json。")
        return 1 if errors else 0
    if not changed_notes:
        print("没有需要写入的变化。")
        return 1 if errors else 0
    if not args.yes:
        answer = input("输入 YES 备份旧 JSON 并写入（其他输入取消）：").strip()
        if answer != "YES":
            print("已取消，未写入任何 JSON。")
            return 0

    backup = backup_notes(notes_path)
    atomic_write_notes(notes_path, working)
    report = {
        "schema_version": 2,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "lora_dir": str(lora_dir),
        "notes": str(notes_path),
        "backup": str(backup or ""),
        "replace": args.replace,
        "summary": {
            "txt": len(sidecars), "paired": len(valid_pairs), "parsed": parsed_files,
            "changed": changed_notes, "empty": len(empty_files),
            "without_lora": len(skipped_without_lora), "errors": len(errors),
            "categories": dict(category_counts),
        },
        "files": details,
        "errors": errors,
    }
    report_path = write_report(report)
    print("=" * 72)
    print("JSON 已安全写入：", notes_path)
    print("旧 JSON 备份：", backup or "（原文件不存在）")
    print("详细识别报告：", report_path)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
