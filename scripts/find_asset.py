#!/usr/bin/env python3
"""Deterministic search over the closed mascot pose library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "channel-assets" / "mascot" / "poses.json"


def load_poses() -> list[dict]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data.get("poses", [])


def matches(pose: dict, args: argparse.Namespace) -> bool:
    if not args.include_unapproved and pose.get("approved") is not True:
        return False
    tags = {str(tag).lower() for tag in pose.get("tags", [])}
    if args.tag and not all(tag.lower() in tags for tag in args.tag):
        return False
    if args.category and pose.get("category") != args.category:
        return False
    if args.direction and pose.get("direction") != args.direction:
        return False
    if args.framing and pose.get("framing") != args.framing:
        return False
    if args.prop and pose.get("prop") != args.prop:
        return False
    return True


def format_human(pose: dict) -> str:
    tags = ", ".join(pose.get("tags", []))
    return "\n".join(
        [
            f"ID          {pose.get('id')}",
            f"file        {pose.get('file')}",
            f"category    {pose.get('category')}",
            f"description {pose.get('description')}",
            f"tags        {tags}",
            f"direction   {pose.get('direction')}",
            f"framing     {pose.get('framing')}",
            f"prop        {pose.get('prop')}",
        ]
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", action="append", help="Require this tag. Repeatable, AND logic.")
    parser.add_argument("--category")
    parser.add_argument("--direction", choices=["front", "left", "right"])
    parser.add_argument("--framing", choices=["chest-up", "waist-up", "upper-thigh"])
    parser.add_argument(
        "--prop",
        choices=["ball", "phone", "yellow-card", "red-card", "newspaper", "clipboard"],
    )
    parser.add_argument("--json", action="store_true", help="Print a JSON array")
    parser.add_argument(
        "--include-unapproved",
        action="store_true",
        help="Include poses that are not approved",
    )
    args = parser.parse_args()

    found = [pose for pose in load_poses() if matches(pose, args)]
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=2))
        return 0

    if not found:
        print("No matches.")
        return 0

    print(f"Found {len(found)} pose(s)\n")
    print("\n---\n".join(format_human(pose) for pose in found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
