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
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    DEFAULT_OUTFIT,
    LOCAL_MASCOT_NEEDS_REVIEW,
    LOCAL_MASCOT_WORK,
    MASCOT,
    PROMPT_VERSION,
    VARIANTS_PATH,
    compose_identity_locked_final,
    composite_destination,
    extract_outfit_layer,
    find_same_outfit_mascot_composite,
    full_edit_destination,
    hashes_current,
    identity_mask_by_pose,
    identity_mask_path,
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
    pose_by_id,
    pose_path,
    recompute_composite_sha256,
    sha256_file,
    sha256_json,
    variant_by_pair,
    variant_cache_key,
    variant_id,
    variant_is_reusable,
    verify_local_outfit_reference,
    vision_qa_model,
    write_json,
)
from mascot_geometry_qa import geometry_qa, identity_lock_qa


EditFn = Callable[..., Image.Image]
VisionFn = Callable[..., dict]

OUTFIT_CONSISTENCY_MIN = 0.90
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
MAX_API_RETRIES = 5

VISION_QA_SCHEMA = {
    "type": "object",
    "properties": {
        "pass": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "missingBranding": {"type": "array", "items": {"type": "string"}},
        "extraBranding": {"type": "array", "items": {"type": "string"}},
        "wrongText": {"type": "array", "items": {"type": "string"}},
        "outfitConsistency": {"type": "number"},
    },
    "required": [
        "pass",
        "issues",
        "missingBranding",
        "extraBranding",
        "wrongText",
        "outfitConsistency",
    ],
    "additionalProperties": False,
}


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


def prepare_api_canvas(
    base: Image.Image,
    binary_mask: Image.Image,
) -> tuple[Image.Image, Image.Image, tuple[int, int, int, int]]:
    """Pad pose/mask to GPT Image dims (multiples of 16) without rescaling pixels."""
    original = base.convert("RGBA")
    mask = binary_mask.convert("L")
    original_w, original_h = original.size
    if mask.size != (original_w, original_h):
        raise ValueError(f"mask size {mask.size} != base {original.size}")
    api_w = math.ceil(original_w / 16) * 16
    api_h = math.ceil(original_h / 16) * 16
    padded_base = Image.new("RGBA", (api_w, api_h), (0, 0, 0, 0))
    padded_base.paste(original, (0, 0))
    # Outside the original canvas must stay non-editable (internal mask = 0).
    padded_mask = Image.new("L", (api_w, api_h), 0)
    padded_mask.paste(mask, (0, 0))
    crop_box = (0, 0, original_w, original_h)
    return padded_base, padded_mask, crop_box


def crop_api_result(
    full_edit: Image.Image,
    crop_box: tuple[int, int, int, int],
    *,
    expected_api_size: tuple[int, int],
) -> Image.Image:
    edited = full_edit.convert("RGBA")
    if edited.size != expected_api_size:
        raise RuntimeError(
            f"Images Edit returned {edited.size}, expected exact API canvas "
            f"{expected_api_size}; refusing to resize AI output"
        )
    cropped = edited.crop(crop_box)
    expected_orig = (crop_box[2] - crop_box[0], crop_box[3] - crop_box[1])
    if cropped.size != expected_orig:
        raise RuntimeError(f"crop produced {cropped.size}, expected {expected_orig}")
    return cropped


def build_generation_prompt(
    outfit_id: str,
    *,
    has_outfit_ref: bool,
    has_consistency_ref: bool = False,
    previous_issues: list[str] | None = None,
) -> str:
    detail = load_outfit_detail(outfit_id)
    rules = "\n".join(f"- {item}" for item in detail.get("generationRules") or [])
    forbidden = "\n".join(f"- {item}" for item in detail.get("forbiddenRules") or [])
    branding = detail.get("branding") or {}

    image_lines = ["IMAGE 1 is the exact approved base pose."]
    next_idx = 2
    if has_outfit_ref:
        image_lines.append(f"IMAGE {next_idx} is the official outfit visual reference.")
        next_idx += 1
    if has_consistency_ref:
        image_lines.append(
            f"IMAGE {next_idx} is an existing approved mascot in the same outfit "
            "(consistency only; do not copy its pose)."
        )
        next_idx += 1
    image_lines.append(f"IMAGE {next_idx} is the canonical mascot identity reference.")

    prompt = f"""You are editing an existing approved mascot asset.

{chr(10).join(image_lines)}

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
Output size MUST be exactly the same pixel dimensions as IMAGE 1.
"""
    if previous_issues:
        joined = "\n".join(f"- {item}" for item in previous_issues)
        prompt += f"""

Previous attempt failed because:
{joined}

Correct these issues in this attempt.
"""
    return prompt


def _exception_status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def is_transient_openai_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if any(token in name for token in ("timeout", "ratelimit", "apiconnection", "internalserver")):
        return True
    if any(token in message for token in ("timeout", "timed out", "rate limit", "429", "503", "502", "504")):
        return True
    status = _exception_status_code(exc)
    return status in TRANSIENT_STATUS if status is not None else False


def call_with_backoff(fn: Callable[[], Any], *, max_retries: int = MAX_API_RETRIES) -> Any:
    delay = 1.0
    last_exc: BaseException | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not is_transient_openai_error(exc) or attempt >= max_retries:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
    assert last_exc is not None
    raise last_exc


def default_openai_edit(
    *,
    pose_path_file: Path,
    outfit_ref: Path | None,
    canonical: Path,
    api_mask_path: Path,
    prompt: str,
    target_size: tuple[int, int],
    consistency_ref: Path | None = None,
) -> Image.Image:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openai package is not installed") from exc
    key = openai_api_key()
    if not key:
        raise RuntimeError("missing OPENAI_API_KEY")
    client = OpenAI(api_key=key)
    width, height = target_size
    size = f"{width}x{height}"
    images: list = []
    opened: list = []
    try:
        images.append(pose_path_file.open("rb"))
        opened.extend(images[-1:])
        if outfit_ref is not None and outfit_ref.exists():
            handle = outfit_ref.open("rb")
            images.append(handle)
            opened.append(handle)
        if consistency_ref is not None and consistency_ref.exists():
            handle = consistency_ref.open("rb")
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
            "size": size,
            "n": 1,
        }

        def _edit_once():
            try:
                return client.images.edit(**kwargs, input_fidelity="high")
            except Exception as first_exc:  # noqa: BLE001
                if "input_fidelity" in str(first_exc):
                    return client.images.edit(**kwargs)
                raise

        response = call_with_backoff(_edit_once)
    finally:
        for handle in opened:
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass

    item = response.data[0]
    if getattr(item, "b64_json", None):
        raw = base64.b64decode(item.b64_json)
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
        if image.size != target_size:
            raise RuntimeError(
                f"Images Edit returned {image.size}, expected exact base-pose size {target_size}; "
                "refusing to resize AI output"
            )
        return image
    raise RuntimeError("OpenAI Images Edit returned no b64_json payload")


def evaluate_vision_payload(payload: dict) -> dict:
    """Ignore model `pass`; compute pass locally from required fields."""
    issues = [str(item) for item in (payload.get("issues") or [])]
    missing = [str(item) for item in (payload.get("missingBranding") or [])]
    extra = [str(item) for item in (payload.get("extraBranding") or [])]
    wrong = [str(item) for item in (payload.get("wrongText") or [])]
    consistency_raw = payload.get("outfitConsistency")
    try:
        consistency = float(consistency_raw)
    except (TypeError, ValueError):
        consistency = None
        issues.append("outfitConsistency missing or non-numeric")
    if consistency is not None and consistency < OUTFIT_CONSISTENCY_MIN:
        issues.append(
            f"outfitConsistency too low ({consistency:.3f} < {OUTFIT_CONSISTENCY_MIN})"
        )
    computed_pass = (
        not issues
        and not missing
        and not extra
        and not wrong
        and consistency is not None
        and consistency >= OUTFIT_CONSISTENCY_MIN
    )
    return {
        "pass": computed_pass,
        "issues": issues,
        "missingBranding": missing,
        "extraBranding": extra,
        "wrongText": wrong,
        "outfitConsistency": consistency,
        "modelPass": payload.get("pass"),
    }


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
    generation_rules = detail.get("generationRules") or []
    forbidden_rules = detail.get("forbiddenRules") or []
    client = OpenAI(api_key=key)

    def b64(path: Path) -> str:
        return base64.b64encode(path.read_bytes()).decode("ascii")

    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "Validate mascot outfit branding and kit consistency strictly. "
                "Return the structured JSON fields only. "
                f"Outfit id={outfit_id}. "
                f"generationRules={json.dumps(generation_rules, ensure_ascii=False)}. "
                f"forbiddenRules={json.dumps(forbidden_rules, ensure_ascii=False)}. "
                f"branding={json.dumps(branding, ensure_ascii=False)}. "
                "Populate issues/missingBranding/extraBranding/wrongText when applicable. "
                "outfitConsistency must be a number from 0 to 1."
            ),
        },
        {
            "type": "input_image",
            "image_url": f"data:image/png;base64,{b64(composite_path)}",
            "detail": "high",
        },
    ]
    if outfit_ref and outfit_ref.exists():
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{b64(outfit_ref)}",
                "detail": "high",
            }
        )

    def _vision_once():
        return client.responses.create(
            model=vision_qa_model(),
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "mascot_outfit_vision_qa",
                    "strict": True,
                    "schema": VISION_QA_SCHEMA,
                }
            },
        )

    try:
        response = call_with_backoff(_vision_once)
        text = getattr(response, "output_text", None) or ""
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            payload = json.loads(text[start : end + 1])
            return evaluate_vision_payload(payload)
        return {"pass": False, "issues": ["vision QA returned non-JSON"], "raw": text[:500]}
    except Exception as exc:  # noqa: BLE001
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
    generation_reference_sha256: str | None = None,
    consistency_reference_sha256: str | None = None,
) -> dict:
    composite_sha = recompute_composite_sha256(pose, layer_file)
    record = {
        "id": variant_id(pose["id"], outfit["id"]),
        "basePose": pose["id"],
        "outfit": outfit["id"],
        "type": "outfit-layer",
        "file": layer_file.relative_to(MASCOT).as_posix(),
        "compositeFile": composite_file.relative_to(MASCOT).as_posix(),
        "status": status,
        "sha256": sha256_file(layer_file),
        "compositeSha256": composite_sha,
        "model": image_model(),
        "promptVersion": PROMPT_VERSION,
        "promptSha256": sha256_json({"prompt": prompt, "version": PROMPT_VERSION}),
        "attempts": attempts,
        "generatedAt": utc_now(),
        "qa": qa,
        "fullEditSha256": full_edit_sha,
        **hashes_current(
            pose,
            mask,
            outfit,
            generation_reference_sha256=generation_reference_sha256,
            consistency_reference_sha256=consistency_reference_sha256,
        ),
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


def _vision_allows_auto_approve(vis: dict, *, skip_vision: bool) -> bool:
    if skip_vision:
        return False
    if vis.get("skipped"):
        return False
    return bool(vis.get("pass"))


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
    ref_check = verify_local_outfit_reference(outfit_id)
    if ref_check.get("error") == "mismatch":
        return {
            "result": "BLOCKED_REFERENCE_MISMATCH",
            "reason": (
                f"local outfit reference SHA does not match tracked expected SHA "
                f"for `{outfit_id}`"
            ),
            "expectedSha256": ref_check.get("sha256"),
            "actualSha256": ref_check.get("actualSha256"),
        }
    outfit_ref = ref_check.get("path")
    generation_reference_sha256 = ref_check.get("sha256")
    if detail.get("referenceRequired") and outfit_ref is None:
        return {
            "result": "BLOCKED_REFERENCE",
            "reason": f"missing outfit reference for `{outfit_id}`",
        }

    consistency_anchor = find_same_outfit_mascot_composite(outfit_id, exclude_pose=pose_id)
    consistency_ref = Path(consistency_anchor["path"]) if consistency_anchor else None
    consistency_reference_sha256 = (
        consistency_anchor.get("sha256") if consistency_anchor else None
    )

    if edit_fn is None and not openai_api_key():
        return {"result": "BLOCKED_GENERATION", "reason": "missing OPENAI_API_KEY"}

    edit = edit_fn or default_openai_edit
    vision = vision_fn or default_vision_qa
    canonical = MASCOT / load_poses()["canonicalReference"]["file"]
    if not canonical.exists():
        return {"result": "ERROR", "reason": "missing canonical mascot reference"}

    root = work_dir or (LOCAL_MASCOT_WORK / f"{pose_id}__{outfit_id}")
    root.mkdir(parents=True, exist_ok=True)
    binary_mask = Image.open(mask_path(mask)).convert("L")
    base = Image.open(pose_path(pose)).convert("RGBA")
    padded_base, padded_mask, crop_box = prepare_api_canvas(base, binary_mask)
    api_size = padded_base.size
    padded_pose_path = root / "pose_api_padded.png"
    padded_base.save(padded_pose_path, format="PNG")
    api_mask = build_api_mask(padded_mask)
    api_mask_path = root / "mask_api.png"
    api_mask.save(api_mask_path, format="PNG")

    previous_issues: list[str] = []
    last_qa: dict = {}
    attempts = max_generation_attempts()
    last_layer_img: Image.Image | None = None
    last_comp_img: Image.Image | None = None
    last_prompt = ""
    for attempt in range(1, attempts + 1):
        prompt = build_generation_prompt(
            outfit_id,
            has_outfit_ref=bool(outfit_ref and Path(outfit_ref).exists()),
            has_consistency_ref=bool(consistency_ref and consistency_ref.exists()),
            previous_issues=previous_issues or None,
        )
        last_prompt = prompt
        try:
            full_edit = edit(
                pose_path_file=padded_pose_path,
                outfit_ref=outfit_ref,
                consistency_ref=consistency_ref,
                canonical=canonical,
                api_mask_path=api_mask_path,
                prompt=prompt,
                target_size=api_size,
            )
        except TypeError:
            full_edit = edit(
                pose_path_file=padded_pose_path,
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

        try:
            full_edit = crop_api_result(full_edit, crop_box, expected_api_size=api_size)
        except Exception as exc:  # noqa: BLE001
            return {
                "result": "ERROR",
                "reason": str(exc),
                "pose": pose_id,
                "outfit": outfit_id,
            }

        if full_edit.size != base.size:
            return {
                "result": "ERROR",
                "reason": (
                    f"cropped edit {full_edit.size} != original pose {base.size}; "
                    "refusing to resize AI output"
                ),
                "pose": pose_id,
                "outfit": outfit_id,
            }

        full_path = root / f"full-edit-attempt-{attempt}.png"
        full_edit.save(full_path, format="PNG")

        identity_rec = identity_mask_by_pose(pose_id)
        identity_img = None
        if identity_rec and identity_rec.get("status") == "approved":
            id_path = identity_mask_path(identity_rec)
            if id_path.exists() and sha256_file(id_path) == identity_rec.get("sha256"):
                identity_img = Image.open(id_path).convert("L")

        geo = geometry_qa(base, full_edit, identity_mask=identity_img)
        # Optional debug clothing layer (not production final).
        layer = extract_outfit_layer(full_edit, binary_mask)
        if identity_img is not None:
            composite = compose_identity_locked_final(base, full_edit, identity_img, feather=1)
            lock = identity_lock_qa(base, composite, identity_img)
            det = {
                "pass": bool(geo.get("pass") and lock.get("pass")),
                "issues": list(geo.get("issues") or []) + list(lock.get("issues") or []),
                "mode": "identity-lock",
                "geometry": geo,
                "identityLock": lock,
            }
        else:
            # No approved identity mask yet: do not fall back to clothing-mask composite.
            composite = full_edit.copy()
            det = {
                "pass": bool(geo.get("pass")),
                "issues": list(geo.get("issues") or []),
                "mode": "full-edit-geometry-only",
                "geometry": geo,
                "identityLock": {
                    "pass": False,
                    "issues": ["identity mask missing/unapproved; clothing composite disabled"],
                },
            }
        last_layer_img = layer
        last_comp_img = composite

        layer_dest = layer_destination(outfit, pose_id)
        composite_dest = composite_destination(outfit, pose_id)
        full_dest = full_edit_destination(outfit, pose_id)
        layer_dest.parent.mkdir(parents=True, exist_ok=True)
        composite_dest.parent.mkdir(parents=True, exist_ok=True)
        full_dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_layer = root / f"layer-attempt-{attempt}.png"
        tmp_comp = root / f"composite-attempt-{attempt}.png"
        layer.save(tmp_layer, format="PNG")
        composite.save(tmp_comp, format="PNG")

        if skip_vision:
            vis = {"pass": True, "skipped": True, "issues": [], "reason": "skip-vision"}
        else:
            vis = vision(composite_path=tmp_comp, outfit_ref=outfit_ref, outfit_id=outfit_id)

        last_qa = {"deterministic": det, "visual": vis, "attempt": attempt, "geometry": geo}
        can_auto = (
            identity_img is not None
            and det.get("pass")
            and _vision_allows_auto_approve(vis, skip_vision=skip_vision)
        )
        if can_auto:
            layer.save(layer_dest, format="PNG")  # debug/optional
            composite.save(composite_dest, format="PNG")
            full_edit.save(full_dest, format="PNG")
            record = register_variant(
                pose=pose,
                outfit=outfit,
                mask=mask,
                layer_file=layer_dest,
                composite_file=composite_dest,
                status="approved-auto",
                attempts=attempt,
                qa={"deterministic": "pass", "visual": "pass", "finalization": "identity-lock"},
                prompt=prompt,
                full_edit_sha=sha256_file(full_path),
                generation_reference_sha256=generation_reference_sha256,
                consistency_reference_sha256=consistency_reference_sha256,
            )
            record["fullEditFile"] = full_dest.relative_to(MASCOT).as_posix()
            record["finalization"] = "identity-lock"
            # re-write with extra fields
            data = load_variants()
            others = [
                item
                for item in data.get("variants", [])
                if not (item.get("basePose") == pose["id"] and item.get("outfit") == outfit["id"])
            ]
            others.append(record)
            others.sort(key=lambda item: item["id"])
            write_json(VARIANTS_PATH, {"version": 1, "variants": others})
            return {
                "result": "GENERATED",
                "variant": record,
                "attempts": attempt,
                "qa": last_qa,
                "cacheKey": variant_cache_key(
                    pose,
                    mask,
                    outfit_id,
                    generation_reference_sha256=generation_reference_sha256,
                    consistency_reference_sha256=consistency_reference_sha256,
                ),
            }

        if det.get("pass") and (skip_vision or vis.get("skipped")):
            layer.save(layer_dest, format="PNG")
            composite.save(composite_dest, format="PNG")
            record = register_variant(
                pose=pose,
                outfit=outfit,
                mask=mask,
                layer_file=layer_dest,
                composite_file=composite_dest,
                status="needs-review",
                attempts=attempt,
                qa={
                    "deterministic": "pass",
                    "visual": "skipped",
                    "reason": "deterministic-only; vision skipped",
                },
                prompt=prompt,
                full_edit_sha=sha256_file(full_path),
                generation_reference_sha256=generation_reference_sha256,
                consistency_reference_sha256=consistency_reference_sha256,
            )
            return {
                "result": "NEEDS_REVIEW",
                "variant": record,
                "attempts": attempt,
                "qa": last_qa,
                "reason": "deterministic-only generation requires human review",
            }

        previous_issues = list(det.get("issues") or []) + list(vis.get("issues") or [])

    needs_dir = LOCAL_MASCOT_NEEDS_REVIEW / f"{pose_id}__{outfit_id}"
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
        "file": None,
        "compositeFile": None,
        "localReviewLayer": str(needs_layer) if needs_layer.exists() else None,
        "localReviewComposite": str(needs_comp) if needs_comp.exists() else None,
        "status": "needs-review",
        "attempts": attempts,
        "generatedAt": utc_now(),
        "qa": {
            "deterministic": "fail",
            "visual": "fail",
            "details": last_qa,
        },
        "promptSha256": sha256_json({"prompt": last_prompt, "version": PROMPT_VERSION}) if last_prompt else None,
        **hashes_current(
            pose,
            mask,
            outfit,
            generation_reference_sha256=generation_reference_sha256,
            consistency_reference_sha256=consistency_reference_sha256,
        ),
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
