#!/usr/bin/env python3
"""Offline tests for automated mascot outfit pipeline. No live OpenAI calls."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from asset_prep_common import write_json
from mascot_auto_generate import (
    build_api_mask,
    build_generation_prompt,
    extract_outfit_layer,
    generate_missing_variant,
)
from mascot_common import (
    DEFAULT_OUTFIT,
    MASCOT,
    VARIANTS_PATH,
    hashes_current,
    load_json,
    load_outfit_detail,
    load_variants,
    load_visual_style,
    mask_by_pose,
    mask_path,
    outfit_by_id,
    outfit_fingerprint,
    pose_by_id,
    pose_path,
    resolve_mascot_outfit,
    sha256_file,
    variant_by_pair,
    variant_cache_key,
    variant_is_stale,
    write_json as mc_write_json,
)
from sync_mascot_assets import sync


def assert_true(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def paint_kit_for_pose(pose_id: str, color=(20, 80, 180, 255)) -> Image.Image:
    pose = pose_by_id(pose_id)
    mask = mask_by_pose(pose_id)
    assert pose and mask
    base = Image.open(pose_path(pose)).convert("RGBA")
    clothing = Image.open(mask_path(mask)).convert("L")
    img = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ipx = img.load()
    mpx = clothing.load()
    w, h = base.size
    for y in range(h):
        for x in range(w):
            if mpx[x, y] > 0:
                ipx[x, y] = color
    return img


def test_barcelona_branding_rules() -> None:
    detail = load_outfit_detail("barcelona-home")
    rules = " ".join(detail.get("generationRules") or []).lower()
    assert_true("crest" in rules, rules)
    assert_true("nike" in rules, rules)
    assert_true("spotify" in rules and "symbol" in rules, rules)
    forbidden = " ".join(detail.get("forbiddenRules") or []).lower()
    assert_true("spotify" in forbidden or "word" in forbidden, forbidden)
    branding = detail.get("branding") or {}
    assert_true(branding.get("crest") is True, branding)
    assert_true(branding.get("manufacturer") == "Nike", branding)
    assert_true("Spotify" in (branding.get("forbiddenText") or []), branding)
    prompt = build_generation_prompt("barcelona-home", has_outfit_ref=True)
    assert_true("NO written Spotify word" in prompt or "circular Spotify symbol" in prompt, prompt)


def test_yamal_national_team_resolves_to_2026() -> None:
    video = ROOT / "videos" / "lamine-yamal-new-messi"
    style = load_visual_style(video)
    assert_true(style["mascotOutfits"]["nationalTeam"] == "spain-home-2026", style)
    resolved = resolve_mascot_outfit(
        "national-team",
        {},
        {"nationalTeam": {"outfit": "spain-home-2022"}},
        style,
    )
    assert_true(resolved == "spain-home-2026", resolved)


def test_reuse_never_calls_api(tmp: Path) -> None:
    pose = pose_by_id("explain-two")
    outfit = outfit_by_id("suit-navy")
    mask = mask_by_pose("explain-two")
    assert pose and outfit and mask
    base = Image.open(pose_path(pose)).convert("RGBA")
    dest_dir = MASCOT / "variants" / "_test_tmp"
    dest_dir.mkdir(parents=True, exist_ok=True)
    layer_path = dest_dir / "explain-two-suit-layer.png"
    Image.new("RGBA", base.size, (0, 0, 0, 0)).save(layer_path)
    comp_path = dest_dir / "explain-two-suit.png"
    base.save(comp_path)
    record = {
        "id": "explain-two__suit-navy",
        "basePose": "explain-two",
        "outfit": "suit-navy",
        "type": "outfit-layer",
        "file": layer_path.relative_to(MASCOT).as_posix(),
        "compositeFile": comp_path.relative_to(MASCOT).as_posix(),
        "status": "approved-auto",
        "sha256": sha256_file(layer_path),
        **hashes_current(pose, mask, outfit),
    }
    original = load_variants()
    try:
        mc_write_json(VARIANTS_PATH, {"version": 1, "variants": [record]})
        from mascot_common import variant_is_reusable

        assert_true(
            variant_is_reusable(variant_by_pair("explain-two", "suit-navy"), pose, mask, outfit),
            "seeded variant must be reusable",
        )
        calls = {"n": 0}

        def boom(**kwargs):
            calls["n"] += 1
            raise AssertionError("API must not be called on reuse")

        result = generate_missing_variant(
            "explain-two",
            "suit-navy",
            edit_fn=boom,
            skip_vision=True,
        )
        assert_true(result["result"] == "REUSED", result)
        assert_true(calls["n"] == 0, calls)
    finally:
        mc_write_json(VARIANTS_PATH, original)


def test_missing_triggers_generation_and_mask_lock(tmp: Path) -> None:
    pose = pose_by_id("explain-two")
    outfit = outfit_by_id("suit-navy")
    mask = mask_by_pose("explain-two")
    assert pose and outfit and mask
    base = Image.open(pose_path(pose)).convert("RGBA")
    binary = Image.open(mask_path(mask)).convert("L")
    # Fake full-edit: paint bright color everywhere (including outside mask)
    polluted = Image.new("RGBA", base.size, (255, 0, 0, 255))

    def fake_edit(**kwargs):
        return polluted.copy()

    original = load_variants()
    # Ensure no existing suit-navy/explain-two variant
    cleaned = [
        v
        for v in original.get("variants", [])
        if not (v.get("basePose") == "explain-two" and v.get("outfit") == "suit-navy")
    ]
    try:
        mc_write_json(VARIANTS_PATH, {"version": 1, "variants": cleaned})
        result = generate_missing_variant(
            "explain-two",
            "suit-navy",
            edit_fn=fake_edit,
            vision_fn=lambda **k: {"pass": True, "issues": []},
            work_dir=tmp / "work",
            skip_vision=False,
        )
        assert_true(result["result"] == "GENERATED", result)
        variant = variant_by_pair("explain-two", "suit-navy")
        assert_true(variant is not None and variant["status"] == "approved-auto", variant)
        # Outside-mask pixels of composite must equal original pose.
        from PIL import Image as PILImage

        composite = PILImage.open(MASCOT / variant["compositeFile"]).convert("RGBA")
        mpx = binary.load()
        bpx = base.load()
        cpx = composite.load()
        mismatch = 0
        w, h = base.size
        for y in range(0, h, 8):
            for x in range(0, w, 8):
                if mpx[x, y] == 0 and cpx[x, y] != bpx[x, y]:
                    mismatch += 1
        assert_true(mismatch == 0, f"outside-mask mutated: {mismatch}")
    finally:
        # cleanup generated files + restore variants
        variant = variant_by_pair("explain-two", "suit-navy")
        if variant:
            for key in ("file", "compositeFile"):
                path = MASCOT / variant[key] if variant.get(key) else None
                if path and path.exists() and "_test" not in str(path):
                    # keep library clean for suit-navy test artifact — remove
                    try:
                        path.unlink()
                    except OSError:
                        pass
        mc_write_json(VARIANTS_PATH, original)


def test_fingerprint_and_invalidation() -> None:
    pose = pose_by_id("celebrate")
    mask = mask_by_pose("celebrate")
    outfit = outfit_by_id("barcelona-home")
    assert pose and mask and outfit
    key1 = variant_cache_key(pose, mask, "barcelona-home")
    key2 = variant_cache_key(pose, mask, "barcelona-home")
    assert_true(key1 == key2, "same inputs must share cache key")
    fp1 = outfit_fingerprint("barcelona-home")
    # Changing pose hash in a copy must invalidate.
    fake_pose = dict(pose)
    fake_pose["sha256"] = "0" * 64
    assert_true(variant_cache_key(fake_pose, mask, "barcelona-home") != key1, "pose change")
    # Stale check on synthetic variant
    variant = {
        "basePoseSha256": pose["sha256"],
        "maskSha256": mask["sha256"],
        "outfitFingerprint": "deadbeef",
        "status": "approved-auto",
    }
    assert_true(variant_is_stale(variant, pose, mask, outfit), "fingerprint mismatch")


def test_missing_api_key_blocks(tmp: Path) -> None:
    original = os.environ.pop("OPENAI_API_KEY", None)
    dotenv = ROOT / ".env"
    renamed = ROOT / ".env.bak_test_mascot_auto"
    moved = False
    if dotenv.exists():
        dotenv.rename(renamed)
        moved = True
    try:
        # suit-navy needs no reference
        variants = load_variants()
        cleaned = [
            v
            for v in variants.get("variants", [])
            if not (v.get("basePose") == "celebrate" and v.get("outfit") == "suit-navy")
        ]
        mc_write_json(VARIANTS_PATH, {"version": 1, "variants": cleaned})
        result = generate_missing_variant("celebrate", "suit-navy")
        assert_true(result["result"] == "BLOCKED_GENERATION", result)
        assert_true("OPENAI_API_KEY" in result.get("reason", ""), result)
    finally:
        if moved and renamed.exists():
            renamed.rename(dotenv)
        if original is not None:
            os.environ["OPENAI_API_KEY"] = original


def test_qa_retries_and_no_promote_on_fail(tmp: Path) -> None:
    pose = pose_by_id("explain-two")
    base = Image.open(pose_path(pose)).convert("RGBA")
    # Empty full-edit => empty layer extraction should fail before QA; use opaque
    # full edit but vision always fails.
    calls = {"n": 0}

    def fake_edit(**kwargs):
        calls["n"] += 1
        return paint_kit_for_pose("explain-two")

    def fail_vision(**kwargs):
        return {"pass": False, "issues": ["Spotify word was added"]}

    original = load_variants()
    cleaned = [
        v
        for v in original.get("variants", [])
        if not (v.get("basePose") == "explain-two" and v.get("outfit") == "suit-navy")
    ]
    os.environ["MAX_GENERATION_ATTEMPTS"] = "3"
    try:
        mc_write_json(VARIANTS_PATH, {"version": 1, "variants": cleaned})
        result = generate_missing_variant(
            "explain-two",
            "suit-navy",
            edit_fn=fake_edit,
            vision_fn=fail_vision,
            work_dir=tmp / "retries",
        )
        assert_true(result["result"] == "NEEDS_REVIEW", result)
        assert_true(calls["n"] == 3, calls)
        variant = variant_by_pair("explain-two", "suit-navy")
        assert_true(variant is not None and variant["status"] == "needs-review", variant)
        assert_true(variant["status"] != "approved-auto", "must not promote")
    finally:
        os.environ.pop("MAX_GENERATION_ATTEMPTS", None)
        mc_write_json(VARIANTS_PATH, original)


def test_cross_video_reuse_after_success(tmp: Path) -> None:
    # After a successful generation, second call must REUSE.
    pose = pose_by_id("explain-two")
    base = Image.open(pose_path(pose)).convert("RGBA")
    calls = {"n": 0}

    def fake_edit(**kwargs):
        calls["n"] += 1
        return paint_kit_for_pose("explain-two", (30, 90, 40, 255))

    original = load_variants()
    cleaned = [
        v
        for v in original.get("variants", [])
        if not (v.get("basePose") == "explain-two" and v.get("outfit") == "suit-navy")
    ]
    try:
        mc_write_json(VARIANTS_PATH, {"version": 1, "variants": cleaned})
        first = generate_missing_variant(
            "explain-two",
            "suit-navy",
            edit_fn=fake_edit,
            vision_fn=lambda **k: {"pass": True, "issues": []},
            work_dir=tmp / "gen1",
        )
        assert_true(first["result"] == "GENERATED", first)
        second = generate_missing_variant(
            "explain-two",
            "suit-navy",
            edit_fn=fake_edit,
            vision_fn=lambda **k: {"pass": True, "issues": []},
            work_dir=tmp / "gen2",
        )
        assert_true(second["result"] == "REUSED", second)
        assert_true(calls["n"] == 1, calls)
    finally:
        # cleanup
        variant = variant_by_pair("explain-two", "suit-navy")
        if variant:
            for key in ("file", "compositeFile"):
                path = MASCOT / variant[key] if variant.get(key) else None
                if path and path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        pass
        mc_write_json(VARIANTS_PATH, original)


def test_sync_uses_visual_style(tmp: Path) -> None:
    video = tmp / "yamal"
    (video / "scenes").mkdir(parents=True)
    (video / "assets").mkdir(parents=True)
    (video / "context").mkdir(parents=True)
    write_json(
        video / "context" / "entities.json",
        {
            "version": 1,
            "entities": [
                {
                    "id": "player-lamine-yamal",
                    "type": "PLAYER",
                    "currentClub": {"outfit": "barcelona-home"},
                    "nationalTeam": {"outfit": "spain-home-2022"},
                }
            ],
        },
    )
    write_json(
        video / "context" / "visual-style.json",
        {
            "version": 1,
            "mascotOutfits": {
                "default": "default-home",
                "currentClub": "barcelona-home",
                "nationalTeam": "spain-home-2026",
                "formal": "suit-navy",
            },
        },
    )
    write_json(
        video / "scenes" / "visual-plan.json",
        {
            "version": 1,
            "scenes": [
                {
                    "id": "scene-14",
                    "outfitIntent": "national-team",
                    "mascot": {
                        "pose": "count-2",
                        "basePose": "count-2",
                        "outfitIntent": "national-team",
                        "subject": "player-lamine-yamal",
                    },
                }
            ],
        },
    )
    write_json(video / "assets" / "assets.json", {"version": 2, "assets": []})
    assert_true(sync(video) == 0, "sync failed")
    plan = load_json(video / "scenes" / "visual-plan.json")
    assert_true(
        plan["scenes"][0]["mascot"]["assetId"] == "mascot-count-2__spain-home-2026",
        plan["scenes"][0],
    )


def test_api_mask_polarity() -> None:
    binary = Image.new("L", (4, 4), 0)
    px = binary.load()
    px[1, 1] = 255
    px[2, 2] = 128
    api = build_api_mask(binary)
    assert_true(api.getpixel((1, 1))[3] == 0, "clothing must be transparent/editable")
    assert_true(api.getpixel((0, 0))[3] == 255, "non-clothing must be opaque")


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

    run("barcelona_branding_rules", test_barcelona_branding_rules)
    run("yamal_national_team_resolves_to_2026", test_yamal_national_team_resolves_to_2026)
    run("fingerprint_and_invalidation", test_fingerprint_and_invalidation)
    run("api_mask_polarity", test_api_mask_polarity)
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        run("reuse_never_calls_api", lambda: test_reuse_never_calls_api(t))
        run("missing_triggers_generation_and_mask_lock", lambda: test_missing_triggers_generation_and_mask_lock(t))
        run("missing_api_key_blocks", lambda: test_missing_api_key_blocks(t))
        run("qa_retries_and_no_promote_on_fail", lambda: test_qa_retries_and_no_promote_on_fail(t))
        run("cross_video_reuse_after_success", lambda: test_cross_video_reuse_after_success(t))
        run("sync_uses_visual_style", lambda: test_sync_uses_visual_style(t))

    if failed:
        print(f"FAIL  {failed} test(s)")
        return 1
    print("PASS  mascot auto pipeline tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
