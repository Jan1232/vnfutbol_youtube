#!/usr/bin/env python3
"""Automatic mascot outfit generation via OpenAI Images Edit.

REUSE approved variants. Generate only when missing/stale.
Final pixels outside the approved clothing mask always come from the original pose.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    DEFAULT_OUTFIT,
    MASCOT,
    PROMPT_VERSION,
    REUSABLE_VARIANT_STATUSES,
    VARIANTS_PATH,
    composite_destination,
    find_outfit_reference_image,
    hashes_current,
    image_model,
    image_quality,
    layer_destination,
    load_outfit_detail,
    load_poses,
    load_variants,
    mask_by_pose,
    mask_path,
    max_generation_attempts,
    openai_api_key,
    outfit_by_id,
    outfit_fingerprint,
    pose_by_id,
    pose_path,
    sha256_file,
    sha256_json,
    variant_by_pair,
    variant_cache_key,
    variant_id,
    variant_is_reusable,
    vision_qa_model,
    write_json,
)
from validate_mascot_variant import validate_variant_images


EditFn = Callable[..., Image.Image]
VisionFn = Callable[..., dict]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_api_mask(binary_mask: Image.Image) -> Image.Image:
    """OpenAI: transparent alpha = editable. Internal: white = clothing."""
    mask = binary_mask.convert("L")
    api = Image.new("RGBA", mask.size, (0, 0, 0, 255))
    mpx = mask.load()
    apx = api.load()
    width, height = mask.size
    for y in range(height):
        for x in range(width):
            if mpx[x, y] > 0:
                apx[x, y] = (0, 0, 0, 0)
            else:
                apx[x, y] = (255, 255, 255, 255)
    return api


def extract_outfit_layer(
    full_edit: Image.Image,
    binary_mask: Image.Image,
    *,
    feather: int = 2,
) -> Image.Image:
    hard = binary_mask.convert("L")
    soft = hard.filter(ImageFilter.GaussianBlur(radius=feather)) if feather else hard
    edited = full_edit.convert("RGBA")
    if edited.size != hard.size:
        raise ValueError(f"full-edit size {edited.size} != mask {hard.size}")
    layer = Image.new("RGBA", hard.size, (0, 0, 0, 0))
    epx = edited.load()
    hpx = hard.load()
    spx = soft.load()
    lpx = layer.load()
    kept = 0
    width, height = hard.size
    for y in range(height):
        for x in range(width):
            hard_v = hpx[x, y]
            if hard_v <= 0:
                continue
            coverage = min(hard_v, spx[x, y])
            if coverage <= 0:
                continue
            r, g, b, a = epx[x, y]
            alpha = min(a, coverage)
            if alpha:
                lpx[x, y] = (r, g, b, alpha)
                kept += 1
    if kept == 0:
        raise ValueError("extracted outfit layer is empty")
    return layer


def build_generation_prompt(outfit_id: str, *, previous_issues: list[str] | None = None) -> str:
    detail = load_outfit_detail(outfit_id)
    rules = "\n".join(f"- {item}" for item in detail.get("generationRules") or [])
    forbidden = "\n".join(f"- {item}" for item in detail.get("forbiddenRules") or [])
    branding = detail.get("branding") or {}
    prompt = f"""You are editing an existing approved mascot asset.

IMAGE 1 is the exact approved base pose.
IMAGE 2 is the outfit visual reference.
IMAGE 3 is the canonical mascot identity reference.

Change ONLY the clothing of IMAGE 1 inside the supplied clothing mask.

ABSOLUTELY PRESERVE:
- exact pose
- head shape
- face mask
- white eyes
- body proportions
- arms
- hands
- fingers
- gesture
- framing
- transparent background

Do not redraw the character.
Do not change anatomy.
Do not change the pose.

OUTFIT:
{detail.get('description') or outfit_id}

REQUIRED DETAILS:
{rules}

BRANDING:
- crest: {branding.get('crest')}
- manufacturer: {branding.get('manufacturer')}
- sponsor: {branding.get('sponsor')}

FORBIDDEN:
{forbidden}
- player name
- player number

The final clothing must look like the same physical outfit used
across all other mascot poses.

No scenery.
No glow.
No decorative background.
Transparent PNG.
"""
    if previous_issues:
        joined = "\n".join(f"- {item}" for item in previous_issues)
        prompt += f"""

Previous attempt failed because:
{joined}

Correct these issues in this attempt.
"""
    return prompt


def default_openai_edit(
    *,
    pose_path_file: Path,
    outfit_ref: Path | None,
    canonical: Path,
    api_mask_path: Path,
    prompt: str,
) -> Image.Image:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openai package is not installed") from exc
    key = openai_api_key()
    if not key:
        raise RuntimeError("missing OPENAI_API_KEY")
    client = OpenAI(api_key=key)
    images = [pose_path_file.open("rb")]
    opened = list(images)
    try:
        if outfit_ref is not None and outfit_ref.exists():
            handle = outfit_ref.open("rb")
            images.append(handle)
            opened.append(handle)
        handle = canonical.open("rb")
        images.append(handle)
        opened.append(handle)
        mask_handle = api_mask_path.open("rb")
        opened.append(mask_handle)
        kwargs = {
            "model": image_model(),
            "image": images,
            "mask": mask_handle,
            "prompt": prompt,
            "quality": image_quality(),
            "background": "transparent",
            "n": 1,
        }
        # input_fidelity is not supported by every image snapshot.
        try:
            response = client.images.edit(**kwargs, input_fidelity="high")
        except Exception as first_exc:  # noqa: BLE001
            message = str(first_exc)
            if "input_fidelity" in message:
                response = client.images.edit(**kwargs)
            else:
                raise
    finally:
        for handle in opened:
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass

    item = response.data[0]
    if getattr(item, "b64_json", None):
        raw = base64.b64decode(item.b64_json)
        return Image.open(io.BytesIO(raw)).convert("RGBA")
    raise RuntimeError("OpenAI Images Edit returned no b64_json payload")


def default_vision_qa(
    *,
    composite_path: Path,
    outfit_ref: Path | None,
    outfit_id: str,
) -> dict:
    key = openai_api_key()
    if not key:
        return {"pass": True, "skipped": True, "issues": [], "reason": "no API key for vision QA"}
    try:
        from openai import OpenAI
    except ImportError:
        return {"pass": True, "skipped": True, "issues": [], "reason": "openai package missing"}

    detail = load_outfit_detail(outfit_id)
    branding = detail.get("branding") or {}
    client = OpenAI(api_key=key)

    def b64(path: Path) -> str:
        return base64.b64encode(path.read_bytes()).decode("ascii")

    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "Validate mascot outfit branding strictly. Reply JSON only with keys: "
                "pass, issues, missingBranding, extraBranding, wrongText, outfitConsistency. "
                f"Outfit id={outfit_id}. Required branding={json.dumps(branding, ensure_ascii=False)}. "
                f"Forbidden text={json.dumps(detail.get('forbiddenRules') or [], ensure_ascii=False)}. "
                "pass must be false if required marks are missing or forbidden text appears."
            ),
        },
        {
            "type": "input_image",
            "image_url": f"data:image/png;base64,{b64(composite_path)}",
        },
    ]
    if outfit_ref and outfit_ref.exists():
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{b64(outfit_ref)}",
            }
        )

    try:
        response = client.responses.create(
            model=vision_qa_model(),
            input=[{"role": "user", "content": content}],
        )
        text = getattr(response, "output_text", None) or ""
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            payload = json.loads(text[start : end + 1])
            if "pass" not in payload:
                payload["pass"] = not payload.get("issues")
            return payload
        return {"pass": False, "issues": ["vision QA returned non-JSON"], "raw": text[:500]}
    except Exception as exc:  # noqa: BLE001
        # Soft-fail vision: do not promote on transport errors; deterministic QA still required.
        return {"pass": False, "issues": [f"vision QA error: {exc}"]}


def register_variant(
    *,
    pose: dict,
    outfit: dict,
    mask: dict,
    layer_file: Path,
    composite_file: Path,
    status: str,
    attempts: int,
    qa: dict,
    prompt: str,
    full_edit_sha: str | None = None,
) -> dict:
    record = {
        "id": variant_id(pose["id"], outfit["id"]),
        "basePose": pose["id"],
        "outfit": outfit["id"],
        "type": "outfit-layer",
        "file": layer_file.relative_to(MASCOT).as_posix(),
        "compositeFile": composite_file.relative_to(MASCOT).as_posix(),
        "status": status,
        "sha256": sha256_file(layer_file),
        "model": image_model(),
        "promptVersion": PROMPT_VERSION,
        "promptSha256": sha256_json({"prompt": prompt, "version": PROMPT_VERSION}),
        "attempts": attempts,
        "generatedAt": utc_now(),
        "qa": qa,
        "fullEditSha256": full_edit_sha,
        **hashes_current(pose, mask, outfit),
    }
    data = load_variants()
    others = [
        item
        for item in data.get("variants", [])
        if not (item.get("basePose") == pose["id"] and item.get("outfit") == outfit["id"])
    ]
    others.append(record)
    others.sort(key=lambda item: item["id"])
    write_json(VARIANTS_PATH, {"version": 1, "variants": others})
    return record


def generate_missing_variant(
    pose_id: str,
    outfit_id: str,
    *,
    edit_fn: EditFn | None = None,
    vision_fn: VisionFn | None = None,
    work_dir: Path | None = None,
    skip_vision: bool = False,
) -> dict:
    """Generate or reuse one pose+outfit variant. Returns status payload."""
    if outfit_id == DEFAULT_OUTFIT:
        return {"result": "REUSED", "reason": "default-home uses base pose", "pose": pose_id, "outfit": outfit_id}

    pose = pose_by_id(pose_id)
    outfit = outfit_by_id(outfit_id)
    mask = mask_by_pose(pose_id)
    if pose is None or outfit is None:
        return {"result": "ERROR", "reason": "unknown pose or outfit"}
    if mask is None or mask.get("status") != "approved":
        return {"result": "BLOCKED_MASK", "reason": "approved clothing mask required"}
    if not pose.get("approved"):
        return {"result": "BLOCKED_POSE", "reason": "base pose is not approved"}

    existing = variant_by_pair(pose_id, outfit_id)
    if variant_is_reusable(existing, pose, mask, outfit):
        return {
            "result": "REUSED",
            "variant": existing,
            "cacheKey": variant_cache_key(pose, mask, outfit_id),
        }

    detail = load_outfit_detail(outfit_id)
    outfit_ref = find_outfit_reference_image(outfit_id)
    if detail.get("referenceRequired") and outfit_ref is None:
        return {
            "result": "BLOCKED_REFERENCE",
            "reason": f"missing outfit reference for `{outfit_id}`",
        }

    if edit_fn is None and not openai_api_key():
        return {"result": "BLOCKED_GENERATION", "reason": "missing OPENAI_API_KEY"}

    edit = edit_fn or default_openai_edit
    vision = vision_fn or default_vision_qa
    canonical = MASCOT / load_poses()["canonicalReference"]["file"]
    if not canonical.exists():
        return {"result": "ERROR", "reason": "missing canonical mascot reference"}

    root = work_dir or (MASCOT / "variants" / "_work" / f"{pose_id}__{outfit_id}")
    root.mkdir(parents=True, exist_ok=True)
    binary_mask = Image.open(mask_path(mask)).convert("L")
    api_mask = build_api_mask(binary_mask)
    api_mask_path = root / "mask_api.png"
    api_mask.save(api_mask_path, format="PNG")

    previous_issues: list[str] = []
    last_qa: dict = {}
    attempts = max_generation_attempts()
    last_full_path: Path | None = None
    last_layer_img: Image.Image | None = None
    last_comp_img: Image.Image | None = None
    for attempt in range(1, attempts + 1):
        prompt = build_generation_prompt(outfit_id, previous_issues=previous_issues or None)
        try:
            full_edit = edit(
                pose_path_file=pose_path(pose),
                outfit_ref=outfit_ref,
                canonical=canonical,
                api_mask_path=api_mask_path,
                prompt=prompt,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "result": "ERROR",
                "reason": f"generation failed: {exc}",
                "pose": pose_id,
                "outfit": outfit_id,
            }
        # Force canvas to base size if model returns a different size.
        base = Image.open(pose_path(pose)).convert("RGBA")
        if full_edit.size != base.size:
            full_edit = full_edit.resize(base.size, Image.Resampling.LANCZOS)

        full_path = root / f"full-edit-attempt-{attempt}.png"
        full_edit.save(full_path, format="PNG")
        last_full_path = full_path
        layer = extract_outfit_layer(full_edit, binary_mask)
        composite = Image.alpha_composite(base, layer)
        last_layer_img = layer
        last_comp_img = composite

        layer_dest = layer_destination(outfit, pose_id)
        composite_dest = composite_destination(outfit, pose_id)
        layer_dest.parent.mkdir(parents=True, exist_ok=True)
        composite_dest.parent.mkdir(parents=True, exist_ok=True)
        # Write to temp names first for QA, then promote paths.
        tmp_layer = root / f"layer-attempt-{attempt}.png"
        tmp_comp = root / f"composite-attempt-{attempt}.png"
        layer.save(tmp_layer, format="PNG")
        composite.save(tmp_comp, format="PNG")

        det = validate_variant_images(
            base_pose_path=pose_path(pose),
            mask_path_file=mask_path(mask),
            full_edit_path=full_path,
            layer_path=tmp_layer,
            composite_path=tmp_comp,
        )
        if skip_vision:
            vis = {"pass": True, "skipped": True, "issues": []}
        else:
            vis = vision(composite_path=tmp_comp, outfit_ref=outfit_ref, outfit_id=outfit_id)

        last_qa = {"deterministic": det, "visual": vis, "attempt": attempt}
        if det.get("pass") and vis.get("pass"):
            layer.save(layer_dest, format="PNG")
            composite.save(composite_dest, format="PNG")
            record = register_variant(
                pose=pose,
                outfit=outfit,
                mask=mask,
                layer_file=layer_dest,
                composite_file=composite_dest,
                status="approved-auto",
                attempts=attempt,
                qa={
                    "deterministic": "pass",
                    "visual": "pass" if not vis.get("skipped") else "skipped",
                },
                prompt=prompt,
                full_edit_sha=sha256_file(full_path),
            )
            return {
                "result": "GENERATED",
                "variant": record,
                "attempts": attempt,
                "qa": last_qa,
                "cacheKey": variant_cache_key(pose, mask, outfit_id),
            }

        previous_issues = list(det.get("issues") or []) + list(vis.get("issues") or [])

    # Failed after retries — keep artifacts under the channel library tree.
    needs_dir = MASCOT / "variants" / "_needs_review" / f"{pose_id}__{outfit_id}"
    needs_dir.mkdir(parents=True, exist_ok=True)
    needs_layer = needs_dir / "layer.png"
    needs_comp = needs_dir / "composite.png"
    if last_layer_img is not None:
        last_layer_img.save(needs_layer, format="PNG")
    if last_comp_img is not None:
        last_comp_img.save(needs_comp, format="PNG")
    record = {
        "id": variant_id(pose_id, outfit_id),
        "basePose": pose_id,
        "outfit": outfit_id,
        "type": "outfit-layer",
        "file": needs_layer.relative_to(MASCOT).as_posix() if needs_layer.exists() else None,
        "compositeFile": needs_comp.relative_to(MASCOT).as_posix() if needs_comp.exists() else None,
        "status": "needs-review",
        "attempts": attempts,
        "generatedAt": utc_now(),
        "qa": {
            "deterministic": "fail",
            "visual": "fail",
            "details": last_qa,
        },
        **hashes_current(pose, mask, outfit),
    }
    data = load_variants()
    others = [
        item
        for item in data.get("variants", [])
        if not (item.get("basePose") == pose_id and item.get("outfit") == outfit_id)
    ]
    others.append(record)
    others.sort(key=lambda item: item["id"])
    write_json(VARIANTS_PATH, {"version": 1, "variants": others})
    return {
        "result": "NEEDS_REVIEW",
        "variant": record,
        "attempts": attempts,
        "qa": last_qa,
        "issues": previous_issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose", required=True)
    parser.add_argument("--outfit", required=True)
    parser.add_argument("--skip-vision", action="store_true")
    args = parser.parse_args()
    result = generate_missing_variant(
        args.pose,
        args.outfit,
        skip_vision=args.skip_vision,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("result") in {"REUSED", "GENERATED"} else 1


if __name__ == "__main__":
    sys.exit(main())
