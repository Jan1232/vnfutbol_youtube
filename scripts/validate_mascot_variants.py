#!/usr/bin/env python3
"""Validate reusable outfit layers. Approved stale variants are errors."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    DEFAULT_OUTFIT,
    VARIANT_STATUSES,
    load_variants,
    mask_by_pose,
    outfit_by_id,
    outfit_spec_sha256,
    pose_by_id,
    pose_path,
    sha256_file,
    variant_is_stale,
    variant_path,
)


def main() -> int:
    errors: list[str] = []
    data = load_variants()
    variants = data.get("variants", [])
    if data.get("version") != 1:
        errors.append("variants.json: version must be 1")

    ids: list[str] = []
    pairs: list[tuple[str, str]] = []
    for index, variant in enumerate(variants):
        prefix = f"variants.json[{index}]"
        variant_id = variant.get("id")
        pose_id = variant.get("basePose")
        outfit_id = variant.get("outfit")
        if not variant_id or not pose_id or not outfit_id:
            errors.append(f"{prefix}: missing id/basePose/outfit")
            continue
        ids.append(variant_id)
        pairs.append((pose_id, outfit_id))
        if outfit_id == DEFAULT_OUTFIT:
            errors.append(f"{variant_id}: default-home must not have a stored layer")
        if variant.get("status") not in VARIANT_STATUSES:
            errors.append(f"{variant_id}: invalid status")
        if variant.get("type") != "outfit-layer":
            errors.append(f"{variant_id}: type must be outfit-layer")

        pose = pose_by_id(pose_id)
        outfit = outfit_by_id(outfit_id)
        mask = mask_by_pose(pose_id)
        if pose is None:
            errors.append(f"{variant_id}: basePose does not exist")
            continue
        if outfit is None:
            errors.append(f"{variant_id}: outfit does not exist")
            continue
        path = variant_path(variant)
        if not path.exists():
            errors.append(f"{variant_id}: missing layer {variant.get('file')}")
            continue
        if sha256_file(path) != variant.get("sha256"):
            errors.append(f"{variant_id}: sha256 mismatch")
        if variant.get("basePoseSha256") != pose.get("sha256"):
            errors.append(f"{variant_id}: basePoseSha256 mismatch")
        if mask and variant.get("maskSha256") != mask.get("sha256"):
            errors.append(f"{variant_id}: maskSha256 mismatch")
        if variant.get("outfitSpecSha256") != outfit_spec_sha256(outfit):
            errors.append(f"{variant_id}: outfitSpecSha256 mismatch")
        if variant_is_stale(variant, pose, mask, outfit):
            if variant.get("status") == "approved":
                errors.append(f"{variant_id}: approved variant is stale")
            elif variant.get("status") != "stale":
                errors.append(f"{variant_id}: hashes are stale but status is {variant.get('status')}")

        try:
            layer = Image.open(path)
            base = Image.open(pose_path(pose))
        except OSError as exc:
            errors.append(f"{variant_id}: cannot open image ({exc})")
            continue
        if layer.format != "PNG":
            errors.append(f"{variant_id}: not a PNG")
        if layer.size != base.size:
            errors.append(f"{variant_id}: layer size {layer.size} != pose {base.size}")
        if "A" not in layer.getbands():
            errors.append(f"{variant_id}: layer has no alpha")
            continue
        extrema = layer.convert("RGBA").getchannel("A").getextrema()
        if extrema[1] == 0:
            errors.append(f"{variant_id}: layer is fully empty")

    for value, count in Counter(ids).items():
        if count > 1:
            errors.append(f"duplicate variant id: {value}")
    for value, count in Counter(pairs).items():
        if count > 1:
            errors.append(f"duplicate pose+outfit pair: {value}")

    for message in errors:
        print(f"ERROR {message}")
    if errors:
        print(f"FAIL  {len(errors)} error(s)")
        return 1
    print(f"OK    {len(variants)} outfit variants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
