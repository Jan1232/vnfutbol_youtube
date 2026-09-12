#!/usr/bin/env python3
"""Promote an approved extracted layer into the shared outfit library."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    DEFAULT_OUTFIT,
    MASCOT,
    hashes_current,
    layer_destination,
    load_json,
    load_variants,
    mask_by_pose,
    mask_path,
    outfit_by_id,
    pose_by_id,
    pose_path,
    sha256_file,
    variant_id,
    VARIANTS_PATH,
    write_json,
)


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("job")
    args = parser.parse_args()

    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()
    jobs = load_json(video_dir / "assets" / "mascot-generation.json").get("jobs", [])
    job = next((item for item in jobs if item.get("id") == args.job), None)
    if job is None:
        return fail(f"unknown job `{args.job}`")
    if job.get("status") != "approved":
        return fail(f"job `{args.job}` must have status=approved")
    if job.get("outfit") == DEFAULT_OUTFIT:
        return fail("default-home does not use an outfit layer")

    pose = pose_by_id(job["basePose"])
    outfit = outfit_by_id(job["outfit"])
    mask = mask_by_pose(job["basePose"])
    if pose is None or outfit is None or mask is None:
        return fail("pose, outfit or mask is missing")
    if mask.get("status") != "approved":
        return fail(f"clothing mask for `{job['basePose']}` is not approved")
    if not mask_path(mask).exists():
        return fail(f"clothing mask file is missing: {mask.get('file')}")

    current = hashes_current(pose, mask, outfit)
    if sha256_file(pose_path(pose)) != pose.get("sha256"):
        return fail("base pose file no longer matches poses.json sha256")
    if sha256_file(mask_path(mask)) != mask.get("sha256"):
        return fail("clothing mask file no longer matches pose-masks.json sha256")
    if mask.get("basePoseSha256") != pose.get("sha256"):
        return fail("clothing mask is stale relative to the base pose")
    for key in ("basePoseSha256", "maskSha256", "outfitSpecSha256"):
        if key in job and job[key] != current[key]:
            return fail(f"{key} changed since the job was created; extract the layer again")

    source = video_dir / job["targetLayer"]
    if not source.exists():
        return fail(f"missing extracted layer {source}")

    dest = layer_destination(outfit, pose["id"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)

    record = {
        "id": variant_id(pose["id"], outfit["id"]),
        "basePose": pose["id"],
        "outfit": outfit["id"],
        "type": "outfit-layer",
        "file": dest.relative_to(MASCOT).as_posix(),
        "status": "approved",
        "sha256": sha256_file(dest),
        **hashes_current(pose, mask, outfit),
    }

    data = load_variants()
    others = [
        item
        for item in data.get("variants", [])
        if not (item.get("basePose") == pose["id"] and item.get("outfit") == outfit["id"])
    ]
    others.append(record)
    others.sort(key=lambda item: item["id"])
    write_json(VARIANTS_PATH, {"version": 1, "variants": others})
    print(f"OK    promoted {record['id']} -> {record['file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
