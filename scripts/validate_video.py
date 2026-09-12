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
    "research/research.md",
    "script/script.md",
    "factcheck/factcheck.md",
    "assets/assets.json",
    "audio/voice.json",
    "scenes/timeline.json",
)
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


def validate_assets(payload, report: Report) -> set[str]:
    ids: set[str] = set()
    if not isinstance(payload, dict):
        report.error("assets.json: root must be an object")
        return ids
    if payload.get("version") != 1:
        report.error("assets.json: version must be 1")
    if "video" not in payload or not isinstance(payload["video"], str):
        report.error("assets.json: video must be a string")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        report.error("assets.json: assets must be a list")
        return ids

    for index, asset in enumerate(assets):
        prefix = f"assets.json[{index}]"
        if not isinstance(asset, dict):
            report.error(f"{prefix}: must be an object")
            continue
        asset_id = asset.get("id")
        if not asset_id:
            report.error(f"{prefix}: missing id")
            continue
        ids.add(asset_id)
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
    for value, count in Counter(ids).items():
        if count > 1:
            report.error(f"duplicate asset id: {value}")
    return ids


def validate_voice(payload, script_ids: set[str], report: Report) -> set[str]:
    ids: set[str] = set()
    if not isinstance(payload, dict):
        report.error("voice.json: root must be an object")
        return ids
    items = payload.get("items")
    if not isinstance(items, list):
        report.error("voice.json: items must be a list")
        return ids
    for index, item in enumerate(items):
        prefix = f"voice.json[{index}]"
        if not isinstance(item, dict):
            report.error(f"{prefix}: must be an object")
            continue
        voice_id = item.get("id")
        if not voice_id:
            report.error(f"{prefix}: missing id")
            continue
        ids.add(voice_id)
        script_id = item.get("script")
        if script_id and script_id not in script_ids:
            report.error(f"{voice_id}: script `{script_id}` is missing from script.md")
        if "pauseAfter" in item and not isinstance(item["pauseAfter"], int):
            report.error(f"{voice_id}: pauseAfter must be an integer (ms)")
    for value, count in Counter(ids).items():
        if count > 1:
            report.error(f"duplicate voice id: {value}")
    return ids


def validate_timeline(
    payload,
    asset_ids: set[str],
    voice_ids: set[str],
    script_ids: set[str],
    pose_ids: set[str],
    report: Report,
) -> set[str]:
    ids: set[str] = set()
    if not isinstance(payload, dict):
        report.error("timeline.json: root must be an object")
        return ids
    if payload.get("version") != 1:
        report.error("timeline.json: version must be 1")
    for field in ("fps", "width", "height"):
        if not isinstance(payload.get(field), int):
            report.error(f"timeline.json: {field} must be an integer")
    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        report.error("timeline.json: scenes must be a list")
        return ids

    for index, scene in enumerate(scenes):
        prefix = f"timeline.json[{index}]"
        if not isinstance(scene, dict):
            report.error(f"{prefix}: must be an object")
            continue
        scene_id = scene.get("id")
        if not scene_id:
            report.error(f"{prefix}: missing id")
            continue
        ids.add(scene_id)
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
    for value, count in Counter(ids).items():
        if count > 1:
            report.error(f"duplicate scene id: {value}")
    return ids


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

    assets_payload = load_json(video_dir / "assets" / "assets.json", report)
    voice_payload = load_json(video_dir / "audio" / "voice.json", report)
    timeline_payload = load_json(video_dir / "scenes" / "timeline.json", report)
    if assets_payload is None or voice_payload is None or timeline_payload is None:
        return report

    asset_ids = validate_assets(assets_payload, report)
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
        for asset in assets_payload.get("assets") or []:
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
