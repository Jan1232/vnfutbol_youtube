#!/usr/bin/env python3
"""Keep only clothing-mask pixels from an AI full edit. Head/hands never leave the layer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import extract_outfit_layer, mask_by_pose, mask_path, pose_by_id, pose_path


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose", required=True)
    parser.add_argument("--edited", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--feather", type=int, default=2, help="0-2px boundary feather")
    args = parser.parse_args()
    if args.feather < 0 or args.feather > 2:
        return fail("feather must be 0-2")

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

    try:
        layer = extract_outfit_layer(edited, clothing, feather=args.feather)
    except ValueError as exc:
        return fail(str(exc))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    layer.save(output, format="PNG")
    print(f"OK    extracted clothing layer -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
