#!/usr/bin/env python3
"""Alpha-composite an approved outfit layer over an immutable base pose."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    DEFAULT_OUTFIT,
    mask_by_pose,
    outfit_by_id,
    pose_by_id,
    pose_path,
    variant_by_pair,
    variant_is_reusable,
    variant_path,
)


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose", required=True)
    parser.add_argument("--outfit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    pose = pose_by_id(args.pose)
    if pose is None:
        return fail(f"unknown pose `{args.pose}`")
    outfit = outfit_by_id(args.outfit)
    if outfit is None:
        return fail(f"unknown outfit `{args.outfit}`")

    base = Image.open(pose_path(pose)).convert("RGBA")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.outfit == DEFAULT_OUTFIT:
        base.save(output, format="PNG")
        print(f"OK    default-home uses base pose only -> {output}")
        return 0

    variant = variant_by_pair(args.pose, args.outfit)
    mask = mask_by_pose(args.pose)
    if not variant_is_reusable(variant, pose, mask, outfit):
        if variant is None:
            return fail(
                f"no outfit layer for {args.pose} + {args.outfit}. "
                "Run ensure_mascot_variants.py and generate the missing layer."
            )
        return fail(
            f"variant `{variant.get('id')}` is not reusable "
            f"(status={variant.get('status')}); regenerate or re-approve"
        )

    layer = Image.open(variant_path(variant)).convert("RGBA")
    if layer.size != base.size:
        return fail(f"layer size {layer.size} != pose {base.size}")
    # Always rebuild from verified base pose + verified layer (do not trust stale composite bytes).
    composed = Image.alpha_composite(base, layer)
    composed.save(output, format="PNG")
    print(f"OK    composed {args.pose} + {args.outfit} -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
