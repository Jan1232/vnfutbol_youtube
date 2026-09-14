#!/usr/bin/env python3
"""Offline tests for mascot outfit export/import/review workflow. No AI/API."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from asset_prep_common import write_json
from export_mascot_generation import export_job, verify_job_inputs
from import_mascot_full_edit import import_full_edit
from mascot_common import (
    DEFAULT_OUTFIT,
    MASCOT,
    hashes_current,
    load_json,
    mask_by_pose,
    outfit_by_id,
    pose_by_id,
    pose_path,
    sha256_file,
)
from promote_mascot_variant import main as promote_main
import review_mascot_variants as review
from ensure_mascot_variants import classify


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
        **hashes,
    }


def test_barcelona_not_aliased() -> None:
    # ensure classify never treats barcelona as default reuse
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
    source = (ROOT / "scripts" / "export_mascot_generation.py").read_text(encoding="utf-8")
    assert_true("default-home" in source and "barcelona-home" in source, "export must mention both")
    assert_true("alias" in source.lower() or "distinct" in source.lower(), source[:200])


def test_export_all_pending_including_barcelona(tmp: Path) -> None:
    video = tmp / "vid"
    (video / "assets").mkdir(parents=True)
    jobs = [
        sample_pending_job("explain-two", "barcelona-home"),
        sample_pending_job("celebrate", "spain-home"),
    ]
    jobs[1]["id"] = "mascot-job-test-002"
    write_json(video / "assets" / "mascot-generation.json", {"version": 1, "jobs": jobs})
    write_json(
        video / "assets" / "asset-prep.json",
        {"version": 1, "paths": {"localRoot": str((tmp / ".local-assets" / "vid").as_posix())}},
    )
    packs_root = tmp / ".local-assets" / "vid" / "mascot-generation"
    packs_root.mkdir(parents=True)
    for job in jobs:
        verify_job_inputs(job)
        path = export_job(video, job, packs_root)
        assert_true((path / "prompt.txt").exists(), path)
        assert_true((path / "base-pose.png").exists(), path)
        assert_true((path / "clothing-mask.png").exists(), path)
        assert_true((path / "canonical-reference.png").exists(), path)
        meta = json.loads((path / "job.json").read_text(encoding="utf-8"))
        assert_true(meta["hashes"]["basePoseSha256"] == job["basePoseSha256"], meta)
        assert_true(meta["expectedFullEdit"] == "output/full-edit.png", meta)
    assert_true((packs_root / "mascot-job-test-001" / "job.json").exists(), "barcelona pack missing")
    barca = json.loads((packs_root / "mascot-job-test-001" / "job.json").read_text(encoding="utf-8"))
    assert_true(barca["outfit"] == "barcelona-home", barca)


def test_import_and_review_gates(tmp: Path) -> None:
    video = tmp / "vid2"
    (video / "assets").mkdir(parents=True)
    job = sample_pending_job("explain-two", "barcelona-home")
    write_json(video / "assets" / "mascot-generation.json", {"version": 1, "jobs": [job]})
    write_json(
        video / "assets" / "asset-prep.json",
        {"version": 1, "paths": {"localRoot": str((tmp / ".local-assets" / "vid2").as_posix())}},
    )

    pose = pose_by_id(job["basePose"])
    base = Image.open(pose_path(pose)).convert("RGBA")
    wrong = Image.new("RGBA", (64, 64), (200, 0, 0, 255))
    wrong_path = tmp / "wrong.png"
    wrong.save(wrong_path)
    assert_true(import_full_edit(video, job["id"], wrong_path) == 1, "wrong size must fail")

    # stale hashes
    queue = load_json(video / "assets" / "mascot-generation.json")
    queue["jobs"][0]["basePoseSha256"] = "0" * 64
    write_json(video / "assets" / "mascot-generation.json", queue)
    good = Image.new("RGBA", base.size, (10, 80, 180, 255))
    # paint garment-ish opaque pixels
    px = good.load()
    for y in range(base.size[1] // 3, 2 * base.size[1] // 3):
        for x in range(base.size[0] // 3, 2 * base.size[0] // 3):
            px[x, y] = (129, 22, 45, 255)
    good_path = tmp / "good.png"
    good.save(good_path)
    assert_true(import_full_edit(video, job["id"], good_path) == 1, "stale hash must fail")

    # restore hashes and import
    job = sample_pending_job("explain-two", "barcelona-home")
    write_json(video / "assets" / "mascot-generation.json", {"version": 1, "jobs": [job]})
    assert_true(import_full_edit(video, job["id"], good_path) == 0, "import should succeed")
    queue = load_json(video / "assets" / "mascot-generation.json")
    assert_true(queue["jobs"][0]["status"] == "needs-review", queue["jobs"][0])
    assert_true((video / job["targetFullEdit"]).exists(), "full edit missing")
    assert_true((video / job["targetLayer"]).exists(), "layer missing")

    # approve requires needs-review — pending fails
    queue["jobs"][0]["status"] = "pending"
    write_json(video / "assets" / "mascot-generation.json", queue)
    assert_true(review.approve_jobs(video, [job["id"]]) == 1, "pending approve must fail")

    queue["jobs"][0]["status"] = "needs-review"
    write_json(video / "assets" / "mascot-generation.json", queue)
    assert_true(review.approve_jobs(video, [job["id"]]) == 0, "needs-review approve must pass")
    queue = load_json(video / "assets" / "mascot-generation.json")
    assert_true(queue["jobs"][0]["status"] == "approved", queue["jobs"][0])

    # reject preserves files
    queue["jobs"][0]["status"] = "needs-review"
    write_json(video / "assets" / "mascot-generation.json", queue)
    full = video / job["targetFullEdit"]
    layer = video / job["targetLayer"]
    assert_true(review.reject_jobs(video, [job["id"]], "bad boundary") == 0, "reject failed")
    assert_true(full.exists() and layer.exists(), "reject must preserve outputs")

    # promotion refuses unapproved
    queue["jobs"][0]["status"] = "needs-review"
    write_json(video / "assets" / "mascot-generation.json", queue)
    old = sys.argv
    try:
        sys.argv = ["promote_mascot_variant.py", str(video), job["id"]]
        assert_true(promote_main() == 1, "promote must refuse unapproved")
    finally:
        sys.argv = old


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
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        run("export_all_pending_including_barcelona", lambda: test_export_all_pending_including_barcelona(t))
        run("import_and_review_gates", lambda: test_import_and_review_gates(t))

    if failed:
        print(f"FAIL  {failed} test(s)")
        return 1
    print("PASS  mascot outfit workflow tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
