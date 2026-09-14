#!/usr/bin/env python3
"""Resolve poseIntent → approved pose and materialize MASCOT assets from visual-plan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asset_prep_common import load_json, stable_pick, write_json
from mascot_common import (
    DEFAULT_OUTFIT,
    entities_by_id,
    load_poses,
    outfit_by_id,
    pose_by_id,
    resolve_outfit,
)

YAMAL_SUBJECT = "player-lamine-yamal"


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def approved_poses() -> list[dict]:
    return [p for p in load_poses().get("poses", []) if p.get("approved") and p.get("id")]


def match_pose_candidates(intent: str, poses: list[dict]) -> list[dict]:
    if not intent:
        return []
    exact = [p for p in poses if p["id"] == intent]
    if exact:
        return exact
    by_category = [p for p in poses if p.get("category") == intent]
    if by_category:
        return by_category
    by_prefix = [p for p in poses if p["id"].startswith(f"{intent}-")]
    if by_prefix:
        return by_prefix
    by_tag = [p for p in poses if intent in (p.get("tags") or [])]
    if by_tag:
        return by_tag
    if "-" in intent:
        head = intent.split("-", 1)[0]
        by_head_cat = [p for p in poses if p.get("category") == head]
        if by_head_cat:
            return by_head_cat
        by_head_tag = [p for p in poses if head in (p.get("tags") or [])]
        if by_head_tag:
            return by_head_tag
    return []


def resolve_base_pose(scene: dict, poses: list[dict]) -> str:
    mascot = scene.get("mascot") or {}
    frozen = mascot.get("basePose")
    if frozen:
        pose = pose_by_id(frozen)
        if pose is None or not pose.get("approved"):
            raise ValueError(
                f"{scene.get('id')}: frozen basePose `{frozen}` is missing or not approved"
            )
        return frozen
    intent = mascot.get("poseIntent")
    if not intent:
        raise ValueError(f"{scene.get('id')}: mascot missing poseIntent")
    candidates = match_pose_candidates(intent, poses)
    if not candidates:
        raise ValueError(
            f"{scene.get('id')}: poseIntent `{intent}` matches no approved pose "
            "(closed library; do not invent poses)"
        )
    return stable_pick([p["id"] for p in candidates], scene["id"])


def scene_outfit_intent(scene: dict) -> str:
    if scene.get("outfitIntent"):
        return scene["outfitIntent"]
    mascot = scene.get("mascot") or {}
    if mascot.get("outfitIntent"):
        return mascot["outfitIntent"]
    raise ValueError(f"{scene.get('id')}: missing outfitIntent")


def subject_for_intent(intent: str) -> str | None:
    if intent in {"current-club", "national-team"}:
        return YAMAL_SUBJECT
    return None


def next_mascot_asset_id(existing_ids: set[str], base_pose: str, outfit: str) -> str:
    preferred = f"mascot-{base_pose}__{outfit}"
    if preferred not in existing_ids:
        return preferred
    # Collision with different content should not happen for same pair.
    return preferred


def find_existing_pair(assets: list[dict], base_pose: str, outfit: str) -> dict | None:
    for asset in assets:
        if asset.get("type") != "MASCOT":
            continue
        mascot = asset.get("mascot") or {}
        if mascot.get("basePose") == base_pose and mascot.get("resolvedOutfit") == outfit:
            return asset
        # Pre-resolve assets may only have outfitIntent + basePose
        if (
            mascot.get("basePose") == base_pose
            and mascot.get("resolvedOutfit") is None
            and mascot.get("outfitIntent")
        ):
            # defer — only match fully resolved pairs for dedupe key
            pass
    return None


def make_mascot_asset(
    asset_id: str,
    base_pose: str,
    outfit_intent: str,
    resolved_outfit: str,
    subject: str | None,
    scenes: list[str],
) -> dict:
    return {
        "id": asset_id,
        "type": "MASCOT",
        "source": "library",
        "status": "planned",
        "usedInScenes": sorted(set(scenes)),
        "tags": ["mascot", base_pose, resolved_outfit],
        "sourceUrl": None,
        "license": None,
        "author": None,
        "rightsStatus": "owned/generated",
        "downloadToPublicRepo": True,
        "mascot": {
            "basePose": base_pose,
            "outfitIntent": outfit_intent,
            "resolvedOutfit": resolved_outfit,
            "subject": subject,
            "variantPolicy": "reuse-else-generate",
            "explicitOutfit": None,
        },
    }


def sync(video_dir: Path) -> int:
    plan_path = video_dir / "scenes" / "visual-plan.json"
    assets_path = video_dir / "assets" / "assets.json"
    if not plan_path.exists():
        return fail(f"missing {plan_path}")
    if not assets_path.exists():
        return fail(f"missing {assets_path}")

    plan = load_json(plan_path)
    assets_payload = load_json(assets_path)
    assets = list(assets_payload.get("assets") or [])
    entities = entities_by_id(video_dir)
    poses = approved_poses()
    existing_ids = {a["id"] for a in assets if a.get("id")}

    pair_to_asset: dict[tuple[str, str], dict] = {}
    for asset in assets:
        if asset.get("type") != "MASCOT":
            continue
        mascot = asset.get("mascot") or {}
        pose = mascot.get("basePose")
        outfit = mascot.get("resolvedOutfit")
        if pose and outfit:
            pair_to_asset[(pose, outfit)] = asset

    scene_updates = 0
    created = 0
    reused = 0
    errors: list[str] = []

    for scene in plan.get("scenes") or []:
        if not scene.get("mascot"):
            continue
        scene_id = scene["id"]
        try:
            base_pose = resolve_base_pose(scene, poses)
            outfit_intent = scene_outfit_intent(scene)
            subject = subject_for_intent(outfit_intent)
            entity = entities.get(subject) if subject else None
            if subject and entity is None:
                raise ValueError(f"subject `{subject}` missing from entities.json")
            resolved = resolve_outfit(
                outfit_intent,
                {"explicitOutfit": (scene.get("mascot") or {}).get("explicitOutfit")},
                entity,
            )
            if not outfit_by_id(resolved):
                raise ValueError(f"resolved outfit `{resolved}` not in outfits.json")
        except ValueError as exc:
            errors.append(str(exc))
            continue

        key = (base_pose, resolved)
        asset = pair_to_asset.get(key)
        if asset is None:
            asset_id = next_mascot_asset_id(existing_ids, base_pose, resolved)
            asset = make_mascot_asset(
                asset_id, base_pose, outfit_intent, resolved, subject, [scene_id]
            )
            assets.append(asset)
            existing_ids.add(asset_id)
            pair_to_asset[key] = asset
            created += 1
        else:
            scenes = list(asset.get("usedInScenes") or [])
            if scene_id not in scenes:
                scenes.append(scene_id)
                asset["usedInScenes"] = sorted(scenes)
            mascot = asset.setdefault("mascot", {})
            mascot["basePose"] = base_pose
            mascot["outfitIntent"] = outfit_intent
            mascot["resolvedOutfit"] = resolved
            mascot["subject"] = subject
            mascot.setdefault("variantPolicy", "reuse-else-generate")
            reused += 1

        # Freeze casting onto visual-plan without changing editorial order/overlays
        scene["mascot"]["basePose"] = base_pose
        scene["mascot"]["assetId"] = asset["id"]
        scene_updates += 1

    if errors:
        for message in errors:
            print(f"ERROR {message}")
        return 1

    assets_payload["assets"] = assets
    write_json(assets_path, assets_payload)
    write_json(plan_path, plan)

    default_pairs = sum(
        1 for (pose, outfit) in pair_to_asset if outfit == DEFAULT_OUTFIT
    )
    print(
        f"OK    scenes={scene_updates} created={created} "
        f"reused_pairs={len(pair_to_asset)} default_pairs={default_pairs}"
    )
    for (pose, outfit), asset in sorted(pair_to_asset.items()):
        print(f"PAIR  {asset['id']} {pose} + {outfit} scenes={asset.get('usedInScenes')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to a video folder")
    args = parser.parse_args()
    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()
    return sync(video_dir)


if __name__ == "__main__":
    sys.exit(main())
