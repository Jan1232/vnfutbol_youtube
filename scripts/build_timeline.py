#!/usr/bin/env python3
"""Build timeline.json from visual-plan + voice timing after asset prep gate."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asset_prep_common import load_json, video_paths, write_json
from mascot_common import DEFAULT_OUTFIT

READY_VISUAL = {"READY", "READY_RENDER_SPEC", "READY_MASCOT"}


def fail(messages: list[str]) -> int:
    for message in messages:
        print(f"ERROR {message}")
    print(f"FAIL  {len(messages)} blocker(s)")
    return 1


def prepared_map(video_dir: Path) -> dict[str, dict]:
    path = video_paths(video_dir)["prepared"]
    if not path.exists():
        return {}
    payload = load_json(path)
    return {
        item["id"]: item
        for item in payload.get("assets", [])
        if isinstance(item, dict) and item.get("id")
    }


def voice_segments(voice: dict) -> list[dict]:
    return list(voice.get("segments") or voice.get("items") or [])


def partition_segments(segments: list[dict], scene_count: int) -> list[list[dict]]:
    if scene_count <= 0:
        raise ValueError("scene_count must be positive")
    if len(segments) < scene_count:
        raise ValueError("AMBIGUOUS_SCENE_SPLIT")
    n = len(segments)
    base = n // scene_count
    rem = n % scene_count
    parts: list[list[dict]] = []
    index = 0
    for i in range(scene_count):
        size = base + (1 if i < rem else 0)
        parts.append(segments[index : index + size])
        index += size
    return parts


def assign_voice(
    scenes: list[dict], segments: list[dict]
) -> dict[str, list[dict]]:
    """Return scene_id -> ordered voice segments.

    Explicit scene.voiceSourceKeys is authoritative when present.
    """
    by_script: dict[str, list[dict]] = defaultdict(list)
    by_key: dict[str, dict] = {}
    for seg in segments:
        script = seg.get("script")
        if script:
            by_script[script].append(seg)
        key = seg.get("sourceKey")
        if key:
            by_key[key] = seg

    assignment: dict[str, list[dict]] = {}
    scenes_by_script: dict[str, list[dict]] = defaultdict(list)
    explicit_keys_used: set[str] = set()

    for scene in scenes:
        refs = scene.get("scriptRefs") or []
        if not refs:
            raise ValueError(f"{scene.get('id')}: missing scriptRefs")
        explicit = scene.get("voiceSourceKeys")
        if explicit:
            chosen: list[dict] = []
            for key in explicit:
                seg = by_key.get(key)
                if seg is None:
                    raise ValueError(
                        f"{scene['id']}: voiceSourceKey `{key}` not found in voice.json"
                    )
                chosen.append(seg)
                explicit_keys_used.add(key)
            assignment[scene["id"]] = chosen
            continue
        if len(refs) == 1:
            scenes_by_script[refs[0]].append(scene)
        else:
            combined: list[dict] = []
            for ref in refs:
                combined.extend(by_script.get(ref) or [])
            if not combined:
                raise ValueError(f"{scene['id']}: no voice segments for {refs}")
            assignment[scene["id"]] = combined

    for script_id, script_scenes in scenes_by_script.items():
        segs = [
            seg
            for seg in (by_script.get(script_id) or [])
            if seg.get("sourceKey") not in explicit_keys_used
        ]
        # If some segments of this script were claimed by explicit keys, remaining
        # auto scenes only see unclaimed segments.
        if not segs and script_scenes:
            raise ValueError(
                f"AMBIGUOUS_SCENE_SPLIT: script {script_id} has no unclaimed voice "
                f"segments for scenes {[s['id'] for s in script_scenes]}; "
                "set explicit voiceSourceKeys on those scenes"
            )
        if len(script_scenes) == 1:
            assignment[script_scenes[0]["id"]] = segs
            continue
        try:
            parts = partition_segments(segs, len(script_scenes))
        except ValueError as exc:
            if str(exc) == "AMBIGUOUS_SCENE_SPLIT":
                raise ValueError(
                    f"AMBIGUOUS_SCENE_SPLIT: script {script_id} has "
                    f"{len(segs)} voice segment(s) for {len(script_scenes)} scenes "
                    f"{[s['id'] for s in script_scenes]}; "
                    "set explicit voiceSourceKeys on those scenes"
                ) from exc
            raise
        for scene, part in zip(script_scenes, parts):
            if not part:
                raise ValueError(
                    f"AMBIGUOUS_SCENE_SPLIT: empty partition for {scene['id']} / {script_id}; "
                    "set explicit voiceSourceKeys"
                )
            assignment[scene["id"]] = part
    return assignment


def collect_gate_blockers(
    scenes: list[dict],
    prepared: dict[str, dict],
    allow_placeholders: bool,
) -> list[str]:
    blockers: list[str] = []
    for scene in scenes:
        sid = scene["id"]
        mascot = scene.get("mascot")
        if mascot:
            if not mascot.get("basePose"):
                blockers.append(f"{sid}: mascot missing concrete basePose")
            if not mascot.get("assetId"):
                blockers.append(f"{sid}: mascot missing assetId")
            else:
                rec = prepared.get(mascot["assetId"])
                if not rec:
                    blockers.append(f"{sid}: prepared record missing for {mascot['assetId']}")
                elif rec.get("status") != "READY_MASCOT":
                    if allow_placeholders and rec.get("status") == "BLOCKED" and mascot.get(
                        "basePose"
                    ):
                        # Draft may use approved base pose as outfit placeholder.
                        pass
                    else:
                        blockers.append(
                            f"{sid}: mascot {mascot['assetId']} status={rec.get('status')} "
                            f"({rec.get('notes')})"
                        )

        for asset_id in scene.get("assetRequests") or []:
            if mascot and asset_id == mascot.get("assetId"):
                continue
            rec = prepared.get(asset_id)
            if not rec:
                blockers.append(f"{sid}: missing prepared record for `{asset_id}`")
                continue
            status = rec.get("status")
            if status in READY_VISUAL:
                continue
            if status in {"MISSING", "BLOCKED"}:
                blockers.append(f"{sid}: asset `{asset_id}` is {status}")
                continue
            if status in {"NEEDS_SOURCE_FILE", "NEEDS_SELECTION"}:
                if allow_placeholders:
                    continue
                blockers.append(
                    f"{sid}: asset `{asset_id}` is {status} (not READY); "
                    "use --allow-placeholders for draft only"
                )
                continue
            blockers.append(f"{sid}: asset `{asset_id}` unexpected status {status}")
    return blockers


def supporting_asset(scene: dict) -> str | None:
    supporting = scene.get("supportingVisual") or {}
    if supporting.get("assetId"):
        return supporting["assetId"]
    ids = supporting.get("assetIds") or []
    return ids[0] if ids else None


def build_scene_entry(
    scene: dict,
    segs: list[dict],
    next_start_ms: int | None,
    prepared: dict[str, dict],
    allow_placeholders: bool,
) -> dict:
    first = segs[0]
    last = segs[-1]
    start_ms = int(first["startMs"])
    # Include trailing pauseAfter on last segment unless it would overlap next scene
    end_ms = int(last["endMs"]) + int(last.get("pauseAfter") or 0)
    if next_start_ms is not None and end_ms > next_start_ms:
        end_ms = next_start_ms
    duration_ms = max(0, end_ms - start_ms)

    mascot = scene.get("mascot")
    primary = scene.get("primaryType")
    visual: dict
    placeholders: list[str] = []

    if mascot and primary == "MASCOT":
        asset_id = mascot.get("assetId")
        rec = prepared.get(asset_id or "") or {}
        outfit = (rec.get("mascot") or {}).get("outfit")
        visual = {
            "type": "MASCOT",
            "asset": asset_id,
            "pose": mascot.get("basePose"),
            "outfit": outfit,
            "supportingAsset": supporting_asset(scene),
        }
        if allow_placeholders and rec.get("status") == "BLOCKED":
            visual["placeholderOutfit"] = True
            visual["prepStatus"] = "BLOCKED"
            placeholders.append(asset_id)
    else:
        asset_id = supporting_asset(scene)
        if not asset_id and scene.get("assetRequests"):
            asset_id = scene["assetRequests"][0]
        rec = prepared.get(asset_id or "") or {}
        visual = {
            "type": scene.get("primaryType") or rec.get("type") or "VIDEO",
            "asset": asset_id,
        }
        if allow_placeholders and rec.get("status") not in READY_VISUAL:
            visual["placeholder"] = True
            visual["prepStatus"] = rec.get("status")
            placeholders.append(asset_id)

    # Mark unresolved supporting media in placeholder mode
    if allow_placeholders:
        for aid in scene.get("assetRequests") or []:
            if mascot and aid == mascot.get("assetId"):
                continue
            rec = prepared.get(aid) or {}
            if rec.get("status") not in READY_VISUAL:
                placeholders.append(aid)

    script_refs = scene.get("scriptRefs") or []
    entry = {
        "id": scene["id"],
        "start": round(start_ms / 1000.0, 3),
        "duration": round(duration_ms / 1000.0, 3),
        "script": script_refs[0] if script_refs else None,
        "scriptRefs": script_refs,
        "voiceIds": [s["id"] for s in segs],
        "voiceSourceKeys": [s.get("sourceKey") for s in segs],
        "layout": scene.get("layout"),
        "visual": visual,
        "overlay": scene.get("overlay"),
        "animation": scene.get("animation"),
    }
    if placeholders:
        entry["unresolvedAssets"] = sorted(set(placeholders))
        entry["draftPlaceholders"] = True
    return entry


def enrich_mascot_outfits(video_dir: Path, scenes_out: list[dict]) -> None:
    assets = load_json(video_dir / "assets" / "assets.json").get("assets") or []
    by_id = {a["id"]: a for a in assets if a.get("id")}
    for scene in scenes_out:
        visual = scene.get("visual") or {}
        if visual.get("type") != "MASCOT":
            continue
        asset = by_id.get(visual.get("asset") or "")
        if not asset:
            continue
        mascot = asset.get("mascot") or {}
        # Always preserve the requested/resolved outfit id, even as a placeholder.
        visual["outfit"] = mascot.get("resolvedOutfit") or visual.get("outfit") or DEFAULT_OUTFIT
        visual["pose"] = mascot.get("basePose") or visual.get("pose")


def build(video_dir: Path, allow_placeholders: bool) -> int:
    paths = video_paths(video_dir)
    for key in ("visual_plan", "voice", "prepared", "assets"):
        if not paths[key].exists():
            return fail([f"missing {paths[key]}"])

    plan = load_json(paths["visual_plan"])
    voice = load_json(paths["voice"])
    prepared = prepared_map(video_dir)
    segments = voice_segments(voice)

    blockers: list[str] = []
    for seg in segments:
        if seg.get("status") != "generated":
            blockers.append(f"{seg.get('id')}: voice status is not generated")
        if seg.get("startMs") is None or seg.get("endMs") is None:
            blockers.append(f"{seg.get('id')}: startMs/endMs missing")

    scenes = list(plan.get("scenes") or [])
    try:
        assignment = assign_voice(scenes, segments)
    except ValueError as exc:
        blockers.append(str(exc))
        assignment = {}

    blockers.extend(collect_gate_blockers(scenes, prepared, allow_placeholders))
    if blockers and not allow_placeholders:
        return fail(blockers)
    if blockers and allow_placeholders:
        # Draft tolerates unresolved externals and blocked outfit variants (base pose only).
        hard = [
            b
            for b in blockers
            if not (
                "NEEDS_SOURCE_FILE" in b
                or "NEEDS_SELECTION" in b
                or "(not READY)" in b
            )
        ]
        if hard:
            return fail(hard)

    # Build ordered timeline with non-overlapping ends
    ordered_ids = [s["id"] for s in scenes]
    scene_by_id = {s["id"]: s for s in scenes}
    starts = []
    for sid in ordered_ids:
        segs = assignment[sid]
        starts.append(int(segs[0]["startMs"]))

    timeline_scenes = []
    for index, sid in enumerate(ordered_ids):
        next_start = starts[index + 1] if index + 1 < len(starts) else None
        entry = build_scene_entry(
            scene_by_id[sid],
            assignment[sid],
            next_start,
            prepared,
            allow_placeholders,
        )
        timeline_scenes.append(entry)

    enrich_mascot_outfits(video_dir, timeline_scenes)

    total_duration = 0.0
    if timeline_scenes:
        last = timeline_scenes[-1]
        total_duration = float(last["start"]) + float(last["duration"])

    existing = load_json(paths["timeline"]) if paths["timeline"].exists() else {}
    payload = {
        "version": 1,
        "fps": int(existing.get("fps") or 30),
        "width": int(existing.get("width") or 1920),
        "height": int(existing.get("height") or 1080),
        "scenes": timeline_scenes,
        "draft": bool(allow_placeholders),
        "totalDuration": round(total_duration, 3),
    }
    write_json(paths["timeline"], payload)
    mode = "draft-placeholders" if allow_placeholders else "final"
    print(
        f"OK    timeline scenes={len(timeline_scenes)} mode={mode} "
        f"duration={total_duration:.3f}s"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to a video folder")
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="Build draft timeline labeling unresolved external media",
    )
    args = parser.parse_args()
    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()
    return build(video_dir, args.allow_placeholders)


if __name__ == "__main__":
    sys.exit(main())
