#!/usr/bin/env python3
"""P0.5 regressions: API canvas pad/crop, tracked reference SHA, classifier, vision, reuse."""

from __future__ import annotations

import ast
import inspect
import math
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from mascot_auto_generate import (
    crop_api_result,
    evaluate_vision_payload,
    generate_missing_variant,
    prepare_api_canvas,
)
from mascot_common import (
    MASCOT,
    OUTFIT_REF_ROOT,
    VARIANTS_PATH,
    expected_reference_sha256,
    find_same_outfit_mascot_composite,
    hashes_current,
    load_outfit_detail,
    load_variants,
    mask_by_pose,
    mask_path,
    outfit_by_id,
    outfit_detail_path,
    outfit_fingerprint,
    outfit_reference_path,
    pose_by_id,
    pose_path,
    recompute_composite_sha256,
    sha256_file,
    update_tracked_outfit_reference,
    variant_by_pair,
    variant_cache_key,
    variant_is_reusable,
    write_json as mc_write_json,
)
from prepare_assets import classify_plan_record


def assert_true(cond: bool, message) -> None:
    if not cond:
        raise AssertionError(message)


def paint_kit(pose_id: str, color=(20, 80, 180, 255)) -> Image.Image:
    pose = pose_by_id(pose_id)
    mask = mask_by_pose(pose_id)
    base = Image.open(pose_path(pose)).convert("RGBA")
    clothing = Image.open(mask_path(mask)).convert("L")
    img = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ipx, mpx = img.load(), clothing.load()
    w, h = base.size
    for y in range(h):
        for x in range(w):
            if mpx[x, y] > 0:
                ipx[x, y] = color
    return img


def padded_edit(pose_id: str, color=(20, 80, 180, 255)):
    def fake_edit(**kwargs):
        img = paint_kit(pose_id, color)
        target = kwargs.get("target_size")
        if target and img.size != target:
            canvas = Image.new("RGBA", target, (0, 0, 0, 0))
            canvas.paste(img, (0, 0))
            return canvas
        return img

    return fake_edit


def clear_pair(pose_id: str, outfit_id: str) -> dict:
    original = load_variants()
    cleaned = [
        v
        for v in original.get("variants", [])
        if not (v.get("basePose") == pose_id and v.get("outfit") == outfit_id)
    ]
    mc_write_json(VARIANTS_PATH, {"version": 1, "variants": cleaned})
    return original


def restore_variants(original: dict) -> None:
    mc_write_json(VARIANTS_PATH, original)


def seed_reusable_variant(pose_id: str, outfit_id: str, dest: Path, *, ref_sha: str | None = None) -> dict:
    pose = pose_by_id(pose_id)
    outfit = outfit_by_id(outfit_id)
    mask = mask_by_pose(pose_id)
    assert pose and outfit and mask
    base = Image.open(pose_path(pose)).convert("RGBA")
    dest.mkdir(parents=True, exist_ok=True)
    layer_path = dest / f"{pose_id}-layer.png"
    comp_path = dest / f"{pose_id}-comp.png"
    layer = paint_kit(pose_id)
    # Extract opaque clothing as layer via mask.
    clothing = Image.open(mask_path(mask)).convert("L")
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    lpx, mpx, opx = layer.load(), clothing.load(), out.load()
    w, h = base.size
    for y in range(h):
        for x in range(w):
            if mpx[x, y] > 0:
                opx[x, y] = lpx[x, y]
    out.save(layer_path)
    Image.alpha_composite(base, out).save(comp_path)
    record = {
        "id": f"{pose_id}__{outfit_id}",
        "basePose": pose_id,
        "outfit": outfit_id,
        "type": "outfit-layer",
        "file": layer_path.relative_to(MASCOT).as_posix(),
        "compositeFile": comp_path.relative_to(MASCOT).as_posix(),
        "status": "approved-auto",
        "sha256": sha256_file(layer_path),
        "compositeSha256": recompute_composite_sha256(pose, layer_path),
        **hashes_current(
            pose,
            mask,
            outfit,
            generation_reference_sha256=ref_sha,
            consistency_reference_sha256=None,
        ),
    }
    return record


# --- 1. API canvas ---------------------------------------------------------


def test_prepare_api_canvas_count3_no_rescale() -> None:
    pose = pose_by_id("count-3")
    mask = mask_by_pose("count-3")
    assert pose and mask
    base = Image.open(pose_path(pose)).convert("RGBA")
    binary = Image.open(mask_path(mask)).convert("L")
    assert_true(base.size == (1122, 1402), base.size)
    padded_base, padded_mask, crop_box = prepare_api_canvas(base, binary)
    assert_true(padded_base.size == (1136, 1408), padded_base.size)
    assert_true(padded_mask.size == (1136, 1408), padded_mask.size)
    assert_true(crop_box == (0, 0, 1122, 1402), crop_box)
    # Original pixels unchanged (no rescale).
    assert_true(list(padded_base.crop(crop_box).getdata()) == list(base.getdata()), "pixels changed")
    # Padding region non-editable.
    assert_true(padded_mask.getpixel((1135, 1407)) == 0, "pad must be non-editable")
    # Simulated API response at padded size crops back.
    fake_api = Image.new("RGBA", (1136, 1408), (9, 9, 9, 255))
    fake_api.paste(base, (0, 0))
    cropped = crop_api_result(fake_api, crop_box, expected_api_size=(1136, 1408))
    assert_true(cropped.size == (1122, 1402), cropped.size)
    assert_true(list(cropped.getdata()) == list(base.getdata()), "crop rescale")


def test_prepare_api_canvas_count2() -> None:
    pose = pose_by_id("count-2")
    mask = mask_by_pose("count-2")
    base = Image.open(pose_path(pose)).convert("RGBA")
    binary = Image.open(mask_path(mask)).convert("L")
    assert_true(base.size == (1122, 1402), base.size)
    padded_base, _, crop_box = prepare_api_canvas(base, binary)
    assert_true(padded_base.size == (1136, 1408), padded_base.size)
    assert_true(math.ceil(1122 / 16) * 16 == 1136, "api_w")
    assert_true(math.ceil(1402 / 16) * 16 == 1408, "api_h")
    assert_true(crop_box == (0, 0, 1122, 1402), crop_box)


# --- 2. Tracked reference SHA / cross-machine reuse ------------------------


def test_reuse_without_local_reference(tmp: Path) -> None:
    pose_id, outfit_id = "explain-two", "barcelona-home"
    detail_path = outfit_detail_path(outfit_id)
    original_detail = detail_path.read_text(encoding="utf-8")
    original_variants = clear_pair(pose_id, outfit_id)
    ref_path = outfit_reference_path(outfit_id)
    backup_ref = None
    if ref_path.exists():
        backup_ref = ref_path.read_bytes()
    try:
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (40, 40), (10, 20, 30, 255)).save(ref_path)
        ref_sha = sha256_file(ref_path)
        update_tracked_outfit_reference(
            outfit_id,
            source_url="https://example.test/kit",
            sha256=ref_sha,
        )
        assert_true(expected_reference_sha256(outfit_by_id(outfit_id)) == ref_sha, "tracked")

        record = seed_reusable_variant(
            pose_id,
            outfit_id,
            MASCOT / "variants" / "_test_p05_ref",
            ref_sha=ref_sha,
        )
        mc_write_json(VARIANTS_PATH, {"version": 1, "variants": [record]})
        pose, mask, outfit = pose_by_id(pose_id), mask_by_pose(pose_id), outfit_by_id(outfit_id)
        assert_true(variant_is_reusable(record, pose, mask, outfit), "with local ref")

        # Remove local third-party PNG — clean clone reuse must still work.
        ref_path.unlink()
        assert_true(not ref_path.exists(), "ref removed")
        assert_true(expected_reference_sha256(outfit_by_id(outfit_id)) == ref_sha, "tracked remains")
        assert_true(
            variant_is_reusable(variant_by_pair(pose_id, outfit_id), pose, mask, outfit),
            "reuse without local PNG",
        )
        result = generate_missing_variant(
            pose_id,
            outfit_id,
            edit_fn=lambda **k: (_ for _ in ()).throw(AssertionError("must not generate")),
        )
        assert_true(result["result"] == "REUSED", result)
    finally:
        detail_path.write_text(original_detail, encoding="utf-8")
        if backup_ref is not None:
            ref_path.parent.mkdir(parents=True, exist_ok=True)
            ref_path.write_bytes(backup_ref)
        elif ref_path.exists():
            ref_path.unlink()
        restore_variants(original_variants)
        for path in (MASCOT / "variants" / "_test_p05_ref").glob("*"):
            try:
                path.unlink()
            except OSError:
                pass


def test_local_reference_mismatch_blocks(tmp: Path) -> None:
    outfit_id = "barcelona-home"
    detail_path = outfit_detail_path(outfit_id)
    original_detail = detail_path.read_text(encoding="utf-8")
    original_variants = clear_pair("explain-two", outfit_id)
    ref_path = outfit_reference_path(outfit_id)
    backup_ref = ref_path.read_bytes() if ref_path.exists() else None
    try:
        update_tracked_outfit_reference(
            outfit_id,
            source_url="https://example.test/kit",
            sha256="a" * 64,
        )
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(ref_path)
        result = generate_missing_variant(
            "explain-two",
            outfit_id,
            edit_fn=padded_edit("explain-two"),
            work_dir=tmp / "mismatch",
        )
        assert_true(result["result"] == "BLOCKED_REFERENCE_MISMATCH", result)
    finally:
        detail_path.write_text(original_detail, encoding="utf-8")
        if backup_ref is not None:
            ref_path.write_bytes(backup_ref)
        elif ref_path.exists():
            ref_path.unlink()
        restore_variants(original_variants)


# --- 3. classify_plan_record -----------------------------------------------


def test_classify_requires_variant_is_reusable(tmp: Path) -> None:
    src = inspect.getsource(classify_plan_record)
    assert_true("variant_is_reusable" in src, src)
    assert_true("status\") in REUSABLE_VARIANT_STATUSES" not in src, src)

    pose_id, outfit_id = "explain-two", "suit-navy"
    original = clear_pair(pose_id, outfit_id)
    pose, mask, outfit = pose_by_id(pose_id), mask_by_pose(pose_id), outfit_by_id(outfit_id)
    asset = {
        "id": "mascot-explain-two__suit-navy",
        "type": "MASCOT",
        "mascot": {"basePose": pose_id, "resolvedOutfit": outfit_id},
    }
    prep = {"renderOnlyAssetIds": [], "externalAssetIds": []}
    plan = {"scenes": []}

    # missing layer
    bad_missing = {
        "id": f"{pose_id}__{outfit_id}",
        "basePose": pose_id,
        "outfit": outfit_id,
        "status": "approved-auto",
        "file": "variants/_missing/layer.png",
        "compositeFile": "variants/_missing/comp.png",
        **hashes_current(pose, mask, outfit),
    }
    mc_write_json(VARIANTS_PATH, {"version": 1, "variants": [bad_missing]})
    rec = classify_plan_record(asset["id"], asset, prep, tmp, plan)
    assert_true(rec["status"] != "READY_MASCOT", rec)

    # corrupt layer sha
    good = seed_reusable_variant(pose_id, outfit_id, MASCOT / "variants" / "_test_p05_cls")
    good["sha256"] = "0" * 64
    mc_write_json(VARIANTS_PATH, {"version": 1, "variants": [good]})
    rec = classify_plan_record(asset["id"], asset, prep, tmp, plan)
    assert_true(rec["status"] != "READY_MASCOT", rec)

    # stale fingerprint
    good2 = seed_reusable_variant(pose_id, outfit_id, MASCOT / "variants" / "_test_p05_cls2")
    good2["outfitFingerprint"] = "deadbeef"
    mc_write_json(VARIANTS_PATH, {"version": 1, "variants": [good2]})
    rec = classify_plan_record(asset["id"], asset, prep, tmp, plan)
    assert_true(rec["status"] != "READY_MASCOT", rec)

    restore_variants(original)
    for folder in ("_test_p05_cls", "_test_p05_cls2"):
        d = MASCOT / "variants" / folder
        if d.exists():
            for path in d.glob("*"):
                try:
                    path.unlink()
                except OSError:
                    pass


# --- 4. Consistency anchor -------------------------------------------------


def test_consistency_anchor_reusable_and_fingerprint(tmp: Path) -> None:
    original = load_variants()
    try:
        a = seed_reusable_variant("explain-one", "suit-navy", MASCOT / "variants" / "_test_p05_c1")
        b = seed_reusable_variant("explain-two", "suit-navy", MASCOT / "variants" / "_test_p05_c2")
        # Corrupt B status-approved but bad sha — must not be chosen.
        b_bad = dict(b)
        b_bad["sha256"] = "0" * 64
        mc_write_json(VARIANTS_PATH, {"version": 1, "variants": [a, b_bad]})
        anchor = find_same_outfit_mascot_composite("suit-navy", exclude_pose="celebrate")
        assert_true(anchor is not None, anchor)
        assert_true(anchor["variantId"] == a["id"], anchor)
        assert_true("sha256" in anchor and anchor["sha256"], anchor)

        key1 = variant_cache_key(
            pose_by_id("celebrate"),
            mask_by_pose("celebrate"),
            "suit-navy",
            consistency_reference_sha256=anchor["sha256"],
        )
        key2 = variant_cache_key(
            pose_by_id("celebrate"),
            mask_by_pose("celebrate"),
            "suit-navy",
            consistency_reference_sha256="f" * 64,
        )
        assert_true(key1 != key2, "consistency sha must affect cache")
        fp1 = outfit_fingerprint("suit-navy", consistency_reference_sha256=anchor["sha256"])
        fp2 = outfit_fingerprint("suit-navy", consistency_reference_sha256="f" * 64)
        assert_true(fp1 != fp2, "consistency sha must affect fingerprint")
    finally:
        restore_variants(original)


# --- 5. Vision QA ----------------------------------------------------------


def test_vision_qa_local_pass_and_schema() -> None:
    src = inspect.getsource(__import__("mascot_auto_generate").default_vision_qa)
    assert_true("json_schema" in src, src)
    assert_true("VISION_QA_SCHEMA" in src or "strict" in src, src)
    # Model says pass=True but consistency low -> fail
    evaluated = evaluate_vision_payload(
        {
            "pass": True,
            "issues": [],
            "missingBranding": [],
            "extraBranding": [],
            "wrongText": [],
            "outfitConsistency": 0.5,
        }
    )
    assert_true(evaluated["pass"] is False, evaluated)
    # Missing consistency -> fail even if model pass true
    evaluated2 = evaluate_vision_payload(
        {
            "pass": True,
            "issues": [],
            "missingBranding": [],
            "extraBranding": [],
            "wrongText": [],
            "outfitConsistency": "nope",
        }
    )
    assert_true(evaluated2["pass"] is False, evaluated2)
    ok = evaluate_vision_payload(
        {
            "pass": False,
            "issues": [],
            "missingBranding": [],
            "extraBranding": [],
            "wrongText": [],
            "outfitConsistency": 0.95,
        }
    )
    assert_true(ok["pass"] is True, ok)


# --- 6. One reuse validator / compositeSha256 ------------------------------


def test_compose_and_resolve_use_variant_is_reusable() -> None:
    compose_src = (SCRIPTS / "compose_mascot.py").read_text(encoding="utf-8")
    resolve_src = (SCRIPTS / "resolve_mascot_assets.py").read_text(encoding="utf-8")
    prep_src = (SCRIPTS / "prepare_assets.py").read_text(encoding="utf-8")
    assert_true("variant_is_reusable" in compose_src, "compose")
    assert_true("REUSABLE_VARIANT_STATUSES" not in compose_src, compose_src)
    assert_true("variant_is_reusable" in resolve_src, "resolve")
    assert_true("variant_is_reusable" in prep_src, "prepare")


def test_composite_sha_verified(tmp: Path) -> None:
    pose_id, outfit_id = "explain-two", "suit-navy"
    original = clear_pair(pose_id, outfit_id)
    try:
        record = seed_reusable_variant(pose_id, outfit_id, MASCOT / "variants" / "_test_p05_comp")
        mc_write_json(VARIANTS_PATH, {"version": 1, "variants": [record]})
        pose, mask, outfit = pose_by_id(pose_id), mask_by_pose(pose_id), outfit_by_id(outfit_id)
        assert_true(variant_is_reusable(record, pose, mask, outfit), "good")
        # Corrupt on-disk composite bytes
        comp = MASCOT / record["compositeFile"]
        Image.new("RGBA", Image.open(comp).size, (255, 0, 0, 255)).save(comp)
        assert_true(not variant_is_reusable(record, pose, mask, outfit), "corrupt composite")
    finally:
        restore_variants(original)


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

    run("prepare_api_canvas_count3_no_rescale", test_prepare_api_canvas_count3_no_rescale)
    run("prepare_api_canvas_count2", test_prepare_api_canvas_count2)
    run("vision_qa_local_pass_and_schema", test_vision_qa_local_pass_and_schema)
    run("compose_and_resolve_use_variant_is_reusable", test_compose_and_resolve_use_variant_is_reusable)

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        run("consistency_anchor_reusable_and_fingerprint", lambda: test_consistency_anchor_reusable_and_fingerprint(t))
        run("reuse_without_local_reference", lambda: test_reuse_without_local_reference(t))
        run("local_reference_mismatch_blocks", lambda: test_local_reference_mismatch_blocks(t))
        run("classify_requires_variant_is_reusable", lambda: test_classify_requires_variant_is_reusable(t))
        run("composite_sha_verified", lambda: test_composite_sha_verified(t))

    if failed:
        print(f"FAIL  {failed} test(s)")
        return 1
    print("PASS  mascot P0.5 regression tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
