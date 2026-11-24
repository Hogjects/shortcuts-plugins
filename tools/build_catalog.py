#!/usr/bin/env python3
"""Builds the plugin catalog from the plugins/<id>/ folders

Writes dist/index.json and dist/zips/<id>-<version>.zip
Run it locally to check your plugins or let the GitHub Action run it
Exits non zero on the first problem so a bad plugin never gets published"""
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"
DIST_DIR = ROOT / "dist"

SCHEMA = 1
MAX_ZIP_BYTES = 10 * 1024 * 1024  # keep in step with plugin_store.py in the app

# The id rule is the app's own rule from plugin_manager.py
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
# Stricter than the app because the version ends up inside a file name
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,31}$")

# A fixed timestamp means identical sources always produce an identical zip and sha256
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def load_manifest(plugin_dir):
    path = plugin_dir / "manifest.json"
    if not path.is_file():
        fail(f"{plugin_dir.name}: manifest.json is missing")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{plugin_dir.name}: manifest.json isn't valid JSON: {exc}")

    plugin_id = str(manifest.get("id", "")).strip()
    name = str(manifest.get("name", "")).strip()
    version = str(manifest.get("version", "")).strip()
    entry = str(manifest.get("entry") or "actions.py")

    if not ID_RE.match(plugin_id):
        fail(f"{plugin_dir.name}: bad id {plugin_id!r}")
    if plugin_id != plugin_dir.name:
        fail(f"{plugin_dir.name}: folder name must match the manifest id ({plugin_id!r})")
    if not name:
        fail(f"{plugin_id}: manifest has no name")
    if not VERSION_RE.match(version):
        fail(f"{plugin_id}: bad version {version!r} (letters, digits, . _ - only)")
    if "/" in entry or "\\" in entry or not entry.endswith(".py"):
        fail(f"{plugin_id}: entry must be a plain .py filename")
    if not (plugin_dir / entry).is_file():
        fail(f"{plugin_id}: entry file {entry!r} doesn't exist")
    return manifest, plugin_id, name, version


def plugin_files(plugin_dir):
    for path in sorted(plugin_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(plugin_dir)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        if path.suffix == ".pyc":
            continue
        yield path, rel.as_posix()


def build_zip(plugin_dir, zip_path):
    with zipfile.ZipFile(zip_path, "w") as zf:
        for path, arcname in plugin_files(plugin_dir):
            info = zipfile.ZipInfo(arcname, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())


def main():
    if not PLUGINS_DIR.is_dir():
        fail("no plugins/ folder")

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    (DIST_DIR / "zips").mkdir(parents=True)

    entries = []
    for plugin_dir in sorted(p for p in PLUGINS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")):
        manifest, plugin_id, name, version = load_manifest(plugin_dir)
        file_name = f"{plugin_id}-{version}.zip"
        zip_path = DIST_DIR / "zips" / file_name
        build_zip(plugin_dir, zip_path)

        data = zip_path.read_bytes()
        if len(data) > MAX_ZIP_BYTES:
            fail(f"{plugin_id}: zip is {len(data)} bytes, over the {MAX_ZIP_BYTES} limit")

        entries.append({
            "id": plugin_id,
            "name": name,
            "version": version,
            "author": str(manifest.get("author", "")).strip(),
            "description": str(manifest.get("description", "")).strip(),
            "category": manifest.get("category") or "",
            "file": file_name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })
        print(f"built {file_name} ({len(data)} bytes)")

    if not entries:
        fail("plugins/ has no plugin folders")

    index = {"schema": SCHEMA, "plugins": entries}
    (DIST_DIR / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"wrote dist/index.json with {len(entries)} plugin(s)")


if __name__ == "__main__":
    main()
