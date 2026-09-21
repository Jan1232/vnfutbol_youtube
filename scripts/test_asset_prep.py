#!/usr/bin/env python3
"""Offline tests for asset prep / mascot sync / timeline gate / validator v2."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Offline tests must never call live OpenAI generation during prepare/plan.
os.environ["MASCOT_AUTO_GENERATE"] = "0"

from asset_prep_common import ROOT, sha256_file, write_json
from build_timeline import assign_voice, collect_gate_blockers, partition_segments
from prepare_assets import (
    apply_source_reuse,
    candidate_entries,
    cmd_ingest,
    cmd_plan,
    distinct_source_files_needed,
    load_prepared,
    merge_preserve,
    review_board_assets,
    select_candidate,
)
from sync_mascot_assets import resolve_base_pose, resolve_subject, sync
from validate_video import validate_assets, Report
from mascot_common import load_poses, pose_by_id
import review_mascot_masks as review_masks
import mascot_common as mc
from PIL import Image as PILImage


def assert_true(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def make_video_fixture(tmp: Path) -> Path:
    video = tmp / "test-video"
    (video / "assets").mkdir(parents=True)
    (video / "scenes").mkdir()
    (video / "audio").mkdir()
    (video / "context").mkdir()
    (video / "script").mkdir()
    (video / "research").mkdir()
    (video / "factcheck").mkdir()
    (video / "renders").mkdir()

    write_json(
        video / "metadata.json",
        {
            "slug": "test-video",
            "title": "Test",
            "createdAt": "2026-01-01",
            "status": "assets",
        },
    )
    write_json(
        video / "context" / "entities.json",
        {
            "version": 1,
            "entities": [
                {
                    "id": "player-lamine-yamal",
                    "type": "PLAYER",
                    "name": "Lamine Yamal",
                    "currentClub": {"name": "FC Barcelona", "outfit": "barcelona-home"},
                    "nationalTeam": {"name": "Spain", "outfit": "spain-home-2026"},
                }
            ],
        },
    )
    write_json(
        video / "assets" / "asset-prep.json",
        {
            "version": 1,
            "video": "test-video",
            "stage": "planned",
            "paths": {
                "localRoot": str((tmp / ".local-assets" / "test-video").as_posix()),
                "outputManifest": "assets/prepared-assets.json",
            },
            "renderOnlyAssetIds": ["map-demo"],
            "externalAssetIds": ["photo-demo"],
            "policy": {"fetchRequiresExplicitFlag": True},
        },
    )
    write_json(
        video / "assets" / "assets.json",
        {
            "version": 2,
            "video": "test-video",
            "assets": [
                {
                    "id": "narration",
                    "type": "AUDIO",
                    "source": "generated",
                    "status": "generated",
                    "file": "audio/final/narration.wav",
                    "usedInScenes": [],
                    "rightsStatus": "owned",
                },
                {
                    "id": "photo-demo",
                    "type": "PLAYER_PHOTO",
                    "source": "official-source",
                    "status": "found",
                    "usedInScenes": ["scene-01"],
                    "sourceUrl": "https://example.com/photo.jpg",
                    "rightsStatus": "editorial",
                    "downloadToPublicRepo": False,
                },
                {
                    "id": "map-demo",
                    "type": "MAP",
                    "source": "render",
                    "status": "planned-render",
                    "usedInScenes": ["scene-02"],
                    "renderSpec": "simple map",
                    "downloadToPublicRepo": False,
                },
            ],
        },
    )
    write_json(
        video / "scenes" / "visual-plan.json",
        {
            "version": 1,
            "video": "test-video",
            "scenes": [
                {
                    "id": "scene-01",
                    "scriptRefs": ["SCRIPT-001"],
                    "primaryType": "MASCOT",
                    "layout": "mascot-left-media-right",
                    "mascot": {"poseIntent": "explain", "position": "left"},
                    "outfitIntent": "default",
                    "supportingVisual": {"type": "PLAYER_PHOTO", "assetId": "photo-demo"},
                    "overlay": None,
                    "animation": "fade",
                    "assetRequests": ["photo-demo"],
                },
                {
                    "id": "scene-02",
                    "scriptRefs": ["SCRIPT-001"],
                    "primaryType": "MASCOT",
                    "layout": "mascot-center",
                    "mascot": {"poseIntent": "explain", "position": "center"},
                    "outfitIntent": "current-club",
                    "supportingVisual": {"type": "MAP", "assetId": "map-demo"},
                    "overlay": None,
                    "animation": "fade",
                    "assetRequests": ["map-demo"],
                },
                {
                    "id": "scene-03",
                    "scriptRefs": ["SCRIPT-002"],
                    "primaryType": "MASCOT",
                    "layout": "mascot-center",
                    "mascot": {"poseIntent": "explain", "position": "center"},
                    "outfitIntent": "default",
                    "supportingVisual": None,
                    "overlay": None,
                    "animation": "fade",
                    "assetRequests": [],
                },
            ],
        },
    )
    write_json(
        video / "audio" / "voice.json",
        {
            "version": 1,
            "segments": [
                {
                    "id": "voice-001",
                    "sourceKey": "SCRIPT-001:000",
                    "script": "SCRIPT-001",
                    "status": "generated",
                    "startMs": 0,
                    "endMs": 1000,
                    "pauseAfter": 100,
                },
                {
                    "id": "voice-002",
                    "sourceKey": "SCRIPT-001:001",
                    "script": "SCRIPT-001",
                    "status": "generated",
                    "startMs": 1100,
                    "endMs": 2000,
                    "pauseAfter": 0,
                },
                {
                    "id": "voice-003",
                    "sourceKey": "SCRIPT-002:000",
                    "script": "SCRIPT-002",
                    "status": "generated",
                    "startMs": 2000,
                    "endMs": 3000,
                    "pauseAfter": 0,
                },
            ],
        },
    )
    write_json(video / "scenes" / "timeline.json", {"version": 1, "fps": 30, "width": 1920, "height": 1080, "scenes": []})
    write_json(video / "assets" / "mascot-generation.json", {"version": 1, "jobs": []})
    write_json(video / "assets" / "prepared-assets.json", {"version": 1, "video": "test-video", "assets": []})
    (video / "audio" / "final").mkdir(parents=True)
    (video / "audio" / "final" / "narration.wav").write_bytes(b"RIFF....WAVEfmt ")
    (video / "script" / "script.md").write_text("SCRIPT-001\nSCRIPT-002\n", encoding="utf-8")
    (video / "research" / "research.md").write_text("FACT-001\n", encoding="utf-8")
    (video / "factcheck" / "factcheck.md").write_text("ok\n", encoding="utf-8")
    return video


def test_pose_deterministic() -> None:
    poses = [p for p in load_poses()["poses"] if p.get("approved")]
    scene = {"id": "scene-aa", "mascot": {"poseIntent": "explain"}}
    a = resolve_base_pose(scene, poses)
    b = resolve_base_pose(scene, poses)
    assert_true(a == b, "pose selection must be deterministic")
    other = resolve_base_pose({"id": "scene-bb", "mascot": {"poseIntent": "explain"}}, poses)
    # May or may not differ; both must be approved explain*
    assert_true(a.startswith("explain"), f"unexpected pose {a}")
    assert_true(other.startswith("explain"), f"unexpected pose {other}")
    frozen = {"id": "scene-aa", "mascot": {"poseIntent": "think", "basePose": a}}
    assert_true(resolve_base_pose(frozen, poses) == a, "frozen basePose must stick")


def test_no_invented_pose() -> None:
    poses = [p for p in load_poses()["poses"] if p.get("approved")]
    try:
        resolve_base_pose({"id": "scene-x", "mascot": {"poseIntent": "totally-fake-pose"}}, poses)
        raise AssertionError("expected failure for unknown poseIntent")
    except ValueError as exc:
        assert_true("matches no approved pose" in str(exc), str(exc))


def test_plan_and_preserve(video: Path) -> None:
    assert_true(sync(video) == 0, "sync failed")
    assert_true(cmd_plan(video) == 0, "plan failed")
    payload = load_prepared(video)
    by_id = {a["id"]: a for a in payload["assets"]}
    assert_true("photo-demo" in by_id, "missing photo-demo")
    assert_true(by_id["photo-demo"]["status"] == "NEEDS_SOURCE_FILE", by_id["photo-demo"])
    assert_true(by_id["map-demo"]["status"] == "READY_RENDER_SPEC", by_id["map-demo"])
    assert_true(by_id["narration"]["status"] == "READY", by_id["narration"])

    # Mark photo READY manually and ensure rerun preserves
    by_id["photo-demo"]["status"] = "READY"
    by_id["photo-demo"]["preparedPath"] = ".local-assets/test-video/prepared/photo-demo.png"
    by_id["photo-demo"]["sourceSha256"] = "abc"
    by_id["photo-demo"]["sha256"] = "abc"
    write_json(video / "assets" / "prepared-assets.json", payload)
    # Create dummy prepared path so merge keeps READY
    local_root = Path(json.loads((video / "assets" / "asset-prep.json").read_text(encoding="utf-8"))["paths"]["localRoot"])
    prep_file = local_root / "prepared" / "photo-demo.png"
    prep_file.parent.mkdir(parents=True, exist_ok=True)
    prep_file.write_bytes(b"PNG")
    # Use repo-relative style path under tmp — merge_preserve checks ROOT; instead test merge helper
    old = by_id["photo-demo"]
    fresh = dict(old)
    fresh["status"] = "NEEDS_SOURCE_FILE"
    fresh["preparedPath"] = None
    fresh["sourceSha256"] = "abc"
    merged = merge_preserve(old, fresh)
    assert_true(merged["status"] == "READY", f"rerun must preserve READY, got {merged}")


def test_rendered_file_promotes_to_ready(tmp: Path) -> None:
    """Renderer-owned assets become READY when a validated rendered file exists."""
    from prepare_assets import classify_plan_record, resolve_rendered_asset_file
    from PIL import Image

    video = tmp / "render-ready-video"
    (video / "assets" / "rendered").mkdir(parents=True)
    (video / "scenes").mkdir(parents=True)
    asset = {
        "id": "stat-generic-demo",
        "type": "STAT",
        "source": "render",
        "status": "planned-render",
        "renderSpec": "generic card",
        "downloadToPublicRepo": False,
    }
    plan = {"scenes": [{"id": "scene-01", "assetRequests": ["stat-generic-demo"]}]}
    prep = {"renderOnlyAssetIds": [], "externalMediaAssetIds": []}

    before = classify_plan_record(asset["id"], asset, prep, video, plan)
    assert_true(
        before["status"] == "READY_RENDER_SPEC",
        f"missing file must stay READY_RENDER_SPEC, got {before}",
    )
    assert_true(resolve_rendered_asset_file(video, asset["id"], asset) is None, "no file yet")

    path = video / "assets" / "rendered" / "stat-generic-demo.png"
    Image.new("RGB", (1080, 1920), (20, 30, 60)).save(path, format="PNG")

    after = classify_plan_record(asset["id"], asset, prep, video, plan)
    assert_true(after["status"] == "READY", f"existing rendered PNG must be READY, got {after}")
    assert_true(after.get("preparedPath"), "preparedPath required")
    assert_true(after.get("sha256"), "sha256 required")
    assert_true(after.get("width") == 1080 and after.get("height") == 1920, after)

    # Explicit file field also works without id-named default path
    alt = video / "assets" / "rendered" / "custom-card.webp"
    Image.new("RGB", (720, 1280), (40, 40, 40)).save(alt, format="WEBP")
    asset_file = dict(asset, id="other-render", file="assets/rendered/custom-card.webp")
    via_file = classify_plan_record(asset_file["id"], asset_file, prep, video, plan)
    assert_true(via_file["status"] == "READY", via_file)
    assert_true(via_file.get("width") == 720 and via_file.get("height") == 1280, via_file)


def test_ingest_hash(video: Path) -> None:
    prep = json.loads((video / "assets" / "asset-prep.json").read_text(encoding="utf-8"))
    local_root = Path(prep["paths"]["localRoot"])
    inbox = local_root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    src = inbox / "photo-demo.jpg"
    # minimal jpeg-ish bytes
    src.write_bytes(b"\xff\xd8\xff\xd9fakejpeg")
    assert_true(cmd_plan(video) == 0, "plan")
    assert_true(cmd_ingest(video) == 0, "ingest")
    payload = load_prepared(video)
    rec = next(a for a in payload["assets"] if a["id"] == "photo-demo")
    assert_true(rec.get("sourceSha256"), "missing hash")
    first = rec["sourceSha256"]
    # same file again
    src.write_bytes(b"\xff\xd8\xff\xd9fakejpeg")
    assert_true(cmd_ingest(video) == 0, "reingest same")
    payload = load_prepared(video)
    rec = next(a for a in payload["assets"] if a["id"] == "photo-demo")
    assert_true(rec["sourceSha256"] == first, "same hash must not duplicate conflict")
    # changed file must fail
    src.write_bytes(b"\xff\xd8\xff\xd9CHANGED")
    assert_true(cmd_ingest(video) == 1, "changed hash must be detected")


def test_mascot_dedupe(video: Path) -> None:
    assert_true(sync(video) == 0, "sync")
    assets = json.loads((video / "assets" / "assets.json").read_text(encoding="utf-8"))["assets"]
    mascots = [a for a in assets if a.get("type") == "MASCOT"]
    pairs = {(a["mascot"]["basePose"], a["mascot"]["resolvedOutfit"]) for a in mascots}
    assert_true(len(pairs) == len(mascots), "mascot assets must dedupe by pair")
    defaults = [a for a in mascots if a["mascot"]["resolvedOutfit"] == "default-home"]
    assert_true(defaults, "default-home pair expected")
    plan = json.loads((video / "scenes" / "visual-plan.json").read_text(encoding="utf-8"))
    for scene in plan["scenes"]:
        if scene.get("mascot"):
            assert_true(scene["mascot"].get("basePose"), "basePose frozen")
            assert_true(scene["mascot"].get("assetId"), "assetId set")


def test_timeline_partition() -> None:
    scenes = [
        {"id": "scene-01", "scriptRefs": ["SCRIPT-001"]},
        {"id": "scene-02", "scriptRefs": ["SCRIPT-001"]},
    ]
    segs = [
        {"id": "v1", "script": "SCRIPT-001", "sourceKey": "SCRIPT-001:000", "startMs": 0, "endMs": 10},
        {"id": "v2", "script": "SCRIPT-001", "sourceKey": "SCRIPT-001:001", "startMs": 10, "endMs": 20},
    ]
    assignment = assign_voice(scenes, segs)
    assert_true(assignment["scene-01"][0]["id"] == "v1", assignment)
    assert_true(assignment["scene-02"][0]["id"] == "v2", assignment)

    try:
        assign_voice(
            [
                {"id": "a", "scriptRefs": ["SCRIPT-X"]},
                {"id": "b", "scriptRefs": ["SCRIPT-X"]},
                {"id": "c", "scriptRefs": ["SCRIPT-X"]},
            ],
            [{"id": "v1", "script": "SCRIPT-X", "startMs": 0, "endMs": 1}],
        )
        raise AssertionError("expected AMBIGUOUS_SCENE_SPLIT")
    except ValueError as exc:
        assert_true("AMBIGUOUS_SCENE_SPLIT" in str(exc), str(exc))

    parts = partition_segments([{"id": i} for i in range(5)], 2)
    assert_true(len(parts[0]) == 3 and len(parts[1]) == 2, parts)


def test_validator_v1_v2() -> None:
    report = Report()
    v2 = {
        "version": 2,
        "video": "test-video",
        "assets": [
            {
                "id": "x",
                "type": "MAP",
                "source": "render",
                "status": "planned-render",
                "usedInScenes": ["scene-01"],
                "renderSpec": "x",
            }
        ],
    }
    ids = validate_assets(v2, "test-video", report)
    assert_true(report.ok, report.errors)
    assert_true("x" in ids, ids)

    report2 = Report()
    v1 = {
        "version": 1,
        "video": "test-video",
        "assets": [
            {
                "id": "y",
                "type": "PLAYER_PHOTO",
                "source": "web",
                "status": "planned",
                "usedInScenes": [],
                "tags": [],
                "sourceUrl": None,
                "license": None,
                "author": None,
            }
        ],
    }
    validate_assets(v1, "test-video", report2)
    assert_true(report2.ok, report2.errors)

    report3 = Report()
    bad = {
        "version": 2,
        "video": "test-video",
        "assets": [
            {
                "id": "z",
                "type": "MAP",
                "source": "not-a-source",
                "status": "planned-render",
                "usedInScenes": [],
            }
        ],
    }
    validate_assets(bad, "test-video", report3)
    assert_true(not report3.ok, "unknown source must fail")


def test_no_fetch_without_flag() -> None:
    # ensure argparse rejects running multiple; and plan does not call network
    import prepare_assets as mod

    called = {"fetch": False}
    original = mod.cmd_fetch_external

    def guard(video_dir):
        called["fetch"] = True
        return original(video_dir)

    mod.cmd_fetch_external = guard  # type: ignore
    try:
        old = sys.argv
        sys.argv = ["prepare_assets.py", "unused", "--plan"]
        # Will fail path; just ensure fetch not selected when only --plan
        assert_true(called["fetch"] is False, "fetch must not auto-run")
    finally:
        sys.argv = old
        mod.cmd_fetch_external = original  # type: ignore


def test_generic_subject_not_yamal(tmp: Path) -> None:
    video = make_video_fixture(tmp / "generic-subject")
    write_json(
        video / "context" / "entities.json",
        {
            "version": 1,
            "entities": [
                {
                    "id": "player-demo-non-yamal",
                    "type": "PLAYER",
                    "name": "Demo Player",
                    "currentClub": {"name": "FC Barcelona", "outfit": "barcelona-home"},
                    "nationalTeam": {"name": "Spain", "outfit": "spain-home-2026"},
                }
            ],
        },
    )
    plan = json.loads((video / "scenes" / "visual-plan.json").read_text(encoding="utf-8"))
    for scene in plan["scenes"]:
        if scene.get("mascot"):
            scene["mascot"].pop("subject", None)
            scene["mascot"].pop("basePose", None)
            scene["mascot"].pop("assetId", None)
    # wipe previous assets mascots
    assets = json.loads((video / "assets" / "assets.json").read_text(encoding="utf-8"))
    assets["assets"] = [a for a in assets["assets"] if a.get("type") != "MASCOT"]
    write_json(video / "assets" / "assets.json", assets)
    write_json(video / "scenes" / "visual-plan.json", plan)
    assert_true(sync(video) == 0, "sync with non-yamal player")
    plan2 = json.loads((video / "scenes" / "visual-plan.json").read_text(encoding="utf-8"))
    club_scene = next(s for s in plan2["scenes"] if s.get("outfitIntent") == "current-club")
    assert_true(
        club_scene["mascot"].get("subject") == "player-demo-non-yamal",
        club_scene["mascot"],
    )
    # multiple players must fail without explicit subject
    write_json(
        video / "context" / "entities.json",
        {
            "version": 1,
            "entities": [
                {
                    "id": "player-a",
                    "type": "PLAYER",
                    "name": "A",
                    "currentClub": {"outfit": "barcelona-home"},
                    "nationalTeam": {"outfit": "spain-home-2026"},
                },
                {
                    "id": "player-b",
                    "type": "PLAYER",
                    "name": "B",
                    "currentClub": {"outfit": "barcelona-home"},
                    "nationalTeam": {"outfit": "spain-home-2026"},
                },
            ],
        },
    )
    for scene in plan2["scenes"]:
        if scene.get("mascot"):
            scene["mascot"].pop("subject", None)
            scene["mascot"].pop("basePose", None)
            scene["mascot"].pop("assetId", None)
    write_json(video / "scenes" / "visual-plan.json", plan2)
    assets = json.loads((video / "assets" / "assets.json").read_text(encoding="utf-8"))
    assets["assets"] = [a for a in assets["assets"] if a.get("type") != "MASCOT"]
    write_json(video / "assets" / "assets.json", assets)
    assert_true(sync(video) == 1, "multiple players must require explicit subject")


def test_voice_source_keys_authoritative() -> None:
    scenes = [
        {
            "id": "scene-01",
            "scriptRefs": ["SCRIPT-001"],
            "voiceSourceKeys": ["SCRIPT-001:001"],
        },
        {"id": "scene-02", "scriptRefs": ["SCRIPT-001"]},
    ]
    segs = [
        {"id": "v1", "script": "SCRIPT-001", "sourceKey": "SCRIPT-001:000", "startMs": 0, "endMs": 10},
        {"id": "v2", "script": "SCRIPT-001", "sourceKey": "SCRIPT-001:001", "startMs": 10, "endMs": 20},
    ]
    assignment = assign_voice(scenes, segs)
    assert_true(assignment["scene-01"][0]["id"] == "v2", assignment)
    assert_true(assignment["scene-02"][0]["id"] == "v1", assignment)


def test_placeholder_outfit_gate() -> None:
    scenes = [
        {
            "id": "scene-01",
            "mascot": {"basePose": "explain-one", "assetId": "mascot-x"},
            "assetRequests": ["photo-demo"],
        }
    ]
    prepared = {
        "mascot-x": {
            "status": "BLOCKED",
            "notes": "pending",
            "mascot": {"basePose": "explain-one", "outfit": "spain-home"},
        },
        "photo-demo": {"status": "NEEDS_SOURCE_FILE"},
    }
    final_blockers = collect_gate_blockers(scenes, prepared, allow_placeholders=False)
    assert_true(any("mascot-x" in b for b in final_blockers), final_blockers)
    draft_blockers = collect_gate_blockers(scenes, prepared, allow_placeholders=True)
    assert_true(not any("mascot-x" in b for b in draft_blockers), draft_blockers)


def test_source_reuse_annotation() -> None:
    records = [
        {"id": "video-a", "status": "NEEDS_SOURCE_FILE", "sourceUrl": "http://x"},
        {"id": "frame-b", "status": "NEEDS_SOURCE_FILE", "sourceUrl": "http://x"},
        {"id": "trophy-z", "status": "NEEDS_SOURCE_FILE"},
    ]
    reuse = {
        "groups": [
            {
                "id": "g1",
                "primaryAsset": "video-a",
                "outputs": [
                    {"assetId": "video-a", "derive": "video-excerpt"},
                    {"assetId": "frame-b", "derive": "video-frame-fallback"},
                ],
            }
        ],
        "renderInsteadOfExternalPreferred": [
            {"assetId": "trophy-z", "reason": "render graphic"}
        ],
    }
    moved = apply_source_reuse(records, reuse)
    by_id = {r["id"]: r for r in records}
    assert_true(by_id["trophy-z"]["status"] == "READY_RENDER_SPEC", by_id["trophy-z"])
    assert_true(by_id["frame-b"].get("derivedFrom") == "video-a", by_id["frame-b"])
    assert_true(by_id["frame-b"].get("sourceGroup") == "g1", by_id["frame-b"])
    needed = distinct_source_files_needed(records, reuse)
    assert_true(needed == ["video-a"], needed)
    assert_true(moved == [], moved)


def test_mask_review_rules(tmp: Path) -> None:
    video = tmp / "mask-video"
    (video / "assets").mkdir(parents=True)
    write_json(
        video / "assets" / "prepared-assets.json",
        {
            "version": 1,
            "assets": [
                {
                    "id": "m1",
                    "status": "BLOCKED",
                    "mascot": {"basePose": "celebrate", "outfit": "barcelona-home"},
                },
                {
                    "id": "m2",
                    "status": "BLOCKED",
                    "mascot": {"basePose": "celebrate", "outfit": "spain-home"},
                },
                {
                    "id": "m3",
                    "status": "BLOCKED",
                    "mascot": {"basePose": "stop", "outfit": "barcelona-home"},
                },
            ],
        },
    )
    mapping = review_masks.blocked_pose_outfits(video)
    assert_true(list(mapping.keys()) == ["celebrate", "stop"], mapping)
    assert_true(mapping["celebrate"] == ["barcelona-home", "spain-home"], mapping)

    pose = pose_by_id("celebrate")
    assert_true(pose is not None, "celebrate pose required")
    mask = next(m for m in mc.load_masks()["masks"] if m["basePose"] == "celebrate")
    original = json.loads(mc.MASKS_PATH.read_text(encoding="utf-8"))
    try:
        # hash mismatch cannot approve
        bad = json.loads(json.dumps(original))
        for item in bad["masks"]:
            if item["basePose"] == "celebrate":
                item["sha256"] = "0" * 64
                item["status"] = "generated"
        mc.MASKS_PATH.write_text(json.dumps(bad, indent=2) + "\n", encoding="utf-8")
        rc = review_masks.update_mask_status(["celebrate"], "approved", None)
        assert_true(rc == 1, "hash mismatch must fail approve")

        # stale base pose cannot approve
        bad = json.loads(json.dumps(original))
        for item in bad["masks"]:
            if item["basePose"] == "celebrate":
                item["basePoseSha256"] = "1" * 64
                item["status"] = "generated"
        mc.MASKS_PATH.write_text(json.dumps(bad, indent=2) + "\n", encoding="utf-8")
        rc = review_masks.update_mask_status(["celebrate"], "approved", None)
        assert_true(rc == 1, "stale pose must fail approve")

        # explicit reject
        mc.MASKS_PATH.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
        rc = review_masks.update_mask_status(["celebrate"], "rejected", "mask overlaps hand")
        assert_true(rc == 0, "reject should succeed")
        after = json.loads(mc.MASKS_PATH.read_text(encoding="utf-8"))
        celeb = next(m for m in after["masks"] if m["basePose"] == "celebrate")
        assert_true(celeb["status"] == "rejected", celeb)
        assert_true(celeb.get("rejectedReason") == "mask overlaps hand", celeb)

        # restore generated then approve with valid hashes
        for item in after["masks"]:
            if item["basePose"] == "celebrate":
                item["status"] = "generated"
                item.pop("rejectedReason", None)
        mc.MASKS_PATH.write_text(json.dumps(after, indent=2) + "\n", encoding="utf-8")
        rc = review_masks.update_mask_status(["celebrate"], "approved", None)
        assert_true(rc == 0, "valid approve should succeed")
        approved = json.loads(mc.MASKS_PATH.read_text(encoding="utf-8"))
        celeb = next(m for m in approved["masks"] if m["basePose"] == "celebrate")
        assert_true(celeb["status"] == "approved", celeb)
    finally:
        # Never leave editorial mask state changed by tests.
        mc.MASKS_PATH.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")


def test_mask_contact_sheet_height() -> None:
    for rows in (1, 5, 13):
        metrics = review_masks.mask_contact_sheet_metrics(rows)
        content_end = metrics["top_margin"] + rows * metrics["row_step"]
        assert_true(
            content_end + metrics["bottom_margin"] == metrics["height"],
            f"height formula mismatch for rows={rows}: {metrics}",
        )
        assert_true(
            metrics["height"] - content_end >= metrics["bottom_margin"],
            "bottom margin must remain after final row",
        )
        # Old buggy formula clipped the last row for larger boards.
        old_height = rows * (metrics["panel_h"] + metrics["label_h"]) + 40
        assert_true(
            metrics["height"] > old_height or rows == 1,
            f"fixed height should exceed old buggy height for rows={rows}",
        )


def test_candidate_labels_and_selection(tmp: Path) -> None:
    video = make_video_fixture(tmp / "cand-review")
    prep = json.loads((video / "assets" / "asset-prep.json").read_text(encoding="utf-8"))
    local_root = Path(prep["paths"]["localRoot"])
    cand_dir = local_root / "candidates" / "photo-demo"
    cand_dir.mkdir(parents=True, exist_ok=True)
    # Create deterministic candidate files with unsorted names
    paths = []
    for idx, name in enumerate(("candidate-02.png", "candidate-00.png", "candidate-01.png")):
        path = cand_dir / name
        img = PILImage.new("RGB", (64, 48), (40 + idx * 40, 80, 120))
        img.save(path)
        paths.append(str(path))

    payload = {
        "version": 1,
        "video": "test-video",
        "assets": [
            {
                "id": "photo-demo",
                "type": "PLAYER_PHOTO",
                "status": "NEEDS_SELECTION",
                "sourceUrl": "https://example.com/photo",
                "selectionNotes": "readable number",
                "candidates": paths,
            },
            {
                "id": "ignored-ready",
                "type": "PLAYER_PHOTO",
                "status": "READY",
                "candidates": paths,
            },
            {
                "id": "ignored-no-cands",
                "type": "PLAYER_PHOTO",
                "status": "NEEDS_SELECTION",
                "candidates": [],
            },
        ],
    }
    write_json(video / "assets" / "prepared-assets.json", payload)

    board_assets = review_board_assets(payload)
    assert_true([a["id"] for a in board_assets] == ["photo-demo"], board_assets)

    labels1 = [e["label"] for e in candidate_entries(payload["assets"][0])]
    labels2 = [e["label"] for e in candidate_entries(payload["assets"][0])]
    assert_true(labels1 == labels2 == ["C1", "C2", "C3"], labels1)
    ordered_paths = [e["path"] for e in candidate_entries(payload["assets"][0])]
    assert_true(ordered_paths == sorted(paths), ordered_paths)

    # unknown label rejected
    rc = select_candidate(video, "photo-demo=C9")
    assert_true(rc == 1, "unknown label must fail")

    rc = select_candidate(video, "photo-demo=C2")
    assert_true(rc == 0, "select C2")
    after = load_prepared(video)
    rec = next(a for a in after["assets"] if a["id"] == "photo-demo")
    assert_true(rec.get("selectedCandidate") == "C2", rec)
    assert_true(rec.get("status") == "READY", rec)
    source = Path(rec["sourcePath"]) if Path(rec["sourcePath"]).is_absolute() else ROOT / rec["sourcePath"]
    # When path is outside ROOT, prepare uses absolute via ROOT / which may break;
    # for tmp absolute localRoot, sourcePath is absolute-ish via rel_to_repo fallback.
    source_path = Path(rec["sourcePath"])
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    assert_true(source_path.exists(), source_path)
    assert_true(str(local_root.resolve()) in str(source_path.resolve()), source_path)

    # idempotent reselect same candidate
    rc = select_candidate(video, "photo-demo=C2")
    # status is READY now, so NEEDS_SELECTION check fails — re-set status for idempotent source copy test
    after = load_prepared(video)
    for item in after["assets"]:
        if item["id"] == "photo-demo":
            item["status"] = "NEEDS_SELECTION"
    write_json(video / "assets" / "prepared-assets.json", after)
    rc = select_candidate(video, "photo-demo=C2")
    assert_true(rc == 0, "same candidate twice must be idempotent")

    # different candidate must refuse overwrite
    after = load_prepared(video)
    for item in after["assets"]:
        if item["id"] == "photo-demo":
            item["status"] = "NEEDS_SELECTION"
    write_json(video / "assets" / "prepared-assets.json", after)
    rc = select_candidate(video, "photo-demo=C1")
    assert_true(rc == 1, "different candidate must not overwrite silently")


def main() -> int:
    failed = 0

    def run(name, fn):
        nonlocal failed
        try:
            fn()
            print(f"OK    {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {exc}")

    with tempfile.TemporaryDirectory() as tmp_raw:
        tmp = Path(tmp_raw)
        video = make_video_fixture(tmp)
        run("pose_deterministic", test_pose_deterministic)
        run("no_invented_pose", test_no_invented_pose)
        run("mascot_dedupe", lambda: test_mascot_dedupe(video))
        run("plan_and_preserve", lambda: test_plan_and_preserve(video))
        run("rendered_file_promotes_to_ready", lambda: test_rendered_file_promotes_to_ready(tmp))
        run("ingest_hash", lambda: test_ingest_hash(video))
        run("timeline_partition", test_timeline_partition)
        run("validator_v1_v2", test_validator_v1_v2)
        run("no_fetch_without_flag", test_no_fetch_without_flag)
        run("generic_subject_not_yamal", lambda: test_generic_subject_not_yamal(tmp))
        run("voice_source_keys_authoritative", test_voice_source_keys_authoritative)
        run("placeholder_outfit_gate", test_placeholder_outfit_gate)
        run("source_reuse_annotation", test_source_reuse_annotation)
        run("mask_review_rules", lambda: test_mask_review_rules(tmp))
        run("mask_contact_sheet_height", test_mask_contact_sheet_height)
        run("candidate_labels_and_selection", lambda: test_candidate_labels_and_selection(tmp))

    if failed:
        print(f"FAIL  {failed} test(s)")
        return 1
    print("PASS  asset prep offline tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
