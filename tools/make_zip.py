#!/usr/bin/env python3
"""Packs the plugin as a zip for Decky (Developer → "Install Plugin from ZIP File").

Included: plugin.json, package.json, main.py, dist/index.js, py_modules/. Not included:
the frontend's source code, tests, captures, source maps.
Usage: python3 -I tools/make_zip.py [output file]
"""

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["plugin.json", "package.json", "main.py", "dist/index.js"]


def collect() -> list:
    paths = [ROOT / f for f in FILES]
    paths += sorted(p for p in (ROOT / "py_modules").rglob("*.py"))
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.is_file()]
    if missing:
        raise SystemExit("Missing: " + ", ".join(missing) + " (frontend built? npm run build)")
    return paths


def build(out: Path) -> Path:
    name = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["name"]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in collect():
            archive.write(path, f"{name}/{path.relative_to(ROOT).as_posix()}")
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "X360-Receiver.zip"
    print(build(target))
