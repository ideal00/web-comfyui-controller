"""Rebuild the query-only creative index from legacy JSON files.

The two JSON files are read as source data and are never rewritten or deleted.
Use explicit paths when rebuilding a copy or a test fixture; the defaults are
the normal Easy Panel project paths.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from easy_panel_app.config import CREATIVE_INDEX_FILE, ROOT, OUTPUT
from easy_panel_app.creative_index import CreativeIndex


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rebuild the Easy Panel creative SQLite index.")
    parser.add_argument(
        "--db",
        type=Path,
        default=CREATIVE_INDEX_FILE,
        help="SQLite index path (default: %(default)s)",
    )
    parser.add_argument(
        "--snapshots",
        type=Path,
        default=ROOT / "generation_snapshots.json",
        help="generation_snapshots.json path (default: %(default)s)",
    )
    parser.add_argument(
        "--jobs",
        type=Path,
        default=ROOT / "rpg_jobs.json",
        help="rpg_jobs.json path (default: %(default)s)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT,
        help="ComfyUI output directory used to mark missing but safe image artifacts (default: %(default)s)",
    )
    parser.add_argument(
        "--scan-output",
        action="store_true",
        help="额外扫描输出目录，把没有记录的成品图按 PNG 内嵌元数据补进索引（快照 JSON 之前的老作品）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="扫描时最多处理多少个文件（0 表示不限）",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    index = CreativeIndex(args.db)
    report = index.import_legacy_files(
        args.snapshots,
        args.jobs,
        output_root=args.output_root,
    )
    if args.scan_output:
        report["output_scan"] = index.import_output_images(args.output_root, limit=args.limit)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report.get("errors") else 2


if __name__ == "__main__":
    raise SystemExit(main())
