#!/usr/bin/env python3
"""Structural validation of clothing masks. Does not judge visual garment quality."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    MASCOT,
    MASK_STATUSES,
    load_masks,
    mask_path,
    pose_by_id,
    pose_path,
    sha256_file,
)

MIN_CHARACTER_COVER = 0.08
MAX_CHARACTER_COVER = 0.80
OUTSIDE_TOLERANCE = 0.02


def main() -> int:
    errors: list[str] = []
    data = load_masks()
    masks = data.get("masks", [])
    if data.get("version") != 1:
        errors.append("pose-masks.json: version must be 1")

    poses_seen: list[str] = []
    for index, mask in enumerate(masks):
        prefix = f"pose-masks.json[{index}]"
        pose_id = mask.get("basePose")
        if not pose_id:
            errors.append(f"{prefix}: missing basePose")
            continue
        poses_seen.append(pose_id)
        if mask.get("status") not in MASK_STATUSES:
            errors.append(f"{pose_id}: invalid status")
        pose = pose_by_id(pose_id)
        if pose is None:
            errors.append(f"{pose_id}: base pose does not exist")
            continue
        path = mask_path(mask)
        if not path.exists():
            errors.append(f"{pose_id}: missing file {mask.get('file')}")
            continue
        if sha256_file(path) != mask.get("sha256"):
            errors.append(f"{pose_id}: sha256 mismatch")
        if mask.get("basePoseSha256") != pose.get("sha256"):
            errors.append(f"{pose_id}: basePoseSha256 no longer matches the pose PNG")

        try:
            mask_im = Image.open(path)
            pose_im = Image.open(pose_path(pose)).convert("RGBA")
        except OSError as exc:
            errors.append(f"{pose_id}: cannot open image ({exc})")
            continue
        if mask_im.size != pose_im.size:
            errors.append(f"{pose_id}: mask size {mask_im.size} != pose {pose_im.size}")
            continue
        gray = mask_im.convert("L")
        white = 0
        outside = 0
        character = 0
        cover = 0
        mpx = gray.load()
        ppx = pose_im.load()
        width, height = gray.size
        for y in range(height):
            for x in range(width):
                clothed = mpx[x, y] >= 128
                opaque = ppx[x, y][3] > 16
                if clothed:
                    white += 1
                    if not opaque:
                        outside += 1
                if opaque:
                    character += 1
                    if clothed:
                        cover += 1
        if white == 0:
            errors.append(f"{pose_id}: mask is empty")
            continue
        if character:
            ratio = cover / character
            if ratio < MIN_CHARACTER_COVER:
                errors.append(f"{pose_id}: mask covers too little of the character ({ratio:.1%})")
            if ratio > MAX_CHARACTER_COVER:
                errors.append(f"{pose_id}: mask covers too much of the character ({ratio:.1%})")
        if white and outside / white > OUTSIDE_TOLERANCE:
            errors.append(f"{pose_id}: mask leaks outside the character")

    for value, count in Counter(poses_seen).items():
        if count > 1:
            errors.append(f"duplicate mask for basePose `{value}`")

    files = {item["file"] for item in masks if "file" in item}
    for png in sorted((MASCOT / "pose-masks").glob("*.png")):
        rel = png.relative_to(MASCOT).as_posix()
        if rel not in files:
            errors.append(f"{rel}: PNG has no pose-masks.json entry")

    for message in errors:
        print(f"ERROR {message}")
    if errors:
        print(f"FAIL  {len(errors)} error(s)")
        return 1
    print(f"OK    {len(masks)} clothing masks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
