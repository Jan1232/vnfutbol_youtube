#!/usr/bin/env python3
"""Deterministic outfit resolver. Does not infer context from prose."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    entities_by_id,
    load_json,
    outfit_by_id,
    resolve_outfit,
    write_json,
)


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def resolve_asset(asset: dict, entities: dict) -> str:
    if asset.get("type") != "MASCOT":
        raise ValueError("not a MASCOT asset")
    mascot = asset.get("mascot") or {}
    intent = mascot.get("outfitIntent")
    if not intent:
        raise ValueError("missing mascot.outfitIntent")
    entity = None
    subject = mascot.get("subject")
    if subject:
        entity = entities.get(subject)
        if entity is None:
            raise ValueError(f"subject `{subject}` is missing from entities.json")
    resolved = resolve_outfit(intent, mascot, entity)
    if not outfit_by_id(resolved):
        raise ValueError(f"resolved outfit `{resolved}` is not in outfits.json")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to a video folder")
    parser.add_argument("asset", nargs="?", help="Asset id, e.g. asset-012")
    parser.add_argument("--all", action="store_true", help="Resolve every MASCOT asset")
    args = parser.parse_args()
    if not args.asset and not args.all:
        parser.error("pass an asset id or --all")

    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()
    assets_path = video_dir / "assets" / "assets.json"
    if not assets_path.exists():
        return fail(f"missing {assets_path}")

    payload = load_json(assets_path)
    entities = entities_by_id(video_dir)
    targets = []
    for asset in payload.get("assets", []):
        if asset.get("type") != "MASCOT":
            continue
        if args.all or asset.get("id") == args.asset:
            targets.append(asset)
    if not args.all and not targets:
        return fail(f"MASCOT asset `{args.asset}` not found")

    for asset in targets:
        try:
            resolved = resolve_asset(asset, entities)
        except ValueError as exc:
            return fail(f"{asset.get('id')}: {exc}")
        mascot = asset.setdefault("mascot", {})
        mascot["resolvedOutfit"] = resolved
        print(f"OK    {asset['id']} -> {resolved}")

    write_json(assets_path, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
