#!/usr/bin/env python3
"""Validate a video production folder against the pipeline contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASCOT_MANIFEST = ROOT / "channel-assets" / "mascot" / "poses.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    DEFAULT_OUTFIT,
    OUTFIT_INTENTS,
    VARIANT_POLICIES,
    entities_by_id,
    outfit_by_id,
    pose_by_id,
    variant_by_pair,
)

REQUIRED_DIRS = (
    "research",
    "script",
    "factcheck",
    "assets",
    "audio",
    "scenes",
    "renders",
)
REQUIRED_FILES = (
    "metadata.json",
    "research/research.md",
    "script/script.md",
    "factcheck/factcheck.md",
    "assets/assets.json",
    "audio/voice.json",
    "scenes/timeline.json",
)
METADATA_STATUSES = {
    "idea",
    "research",
    "script",
    "factcheck",
    "visual-plan",
    "assets",
    "voice",
    "timeline",
    "draft",
    "published",
}
ASSET_TYPES = {
    "MASCOT",
    "PLAYER_PHOTO",
    "HISTORICAL_PHOTO",
    "GENERATED_IMAGE",
    "MEME",
    "STAT",
    "TEXT",
    "DIAGRAM",
    "VIDEO",
    "NEWSPAPER",
    "TROPHY",
    "MAP",
    "ARCHIVE",
    "COACH_PHOTO",
    "STADIUM",
    "CLUB",
}
ASSET_SOURCES = {"library", "web", "generated", "video-specific"}
ASSET_STATUSES = {"planned", "found", "ready", "missing", "rejected"}
ANIMATIONS = {
    "slowZoom",
    "zoomOut",
    "slideLeft",
    "slideRight",
    "slideUp",
    "fade",
    "hardCut",
    "shake",
    "counter",
    "panLeft",
    "panRight",
}
SCRIPT_RE = re.compile(r"SCRIPT-\d+")
FACT_RE = re.compile(r"FACT-\d+")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_json(path: Path, report: Report) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.error(f"{path.name}: invalid JSON ({exc})")
        return None


def mascot_ids() -> set[str]:
    if not MASCOT_MANIFEST.exists():
        return set()
    data = json.loads(MASCOT_MANIFEST.read_text(encoding="utf-8"))
    return {pose["id"] for pose in data.get("poses", []) if "id" in pose}


def unique_ids(ids: list[str], kind: str, report: Report) -> set[str]:
    for value, count in Counter(ids).items():
        if count > 1:
            report.error(f"duplicate {kind} id: {value}")
    return set(ids)


def validate_metadata(payload, folder_name: str, report: Report) -> None:
    if not isinstance(payload, dict):
        report.error("metadata.json: root must be an object")
        return
    if payload.get("slug") != folder_name:
        report.error(
            f"metadata.json: slug `{payload.get('slug')}` does not match folder `{folder_name}`"
        )
    if not isinstance(payload.get("title"), str):
        report.error("metadata.json: title must be a string")
    created_at = payload.get("createdAt")
    if not isinstance(created_at, str) or not created_at.strip():
        report.error("metadata.json: createdAt must be a non-empty string")
    if payload.get("status") not in METADATA_STATUSES:
        report.error(f"metadata.json: invalid status `{payload.get('status')}`")


def validate_assets(payload, folder_name: str, report: Report) -> set[str]:
    ids: list[str] = []
    if not isinstance(payload, dict):
        report.error("assets.json: root must be an object")
        return set()
    if payload.get("version") != 1:
        report.error("assets.json: version must be 1")
    if not isinstance(payload.get("video"), str):
        report.error("assets.json: video must be a string")
    elif payload.get("video") != folder_name:
        report.error(
            f"assets.json: video `{payload.get('video')}` does not match folder `{folder_name}`"
        )
    assets = payload.get("assets")
    if not isinstance(assets, list):
        report.error("assets.json: assets must be a list")
        return set()

    for index, asset in enumerate(assets):
        prefix = f"assets.json[{index}]"
        if not isinstance(asset, dict):
            report.error(f"{prefix}: must be an object")
            continue
        asset_id = asset.get("id")
        if not asset_id:
            report.error(f"{prefix}: missing id")
            continue
        ids.append(asset_id)
        if asset.get("type") not in ASSET_TYPES:
            report.error(f"{asset_id}: invalid type")
        if asset.get("source") not in ASSET_SOURCES:
            report.error(f"{asset_id}: invalid source")
        if asset.get("status") not in ASSET_STATUSES:
            report.error(f"{asset_id}: invalid status")
        if not isinstance(asset.get("usedInScenes"), list):
            report.error(f"{asset_id}: usedInScenes must be a list")
        if not isinstance(asset.get("tags"), list):
            report.error(f"{asset_id}: tags must be a list")
        for field in ("sourceUrl", "license", "author"):
            value = asset.get(field, None)
            if value is not None and not isinstance(value, str):
                report.error(f"{asset_id}: {field} must be string or null")
        if asset.get("type") == "MASCOT" and asset.get("mascot") is not None:
            if not isinstance(asset.get("mascot"), dict):
                report.error(f"{asset_id}: mascot must be an object")
    return unique_ids(ids, "asset", report)


def validate_mascot_assets(assets: list, video_dir: Path, report: Report) -> None:
    entities = entities_by_id(video_dir)
    for asset in assets:
        if asset.get("type") != "MASCOT" or not isinstance(asset.get("mascot"), dict):
            continue
        asset_id = asset.get("id")
        mascot = asset["mascot"]
        pose_id = mascot.get("basePose")
        if pose_id and pose_by_id(pose_id) is None:
            report.error(f"{asset_id}: mascot.basePose `{pose_id}` does not exist")
        intent = mascot.get("outfitIntent")
        if intent is not None and intent not in OUTFIT_INTENTS:
            report.error(f"{asset_id}: invalid outfitIntent `{intent}`")
        policy = mascot.get("variantPolicy")
        if policy is not None and policy not in VARIANT_POLICIES:
            report.error(f"{asset_id}: invalid variantPolicy `{policy}`")
        subject = mascot.get("subject")
        if subject:
            if not (video_dir / "context" / "entities.json").exists():
                report.error(f"{asset_id}: subject is set but context/entities.json is missing")
            elif subject not in entities:
                report.error(f"{asset_id}: subject `{subject}` is missing from entities.json")
        resolved = mascot.get("resolvedOutfit")
        if resolved and outfit_by_id(resolved) is None:
            report.error(f"{asset_id}: resolvedOutfit `{resolved}` is not in outfits.json")
        if asset.get("status") == "ready" and resolved and resolved != DEFAULT_OUTFIT:
            variant = variant_by_pair(pose_id, resolved) if pose_id else None
            if variant is None or variant.get("status") != "approved":
                report.error(
                    f"{asset_id}: status=ready requires an approved outfit variant "
                    f"for {pose_id} + {resolved}"
                )


def validate_voice(payload, script_ids: set[str], report: Report) -> set[str]:
    ids: list[str] = []
    if not isinstance(payload, dict):
        report.error("voice.json: root must be an object")
        return set()
    items = payload.get("items")
    if not isinstance(items, list):
        report.error("voice.json: items must be a list")
        return set()
    for index, item in enumerate(items):
        prefix = f"voice.json[{index}]"
        if not isinstance(item, dict):
            report.error(f"{prefix}: must be an object")
            continue
        voice_id = item.get("id")
        if not voice_id:
            report.error(f"{prefix}: missing id")
            continue
        ids.append(voice_id)
        script_id = item.get("script")
        if script_id and script_id not in script_ids:
            report.error(f"{voice_id}: script `{script_id}` is missing from script.md")
        if "pauseAfter" in item and not isinstance(item["pauseAfter"], int):
            report.error(f"{voice_id}: pauseAfter must be an integer (ms)")
    return unique_ids(ids, "voice", report)


def validate_timeline(
    payload,
    asset_ids: set[str],
    voice_ids: set[str],
    script_ids: set[str],
    pose_ids: set[str],
    report: Report,
) -> set[str]:
    ids: list[str] = []
    if not isinstance(payload, dict):
        report.error("timeline.json: root must be an object")
        return set()
    if payload.get("version") != 1:
        report.error("timeline.json: version must be 1")
    for field in ("fps", "width", "height"):
        if not isinstance(payload.get(field), int):
            report.error(f"timeline.json: {field} must be an integer")
    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        report.error("timeline.json: scenes must be a list")
        return set()

    for index, scene in enumerate(scenes):
        prefix = f"timeline.json[{index}]"
        if not isinstance(scene, dict):
            report.error(f"{prefix}: must be an object")
            continue
        scene_id = scene.get("id")
        if not scene_id:
            report.error(f"{prefix}: missing id")
            continue
        ids.append(scene_id)
        voice = scene.get("voice")
        if voice and voice not in voice_ids:
            report.error(f"{scene_id}: voice `{voice}` is missing from voice.json")
        script = scene.get("script")
        if script and script not in script_ids:
            report.error(f"{scene_id}: script `{script}` is missing from script.md")
        animation = scene.get("animation")
        if animation and animation not in ANIMATIONS:
            report.error(f"{scene_id}: invalid animation `{animation}`")
        visual = scene.get("visual") or {}
        visual_asset = visual.get("asset")
        if visual_asset and visual_asset not in asset_ids and visual_asset not in pose_ids:
            report.error(
                f"{scene_id}: visual.asset `{visual_asset}` is not in assets.json or poses.json"
            )
    return unique_ids(ids, "scene", report)


def validate_video(video_dir: Path) -> Report:
    report = Report()
    if not video_dir.exists() or not video_dir.is_dir():
        report.error(f"video folder does not exist: {video_dir}")
        return report

    for name in REQUIRED_DIRS:
        if not (video_dir / name).is_dir():
            report.error(f"missing folder: {name}/")
    for rel in REQUIRED_FILES:
        if not (video_dir / rel).is_file():
            report.error(f"missing file: {rel}")

    required_ok = all((video_dir / rel).is_file() for rel in REQUIRED_FILES)
    if not required_ok:
        return report

    script_text = (video_dir / "script" / "script.md").read_text(encoding="utf-8")
    research_text = (video_dir / "research" / "research.md").read_text(encoding="utf-8")
    script_ids = set(SCRIPT_RE.findall(script_text))
    fact_ids = set(FACT_RE.findall(research_text))
    if "FACT-" in script_text:
        for fact_id in FACT_RE.findall(script_text):
            if fact_id not in fact_ids:
                report.error(f"script.md references missing {fact_id}")

    metadata_payload = load_json(video_dir / "metadata.json", report)
    assets_payload = load_json(video_dir / "assets" / "assets.json", report)
    voice_payload = load_json(video_dir / "audio" / "voice.json", report)
    timeline_payload = load_json(video_dir / "scenes" / "timeline.json", report)
    if (
        metadata_payload is None
        or assets_payload is None
        or voice_payload is None
        or timeline_payload is None
    ):
        return report

    folder_name = video_dir.name
    validate_metadata(metadata_payload, folder_name, report)
    asset_ids = validate_assets(assets_payload, folder_name, report)
    voice_ids = validate_voice(voice_payload, script_ids, report)
    scene_ids = validate_timeline(
        timeline_payload,
        asset_ids,
        voice_ids,
        script_ids,
        mascot_ids(),
        report,
    )

    if isinstance(assets_payload, dict):
        assets = assets_payload.get("assets") or []
        validate_mascot_assets(assets, video_dir, report)
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            for scene_id in asset.get("usedInScenes") or []:
                if scene_id not in scene_ids:
                    report.error(
                        f"{asset.get('id')}: usedInScenes references missing scene `{scene_id}`"
                    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to a video folder, e.g. videos/my-video")
    args = parser.parse_args()
    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()

    report = validate_video(video_dir)
    for message in report.errors:
        print(f"ERROR {message}")
    if report.ok:
        print("OK")
        return 0
    print(f"FAIL  {len(report.errors)} error(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
