#!/usr/bin/env python3
"""Offline tests for seasonal outfit references + export/import workflow. No AI/API."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from asset_prep_common import write_json
from build_mascot_outfit_prompt import build_prompt
from export_mascot_generation import export_job
from import_mascot_full_edit import import_full_edit
from import_outfit_reference import import_reference
from mascot_common import (
    DEFAULT_OUTFIT,
    current_outfit_reference_sha,
    entities_by_id,
    hashes_current,
    load_json,
    mask_by_pose,
    outfit_by_id,
    outfit_detail_path,
    outfit_reference_path,
    pose_by_id,
    pose_path,
    resolve_outfit,
    sha256_file,
    update_tracked_outfit_reference,
)
from promote_mascot_variant import main as promote_main
import review_mascot_variants as review
from ensure_mascot_variants import classify
from sync_mascot_assets import sync


def assert_true(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def sample_pending_job(pose_id: str = "explain-two", outfit_id: str = "barcelona-home") -> dict:
    pose = pose_by_id(pose_id)
    outfit = outfit_by_id(outfit_id)
    mask = mask_by_pose(pose_id)
    assert pose and outfit and mask
    hashes = hashes_current(pose, mask, outfit)
    return {
        "id": "mascot-job-test-001",
        "asset": f"mascot-{pose_id}__{outfit_id}",
        "basePose": pose_id,
        "basePoseFile": pose["file"],
        "canonicalReference": "references/mascot_reference_main.png",
        "clothingMask": mask["file"],
        "outfit": outfit_id,
        "outfitDescription": outfit.get("generationDescription", ""),
        "targetFullEdit": f"assets/mascot/generated/{pose_id}__{outfit_id}_full.png",
        "targetLayer": f"assets/mascot/generated/{pose_id}__{outfit_id}_layer.png",
        "status": "pending",
        "outfitReferenceSha256": current_outfit_reference_sha(outfit),
        **hashes,
    }


def write_dummy_png(path: Path, color=(200, 30, 40, 255), size=(64, 64)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path, format="PNG")
    return path


def test_barcelona_not_aliased() -> None:
    asset = {
        "id": "x",
        "type": "MASCOT",
        "mascot": {
            "basePose": "explain-two",
            "resolvedOutfit": "barcelona-home",
            "variantPolicy": "reuse-else-generate",
        },
    }
    label, _ = classify(asset)
    assert_true(label != "REUSED", f"barcelona-home must not be REUSED as base pose, got {label}")
    assert_true("barcelona-home" != DEFAULT_OUTFIT, "ids must differ")
    barca = outfit_by_id("barcelona-home")
    assert_true(barca is not None and barca.get("season") == "2025/26", barca)
    assert_true(barca.get("referenceRequired") is True, barca)
    assert_true(barca.get("sponsorPolicy") == "match-reference", barca)


def test_spain_seasonal_ids() -> None:
    for outfit_id, season in (
        ("spain-home-2022", "2022"),
        ("spain-home-2024", "2024"),
        ("spain-home-2026", "2026"),
    ):
        outfit = outfit_by_id(outfit_id)
        assert_true(outfit is not None, outfit_id)
        assert_true(outfit.get("season") == season, outfit)
        assert_true(outfit.get("referenceRequired") is True, outfit)
        assert_true(outfit.get("sponsorPolicy") == "omit", outfit)
        assert_true(outfit.get("crestPolicy") == "match-reference", outfit)
    legacy = outfit_by_id("spain-home")
    assert_true(legacy is not None and legacy.get("active") is False, legacy)


def test_prompt_policy_rendering() -> None:
    barca_job = sample_pending_job("explain-two", "barcelona-home")
    prompt = build_prompt(barca_job)
    assert_true("Image C: official outfit visual reference" in prompt, prompt)
    assert_true("Sponsor / front branding: reproduce the visible element from Image C." in prompt, prompt)
    assert_true("No sponsor text." not in prompt, prompt)

    spain_job = sample_pending_job("count-2", "spain-home-2022")
    spain_prompt = build_prompt(spain_job)
    assert_true("Sponsor / front branding: do not add." in spain_prompt, spain_prompt)
    assert_true("Manufacturer mark: reproduce the visible element from Image C." in spain_prompt, spain_prompt)

    suit_job = sample_pending_job("explain-five", "suit-navy")
    suit_prompt = build_prompt(suit_job)
    assert_true("Image C:" not in suit_prompt, suit_prompt)

    # Generic helpers must not hardcode Barcelona/Spain kit logic.
    helper = (ROOT / "scripts" / "build_mascot_outfit_prompt.py").read_text(encoding="utf-8")
    assert_true("barcelona-home" not in helper, "prompt builder must stay policy-driven")
    assert_true("spain-home" not in helper, "prompt builder must stay policy-driven")


def test_import_outfit_reference(tmp: Path) -> None:
    # Shared OUTFIT_REF_ROOT is gitignored but may already hold a real local reference;
    # clear it so the no-replace first-import path is exercisable and isolated.
    outfit_id = "barcelona-home"
    dest_existing = outfit_reference_path(outfit_id)
    if dest_existing.exists():
        dest_existing.unlink()
    meta_existing = dest_existing.parent / "meta.json"
    if meta_existing.exists():
        meta_existing.unlink()
    src = write_dummy_png(tmp / "kit-ref.png", (10, 40, 160, 255), (80, 100))
    assert_true(
        import_reference(
            outfit_id,
            src,
            "https://store.fcbarcelona.com/collections/men-home-kit/products/fc-barcelona-home-amshirt-25-26-ucl",
        )
        == 0,
        "import should succeed",
    )
    dest = outfit_reference_path(outfit_id)
    assert_true(dest.exists(), dest)
    meta = load_json(dest.parent / "meta.json")
    assert_true(meta["outfitId"] == outfit_id, meta)
    assert_true(meta["sha256"] == sha256_file(dest), meta)
    assert_true("do not commit" in meta["rights"], meta)

    other = write_dummy_png(tmp / "kit-ref-2.png", (1, 2, 3, 255), (80, 100))
    assert_true(
        import_reference(outfit_id, other, meta["sourceUrl"]) == 1,
        "silent overwrite must fail",
    )
    assert_true(
        import_reference(outfit_id, other, meta["sourceUrl"], replace=True) == 0,
        "replace must succeed",
    )


def test_export_requires_reference_and_suit_without(tmp: Path) -> None:
    video = tmp / "vid"
    (video / "assets").mkdir(parents=True)
    packs_root = tmp / ".local-assets" / "vid" / "mascot-generation"
    packs_root.mkdir(parents=True)

    # Ensure a barcelona reference exists for the happy path later.
    ref = write_dummy_png(tmp / "barca.png", (20, 30, 140, 255), (90, 110))
    assert_true(
        import_reference(
            "barcelona-home",
            ref,
            "https://store.fcbarcelona.com/collections/men-home-kit/products/fc-barcelona-home-amshirt-25-26-ucl",
            replace=True,
        )
        == 0,
        "need barca reference",
    )

    # Missing Spain reference blocks export.
    spain_job = sample_pending_job("count-2", "spain-home-2022")
    spain_job["id"] = "mascot-job-spain"
    spain_job["outfitReferenceSha256"] = None
    # Remove spain reference if present from prior runs.
    spain_ref = outfit_reference_path("spain-home-2022")
    if spain_ref.exists():
        spain_ref.unlink()
        meta = spain_ref.parent / "meta.json"
        if meta.exists():
            meta.unlink()
    try:
        export_job(video, spain_job, packs_root)
        raise AssertionError("export should fail without Spain reference")
    except ValueError as exc:
        assert_true("missing local outfit reference" in str(exc), str(exc))

    suit_job = sample_pending_job("explain-five", "suit-navy")
    suit_job["id"] = "mascot-job-suit"
    path = export_job(video, suit_job, packs_root)
    assert_true((path / "prompt.txt").exists(), path)
    assert_true(not (path / "outfit-reference.png").exists(), "suit must not need Image C")

    barca_job = sample_pending_job("explain-two", "barcelona-home")
    barca_job["outfitReferenceSha256"] = current_outfit_reference_sha(outfit_by_id("barcelona-home"))
    path = export_job(video, barca_job, packs_root)
    assert_true((path / "outfit-reference.png").exists(), path)
    meta = json.loads((path / "job.json").read_text(encoding="utf-8"))
    assert_true(meta["hashes"]["outfitReferenceSha256"] == barca_job["outfitReferenceSha256"], meta)
    assert_true(meta["outfit"] == "barcelona-home", meta)


def test_reference_change_invalidates_import(tmp: Path) -> None:
    video = tmp / "vid2"
    (video / "assets").mkdir(parents=True)
    write_json(
        video / "assets" / "asset-prep.json",
        {"version": 1, "paths": {"localRoot": str((tmp / ".local-assets" / "vid2").as_posix())}},
    )
    ref_a = write_dummy_png(tmp / "ref-a.png", (11, 22, 33, 255), (70, 90))
    assert_true(
        import_reference(
            "barcelona-home",
            ref_a,
            "https://store.fcbarcelona.com/collections/men-home-kit/products/fc-barcelona-home-amshirt-25-26-ucl",
            replace=True,
        )
        == 0,
        "import ref a",
    )
    job = sample_pending_job("explain-two", "barcelona-home")
    write_json(video / "assets" / "mascot-generation.json", {"version": 1, "jobs": [job]})

    pose = pose_by_id(job["basePose"])
    base = Image.open(pose_path(pose)).convert("RGBA")
    good = Image.new("RGBA", base.size, (10, 80, 180, 255))
    px = good.load()
    for y in range(base.size[1] // 3, 2 * base.size[1] // 3):
        for x in range(base.size[0] // 3, 2 * base.size[0] // 3):
            px[x, y] = (129, 22, 45, 255)
    good_path = tmp / "good.png"
    good.save(good_path)

    # Change reference bytes after freeze.
    ref_b = write_dummy_png(tmp / "ref-b.png", (200, 10, 10, 255), (70, 90))
    assert_true(
        import_reference(
            "barcelona-home",
            ref_b,
            "https://store.fcbarcelona.com/collections/men-home-kit/products/fc-barcelona-home-amshirt-25-26-ucl",
            replace=True,
        )
        == 0,
        "replace ref",
    )
    assert_true(import_full_edit(video, job["id"], good_path) == 1, "changed reference must invalidate")

    # Restore matching freeze and import succeeds.
    job["outfitReferenceSha256"] = current_outfit_reference_sha(outfit_by_id("barcelona-home"))
    write_json(video / "assets" / "mascot-generation.json", {"version": 1, "jobs": [job]})
    assert_true(import_full_edit(video, job["id"], good_path) == 0, "matching reference must import")
    queue = load_json(video / "assets" / "mascot-generation.json")
    assert_true(queue["jobs"][0]["status"] == "needs-review", queue["jobs"][0])

    queue["jobs"][0]["status"] = "pending"
    write_json(video / "assets" / "mascot-generation.json", queue)
    assert_true(review.approve_jobs(video, [job["id"]]) == 1, "pending approve must fail")
    queue["jobs"][0]["status"] = "needs-review"
    write_json(video / "assets" / "mascot-generation.json", queue)
    assert_true(review.approve_jobs(video, [job["id"]]) == 0, "needs-review approve must pass")

    queue["jobs"][0]["status"] = "needs-review"
    write_json(video / "assets" / "mascot-generation.json", queue)
    old = sys.argv
    try:
        sys.argv = ["promote_mascot_variant.py", str(video), job["id"]]
        assert_true(promote_main() == 1, "promote must refuse unapproved")
    finally:
        sys.argv = old


def test_historical_and_current_outfit_resolution(tmp: Path) -> None:
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
                    "nationalTeam": {"outfit": "spain-home-2026"},
                }
            ],
        },
    )
    write_json(
        video / "scenes" / "visual-plan.json",
        {
            "version": 1,
            "scenes": [
                {
                    "id": "scene-03",
                    "outfitIntent": "national-team",
                    "mascot": {
                        "poseIntent": "point-left-two",
                        "basePose": "point-left-two",
                        "subject": "player-lamine-yamal",
                    },
                },
                {
                    "id": "scene-14",
                    "outfitIntent": "explicit",
                    "mascot": {
                        "poseIntent": "count-2",
                        "basePose": "count-2",
                        "subject": "player-lamine-yamal",
                        "explicitOutfit": "spain-home-2022",
                    },
                },
                {
                    "id": "scene-16",
                    "outfitIntent": "explicit",
                    "mascot": {
                        "poseIntent": "count-3",
                        "basePose": "count-3",
                        "subject": "player-lamine-yamal",
                        "explicitOutfit": "spain-home-2024",
                    },
                },
                {
                    "id": "scene-21",
                    "outfitIntent": "national-team",
                    "mascot": {
                        "poseIntent": "celebrate",
                        "basePose": "celebrate",
                        "subject": "player-lamine-yamal",
                    },
                },
            ],
        },
    )
    write_json(video / "assets" / "assets.json", {"version": 2, "assets": []})
    assert_true(sync(video) == 0, "sync failed")
    plan = load_json(video / "scenes" / "visual-plan.json")
    by_id = {s["id"]: s for s in plan["scenes"]}
    assert_true(by_id["scene-03"]["mascot"]["assetId"] == "mascot-point-left-two__spain-home-2026", by_id["scene-03"])
    assert_true(by_id["scene-14"]["mascot"]["assetId"] == "mascot-count-2__spain-home-2022", by_id["scene-14"])
    assert_true(by_id["scene-16"]["mascot"]["assetId"] == "mascot-count-3__spain-home-2024", by_id["scene-16"])
    assert_true(by_id["scene-21"]["mascot"]["assetId"] == "mascot-celebrate__spain-home-2026", by_id["scene-21"])
    assert_true(by_id["scene-14"]["outfitIntent"] == "explicit", by_id["scene-14"])
    assert_true(by_id["scene-16"]["mascot"]["explicitOutfit"] == "spain-home-2024", by_id["scene-16"])

    entities = entities_by_id(video)
    resolved = resolve_outfit("national-team", {}, entities["player-lamine-yamal"])
    assert_true(resolved == "spain-home-2026", resolved)


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

    run("barcelona_not_aliased", test_barcelona_not_aliased)
    run("spain_seasonal_ids", test_spain_seasonal_ids)
    run("prompt_policy_rendering", test_prompt_policy_rendering)
    barca_detail = outfit_detail_path("barcelona-home")
    barca_snapshot = barca_detail.read_text(encoding="utf-8") if barca_detail.exists() else None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            run("import_outfit_reference", lambda: test_import_outfit_reference(t))
            run("export_requires_reference_and_suit_without", lambda: test_export_requires_reference_and_suit_without(t))
            run("reference_change_invalidates_import", lambda: test_reference_change_invalidates_import(t))
            run("historical_and_current_outfit_resolution", lambda: test_historical_and_current_outfit_resolution(t))
    finally:
        if barca_snapshot is not None:
            barca_detail.write_text(barca_snapshot, encoding="utf-8")
        else:
            update_tracked_outfit_reference(
                "barcelona-home",
                source_url="https://store.fcbarcelona.com/collections/men-home-kit/products/fc-barcelona-home-amshirt-25-26-ucl",
                sha256="",
            )

    if failed:
        print(f"FAIL  {failed} test(s)")
        return 1
    print("PASS  mascot outfit workflow tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
