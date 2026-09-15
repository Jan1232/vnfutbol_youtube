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
    load_visual_style,
    outfit_by_id,
    pose_by_id,
    resolve_mascot_outfit,
)

def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def player_entities(entities: dict[str, dict]) -> list[dict]:
    return [
        entity
        for entity in entities.values()
        if isinstance(entity, dict) and entity.get("type") == "PLAYER" and entity.get("id")
    ]


def resolve_subject(
    scene: dict,
    outfit_intent: str,
    entities: dict[str, dict],
) -> str | None:
    """Resolve mascot subject without hardcoding any player id."""
    mascot = scene.get("mascot") or {}
    explicit = mascot.get("subject")
    if explicit:
        if explicit not in entities:
            raise ValueError(
                f"{scene.get('id')}: mascot.subject `{explicit}` is missing from entities.json"
            )
        return explicit
    if outfit_intent not in {"current-club", "national-team"}:
        return None
    players = player_entities(entities)
    if len(players) == 1:
        subject = players[0]["id"]
        mascot["subject"] = subject
        scene["mascot"] = mascot
        return subject
    if not players:
        raise ValueError(
            f"{scene.get('id')}: outfitIntent={outfit_intent} requires mascot.subject, "
            "but context/entities.json has no PLAYER entities"
        )
    ids = ", ".join(sorted(p["id"] for p in players))
    raise ValueError(
        f"{scene.get('id')}: outfitIntent={outfit_intent} requires explicit mascot.subject "
        f"because multiple PLAYER entities exist ({ids})"
    )


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
    frozen = mascot.get("basePose") or mascot.get("pose")
    if frozen:
        pose = pose_by_id(frozen)
        if pose is None or not pose.get("approved"):
            raise ValueError(
                f"{scene.get('id')}: frozen basePose `{frozen}` is missing or not approved"
            )
        return frozen
    intent = mascot.get("poseIntent") or mascot.get("pose")
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
    explicit_outfit: str | None = None,
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
            "explicitOutfit": explicit_outfit if outfit_intent == "explicit" else None,
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
    visual_style = load_visual_style(video_dir)
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
    active_keys: set[tuple[str, str]] = set()
    scenes_by_key: dict[tuple[str, str], list[str]] = {}

    for scene in plan.get("scenes") or []:
        if not scene.get("mascot"):
            continue
        scene_id = scene["id"]
        try:
            base_pose = resolve_base_pose(scene, poses)
            outfit_intent = scene_outfit_intent(scene)
            subject = resolve_subject(scene, outfit_intent, entities)
            entity = entities.get(subject) if subject else None
            explicit_outfit = (
                (scene.get("mascot") or {}).get("outfit")
                or (scene.get("mascot") or {}).get("explicitOutfit")
            )
            if outfit_intent == "explicit" and not explicit_outfit:
                raise ValueError(f"{scene_id}: outfitIntent=explicit requires mascot.outfit")
            resolved = resolve_mascot_outfit(
                outfit_intent,
                {
                    "outfit": explicit_outfit,
                    "explicitOutfit": explicit_outfit,
                },
                entity,
                visual_style,
            )
            outfit = outfit_by_id(resolved)
            if not outfit:
                raise ValueError(f"resolved outfit `{resolved}` not in outfits.json")
            if outfit.get("active") is False:
                raise ValueError(
                    f"resolved outfit `{resolved}` is inactive; migrate scene to an active kit"
                )
        except ValueError as exc:
            errors.append(str(exc))
            continue

        key = (base_pose, resolved)
        active_keys.add(key)
        scenes_by_key.setdefault(key, []).append(scene_id)
        asset = pair_to_asset.get(key)
        if asset is None:
            asset_id = next_mascot_asset_id(existing_ids, base_pose, resolved)
            asset = make_mascot_asset(
                asset_id,
                base_pose,
                outfit_intent,
                resolved,
                subject,
                [scene_id],
                explicit_outfit=explicit_outfit if outfit_intent == "explicit" else None,
            )
            assets.append(asset)
            existing_ids.add(asset_id)
            pair_to_asset[key] = asset
            created += 1
        else:
            mascot = asset.setdefault("mascot", {})
            mascot["basePose"] = base_pose
            mascot["outfitIntent"] = outfit_intent
            mascot["resolvedOutfit"] = resolved
            mascot["subject"] = subject
            mascot["explicitOutfit"] = (
                explicit_outfit if outfit_intent == "explicit" else None
            )
            mascot.setdefault("variantPolicy", "reuse-else-generate")
            asset["tags"] = ["mascot", base_pose, resolved]
            reused += 1

        # Freeze casting onto visual-plan without changing editorial order/overlays
        scene["mascot"]["basePose"] = base_pose
        scene["mascot"]["assetId"] = asset["id"]
        if outfit_intent == "explicit":
            scene["mascot"]["outfit"] = explicit_outfit
            scene["mascot"]["explicitOutfit"] = explicit_outfit
        scene_updates += 1

    if errors:
        for message in errors:
            print(f"ERROR {message}")
        return 1

    for key, scene_ids in scenes_by_key.items():
        asset = pair_to_asset[key]
        asset["usedInScenes"] = sorted(set(scene_ids))

    # Drop MASCOT assets no longer referenced by any scene pair (e.g. legacy spain-home).
    assets = [
        asset
        for asset in assets
        if asset.get("type") != "MASCOT"
        or (
            (asset.get("mascot") or {}).get("basePose"),
            (asset.get("mascot") or {}).get("resolvedOutfit"),
        )
        in active_keys
    ]
    assets_payload["assets"] = assets
    write_json(assets_path, assets_payload)
    write_json(plan_path, plan)

    default_pairs = sum(1 for (_pose, outfit) in active_keys if outfit == DEFAULT_OUTFIT)
    print(
        f"OK    scenes={scene_updates} created={created} "
        f"active_pairs={len(active_keys)} default_pairs={default_pairs}"
    )
    for pose, outfit in sorted(active_keys):
        asset = pair_to_asset[(pose, outfit)]
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
