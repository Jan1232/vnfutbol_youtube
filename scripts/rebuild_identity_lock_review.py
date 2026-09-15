#!/usr/bin/env python3
"""Offline rebuild: identity-lock final for count-3 + spain-home-2026 + review board.

Uses existing full-edit-attempt-1. No OpenAI / paid API calls.
Stops after writing review PNG for editor approval.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_identity_mask import generate_for_pose
from mascot_common import (
    MASCOT,
    VARIANTS_PATH,
    compose_identity_locked_final,
    compose_masked_replacement,
    extract_outfit_layer,
    full_edit_destination,
    hashes_current,
    identity_mask_by_pose,
    load_variants,
    mask_by_pose,
    mask_path,
    outfit_by_id,
    pose_by_id,
    pose_path,
    sha256_file,
    write_json,
)
from mascot_geometry_qa import geometry_qa, identity_lock_qa


def _fit(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (24, 24, 28, 255))
    copy = img.convert("RGBA")
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    ox = (size[0] - copy.size[0]) // 2
    oy = (size[1] - copy.size[1]) // 2
    canvas.alpha_composite(copy, (ox, oy))
    return canvas


def build_review_board(
    panels: list[tuple[str, Image.Image]],
    out_path: Path,
) -> None:
    panel_w, panel_h = 360, 450
    label_h = 48
    margin = 16
    cols = len(panels)
    width = margin * (cols + 1) + panel_w * cols
    height = margin * 2 + label_h + panel_h
    board = Image.new("RGB", (width, height), (18, 18, 22))
    draw = ImageDraw.Draw(board)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for index, (label, img) in enumerate(panels):
        x = margin + index * (panel_w + margin)
        y = margin + label_h
        board.paste(_fit(img, (panel_w, panel_h)).convert("RGB"), (x, y))
        draw.text((x, margin + 10), label, fill=(240, 240, 240), font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    board.save(out_path, format="PNG")


def main() -> int:
    pose_id = "count-3"
    outfit_id = "spain-home-2026"
    full_edit_src = (
        ROOT
        / ".local-assets"
        / "channel"
        / "mascot"
        / "_work"
        / f"{pose_id}__{outfit_id}"
        / "full-edit-attempt-1.png"
    )
    if not full_edit_src.exists():
        print(f"ERROR missing full-edit candidate: {full_edit_src}")
        return 1

    pose = pose_by_id(pose_id)
    outfit = outfit_by_id(outfit_id)
    clothing = mask_by_pose(pose_id)
    if pose is None or outfit is None or clothing is None:
        print("ERROR pose/outfit/clothing mask missing")
        return 1

    print(f"OK    generating identity mask for `{pose_id}` (status=generated)")
    identity_path = generate_for_pose(pose_id)
    identity_rec = identity_mask_by_pose(pose_id)
    assert identity_rec is not None

    base = Image.open(pose_path(pose)).convert("RGBA")
    full_edit = Image.open(full_edit_src).convert("RGBA")
    clothing_img = Image.open(mask_path(clothing)).convert("L")
    identity_img = Image.open(identity_path).convert("L")

    if full_edit.size != base.size:
        print(f"ERROR full-edit size {full_edit.size} != base {base.size}")
        return 1

    # A/B/C/D candidates
    old_layer = extract_outfit_layer(full_edit, clothing_img, feather=2)
    old_composite = compose_masked_replacement(base, old_layer)
    new_final = compose_identity_locked_final(base, full_edit, identity_img, feather=1)

    geo = geometry_qa(base, full_edit, identity_mask=identity_img)
    lock = identity_lock_qa(base, new_final, identity_img)
    print(f"OK    geometry_qa pass={geo.get('pass')} issues={geo.get('issues')}")
    print(f"OK    identity_lock_qa pass={lock.get('pass')} issues={lock.get('issues')}")

    # Persist candidates under local review + channel full-edit/final (pending editor approve).
    review_dir = ROOT / ".local-assets" / "lamine-yamal-new-messi" / "previews"
    review_dir.mkdir(parents=True, exist_ok=True)
    full_dest = full_edit_destination(outfit, pose_id)
    final_dest = MASCOT / "variants" / outfit_id / f"{pose_id}.png"
    debug_layer = MASCOT / "variants" / outfit_id / "layers" / f"{pose_id}.png"
    old_comp_debug = (
        ROOT
        / ".local-assets"
        / "channel"
        / "mascot"
        / "_work"
        / f"{pose_id}__{outfit_id}"
        / "old-clothing-mask-composite.png"
    )

    full_dest.parent.mkdir(parents=True, exist_ok=True)
    final_dest.parent.mkdir(parents=True, exist_ok=True)
    debug_layer.parent.mkdir(parents=True, exist_ok=True)
    full_edit.save(full_dest, format="PNG")
    new_final.save(final_dest, format="PNG")
    old_layer.save(debug_layer, format="PNG")  # optional/debug only
    old_composite.save(old_comp_debug, format="PNG")

    board_path = review_dir / "mascot-identity-lock-review-count-3-spain-home-2026.png"
    build_review_board(
        [
            ("A original pose", base),
            ("B raw full-edit", full_edit),
            ("C old clothing-mask composite", old_composite),
            ("D new identity-lock final", new_final),
        ],
        board_path,
    )

    # Update variants.json as needs-review (editor must approve identity mask + visual).
    record = {
        "id": f"{pose_id}__{outfit_id}",
        "basePose": pose_id,
        "outfit": outfit_id,
        "type": "identity-lock-final",
        "file": debug_layer.relative_to(MASCOT).as_posix(),  # debug layer path kept optional
        "compositeFile": final_dest.relative_to(MASCOT).as_posix(),
        "fullEditFile": full_dest.relative_to(MASCOT).as_posix(),
        "status": "needs-review",
        "sha256": sha256_file(debug_layer),
        "compositeSha256": sha256_file(final_dest),
        "fullEditSha256": sha256_file(full_dest),
        "finalization": "identity-lock",
        "identityMask": identity_rec.get("file"),
        "identityMaskStatus": identity_rec.get("status"),
        "qa": {
            "geometry": geo,
            "identityLock": lock,
            "visual": "pending-editor-review",
        },
        **hashes_current(pose, clothing, outfit),
    }
    data = load_variants()
    others = [
        item
        for item in data.get("variants") or []
        if not (item.get("basePose") == pose_id and item.get("outfit") == outfit_id)
    ]
    others.append(record)
    others.sort(key=lambda item: item["id"])
    write_json(VARIANTS_PATH, {"version": 1, "variants": others})

    summary = {
        "pose": pose_id,
        "outfit": outfit_id,
        "identityMask": str(identity_path),
        "identityMaskStatus": identity_rec.get("status"),
        "fullEdit": str(full_dest),
        "identityLockFinal": str(final_dest),
        "oldClothingComposite": str(old_comp_debug),
        "reviewBoard": str(board_path),
        "geometryQa": geo,
        "identityLockQa": lock,
        "variantStatus": "needs-review",
        "note": "STOP for editor review. Do not approve-auto. No paid API used.",
    }
    summary_path = review_dir / "mascot-identity-lock-review-count-3-spain-home-2026.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("STOP  awaiting editor review of identity-lock strategy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
