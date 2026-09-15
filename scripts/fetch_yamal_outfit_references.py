#!/usr/bin/env python3
"""Download official Yamal outfit references into .local-assets and import them.

Third-party image bytes remain local-only and are never committed.
This script only uses official FC Barcelona / RFEF store sources.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_outfit_reference import import_reference
from mascot_common import ROOT


REFERENCES = {
    "barcelona-home": {
        "source_page": "https://store.fcbarcelona.com/collections/men-kits/products/fc-barcelona-home-amshirt-25-26-ucl",
        "image_url": "https://store.fcbarcelona.com/cdn/shop/files/HJ4590-456_415227879_D_A_1X1_e3028dab-beb3-4a47-a7bc-0783a5f75462.jpg?v=1751431616&width=1200",
        "filename": "barcelona-home-2025-26.jpg",
    },
    "spain-home-2026": {
        "source_page": "https://shop.rfef.es/en-int/products/camiseta-hombre-primera-equipacion",
        "image_url": "https://shop.rfef.es/cdn/shop/files/25CM0844-3.png?v=1764595319&width=2000",
        "filename": "spain-home-2026.png",
    },
}


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; vnfutbol-asset-prep/1.0)",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
        },
    )
    with urlopen(req, timeout=60) as response, dest.open("wb") as out:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "image" not in content_type:
            raise RuntimeError(f"expected image content-type, got {content_type!r} from {url}")
        shutil.copyfileobj(response, out)

    try:
        with Image.open(dest) as image:
            image.load()
            width, height = image.size
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded file is not a readable image: {url}: {exc}") from exc

    if width < 600 or height < 600:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"reference image too small ({width}x{height}): {url}")


def process(outfit_id: str, *, replace: bool) -> int:
    spec = REFERENCES[outfit_id]
    download_dir = ROOT / ".local-assets" / "shared" / "mascot-outfit-references" / "_downloads"
    dest = download_dir / spec["filename"]
    print(f"DOWNLOAD {outfit_id}: {spec['image_url']}")
    download(spec["image_url"], dest)
    print(f"IMPORT   {outfit_id}: {dest}")
    return import_reference(
        outfit_id,
        dest,
        spec["source_page"],
        replace=replace,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=sorted(REFERENCES),
        default=None,
        help="Download/import only one outfit reference.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Allow replacing an existing local reference with different bytes.",
    )
    args = parser.parse_args()

    targets = [args.only] if args.only else list(REFERENCES)
    failed = 0
    for outfit_id in targets:
        try:
            code = process(outfit_id, replace=args.replace)
            if code != 0:
                failed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {outfit_id}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
