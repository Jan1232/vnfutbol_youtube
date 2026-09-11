#!/usr/bin/env python3
"""Validate mascot pose assets against poses.json."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MASCOT = ROOT / "channel-assets" / "mascot"
MANIFEST_PATH = MASCOT / "poses.json"

REQUIRED_FIELDS = (
    "id",
    "file",
    "category",
    "tags",
    "approved",
    "transparent",
    "handsVerified",
)
ALLOWED_SIZES = {
    (1024, 1536),
    (1086, 1448),
    (1122, 1402),
}
MIN_TRANSPARENT_RATIO = 0.15
CORNER_ALPHA_LIMIT = 16
REQUIRED_REFERENCES = (
    "references/mascot_reference_main.png",
    "references/mascot_reference_hips.png",
)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"Missing manifest: {MANIFEST_PATH}")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def pose_pngs() -> list[Path]:
    return sorted(MASCOT.joinpath("poses").rglob("*.png"))


def check_png(path: Path, report: Report, require_library_size: bool) -> dict:
    meta = {
        "mode": None,
        "size": None,
        "transparent_ratio": 0.0,
        "has_alpha": False,
    }
    try:
        image = Image.open(path)
    except OSError as exc:
        report.error(f"{path.relative_to(MASCOT)}: cannot open PNG ({exc})")
        return meta

    if image.format != "PNG":
        report.error(f"{path.relative_to(MASCOT)}: not a PNG ({image.format})")

    image = image.convert("RGBA")
    width, height = image.size
    alpha = image.getchannel("A")
    extrema = alpha.getextrema()
    alpha_values = (
        alpha.get_flattened_data()
        if hasattr(alpha, "get_flattened_data")
        else alpha.getdata()
    )
    transparent = sum(1 for value in alpha_values if value == 0)
    total = width * height
    corners = [
        image.getpixel((0, 0))[3],
        image.getpixel((width - 1, 0))[3],
        image.getpixel((0, height - 1))[3],
        image.getpixel((width - 1, height - 1))[3],
    ]

    meta.update(
        {
            "mode": "RGBA",
            "size": (width, height),
            "transparent_ratio": transparent / total if total else 0.0,
            "has_alpha": "A" in Image.open(path).getbands(),
        }
    )

    if extrema[0] == 255:
        report.error(f"{path.relative_to(MASCOT)}: no alpha transparency")
    elif meta["transparent_ratio"] < MIN_TRANSPARENT_RATIO:
        report.error(
            f"{path.relative_to(MASCOT)}: too little true alpha "
            f"({meta['transparent_ratio']:.1%})"
        )

    opaque_corners = sum(1 for value in corners if value > CORNER_ALPHA_LIMIT)
    if opaque_corners > 1:
        report.error(
            f"{path.relative_to(MASCOT)}: background looks baked in "
            f"(opaque corners: {opaque_corners})"
        )

    if require_library_size and (width, height) not in ALLOWED_SIZES:
        report.error(
            f"{path.relative_to(MASCOT)}: unexpected size {width}x{height}; "
            f"allowed {sorted(ALLOWED_SIZES)}"
        )

    if width < 512 or height < 512:
        report.error(f"{path.relative_to(MASCOT)}: image is too small ({width}x{height})")

    return meta


def validate(strict_qc: bool) -> Report:
    report = Report()
    manifest = load_manifest()
    poses = manifest.get("poses")
    if not isinstance(poses, list) or not poses:
        report.error("poses.json: `poses` must be a non-empty list")
        return report

    ids: list[str] = []
    files: list[str] = []
    names: list[str] = []

    for index, pose in enumerate(poses):
        prefix = f"poses.json[{index}]"
        if not isinstance(pose, dict):
            report.error(f"{prefix}: entry must be an object")
            continue

        missing = [field for field in REQUIRED_FIELDS if field not in pose]
        if missing:
            report.error(f"{prefix}: missing fields {missing}")
            continue

        pose_id = pose["id"]
        rel_file = pose["file"]
        ids.append(pose_id)
        files.append(rel_file)
        names.append(Path(rel_file).name)

        if not isinstance(pose["tags"], list) or not pose["tags"]:
            report.error(f"{prefix} ({pose_id}): tags must be a non-empty list")
        if not isinstance(pose["approved"], bool):
            report.error(f"{prefix} ({pose_id}): approved must be boolean")
        if not isinstance(pose["transparent"], bool):
            report.error(f"{prefix} ({pose_id}): transparent must be boolean")
        if not isinstance(pose["handsVerified"], bool):
            report.error(f"{prefix} ({pose_id}): handsVerified must be boolean")

        path = MASCOT / rel_file
        expected_category = Path(rel_file).parts[1] if len(Path(rel_file).parts) > 1 else ""
        if Path(rel_file).parts[0] != "poses":
            report.error(f"{pose_id}: file must live under poses/")
        if pose["category"] != expected_category:
            report.error(
                f"{pose_id}: category `{pose['category']}` does not match folder "
                f"`{expected_category}`"
            )
        if not path.exists():
            report.error(f"{pose_id}: missing file {rel_file}")
            continue

        meta = check_png(path, report, require_library_size=True)
        if pose.get("transparent") and meta["transparent_ratio"] < MIN_TRANSPARENT_RATIO:
            report.error(f"{pose_id}: marked transparent, but alpha is insufficient")

        if strict_qc and pose.get("approved") and not pose.get("handsVerified"):
            report.error(f"{pose_id}: approved pose is missing handsVerified QC")

    for value, count in Counter(ids).items():
        if count > 1:
            report.error(f"duplicate pose id: {value}")
    for value, count in Counter(files).items():
        if count > 1:
            report.error(f"duplicate pose file: {value}")
    for value, count in Counter(names).items():
        if count > 1:
            report.error(f"duplicate file name: {value}")

    catalog_files = {item["file"] for item in poses if isinstance(item, dict) and "file" in item}
    for png in pose_pngs():
        rel = png.relative_to(MASCOT).as_posix()
        if rel not in catalog_files:
            report.error(f"{rel}: PNG has no poses.json entry")

    canonical = manifest.get("canonicalReference")
    if canonical != "references/mascot_reference_main.png":
        report.error("canonicalReference must be references/mascot_reference_main.png")

    for rel in REQUIRED_REFERENCES:
        path = MASCOT / rel
        if not path.exists():
            report.error(f"missing reference: {rel}")
        else:
            check_png(path, report, require_library_size=True)

    extra_refs = [
        path.relative_to(MASCOT).as_posix()
        for path in sorted((MASCOT / "references").glob("*.png"))
        if path.relative_to(MASCOT).as_posix() not in REQUIRED_REFERENCES
    ]
    if extra_refs:
        report.error(f"references/ should only keep canonical etalons: {extra_refs}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-qc",
        action="store_true",
        help="Fail if an approved pose still has handsVerified=false",
    )
    args = parser.parse_args()

    report = validate(strict_qc=args.strict_qc)
    for message in report.warnings:
        print(f"WARN  {message}")
    for message in report.errors:
        print(f"ERROR {message}")

    if report.ok:
        pose_count = len(json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["poses"])
        print(f"OK    {pose_count} poses, references and poses.json are in sync")
        return 0

    print(f"FAIL  {len(report.errors)} error(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
