#!/usr/bin/env python3
"""Deterministic QA for a generated mascot outfit variant. No network."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import mask_by_pose, mask_path, pose_by_id, pose_path


def _pixel_equal(a: tuple, b: tuple, tol: int = 0) -> bool:
    return all(abs(int(x) - int(y)) <= tol for x, y in zip(a, b))


def validate_variant_images(
    *,
    base_pose_path: Path,
    mask_path_file: Path,
    full_edit_path: Path | None,
    layer_path: Path,
    composite_path: Path,
) -> dict:
    """Return {pass: bool, issues: [...] } for deterministic checks."""
    issues: list[str] = []
    base = Image.open(base_pose_path).convert("RGBA")
    mask = Image.open(mask_path_file).convert("L")
    layer = Image.open(layer_path).convert("RGBA")
    composite = Image.open(composite_path).convert("RGBA")

    if mask.size != base.size:
        issues.append(f"mask size {mask.size} != base {base.size}")
    if layer.size != base.size:
        issues.append(f"layer size {layer.size} != base {base.size}")
    if composite.size != base.size:
        issues.append(f"composite size {composite.size} != base {base.size}")
    if full_edit_path is not None and full_edit_path.exists():
        edited = Image.open(full_edit_path).convert("RGBA")
        if edited.size != base.size:
            issues.append(f"full-edit size {edited.size} != base {base.size}")

    if not any(px[3] > 0 for px in composite.getdata()):
        issues.append("composite has no alpha/content")

    layer_pixels = 0
    garment_pixels = 0
    outside_mismatch = 0
    hole_like = 0
    width, height = base.size
    bpx = base.load()
    mpx = mask.load()
    lpx = layer.load()
    cpx = composite.load()

    for y in range(height):
        for x in range(width):
            m = mpx[x, y]
            if m > 0:
                garment_pixels += 1
                if lpx[x, y][3] > 0:
                    layer_pixels += 1
                else:
                    # soft holes inside garment region
                    if m >= 200:
                        hole_like += 1
            else:
                if not _pixel_equal(cpx[x, y], bpx[x, y], tol=0):
                    outside_mismatch += 1

    if layer_pixels == 0:
        issues.append("outfit layer is empty")
    coverage = (layer_pixels / garment_pixels) if garment_pixels else 0.0
    hole_ratio = (hole_like / garment_pixels) if garment_pixels else 0.0
    if garment_pixels and coverage < 0.90:
        issues.append(f"coverage ratio too low ({coverage:.3f})")
    if garment_pixels and hole_ratio > 0.05:
        issues.append(f"large holes in garment region ({hole_like}/{garment_pixels})")
    if outside_mismatch > 0:
        issues.append(f"outside-mask pixels differ from original pose ({outside_mismatch})")

    # Transparent background preserved: corners should stay fully transparent if base was.
    for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if bpx[point][3] == 0 and cpx[point][3] != 0:
            issues.append("transparent background not preserved at corners")
            break

    return {
        "pass": not issues,
        "issues": issues,
        "coverage": coverage,
        "holeRatio": hole_ratio,
        "layerPixels": layer_pixels,
        "garmentPixels": garment_pixels,
        "outsideMismatch": outside_mismatch,
    }


def validate_pose_outfit(pose_id: str, outfit_id: str, paths: dict) -> dict:
    pose = pose_by_id(pose_id)
    mask = mask_by_pose(pose_id)
    if pose is None or mask is None:
        return {"pass": False, "issues": ["pose or mask missing"]}
    return validate_variant_images(
        base_pose_path=pose_path(pose),
        mask_path_file=mask_path(mask),
        full_edit_path=Path(paths["fullEdit"]) if paths.get("fullEdit") else None,
        layer_path=Path(paths["layer"]),
        composite_path=Path(paths["composite"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose", required=True)
    parser.add_argument("--outfit", required=True)
    parser.add_argument("--layer", required=True)
    parser.add_argument("--composite", required=True)
    parser.add_argument("--full-edit", default=None)
    args = parser.parse_args()
    result = validate_pose_outfit(
        args.pose,
        args.outfit,
        {
            "layer": args.layer,
            "composite": args.composite,
            "fullEdit": args.full_edit,
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    sys.exit(main())
