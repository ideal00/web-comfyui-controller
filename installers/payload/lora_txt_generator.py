"""Generate safe, structured same-name TXT files from LoRA safetensors metadata."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from easy_panel_app.config import LORA_DIR, ROOT
from easy_panel_app.lora_sidecars import (
    is_generated_sidecar,
    render_sidecar,
    sidecar_from_safetensors,
)


def discover_loras(inputs: list[str], lora_dir: Path) -> list[Path]:
    roots = [Path(item).expanduser() for item in inputs] if inputs else [lora_dir]
    found: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.casefold() == ".safetensors":
            found.append(root.resolve())
        elif root.is_dir():
            found.extend(path.resolve() for path in root.rglob("*.safetensors") if path.is_file())
        else:
            print(f"[跳过] 路径不存在或不是 LoRA：{root}")
    return sorted(set(found), key=lambda path: str(path).casefold())


def atomic_write_text(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def relative_label(path: Path, lora_dir: Path) -> str:
    try:
        return path.relative_to(lora_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="读取 LoRA safetensors 头部元数据，生成同名结构化 TXT；默认绝不覆盖已有 TXT。",
    )
    parser.add_argument("paths", nargs="*", help="可拖入一个或多个 LoRA / 文件夹；省略则扫描整个 LoRA 目录")
    parser.add_argument("--lora-dir", type=Path, default=LORA_DIR, help="LoRA 根目录")
    parser.add_argument("--dry-run", action="store_true", help="只分析，不写文件")
    parser.add_argument("--yes", action="store_true", help="无需交互确认")
    parser.add_argument("--overwrite-generated", action="store_true", help="只重建带 Easy Panel v2 标记的旧生成 TXT")
    parser.add_argument("--force", action="store_true", help="覆盖任意已有 TXT（会先备份；谨慎使用）")
    parser.add_argument("--max-tags", type=int, default=80, help="最多从训练元数据保留多少标签，默认 80")
    args = parser.parse_args(argv)

    lora_dir = args.lora_dir.expanduser().resolve()
    candidates = discover_loras(args.paths, lora_dir)
    selected: list[Path] = []
    skipped_existing = 0
    for lora in candidates:
        text_file = lora.with_suffix(".txt")
        if not text_file.exists():
            selected.append(lora)
        elif args.force or (args.overwrite_generated and is_generated_sidecar(text_file)):
            selected.append(lora)
        else:
            skipped_existing += 1

    print("=" * 68)
    print("Easy Panel｜LoRA 同名 TXT 生成器 v2")
    print(f"LoRA 根目录：{lora_dir}")
    print(f"扫描到 LoRA：{len(candidates)}")
    print(f"准备生成：{len(selected)}")
    print(f"保护并跳过已有 TXT：{skipped_existing}")
    print("规则：只读取 safetensors JSON 头，不加载模型权重，不联网。")
    if not selected:
        print("没有需要生成的文件。")
        return 0
    for path in selected[:20]:
        print("  -", relative_label(path, lora_dir))
    if len(selected) > 20:
        print(f"  ... 以及 {len(selected) - 20} 个")
    if args.dry_run:
        print("DRY-RUN：未写入任何文件。")
    elif not args.yes:
        answer = input("输入 YES 开始生成（其他输入取消）：").strip()
        if answer != "YES":
            print("已取消，未写入任何文件。")
            return 0

    backup_root: Path | None = None
    generated = 0
    errors: list[tuple[Path, str]] = []
    for lora in selected:
        try:
            document = sidecar_from_safetensors(lora, max_tags=max(10, min(300, args.max_tags)))
            content = render_sidecar(document, relative_label(lora, lora_dir))
            if args.dry_run:
                print(
                    f"[预览] {relative_label(lora, lora_dir)}｜底模 {document.get('base_model') or '未知'}｜"
                    f"触发词 {document.get('trigger') or '未识别'}｜训练标签 {document.get('training_tag_count', 0)}"
                )
                continue
            text_file = lora.with_suffix(".txt")
            if text_file.exists():
                if backup_root is None:
                    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                    backup_root = ROOT / "backup" / f"lora-txt-generator-{stamp}"
                try:
                    relative = text_file.resolve().relative_to(lora_dir)
                except ValueError:
                    relative = Path(text_file.name)
                backup_file = backup_root / relative
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(text_file, backup_file)
            atomic_write_text(text_file, content)
            generated += 1
            print("[已生成]", relative_label(text_file, lora_dir))
        except Exception as exc:
            errors.append((lora, str(exc)))
            print("[失败]", relative_label(lora, lora_dir), "-", exc)

    print("=" * 68)
    print(f"完成：生成 {generated}，失败 {len(errors)}。")
    if backup_root:
        print("被覆盖的旧 TXT 已备份到：", backup_root)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
