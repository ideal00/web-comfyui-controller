"""Check release versions, shipped assets, payload parity and ZIP checksums offline."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "installers" / "payload"


def panel_version() -> str:
    for node in ast.parse((ROOT / "easy_panel.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PANEL_VERSION" for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError("PANEL_VERSION missing")


def verify_document_links() -> None:
    """Keep public tutorials and screenshot links usable in a fresh checkout."""
    documents = [ROOT / "README.md", ROOT / "android-client/README.md"]
    documents.extend((ROOT / "docs").glob("*.md"))
    for document in documents:
        content = document.read_text(encoding="utf-8")
        links = re.findall(r'\]\(([^\s)]+)\)', content)
        links.extend(re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', content))
        for link in links:
            parsed = urlsplit(link)
            if parsed.scheme or not parsed.path or parsed.path.startswith("/"):
                continue
            target = (document.parent / unquote(parsed.path)).resolve()
            assert target.is_relative_to(ROOT), f"Document link outside repository: {document.name}: {link}"
            assert target.exists(), f"Missing document resource: {document.relative_to(ROOT)}: {link}"


def verify(tag: str = "", packages: bool = False) -> None:
    server = panel_version()
    mobile = json.loads((ROOT / "android-client/package.json").read_text(encoding="utf-8"))["version"]
    if tag and tag not in {f"v{server}", f"mobile-v{mobile}"}:
        raise ValueError(f"Tag {tag} differs from server v{server} / mobile-v{mobile}")
    verify_document_links()
    for name in ("README.md", "RPG_MOBILE_API.md", "android-client/README.md", "docs/QUICKSTART.md", "docs/FEATURE_MATRIX.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert server in text and mobile in text, f"Version missing in {name}"

    files = ["easy_panel.py", "index.html", "README.md", "CHANGELOG.md", "LORA_MEMO_RULES.md",
             "RPG_MOBILE_API.md", "RPG_MOBILE_CHANGELOG.md", "START_HERE_RPG_MOBILE.txt",
             "android-client/README.md", "android-client/android/app/src/main/res/drawable-nodpi/easy_panel_brand_source.png", "embedding_notes.json", "pose_editor_workflow.json",
             "lora_txt_generator.py", "lora_txt_to_json.py", "classify_tags.py", "import_all_sidecars.py", "requirements.txt", "requirements-image-tools.txt", "tools/import_lora_previews.py"]
    for directory in ("easy_panel_app", "web", "docs"):
        for path in (ROOT / directory).rglob("*"):
            relative = path.relative_to(ROOT)
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".lnk"} and relative.parts[:2] != ("docs", "images"):
                files.append(relative.as_posix())
    for name in files:
        assert (PAYLOAD / name).is_file(), f"Payload missing {name}"
        assert (ROOT / name).read_bytes() == (PAYLOAD / name).read_bytes(), f"Payload differs: {name}"
    for directory in ("easy_panel_app", "web", "docs"):
        expected = {name for name in files if name.startswith(directory + "/")}
        actual = {p.relative_to(PAYLOAD).as_posix() for p in (PAYLOAD / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
        assert expected == actual, f"Unexpected payload files in {directory}: {actual - expected}"
    for asset in re.findall(r'(?:src|href)="(/assets/[^"?]+)(?:\?[^" ]*)?"', (ROOT / "index.html").read_text(encoding="utf-8")):
        assert (ROOT / "web" / asset.lstrip("/")).is_file(), f"Missing frontend resource: {asset}"

    if packages:
        package_dir = ROOT / "installers/packages"
        checksum_rows = (package_dir / "SHA256SUMS.txt").read_text().splitlines()
        assert len(checksum_rows) == 7, "Expected seven installer ZIPs"
        private = {"lora_notes.json", "rpg_mobile_token.txt", "easy_panel_shared_state.json", "generation_snapshots.json", "rpg_jobs.json", "task_queue.json", "creative_index.sqlite3"}
        for row in checksum_rows:
            digest, name = row.split(None, 1)
            path = package_dir / name.strip()
            assert path.parent == package_dir and path.suffix == ".zip", "Invalid checksum filename"
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest.lower(), f"Checksum mismatch: {path.name}"
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    parts = Path(name.replace("\\", "/")).parts
                    assert not (set(parts) & private), f"Private data in {path.name}: {name}"
                    assert "__pycache__" not in parts and not name.endswith((".pyc", ".lnk", ".safetensors")), f"Local artifact in {path.name}: {name}"
                if path.name in {"EasyPanel-Core-OneClick.zip", "EasyPanel-All-OneClick.zip", "EasyPanel-LoRA-Tools-OneClick.zip"}:
                    for relative in files:
                        assert archive.read("payload/" + relative) == (ROOT / relative).read_bytes(), f"Stale ZIP payload: {relative}"
    print(f"Release verified: server {server}, mobile {mobile}, {len(files)} payload files" + (", seven ZIPs and SHA256" if packages else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="")
    parser.add_argument("--packages", action="store_true")
    args = parser.parse_args()
    verify(args.tag, args.packages)
