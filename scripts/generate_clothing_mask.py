#!/usr/bin/env python3
"""Build initial clothing masks from canonical jersey colors. Never auto-approves."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    MASCOT,
    load_masks,
    load_poses,
    pose_path,
    sha256_file,
    write_json,
    MASKS_PATH,
)

GARNET = (0x81, 0x16, 0x2D)
NAVY = (0x17, 0x21, 0x46)
HEAD_RATIO = 0.30
RGB_LIMIT = 82.0
NAVY_LIMIT = 70.0


def rgb_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def hsv(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = (c / 255.0 for c in rgb)
    mx = max(r, g, b)
    mn = min(r, g, b)
    df = mx - mn
    if df == 0:
        h = 0.0
    elif mx == r:
        h = (60 * ((g - b) / df) + 360) % 360
    elif mx == g:
        h = (60 * ((b - r) / df) + 120) % 360
    else:
        h = (60 * ((r - g) / df) + 240) % 360
    s = 0.0 if mx == 0 else df / mx
    return h, s, mx


def is_garment(rgb: tuple[int, int, int]) -> bool:
    h, s, v = hsv(rgb)
    # Black mask/skin is near-neutral. Jersey navy is saturated blue.
    if s < 0.32:
        return False
    if rgb_dist(rgb, GARNET) <= RGB_LIMIT:
        return True
    if rgb_dist(rgb, NAVY) <= NAVY_LIMIT and s >= 0.40:
        return True
    garnet_hue = abs(h - 348) <= 28 or h <= 14
    navy_hue = 205 <= h <= 250
    if garnet_hue and s >= 0.35 and 0.14 <= v <= 0.80:
        return True
    if navy_hue and s >= 0.40 and 0.08 <= v <= 0.50:
        return True
    return False


def character_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    alpha = image.getchannel("A")
    bbox = alpha.point(lambda p: 255 if p > 16 else 0).getbbox()
    return bbox


def build_mask(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    bbox = character_bbox(rgba)
    mask = Image.new("L", (width, height), 0)
    if bbox is None:
        return mask

    left, top, right, bottom = bbox
    head_cut = top + int((bottom - top) * HEAD_RATIO)
    pixels = rgba.load()
    out = mask.load()
    for y in range(top, bottom):
        if y < head_cut:
            continue
        for x in range(left, right):
            r, g, b, a = pixels[x, y]
            if a < 16:
                continue
            if is_garment((r, g, b)):
                out[x, y] = 255

    mask = mask.filter(ImageFilter.MaxFilter(5))
    mask = mask.filter(ImageFilter.MinFilter(3))
    mask = mask.filter(ImageFilter.MaxFilter(3))

    # Keep garment pixels inside the opaque character only.
    alpha = rgba.getchannel("A")
    cleaned = Image.new("L", (width, height), 0)
    src = mask.load()
    dst = cleaned.load()
    alp = alpha.load()
    for y in range(height):
        for x in range(width):
            if src[x, y] >= 128 and alp[x, y] > 16:
                dst[x, y] = 255
    return cleaned


def generate_one(pose: dict) -> dict:
    source = pose_path(pose)
    image = Image.open(source)
    mask = build_mask(image)
    rel = f"pose-masks/{pose['id']}.png"
    dest = MASCOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    mask.save(dest, format="PNG")
    return {
        "basePose": pose["id"],
        "file": rel,
        "status": "generated",
        "sha256": sha256_file(dest),
        "basePoseSha256": pose["sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pose", nargs="?", help="Pose id, e.g. argument")
    parser.add_argument("--all", action="store_true", help="Generate masks for every pose")
    args = parser.parse_args()
    if not args.pose and not args.all:
        parser.error("pass a pose id or --all")

    poses = load_poses().get("poses", [])
    by_id = {item["id"]: item for item in poses}
    targets = list(poses) if args.all else [by_id.get(args.pose)]
    if not args.all and targets[0] is None:
        print(f"ERROR unknown pose `{args.pose}`")
        return 1

    existing = {item["basePose"]: item for item in load_masks().get("masks", [])}
    for pose in targets:
        record = generate_one(pose)
        existing[record["basePose"]] = record
        print(f"OK    {record['basePose']} -> {record['file']} status=generated")

    write_json(MASKS_PATH, {"version": 1, "masks": [existing[key] for key in sorted(existing)]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
