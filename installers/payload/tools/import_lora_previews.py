"""Attach verified test outputs to installed LoRAs without changing prompt memos."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from easy_panel_app import preset_examples
from easy_panel_app.lora_sidecars import atomic_write_notes


def sha256(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def verify_image(path: Path, entry: dict, manifest: dict) -> None:
    with Image.open(path) as image:
        graph = json.loads(image.info.get('prompt', '{}'))
        names = [str(node.get('inputs', {}).get('lora_name', '')).replace('\\', '/')
                 for node in graph.values() if node.get('class_type') == 'LoraLoader']
        if names != [entry['lora_name'].replace('\\', '/')]:
            raise ValueError(f'Image LoRA differs from submission: {path.name}')
        loader = next(node['inputs'] for node in graph.values() if node.get('class_type') == 'LoraLoader')
        sampler = next(node['inputs'] for node in graph.values() if node.get('class_type') == 'KSampler')
        if (image.size != (manifest['width'], manifest['height'])
                or loader['strength_model'] != manifest['weight']
                or loader['strength_clip'] != manifest['weight']
                or sampler['seed'] != manifest['seed']
                or sampler['steps'] != manifest['steps']):
            raise ValueError(f'Image parameters differ from test: {path.name}')


def import_previews(manifest_path: Path, outputs: Path, model_root: Path, notes_path: Path, report_path: Path) -> dict:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    notes = json.loads(notes_path.read_text(encoding='utf-8-sig')) if notes_path.exists() else {}
    models = {}
    for model in model_root.rglob('*.safetensors'):
        if 'Anima_Soft_Illustration' in model.parts:
            models.setdefault(sha256(model), []).append(model)
    report = {'bound': [], 'missing_images': [], 'missing_models': []}
    original_notes = notes_path.read_bytes() if notes_path.exists() else None
    for entry in manifest['entries']:
        prefix = entry['filename_prefix'].rsplit('/', 1)[-1]
        images = sorted(outputs.glob(prefix + '_*.png'))
        if not images:
            report['missing_images'].append(entry['file'])
            continue
        if len(images) != 1:
            raise ValueError(f'Ambiguous test images for {entry["file"]}: {len(images)}')
        image = images[0]
        verify_image(image, entry, manifest)
        matching = models.get(entry['sha256'], [])
        if not matching:
            report['missing_models'].append({'model': entry['file'], 'image': image.name})
            continue
        result = preset_examples.save_example(image.read_bytes())
        for model in matching:
            key = model.relative_to(model_root).as_posix()
            note_key = key if key in notes else model.name if model.name in notes else key
            note = notes.setdefault(note_key, {'title': model.stem, 'base_model': 'Anima', 'weight': '', 'trigger': '', 'url': '', 'outfits': []})
            reference = {'imageId': result['exampleImage'], 'modelSha256': entry['sha256'],
                         'weight': manifest['weight'], 'width': manifest['width'], 'height': manifest['height'],
                         'steps': manifest['steps'], 'seed': manifest['seed'], 'source': '本机统一画风测试'}
            note['referenceImage'] = reference
            preview = model.with_suffix('.preview.png')
            if preview.exists() and sha256(preview) != sha256(image):
                backup = preview.with_suffix('.png.before-style-test')
                if backup.exists():
                    raise ValueError(f'Preview backup already exists: {backup}')
                shutil.copy2(preview, backup)
            if not preview.exists() or sha256(preview) != sha256(image):
                shutil.copy2(image, preview)
            report['bound'].append({'model': key, 'image': image.name, 'preview': str(preview),
                                    'imageId': result['exampleImage'], 'sha256': entry['sha256']})
    if original_notes is not None:
        backup = report_path.with_name('lora_notes.before-preview-import.json')
        if not backup.exists():
            backup.write_bytes(original_notes)
    atomic_write_notes(notes_path, notes)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--outputs', required=True, type=Path)
    parser.add_argument('--model-root', required=True, type=Path)
    parser.add_argument('--notes', type=Path, default=Path(__file__).resolve().parents[1] / 'lora_notes.json')
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    result = import_previews(args.manifest, args.outputs, args.model_root, args.notes, args.report)
    print(json.dumps({key: len(items) for key, items in result.items()}, ensure_ascii=False))
