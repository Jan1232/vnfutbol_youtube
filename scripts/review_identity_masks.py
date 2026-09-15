#!/usr/bin/env python3
"""Approve / reject identity masks (same approval contract as clothing masks)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    IDENTITY_MASKS_PATH,
    identity_mask_by_pose,
    identity_mask_path,
    load_identity_masks,
    pose_by_id,
    sha256_file,
    write_json,
)


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def integrity(pose_id: str) -> tuple[str, str]:
    pose = pose_by_id(pose_id)
    if pose is None or not pose.get("approved"):
        return "no_pose", f"approved pose `{pose_id}` missing"
    mask = identity_mask_by_pose(pose_id)
    if mask is None:
        return "no_mask", "identity mask entry missing"
    path = identity_mask_path(mask)
    if not path.exists():
        return "missing", f"file missing: {mask.get('file')}"
    digest = sha256_file(path)
    if digest != mask.get("sha256"):
        return "hash_mismatch", f"{digest[:12]}… != {str(mask.get('sha256'))[:12]}…"
    if mask.get("basePoseSha256") != pose.get("sha256"):
        return "stale_pose", "basePoseSha256 mismatch"
    return "ok", mask.get("status") or "unknown"


def update_status(pose_ids: list[str], status: str) -> int:
    data = load_identity_masks()
    masks = list(data.get("masks") or [])
    by_pose = {m.get("basePose"): m for m in masks}
    updated = 0
    for pose_id in pose_ids:
        state, detail = integrity(pose_id)
        if state != "ok":
            print(f"ERROR {pose_id}: cannot set {status} ({state}: {detail})")
            return 1
        record = by_pose[pose_id]
        if status == "approved" and record.get("status") == "rejected":
            print(f"ERROR {pose_id}: rejected mask cannot be approved without regenerate")
            return 1
        record["status"] = status
        updated += 1
        print(f"{status.upper()} {pose_id}")
    write_json(IDENTITY_MASKS_PATH, {"version": 1, "masks": sorted(masks, key=lambda m: m.get("basePose") or "")})
    print(f"OK    updated={updated}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--approve", nargs="+", metavar="POSE")
    parser.add_argument("--reject", nargs="+", metavar="POSE")
    args = parser.parse_args()
    if args.status:
        data = load_identity_masks()
        for mask in data.get("masks") or []:
            pose_id = mask.get("basePose")
            state, detail = integrity(pose_id)
            print(f"{pose_id:24} status={mask.get('status')} integrity={state} ({detail})")
        return 0
    if args.approve:
        return update_status(args.approve, "approved")
    if args.reject:
        return update_status(args.reject, "rejected")
    parser.error("pass --status, --approve POSE..., or --reject POSE...")
    return 2


if __name__ == "__main__":
    sys.exit(main())
