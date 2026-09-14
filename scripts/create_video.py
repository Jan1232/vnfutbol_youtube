#!/usr/bin/env python3
"""Create a new video folder from videos/_template."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "videos" / "_template"
VIDEOS = ROOT / "videos"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_video(slug: str, force: bool) -> int:
    if not SLUG_RE.fullmatch(slug):
        return fail("slug must be lowercase kebab-case, e.g. ballon-dor-history")
    if slug == "_template":
        return fail("_template is reserved")
    if not TEMPLATE.exists():
        return fail(f"missing template: {TEMPLATE}")

    dest = VIDEOS / slug
    if dest.exists():
        if not force:
            return fail(f"{dest} already exists. Use --force to replace it.")
        shutil.rmtree(dest)

    shutil.copytree(TEMPLATE, dest, ignore=shutil.ignore_patterns(".DS_Store", "Thumbs.db"))

    assets_path = dest / "assets" / "assets.json"
    assets = json.loads(assets_path.read_text(encoding="utf-8"))
    assets["video"] = slug
    write_json(assets_path, assets)

    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    write_json(
        dest / "metadata.json",
        {
            "slug": slug,
            "title": "",
            "status": "idea",
            "createdAt": created,
        },
    )
    entities_path = dest / "context" / "entities.json"
    if not entities_path.exists():
        write_json(entities_path, {"version": 1, "entities": []})
    queue_path = dest / "assets" / "mascot-generation.json"
    if not queue_path.exists():
        write_json(queue_path, {"version": 1, "jobs": []})
    generated = dest / "assets" / "mascot" / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    keep = generated / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
    for rel in ("audio/segments", "audio/previews", "audio/final", "audio/test"):
        folder = dest / rel
        folder.mkdir(parents=True, exist_ok=True)
        marker = folder / ".gitkeep"
        if not marker.exists():
            marker.write_text("", encoding="utf-8")
    print(f"OK    created {dest.as_posix()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", help="lowercase kebab-case folder name")
    parser.add_argument("--force", action="store_true", help="Replace an existing video folder")
    args = parser.parse_args()
    return create_video(args.slug, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
