#!/usr/bin/env python3
"""Resolve mascot outfits for a video and auto-generate missing variants.

Normal production entrypoint used by prepare_assets --plan/--prepare.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asset_prep_common import load_json, write_json
from mascot_auto_generate import generate_missing_variant
from mascot_common import (
    DEFAULT_OUTFIT,
    entities_by_id,
    load_visual_style,
    mask_by_pose,
    outfit_by_id,
    pose_by_id,
    resolve_mascot_outfit,
    variant_by_pair,
    variant_is_reusable,
)
from sync_mascot_assets import sync


def resolve_one_asset(asset: dict, entities: dict, visual_style: dict) -> str:
    mascot = asset.setdefault("mascot", {})
    intent = mascot.get("outfitIntent")
    if not intent:
        raise ValueError("missing mascot.outfitIntent")
    subject = mascot.get("subject")
    entity = entities.get(subject) if subject else None
    resolved = resolve_mascot_outfit(intent, mascot, entity, visual_style)
    if not outfit_by_id(resolved):
        raise ValueError(f"resolved outfit `{resolved}` is not in outfits.json")
    if outfit_by_id(resolved).get("active") is False:
        raise ValueError(f"resolved outfit `{resolved}` is inactive")
    mascot["resolvedOutfit"] = resolved
    return resolved


def resolve_mascot_assets(
    video_dir: Path,
    *,
    generate: bool = True,
    skip_vision: bool = False,
    sync_first: bool = True,
) -> dict:
    # Tests / offline planning can disable live generation.
    if os.environ.get("MASCOT_AUTO_GENERATE", "1").strip() in {"0", "false", "False", "no"}:
        generate = False
    if sync_first:
        code = sync(video_dir)
        if code != 0:
            return {"ok": False, "error": "sync_mascot_assets failed", "code": code}

    assets_path = video_dir / "assets" / "assets.json"
    payload = load_json(assets_path)
    entities = entities_by_id(video_dir)
    visual_style = load_visual_style(video_dir)

    summary = {
        "ok": True,
        "reused": 0,
        "generated": 0,
        "blocked_generation": 0,
        "blocked_reference": 0,
        "blocked_mask": 0,
        "needs_review": 0,
        "errors": 0,
        "results": [],
    }

    for asset in payload.get("assets") or []:
        if asset.get("type") != "MASCOT":
            continue
        try:
            resolved = resolve_one_asset(asset, entities, visual_style)
        except ValueError as exc:
            summary["errors"] += 1
            summary["results"].append({"asset": asset.get("id"), "result": "ERROR", "reason": str(exc)})
            continue

        mascot = asset["mascot"]
        pose_id = mascot.get("basePose")
        pose = pose_by_id(pose_id) if pose_id else None
        outfit = outfit_by_id(resolved)
        mask = mask_by_pose(pose_id) if pose_id else None
        if resolved == DEFAULT_OUTFIT:
            summary["reused"] += 1
            summary["results"].append(
                {"asset": asset.get("id"), "result": "REUSED", "pose": pose_id, "outfit": resolved}
            )
            continue

        if pose and outfit and mask and variant_is_reusable(
            variant_by_pair(pose_id, resolved), pose, mask, outfit
        ):
            summary["reused"] += 1
            summary["results"].append(
                {
                    "asset": asset.get("id"),
                    "result": "REUSED",
                    "pose": pose_id,
                    "outfit": resolved,
                }
            )
            continue

        if not generate:
            summary["results"].append(
                {
                    "asset": asset.get("id"),
                    "result": "MISSING",
                    "pose": pose_id,
                    "outfit": resolved,
                }
            )
            continue

        outcome = generate_missing_variant(
            pose_id,
            resolved,
            skip_vision=skip_vision,
        )
        result = outcome.get("result")
        summary["results"].append(
            {
                "asset": asset.get("id"),
                "pose": pose_id,
                "outfit": resolved,
                **outcome,
            }
        )
        if result == "REUSED":
            summary["reused"] += 1
        elif result == "GENERATED":
            summary["generated"] += 1
        elif result == "BLOCKED_GENERATION":
            summary["blocked_generation"] += 1
        elif result == "BLOCKED_REFERENCE":
            summary["blocked_reference"] += 1
        elif result == "BLOCKED_MASK":
            summary["blocked_mask"] += 1
        elif result == "NEEDS_REVIEW":
            summary["needs_review"] += 1
        else:
            summary["errors"] += 1

    write_json(assets_path, payload)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--no-generate", action="store_true")
    parser.add_argument("--skip-vision", action="store_true")
    parser.add_argument("--no-sync", action="store_true")
    args = parser.parse_args()
    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()
    summary = resolve_mascot_assets(
        video_dir,
        generate=not args.no_generate,
        skip_vision=args.skip_vision,
        sync_first=not args.no_sync,
    )
    print(
        "OK    "
        f"reused={summary['reused']} generated={summary['generated']} "
        f"blocked_generation={summary['blocked_generation']} "
        f"blocked_reference={summary['blocked_reference']} "
        f"needs_review={summary['needs_review']} errors={summary['errors']}"
    )
    for item in summary.get("results") or []:
        print(
            f"{item.get('result', '?'):20} {item.get('asset')} "
            f"{item.get('pose')} + {item.get('outfit')} "
            f"{item.get('reason') or ''}"
        )
    return 0 if summary.get("ok") and summary.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
