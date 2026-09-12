#!/usr/bin/env python3
"""Look up a reusable outfit layer for a pose + outfit pair."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    DEFAULT_OUTFIT,
    mask_by_pose,
    outfit_by_id,
    pose_by_id,
    variant_by_pair,
    variant_is_stale,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose", required=True)
    parser.add_argument("--outfit", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    pose = pose_by_id(args.pose)
    outfit = outfit_by_id(args.outfit)
    if pose is None or outfit is None:
        payload = {"result": "MISSING", "reason": "unknown pose or outfit"}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else "MISSING")
        return 0

    if args.outfit == DEFAULT_OUTFIT:
        payload = {
            "result": "FOUND",
            "id": None,
            "file": pose["file"],
            "status": "default-home",
            "hashStatus": "n/a",
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("FOUND")
            print("id          (base pose, no overlay)")
            print(f"file        {pose['file']}")
            print("status      default-home")
            print("hash status n/a")
        return 0

    variant = variant_by_pair(args.pose, args.outfit)
    if variant is None:
        print("MISSING" if not args.json else json.dumps({"result": "MISSING"}, indent=2))
        return 0

    mask = mask_by_pose(args.pose)
    stale = variant_is_stale(variant, pose, mask, outfit)
    hash_status = "STALE" if stale else "OK"
    payload = {
        "result": "FOUND",
        "id": variant.get("id"),
        "file": variant.get("file"),
        "status": variant.get("status"),
        "hashStatus": hash_status,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("FOUND")
        print(f"id          {variant.get('id')}")
        print(f"file        {variant.get('file')}")
        print(f"status      {variant.get('status')}")
        print(f"hash status {hash_status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
