#!/usr/bin/env python3
"""Import a local official outfit visual reference (Image C). No network, no AI."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    OUTFIT_REF_RIGHTS,
    outfit_by_id,
    outfit_reference_dir,
    outfit_reference_meta_path,
    outfit_reference_path,
    sha256_file,
    update_tracked_outfit_reference,
    write_json,
)


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def import_reference(
    outfit_id: str,
    input_path: Path,
    source_url: str,
    *,
    replace: bool = False,
) -> int:
    outfit = outfit_by_id(outfit_id)
    if outfit is None:
        return fail(f"unknown outfit `{outfit_id}`")
    if not outfit.get("referenceRequired"):
        return fail(f"outfit `{outfit_id}` does not require a visual reference")
    if not input_path.exists():
        return fail(f"missing input `{input_path}`")

    try:
        image = Image.open(input_path)
        image.load()
    except OSError as exc:
        return fail(f"unreadable image: {exc}")
    width, height = image.size
    if width < 2 or height < 2:
        return fail("input image is empty/too small")

    dest_dir = outfit_reference_dir(outfit_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = outfit_reference_path(outfit_id)
    rgba = image.convert("RGBA")

    if dest.exists():
        tmp = dest_dir / "_incoming.png"
        rgba.save(tmp, format="PNG")
        incoming = sha256_file(tmp)
        existing = sha256_file(dest)
        if incoming != existing and not replace:
            tmp.unlink(missing_ok=True)
            return fail(
                f"refusing silent overwrite of different reference for `{outfit_id}` "
                f"({existing[:12]}… vs {incoming[:12]}…); pass --replace"
            )
        tmp.replace(dest)
    else:
        rgba.save(dest, format="PNG")

    digest = sha256_file(dest)
    with Image.open(dest) as saved:
        width, height = saved.size
    meta = {
        "outfitId": outfit_id,
        "sourceUrl": source_url,
        "sha256": digest,
        "width": width,
        "height": height,
        "importedAt": utc_now(),
        "rights": OUTFIT_REF_RIGHTS,
    }
    write_json(outfit_reference_meta_path(outfit_id), meta)
    update_tracked_outfit_reference(outfit_id, source_url=source_url, sha256=digest)
    print(f"OK    imported outfit reference `{outfit_id}` -> {dest} sha256={digest[:12]}…")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outfit", required=True, help="Outfit id, e.g. barcelona-home")
    parser.add_argument("--input", required=True, help="Local PNG/JPEG reference image")
    parser.add_argument("--source-url", required=True, help="Official source page URL")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Allow replacing an existing reference with different bytes",
    )
    args = parser.parse_args()
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = (Path.cwd() / input_path).resolve()
    return import_reference(args.outfit, input_path, args.source_url, replace=args.replace)


if __name__ == "__main__":
    sys.exit(main())
