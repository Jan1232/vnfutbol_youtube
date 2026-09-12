#!/usr/bin/env python3
"""Classify mascot assets and queue generation jobs for missing/stale layers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    DEFAULT_OUTFIT,
    load_json,
    load_poses,
    mask_by_pose,
    mask_path,
    outfit_by_id,
    pose_by_id,
    variant_by_pair,
    variant_is_stale,
    write_json,
)


def classify(asset: dict) -> tuple[str, dict]:
    mascot = asset.get("mascot") or {}
    pose_id = mascot.get("basePose")
    outfit_id = mascot.get("resolvedOutfit")
    if not pose_id or not outfit_id:
        return "UNRESOLVED", {}
    pose = pose_by_id(pose_id)
    outfit = outfit_by_id(outfit_id)
    if pose is None or outfit is None:
        return "UNRESOLVED", {}
    if outfit_id == DEFAULT_OUTFIT:
        return "REUSED", {"note": "default-home uses the base pose"}

    mask = mask_by_pose(pose_id)
    if mask is None or mask.get("status") == "rejected" or not mask_path(mask).exists():
        return "BLOCKED_MASK", {}

    variant = variant_by_pair(pose_id, outfit_id)
    if variant is None:
        return "MISSING", {"pose": pose, "outfit": outfit, "mask": mask}
    if variant_is_stale(variant, pose, mask, outfit) or variant.get("status") == "stale":
        return "STALE", {"pose": pose, "outfit": outfit, "mask": mask, "variant": variant}
    if variant.get("status") == "approved":
        return "REUSED", {"variant": variant}
    return "MISSING", {"pose": pose, "outfit": outfit, "mask": mask}


def make_job(asset: dict, pose: dict, outfit: dict, mask: dict, index: int) -> dict:
    stem = f"{pose['id']}__{outfit['id']}"
    return {
        "id": f"mascot-job-{index:03d}",
        "asset": asset["id"],
        "basePose": pose["id"],
        "basePoseFile": pose["file"],
        "canonicalReference": load_poses()["canonicalReference"]["file"],
        "clothingMask": mask["file"],
        "outfit": outfit["id"],
        "outfitDescription": outfit.get("generationDescription", ""),
        "targetFullEdit": f"assets/mascot/generated/{stem}_full.png",
        "targetLayer": f"assets/mascot/generated/{stem}_layer.png",
        "status": "pending",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to a video folder")
    args = parser.parse_args()
    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()

    assets = load_json(video_dir / "assets" / "assets.json").get("assets", [])
    jobs = []
    counts = {"REUSED": 0, "MISSING": 0, "STALE": 0, "BLOCKED_MASK": 0, "UNRESOLVED": 0}
    for asset in assets:
        if asset.get("type") != "MASCOT":
            continue
        label, extra = classify(asset)
        counts[label] += 1
        print(f"{label:13} {asset.get('id')} {asset.get('mascot', {}).get('basePose')} "
              f"{asset.get('mascot', {}).get('resolvedOutfit')}")
        if label in {"MISSING", "STALE"}:
            jobs.append(
                make_job(asset, extra["pose"], extra["outfit"], extra["mask"], len(jobs) + 1)
            )

    queue_path = video_dir / "assets" / "mascot-generation.json"
    write_json(queue_path, {"version": 1, "jobs": jobs})
    print(
        f"OK    jobs={len(jobs)} reused={counts['REUSED']} missing={counts['MISSING']} "
        f"stale={counts['STALE']} blocked={counts['BLOCKED_MASK']} unresolved={counts['UNRESOLVED']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
