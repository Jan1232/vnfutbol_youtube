#!/usr/bin/env python3
"""Import an external AI full-edit PNG for a mascot generation job. No AI calls."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asset_prep_common import ensure_local_dirs, load_asset_prep, load_json, write_json
from mascot_common import (
    current_outfit_reference_sha,
    hashes_current,
    mask_by_pose,
    mask_path,
    outfit_by_id,
    outfit_requires_reference,
    pose_by_id,
    pose_path,
    sha256_file,
)

IMPORTABLE = {"pending", "generated-review", "needs-review"}


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def extract_layer(pose_id: str, edited: Image.Image, feather: int = 2) -> Image.Image:
    pose = pose_by_id(pose_id)
    mask = mask_by_pose(pose_id)
    if pose is None or mask is None:
        raise ValueError("pose/mask missing")
    if mask.get("status") != "approved":
        raise ValueError("clothing mask is not approved")
    base = Image.open(pose_path(pose)).convert("RGBA")
    clothing = Image.open(mask_path(mask)).convert("L")
    if edited.size != base.size or clothing.size != base.size:
        raise ValueError(
            f"edited size {edited.size} must equal base pose size {base.size}"
        )
    hard_mask = clothing
    soft_mask = (
        hard_mask.filter(ImageFilter.GaussianBlur(radius=feather)) if feather else hard_mask
    )
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    epx = edited.load()
    hpx = hard_mask.load()
    spx = soft_mask.load()
    lpx = layer.load()
    kept = 0
    width, height = base.size
    for y in range(height):
        for x in range(width):
            hard = hpx[x, y]
            if hard <= 0:
                continue
            coverage = min(hard, spx[x, y])
            if coverage <= 0:
                continue
            r, g, b, a = epx[x, y]
            alpha = min(a, coverage)
            if alpha:
                lpx[x, y] = (r, g, b, alpha)
                kept += 1
    if kept == 0:
        raise ValueError("extracted layer is empty")
    return layer


def layer_has_alpha(path: Path) -> bool:
    img = Image.open(path).convert("RGBA")
    return any(px[3] > 0 for px in img.getdata())


def import_full_edit(video_dir: Path, job_id: str, input_path: Path) -> int:
    queue_path = video_dir / "assets" / "mascot-generation.json"
    queue = load_json(queue_path)
    jobs = list(queue.get("jobs") or [])
    job = next((item for item in jobs if item.get("id") == job_id), None)
    if job is None:
        return fail(f"unknown job `{job_id}`")
    if job.get("status") not in IMPORTABLE:
        return fail(f"job `{job_id}` status={job.get('status')} is not importable")

    pose = pose_by_id(job["basePose"])
    outfit = outfit_by_id(job["outfit"])
    mask = mask_by_pose(job["basePose"])
    if pose is None or outfit is None or mask is None:
        return fail("pose/outfit/mask missing")
    current = hashes_current(pose, mask, outfit)
    for key in ("basePoseSha256", "maskSha256", "outfitSpecSha256"):
        if job.get(key) != current[key]:
            return fail(f"stale job hash `{key}`; re-run ensure_mascot_variants")

    if outfit_requires_reference(outfit):
        frozen_ref = job.get("outfitReferenceSha256")
        current_ref = current_outfit_reference_sha(outfit)
        if not frozen_ref:
            return fail(
                f"job `{job_id}` missing frozen outfitReferenceSha256; "
                "export pack / re-run ensure after importing the outfit reference"
            )
        if not current_ref:
            return fail(f"missing local outfit reference for `{outfit['id']}`")
        if frozen_ref != current_ref:
            return fail(
                "frozen outfitReferenceSha256 no longer matches the local outfit reference"
            )

    if not input_path.exists():
        return fail(f"missing input `{input_path}`")
    try:
        edited = Image.open(input_path).convert("RGBA")
    except OSError as exc:
        return fail(f"input is not a readable image: {exc}")
    if edited.size[0] < 2 or edited.size[1] < 2:
        return fail("input image is empty/too small")
    base = Image.open(pose_path(pose)).convert("RGBA")
    if edited.size != base.size:
        return fail(
            f"canvas {edited.size} != base pose {base.size}"
        )

    target_full = video_dir / job["targetFullEdit"]
    target_layer = video_dir / job["targetLayer"]
    target_full.parent.mkdir(parents=True, exist_ok=True)
    target_layer.parent.mkdir(parents=True, exist_ok=True)

    incoming = sha256_file(input_path)
    if target_full.exists():
        existing = sha256_file(target_full)
        if existing != incoming:
            return fail(
                f"refusing silent overwrite of different full-edit "
                f"({existing[:12]}… vs {incoming[:12]}…)"
            )

    shutil.copy2(input_path, target_full)
    try:
        layer = extract_layer(job["basePose"], edited)
    except ValueError as exc:
        return fail(str(exc))
    layer.save(target_layer, format="PNG")

    composed = Image.alpha_composite(base, layer)
    prep = load_asset_prep(video_dir) if (video_dir / "assets" / "asset-prep.json").exists() else {
        "paths": {"localRoot": f".local-assets/{video_dir.name}"}
    }
    dirs = ensure_local_dirs(video_dir, prep)
    preview = dirs["previews"] / f"{job_id}-composed.png"
    composed.save(preview, format="PNG")

    # Also drop a copy next to the generation pack if present.
    pack_preview = dirs["root"] / "mascot-generation" / job_id / "output" / "composed-preview.png"
    pack_preview.parent.mkdir(parents=True, exist_ok=True)
    composed.save(pack_preview, format="PNG")

    job["status"] = "needs-review"
    job["fullEditSha256"] = sha256_file(target_full)
    job["layerSha256"] = sha256_file(target_layer)
    job["composedPreviewSha256"] = sha256_file(preview)
    job["composedPreview"] = str(preview)
    write_json(queue_path, {"version": 1, "jobs": jobs})
    print(
        f"OK    imported {job_id} -> needs-review "
        f"full={target_full} layer={target_layer}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("job")
    parser.add_argument("--input", required=True, help="Path to full-edit.png")
    args = parser.parse_args()
    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = (Path.cwd() / input_path).resolve()
    return import_full_edit(video_dir, args.job, input_path)


if __name__ == "__main__":
    sys.exit(main())
