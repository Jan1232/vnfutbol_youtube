#!/usr/bin/env python3
"""Regression tests for P0 mascot auto-generation review blockers.

Offline by default. One opt-in LIVE smoke when OPENAI_LIVE_TEST=1.
Does not run Yamal multi-job generation.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from mascot_auto_generate import (
    build_generation_prompt,
    call_with_backoff,
    default_vision_qa,
    generate_missing_variant,
    is_transient_openai_error,
)
from mascot_common import (
    LOCAL_MASCOT_NEEDS_REVIEW,
    LOCAL_MASCOT_WORK,
    MASCOT,
    OUTFIT_REF_CHANNEL_LOCAL,
    OUTFIT_REF_ROOT,
    VARIANTS_PATH,
    channel_outfit_reference_path,
    compose_masked_replacement,
    extract_outfit_layer,
    find_official_outfit_reference,
    hashes_current,
    load_variants,
    mask_by_pose,
    mask_path,
    outfit_by_id,
    outfit_fingerprint,
    outfit_reference_path,
    pose_by_id,
    pose_path,
    sha256_file,
    variant_by_pair,
    variant_cache_key,
    variant_is_reusable,
    write_json as mc_write_json,
)
from validate_mascot_variant import validate_variant_images


def assert_true(cond: bool, message) -> None:
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


def padded_paint_edit(pose_id: str, color=(20, 80, 180, 255)):
    def fake_edit(**kwargs):
        img = paint_kit_for_pose(pose_id, color)
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


# --- P0.1 ------------------------------------------------------------------


def test_requirements_openai_pin() -> None:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert_true("openai>=3.10.0,<4" in text, text)
    assert_true("openai>=1.40.0" not in text, text)


# --- P0.2 ------------------------------------------------------------------


def test_plan_does_not_generate_prepare_does() -> None:
    prep_src = (SCRIPTS / "prepare_assets.py").read_text(encoding="utf-8")
    tree = ast.parse(prep_src)
    plan_generate = None
    prepare_generate = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "cmd_plan":
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "resolve_mascot_assets"
                ):
                    for kw in call.keywords:
                        if kw.arg == "generate":
                            plan_generate = ast.literal_eval(kw.value)
        if isinstance(node, ast.FunctionDef) and node.name == "cmd_prepare":
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "resolve_mascot_assets"
                ):
                    for kw in call.keywords:
                        if kw.arg == "generate":
                            prepare_generate = ast.literal_eval(kw.value)
    assert_true(plan_generate is False, f"cmd_plan generate={plan_generate}")
    assert_true(prepare_generate is True, f"cmd_prepare generate={prepare_generate}")


# --- P0.3 ------------------------------------------------------------------


def test_wrong_size_never_resized(tmp: Path) -> None:
    pose = pose_by_id("explain-two")
    assert pose
    base = Image.open(pose_path(pose)).convert("RGBA")

    def fake_edit(**kwargs):
        # Deliberately wrong API canvas size.
        return Image.new("RGBA", (base.size[0] // 2, base.size[1] // 2), (255, 0, 0, 255))

    original = clear_pair("explain-two", "suit-navy")
    try:
        result = generate_missing_variant(
            "explain-two",
            "suit-navy",
            edit_fn=fake_edit,
            vision_fn=lambda **k: {"pass": True, "issues": [], "outfitConsistency": 1.0},
            work_dir=tmp / "wrong-size",
        )
        assert_true(result["result"] == "ERROR", result)
        assert_true("refusing to resize" in result.get("reason", ""), result)
    finally:
        restore_variants(original)


# --- P0.4 ------------------------------------------------------------------


def test_dynamic_image_index_prompt() -> None:
    with_ref = build_generation_prompt("suit-navy", has_outfit_ref=True, has_consistency_ref=False)
    assert_true("IMAGE 2 is the official outfit visual reference" in with_ref, with_ref)
    assert_true("IMAGE 3 is the canonical mascot identity reference" in with_ref, with_ref)

    without = build_generation_prompt("suit-navy", has_outfit_ref=False, has_consistency_ref=False)
    assert_true("IMAGE 2 is the canonical mascot identity reference" in without, without)
    assert_true("official outfit visual reference" not in without, without)

    both = build_generation_prompt("suit-navy", has_outfit_ref=True, has_consistency_ref=True)
    assert_true("IMAGE 2 is the official outfit visual reference" in both, both)
    assert_true("IMAGE 3 is an existing approved mascot" in both, both)
    assert_true("IMAGE 4 is the canonical mascot identity reference" in both, both)


# --- P0.5 ------------------------------------------------------------------


def test_variant_is_reusable_checks_files_and_hash(tmp: Path) -> None:
    pose = pose_by_id("explain-two")
    outfit = outfit_by_id("suit-navy")
    mask = mask_by_pose("explain-two")
    assert pose and outfit and mask
    base = Image.open(pose_path(pose)).convert("RGBA")
    layer = tmp / "layer.png"
    composite = tmp / "composite.png"
    Image.new("RGBA", base.size, (10, 20, 30, 255)).save(layer)
    base.save(composite)
    # Point into MASCOT tree via relative paths under a tmp subdir linked conceptually —
    # write under MASCOT/_test_p0 so relative_to(MASCOT) works.
    dest = MASCOT / "variants" / "_test_p0_reusable"
    dest.mkdir(parents=True, exist_ok=True)
    layer_m = dest / "layer.png"
    comp_m = dest / "composite.png"
    layer_img = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer_img.save(layer_m)
    compose_masked_replacement(base, layer_img).save(comp_m)
    from mascot_common import recompute_composite_sha256

    good = {
        "id": "explain-two__suit-navy",
        "basePose": "explain-two",
        "outfit": "suit-navy",
        "file": layer_m.relative_to(MASCOT).as_posix(),
        "compositeFile": comp_m.relative_to(MASCOT).as_posix(),
        "status": "approved-auto",
        "sha256": sha256_file(layer_m),
        "compositeSha256": recompute_composite_sha256(pose, layer_m),
        **hashes_current(pose, mask, outfit),
    }
    assert_true(variant_is_reusable(good, pose, mask, outfit), "good row must reuse")

    bad_status = dict(good, status="needs-review")
    assert_true(not variant_is_reusable(bad_status, pose, mask, outfit), "status")

    bad_hash = dict(good, sha256="0" * 64)
    assert_true(not variant_is_reusable(bad_hash, pose, mask, outfit), "layer sha")

    missing_layer = dict(good, file="variants/_test_p0_reusable/missing-layer.png")
    assert_true(not variant_is_reusable(missing_layer, pose, mask, outfit), "layer exists")

    missing_comp = dict(good, compositeFile="variants/_test_p0_reusable/missing-comp.png")
    assert_true(not variant_is_reusable(missing_comp, pose, mask, outfit), "composite exists")

    stale = dict(good, outfitFingerprint="deadbeef")
    assert_true(not variant_is_reusable(stale, pose, mask, outfit), "hashes current")
    # Cleanup local test artifacts so they are never committed.
    for path in (layer_m, comp_m):
        try:
            path.unlink()
        except OSError:
            pass
    try:
        dest.rmdir()
    except OSError:
        pass


# --- P0.6 ------------------------------------------------------------------


def test_deterministic_qa_thresholds(tmp: Path) -> None:
    pose = pose_by_id("explain-two")
    mask = mask_by_pose("explain-two")
    assert pose and mask
    base = Image.open(pose_path(pose)).convert("RGBA")
    binary = Image.open(mask_path(mask)).convert("L")
    # Low coverage layer: only a tiny fraction of garment pixels filled.
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    lpx = layer.load()
    mpx = binary.load()
    filled = 0
    w, h = base.size
    for y in range(h):
        for x in range(w):
            if mpx[x, y] > 0 and filled < 5:
                lpx[x, y] = (255, 0, 0, 255)
                filled += 1
    composite = compose_masked_replacement(base, layer)
    layer_p = tmp / "low-layer.png"
    comp_p = tmp / "low-comp.png"
    full_p = tmp / "low-full.png"
    layer.save(layer_p)
    composite.save(comp_p)
    paint_kit_for_pose("explain-two").save(full_p)
    result = validate_variant_images(
        base_pose_path=pose_path(pose),
        mask_path_file=mask_path(mask),
        full_edit_path=full_p,
        layer_path=layer_p,
        composite_path=comp_p,
    )
    assert_true(result["coverage"] < 0.90, result)
    assert_true(result["pass"] is False, result)
    assert_true(any("coverage" in i for i in result["issues"]), result["issues"])

    # High coverage should pass coverage check (outside-mask may still pass via extract path).
    good_full = paint_kit_for_pose("explain-two")

    good_layer = extract_outfit_layer(good_full, binary)
    good_comp = compose_masked_replacement(base, good_layer)
    g_layer = tmp / "good-layer.png"
    g_comp = tmp / "good-comp.png"
    g_full = tmp / "good-full.png"
    good_layer.save(g_layer)
    good_comp.save(g_comp)
    good_full.save(g_full)
    ok = validate_variant_images(
        base_pose_path=pose_path(pose),
        mask_path_file=mask_path(mask),
        full_edit_path=g_full,
        layer_path=g_layer,
        composite_path=g_comp,
    )
    assert_true(ok["coverage"] >= 0.90, ok)
    assert_true(ok.get("holeRatio", 0) <= 0.05, ok)
    assert_true(ok["pass"] is True, ok)


# --- P0.7 ------------------------------------------------------------------


def test_vision_qa_contract() -> None:
    src = inspect.getsource(default_vision_qa)
    assert_true("generationRules" in src, "must include generationRules")
    assert_true("forbiddenRules" in src, "must include forbiddenRules")
    assert_true("branding" in src, "must include branding")
    assert_true('"detail": "high"' in src or "detail\": \"high\"" in src or 'detail": "high"' in src, src)
    assert_true("json_schema" in src or "json_object" in src or "JSON" in src, src)
    eval_src = inspect.getsource(__import__("mascot_auto_generate").evaluate_vision_payload)
    assert_true("OUTFIT_CONSISTENCY_MIN" in eval_src or "0.90" in eval_src, eval_src)


# --- P0.8 ------------------------------------------------------------------


def test_skip_vision_needs_review_not_approved(tmp: Path) -> None:
    original = clear_pair("explain-two", "suit-navy")
    try:
        result = generate_missing_variant(
            "explain-two",
            "suit-navy",
            edit_fn=padded_paint_edit("explain-two"),
            vision_fn=lambda **k: {"pass": True, "issues": [], "outfitConsistency": 1.0},
            work_dir=tmp / "skip-vis",
            skip_vision=True,
        )
        assert_true(result["result"] == "NEEDS_REVIEW", result)
        variant = variant_by_pair("explain-two", "suit-navy")
        assert_true(variant is not None, variant)
        assert_true(variant["status"] == "needs-review", variant)
        assert_true(variant["status"] != "approved-auto", variant)
    finally:
        variant = variant_by_pair("explain-two", "suit-navy")
        if variant:
            for key in ("file", "compositeFile"):
                path = MASCOT / variant[key] if variant.get(key) else None
                if path and path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        pass
        restore_variants(original)


# --- P0.9 / P0.12 ----------------------------------------------------------


def test_official_ref_is_image2_and_local_only(tmp: Path) -> None:
    # Official lookup must never prefer channel-assets committed tree.
    committed = channel_outfit_reference_path("suit-navy")
    assert_true("channel-assets" in committed.as_posix(), committed)
    assert_true(".local-assets" in OUTFIT_REF_ROOT.as_posix(), OUTFIT_REF_ROOT)
    assert_true(".local-assets" in OUTFIT_REF_CHANNEL_LOCAL.as_posix(), OUTFIT_REF_CHANNEL_LOCAL)
    assert_true(find_official_outfit_reference.__doc__ and "local-assets" in find_official_outfit_reference.__doc__, find_official_outfit_reference.__doc__)
    # Source must not list channel_outfit_reference_path as a candidate.
    src = inspect.getsource(find_official_outfit_reference)
    assert_true("channel_outfit_reference_path" not in src, src)
    assert_true("OUTFIT_REF_CHANNEL_LOCAL" in src or "outfit_reference_path" in src, src)

    captured = {}

    def fake_edit(**kwargs):
        captured["outfit_ref"] = kwargs.get("outfit_ref")
        captured["consistency_ref"] = kwargs.get("consistency_ref")
        captured["prompt"] = kwargs.get("prompt")
        return padded_paint_edit("explain-two")(**kwargs)
    official = tmp / "official-ref.png"
    Image.new("RGBA", (32, 32), (1, 2, 3, 255)).save(official)
    original = clear_pair("explain-two", "suit-navy")
    try:
        with mock.patch(
            "mascot_auto_generate.find_same_outfit_mascot_composite",
            return_value=None,
        ), mock.patch(
            "mascot_auto_generate.verify_local_outfit_reference",
            return_value={"path": official, "sha256": sha256_file(official), "error": None},
        ):
            result = generate_missing_variant(
                "explain-two",
                "suit-navy",
                edit_fn=fake_edit,
                vision_fn=lambda **k: {
                    "pass": True,
                    "issues": [],
                    "outfitConsistency": 0.95,
                },
                work_dir=tmp / "ref-order",
                skip_vision=False,
            )
        assert_true(result["result"] == "GENERATED", result)
        assert_true(captured.get("outfit_ref") == official, captured)
        assert_true("IMAGE 2 is the official outfit visual reference" in (captured.get("prompt") or ""), captured)
        variant = variant_by_pair("explain-two", "suit-navy")
        assert_true(variant is not None, variant)
        assert_true(variant.get("generationReferenceSha256") == sha256_file(official), variant)
    finally:
        variant = variant_by_pair("explain-two", "suit-navy")
        if variant:
            for key in ("file", "compositeFile"):
                path = MASCOT / variant[key] if variant.get(key) else None
                if path and path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        pass
        restore_variants(original)


# --- P0.10 -----------------------------------------------------------------


def test_generation_reference_hash_in_fingerprint(tmp: Path) -> None:
    pose = pose_by_id("explain-two")
    mask = mask_by_pose("explain-two")
    assert pose and mask
    a = "a" * 64
    b = "b" * 64
    key_a = variant_cache_key(pose, mask, "suit-navy", generation_reference_sha256=a)
    key_b = variant_cache_key(pose, mask, "suit-navy", generation_reference_sha256=b)
    assert_true(key_a != key_b, (key_a, key_b))
    fp_a = outfit_fingerprint("suit-navy", generation_reference_sha256=a)
    fp_b = outfit_fingerprint("suit-navy", generation_reference_sha256=b)
    assert_true(fp_a != fp_b, (fp_a, fp_b))
    hashes = hashes_current(
        pose,
        mask,
        outfit_by_id("suit-navy"),
        generation_reference_sha256=a,
    )
    assert_true(hashes.get("generationReferenceSha256") == a, hashes)


# --- P0.11 -----------------------------------------------------------------


def test_work_dirs_under_local_assets() -> None:
    assert_true(".local-assets" in LOCAL_MASCOT_WORK.as_posix(), LOCAL_MASCOT_WORK)
    assert_true(".local-assets" in LOCAL_MASCOT_NEEDS_REVIEW.as_posix(), LOCAL_MASCOT_NEEDS_REVIEW)
    assert_true("channel-assets" not in LOCAL_MASCOT_WORK.as_posix(), LOCAL_MASCOT_WORK)
    src = (SCRIPTS / "mascot_auto_generate.py").read_text(encoding="utf-8")
    assert_true("LOCAL_MASCOT_WORK" in src, "work dir constant")
    assert_true("LOCAL_MASCOT_NEEDS_REVIEW" in src, "needs-review constant")
    assert_true('MASCOT / "variants" / "_work"' not in src, src)
    assert_true('MASCOT / "variants" / "_needs_review"' not in src, src)


# --- P0.13 -----------------------------------------------------------------


def test_retry_backoff_transient() -> None:
    class RateLimitError(Exception):
        status_code = 429

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError("429 rate limit")
        return "ok"

    assert_true(is_transient_openai_error(RateLimitError("429")), "429 transient")
    with mock.patch("mascot_auto_generate.time.sleep", return_value=None):
        assert_true(call_with_backoff(flaky, max_retries=5) == "ok", calls)
    assert_true(calls["n"] == 3, calls)

    def permanent():
        raise ValueError("bad request")

    try:
        call_with_backoff(permanent, max_retries=3)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# --- LIVE smoke ------------------------------------------------------------


def test_live_openai_sunburst_smoke(tmp: Path) -> None:
    if os.environ.get("OPENAI_LIVE_TEST") != "1":
        raise RuntimeError("SKIP live_openai_sunburst_smoke (set OPENAI_LIVE_TEST=1)")
    # Tiny synthetic pose/mask — one real Images Edit call, not Yamal jobs.
    pose_img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    for y in range(40, 220):
        for x in range(80, 176):
            pose_img.putpixel((x, y), (240, 240, 240, 255))
    mask_img = Image.new("L", (256, 256), 0)
    for y in range(100, 180):
        for x in range(90, 166):
            mask_img.putpixel((x, y), 255)
    pose_file = tmp / "live-pose.png"
    mask_file = tmp / "live-mask.png"
    api_mask_file = tmp / "live-api-mask.png"
    ref_file = tmp / "live-ref.png"
    canon_file = tmp / "live-canon.png"
    pose_img.save(pose_file)
    mask_img.save(mask_file)
    Image.new("RGBA", (64, 64), (200, 16, 46, 255)).save(ref_file)
    pose_img.save(canon_file)

    from mascot_auto_generate import build_api_mask, default_openai_edit

    build_api_mask(mask_img).save(api_mask_file)
    prompt = (
        "Edit IMAGE 1 clothing only inside the mask to a simple solid red jersey. "
        "Preserve pose and transparent background. Exact same pixel size."
    )
    out = default_openai_edit(
        pose_path_file=pose_file,
        outfit_ref=ref_file,
        canonical=canon_file,
        api_mask_path=api_mask_file,
        prompt=prompt,
        target_size=(256, 256),
    )
    assert_true(out.size == (256, 256), out.size)
    out_path = tmp / "live-out.png"
    out.save(out_path)
    assert_true(out_path.exists(), out_path)


def main() -> int:
    failed = 0
    skipped = 0

    def run(name, fn):
        nonlocal failed, skipped
        try:
            fn()
            print(f"OK    {name}")
        except Exception as exc:  # noqa: BLE001
            if str(exc).startswith("SKIP"):
                skipped += 1
                print(str(exc))
                return
            failed += 1
            print(f"FAIL  {name}: {exc}")

    run("requirements_openai_pin", test_requirements_openai_pin)
    run("plan_does_not_generate_prepare_does", test_plan_does_not_generate_prepare_does)
    run("dynamic_image_index_prompt", test_dynamic_image_index_prompt)
    run("vision_qa_contract", test_vision_qa_contract)
    run("work_dirs_under_local_assets", test_work_dirs_under_local_assets)
    run("retry_backoff_transient", test_retry_backoff_transient)
    run("generation_reference_hash_in_fingerprint", lambda: test_generation_reference_hash_in_fingerprint(Path(".")))

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        run("wrong_size_never_resized", lambda: test_wrong_size_never_resized(t))
        run("variant_is_reusable_checks_files_and_hash", lambda: test_variant_is_reusable_checks_files_and_hash(t))
        run("deterministic_qa_thresholds", lambda: test_deterministic_qa_thresholds(t))
        run("skip_vision_needs_review_not_approved", lambda: test_skip_vision_needs_review_not_approved(t))
        run("official_ref_is_image2_and_local_only", lambda: test_official_ref_is_image2_and_local_only(t))
        run("live_openai_sunburst_smoke", lambda: test_live_openai_sunburst_smoke(t))

    if failed:
        print(f"FAIL  {failed} test(s)")
        return 1
    print(f"PASS  mascot P0 regression tests (skipped={skipped})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
