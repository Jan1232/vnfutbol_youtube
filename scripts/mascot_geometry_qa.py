#!/usr/bin/env python3
"""Geometry / identity QA for mascot full-edits. No pixel equality outside identity."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def _bbox(alpha: Image.Image, threshold: int = 16) -> tuple[int, int, int, int] | None:
    return alpha.point(lambda p: 255 if p > threshold else 0).getbbox()


def _center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _white_eye_centroid(img: Image.Image) -> tuple[float, float] | None:
    rgba = img.convert("RGBA")
    px = rgba.load()
    width, height = rgba.size
    xs: list[int] = []
    ys: list[int] = []
    for y in range(height):
        for x in range(width):
            r, g, b, a = px[x, y]
            if a < 200:
                continue
            if r >= 220 and g >= 220 and b >= 220 and abs(r - g) < 20 and abs(g - b) < 20:
                xs.append(x)
                ys.append(y)
    if len(xs) < 20:
        return None
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def geometry_qa(
    base: Image.Image,
    full_edit: Image.Image,
    *,
    identity_mask: Image.Image | None = None,
    max_center_shift_px: float = 18.0,
    max_bbox_delta_ratio: float = 0.08,
    max_eye_shift_px: float = 14.0,
) -> dict:
    """Reject only meaningful structural drift — not pixel equality."""
    issues: list[str] = []
    base_rgba = base.convert("RGBA")
    edit = full_edit.convert("RGBA")
    if base_rgba.size != edit.size:
        return {
            "pass": False,
            "issues": [f"canvas mismatch base={base_rgba.size} edit={edit.size}"],
        }

    base_bbox = _bbox(base_rgba.getchannel("A"))
    edit_bbox = _bbox(edit.getchannel("A"))
    if base_bbox is None or edit_bbox is None:
        issues.append("missing opaque silhouette")
    else:
        bc = _center(base_bbox)
        ec = _center(edit_bbox)
        shift = ((ec[0] - bc[0]) ** 2 + (ec[1] - bc[1]) ** 2) ** 0.5
        if shift > max_center_shift_px:
            issues.append(f"silhouette center shifted {shift:.1f}px")
        bw = base_bbox[2] - base_bbox[0]
        bh = base_bbox[3] - base_bbox[1]
        ew = edit_bbox[2] - edit_bbox[0]
        eh = edit_bbox[3] - edit_bbox[1]
        if bw > 0 and abs(ew - bw) / bw > max_bbox_delta_ratio:
            issues.append(f"silhouette width drift {(abs(ew - bw) / bw):.3f}")
        if bh > 0 and abs(eh - bh) / bh > max_bbox_delta_ratio:
            issues.append(f"silhouette height drift {(abs(eh - bh) / bh):.3f}")

    base_eye = _white_eye_centroid(base_rgba)
    edit_eye = _white_eye_centroid(edit)
    if base_eye and edit_eye:
        eye_shift = ((edit_eye[0] - base_eye[0]) ** 2 + (edit_eye[1] - base_eye[1]) ** 2) ** 0.5
        if eye_shift > max_eye_shift_px:
            issues.append(f"eye centroid shifted {eye_shift:.1f}px")
    elif base_eye and not edit_eye:
        issues.append("white eyes missing/altered in full-edit")

    # Corner transparency preserved (no background fill).
    width, height = base_rgba.size
    bpx = base_rgba.load()
    epx = edit.load()
    for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if bpx[point][3] == 0 and epx[point][3] > 8:
            issues.append("transparent background not preserved at corners")
            break

    identity_match = None
    if identity_mask is not None:
        hard = identity_mask.convert("L")
        mismatched = 0
        checked = 0
        ipx = hard.load()
        for y in range(0, height, 2):
            for x in range(0, width, 2):
                if ipx[x, y] < 200:
                    continue
                checked += 1
                # After identity lock these should match; for raw full-edit they may differ.
                if bpx[x, y] != epx[x, y]:
                    mismatched += 1
        identity_match = {
            "checked": checked,
            "mismatchedBeforeLock": mismatched,
        }

    return {
        "pass": not issues,
        "issues": issues,
        "identityProbe": identity_match,
    }


def identity_lock_qa(base: Image.Image, final: Image.Image, identity_mask: Image.Image) -> dict:
    """After lock: identity pixels must equal original pose exactly."""
    issues: list[str] = []
    base_rgba = base.convert("RGBA")
    final_rgba = final.convert("RGBA")
    hard = identity_mask.convert("L")
    if base_rgba.size != final_rgba.size or hard.size != base_rgba.size:
        return {"pass": False, "issues": ["size mismatch"]}
    bpx = base_rgba.load()
    fpx = final_rgba.load()
    ipx = hard.load()
    width, height = base_rgba.size
    mismatches = 0
    checked = 0
    for y in range(height):
        for x in range(width):
            if ipx[x, y] < 255:
                continue
            checked += 1
            if bpx[x, y] != fpx[x, y]:
                mismatches += 1
    if mismatches:
        issues.append(f"identity pixels differ from base ({mismatches}/{checked})")
    return {"pass": not issues, "issues": issues, "checked": checked, "mismatches": mismatches}
