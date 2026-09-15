#!/usr/bin/env python3
"""Generate identity masks: immutable head/hands/eyes/skin zones. Never auto-approves.

Identity = character opaque pixels that are NOT clothing.
White eyes are always forced into the identity mask.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    IDENTITY_MASKS_DIR,
    IDENTITY_MASKS_PATH,
    MASCOT,
    load_identity_masks,
    load_masks,
    mask_by_pose,
    mask_path,
    pose_by_id,
    pose_path,
    sha256_file,
    write_json,
)


def is_white_eye(rgb: tuple[int, int, int], alpha: int) -> bool:
    if alpha < 200:
        return False
    r, g, b = rgb
    # Large white eye plates on the black mask head.
    return r >= 220 and g >= 220 and b >= 220 and abs(r - g) < 20 and abs(g - b) < 20


def build_identity_mask(base: Image.Image, clothing: Image.Image) -> Image.Image:
    rgba = base.convert("RGBA")
    cloth = clothing.convert("L")
    if cloth.size != rgba.size:
        raise ValueError(f"clothing mask size {cloth.size} != pose {rgba.size}")
    out = Image.new("L", rgba.size, 0)
    rpx = rgba.load()
    cpx = cloth.load()
    opx = out.load()
    width, height = rgba.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = rpx[x, y]
            if a <= 16:
                continue
            if is_white_eye((r, g, b), a):
                opx[x, y] = 255
                continue
            if cpx[x, y] > 0:
                continue
            # Non-clothing character pixels: head, hands, exposed limbs, props.
            opx[x, y] = 255
    # Light close to keep eye/hand regions contiguous without eating clothing.
    out = out.filter(ImageFilter.MaxFilter(3))
    out = out.filter(ImageFilter.MinFilter(3))
    opx = out.load()
    # Never reclaim clothing pixels after morphology (eyes may sit over black head only).
    for y in range(height):
        for x in range(width):
            r, g, b, a = rpx[x, y]
            if cpx[x, y] > 0 and not is_white_eye((r, g, b), a):
                opx[x, y] = 0
    return out


def upsert_identity_record(pose_id: str, rel_file: str, digest: str, base_pose_sha: str) -> None:
    data = load_identity_masks()
    masks = list(data.get("masks") or [])
    record = {
        "basePose": pose_id,
        "file": rel_file,
        "status": "generated",
        "sha256": digest,
        "basePoseSha256": base_pose_sha,
    }
    others = [m for m in masks if m.get("basePose") != pose_id]
    others.append(record)
    others.sort(key=lambda item: item.get("basePose") or "")
    write_json(IDENTITY_MASKS_PATH, {"version": 1, "masks": others})


def generate_for_pose(pose_id: str) -> Path:
    pose = pose_by_id(pose_id)
    if pose is None or not pose.get("approved"):
        raise ValueError(f"approved pose `{pose_id}` missing")
    clothing = mask_by_pose(pose_id)
    if clothing is None:
        raise ValueError(f"clothing mask missing for `{pose_id}`")
    clothing_file = mask_path(clothing)
    if not clothing_file.exists():
        raise ValueError(f"clothing mask file missing: {clothing_file}")

    base = Image.open(pose_path(pose)).convert("RGBA")
    cloth = Image.open(clothing_file).convert("L")
    identity = build_identity_mask(base, cloth)

    IDENTITY_MASKS_DIR.mkdir(parents=True, exist_ok=True)
    rel = f"identity-masks/{pose_id}.png"
    dest = MASCOT / rel
    identity.save(dest, format="PNG")
    digest = sha256_file(dest)
    upsert_identity_record(pose_id, rel, digest, pose.get("sha256"))
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose", action="append", dest="poses", default=[])
    parser.add_argument("--all-approved-clothing", action="store_true")
    args = parser.parse_args()

    pose_ids = list(args.poses or [])
    if args.all_approved_clothing:
        for mask in load_masks().get("masks") or []:
            if mask.get("status") == "approved" and mask.get("basePose"):
                pose_ids.append(mask["basePose"])
    pose_ids = sorted(set(pose_ids))
    if not pose_ids:
        print("ERROR pass --pose ID or --all-approved-clothing")
        return 1

    for pose_id in pose_ids:
        path = generate_for_pose(pose_id)
        print(f"OK    identity mask `{pose_id}` -> {path} (status=generated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
