#!/usr/bin/env python3
"""Keep only clothing-mask pixels from an AI full edit. Head/hands never leave the layer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import mask_by_pose, mask_path, pose_by_id, pose_path


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose", required=True)
    parser.add_argument("--edited", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--feather", type=int, default=2, help="1-3px controlled feather")
    args = parser.parse_args()
    if args.feather < 0 or args.feather > 3:
        return fail("feather must be 0-3")

    pose = pose_by_id(args.pose)
    if pose is None:
        return fail(f"unknown pose `{args.pose}`")
    mask = mask_by_pose(args.pose)
    if mask is None:
        return fail(f"no clothing mask for `{args.pose}`")
    if mask.get("status") != "approved":
        return fail(f"clothing mask for `{args.pose}` is not approved")

    base = Image.open(pose_path(pose)).convert("RGBA")
    edited = Image.open(args.edited).convert("RGBA")
    clothing = Image.open(mask_path(mask)).convert("L")
    if edited.size != base.size or clothing.size != base.size:
        return fail("edited image and mask must match the base pose size")

    if args.feather:
        clothing = clothing.filter(ImageFilter.GaussianBlur(radius=args.feather))

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    epx = edited.load()
    mpx = clothing.load()
    lpx = layer.load()
    width, height = base.size
    kept = 0
    for y in range(height):
        for x in range(width):
            coverage = mpx[x, y]
            if coverage <= 0:
                continue
            r, g, b, a = epx[x, y]
            alpha = min(a, coverage)
            if alpha:
                lpx[x, y] = (r, g, b, alpha)
                kept += 1
    if kept == 0:
        return fail("extracted layer is empty")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    layer.save(output, format="PNG")
    print(f"OK    extracted clothing layer -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
