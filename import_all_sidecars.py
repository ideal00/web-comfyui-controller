import sys
sys.path.insert(0, r"g:\ComfyUI\ComfyUI_Easy_Panel")
import easy_panel as ep
from pathlib import Path

LORA_DIR = ep.LORA_DIR
notes = ep.load_lora_notes()
imported = 0
meta_only = 0
total_outfits = 0
skipped_no_model = []
skipped_empty = []

for tf in sorted(LORA_DIR.rglob("*.txt")):
    companion = tf.with_suffix(".safetensors")
    if not companion.is_file():
        skipped_no_model.append(str(tf.relative_to(LORA_DIR)))
        continue
    target = companion.name
    try:
        content = tf.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        continue
    parsed = ep.parse_lora_sidecar(content, tf.name)
    has_meta = any(parsed.get(k) for k in ("base_model", "weight", "trigger"))
    if not parsed["outfits"] and not has_meta:
        skipped_empty.append(str(tf.relative_to(LORA_DIR)))
        continue
    note = notes.get(target, {})
    if not isinstance(note, dict):
        note = {}
    for key in ("base_model", "weight", "trigger"):
        if not str(note.get(key, "")).strip() and parsed.get(key):
            note[key] = parsed[key]
    added = 0
    if parsed["outfits"]:
        existing = [o for o in (note.get("outfits") or []) if isinstance(o, dict)]
        existing_names = {str(o.get("name", "")).strip() for o in existing}
        for outfit in parsed["outfits"]:
            name = str(outfit.get("name", "")).strip()
            if not name:
                continue
            if name in existing_names:
                existing = [o for o in existing if str(o.get("name", "")).strip() != name]
            existing.append(outfit)
            added += 1
        note["outfits"] = existing
    notes[target] = note
    imported += 1
    if added:
        total_outfits += added
    else:
        meta_only += 1

ep.save_lora_notes(notes)
print("=" * 40)
print("导入 LoRA 数:", imported, "(其中仅元信息:", meta_only, ")")
print("新增/更新预设总数:", total_outfits)
print("lora_notes.json 总条数:", len(notes))
print("无对应 safetensors 的 TXT:", len(skipped_no_model))
for s in skipped_no_model[:25]:
    print("  跳过(无模型):", s)
print("完全空结果的 TXT:", len(skipped_empty))
for s in skipped_empty[:25]:
    print("  跳过(空):", s)
