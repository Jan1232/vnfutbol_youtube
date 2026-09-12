#!/usr/bin/env python3
"""Validate mascot pose assets against poses.json."""

from __future__ import annotations

import argparse
import hashlib
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
    "framing",
    "direction",
    "prop",
    "sha256",
)
FRAMING = {"chest-up", "waist-up", "upper-thigh"}
DIRECTION = {"front", "left", "right"}
PROP = {None, "ball", "phone", "yellow-card", "red-card", "newspaper", "clipboard"}
MIN_SIDE = 512
MIN_LONG_SIDE = 1024
MIN_ASPECT = 0.4
MAX_ASPECT = 2.5
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"Missing manifest: {MANIFEST_PATH}")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def pose_pngs() -> list[Path]:
    return sorted(MASCOT.joinpath("poses").rglob("*.png"))


def alpha_values(alpha: Image.Image):
    if hasattr(alpha, "get_flattened_data"):
        return alpha.get_flattened_data()
    return alpha.getdata()


def check_png(path: Path, report: Report) -> dict:
    rel = path.relative_to(MASCOT).as_posix()
    meta = {"transparent_ratio": 0.0}
    try:
        image = Image.open(path)
    except OSError as exc:
        report.error(f"{rel}: cannot open PNG ({exc})")
        return meta

    if image.format != "PNG":
        report.error(f"{rel}: not a PNG ({image.format})")
        return meta

    bands = image.getbands()
    if "A" not in bands:
        report.error(f"{rel}: no alpha channel")
        return meta

    image = image.convert("RGBA")
    width, height = image.size
    alpha = image.getchannel("A")
    extrema = alpha.getextrema()
    transparent = sum(1 for value in alpha_values(alpha) if value == 0)
    total = width * height
    ratio = transparent / total if total else 0.0
    corners = [
        image.getpixel((0, 0))[3],
        image.getpixel((width - 1, 0))[3],
        image.getpixel((0, height - 1))[3],
        image.getpixel((width - 1, height - 1))[3],
    ]
    meta["transparent_ratio"] = ratio

    if width < MIN_SIDE or height < MIN_SIDE:
        report.error(f"{rel}: image is too small ({width}x{height})")
    if max(width, height) < MIN_LONG_SIDE:
        report.error(f"{rel}: long side must be >= {MIN_LONG_SIDE}px ({width}x{height})")

    aspect = width / height if height else 0
    if aspect < MIN_ASPECT or aspect > MAX_ASPECT:
        report.error(f"{rel}: unreasonable aspect ratio {aspect:.3f} ({width}x{height})")

    if extrema[0] == 255:
        report.error(f"{rel}: no alpha transparency")
    elif ratio < MIN_TRANSPARENT_RATIO:
        report.error(f"{rel}: too little true alpha ({ratio:.1%})")

    opaque_corners = sum(1 for value in corners if value > CORNER_ALPHA_LIMIT)
    if opaque_corners > 1:
        report.error(f"{rel}: background looks baked in (opaque corners: {opaque_corners})")

    return meta


def reference_file(entry) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("file")
    return None


def check_hash(path: Path, expected, label: str, report: Report) -> None:
    if not isinstance(expected, str) or len(expected) != 64:
        report.error(f"{label}: sha256 must be a 64-char hex digest")
        return
    actual = sha256_file(path)
    if actual != expected.lower():
        report.error(f"{label}: sha256 mismatch (QC hash no longer matches this PNG)")


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
        if pose["framing"] not in FRAMING:
            report.error(f"{pose_id}: invalid framing `{pose['framing']}`")
        if pose["direction"] not in DIRECTION:
            report.error(f"{pose_id}: invalid direction `{pose['direction']}`")
        if pose["prop"] not in PROP:
            report.error(f"{pose_id}: invalid prop `{pose['prop']}`")

        if pose.get("approved") and not pose.get("handsVerified"):
            report.error(f"{pose_id}: approved pose must have handsVerified=true")

        if strict_qc and not str(pose.get("description") or "").strip():
            report.error(f"{pose_id}: --strict-qc requires a description")

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

        meta = check_png(path, report)
        if pose.get("transparent") and meta["transparent_ratio"] < MIN_TRANSPARENT_RATIO:
            report.error(f"{pose_id}: marked transparent, but alpha is insufficient")
        check_hash(path, pose.get("sha256"), pose_id, report)

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

    extra_manifest = catalog_files - {png.relative_to(MASCOT).as_posix() for png in pose_pngs()}
    for rel in sorted(extra_manifest):
        report.error(f"{rel}: manifest entry has no PNG")

    canonical = manifest.get("canonicalReference")
    canonical_file = reference_file(canonical)
    if canonical_file != "references/mascot_reference_main.png":
        report.error("canonicalReference.file must be references/mascot_reference_main.png")
    elif isinstance(canonical, dict):
        path = MASCOT / canonical_file
        if path.exists():
            check_png(path, report)
            check_hash(path, canonical.get("sha256"), "canonicalReference", report)
        else:
            report.error(f"missing reference: {canonical_file}")

    aux = manifest.get("auxiliaryReferences")
    if not isinstance(aux, list) or not aux:
        report.error("auxiliaryReferences must be a non-empty list")
    else:
        for item in aux:
            rel = reference_file(item)
            if not rel:
                report.error("auxiliaryReferences entry is missing file")
                continue
            path = MASCOT / rel
            if not path.exists():
                report.error(f"missing reference: {rel}")
                continue
            check_png(path, report)
            if isinstance(item, dict):
                check_hash(path, item.get("sha256"), rel, report)

    listed_refs = {canonical_file, *(reference_file(item) for item in aux or [])}
    extra_refs = [
        path.relative_to(MASCOT).as_posix()
        for path in sorted((MASCOT / "references").glob("*.png"))
        if path.relative_to(MASCOT).as_posix() not in listed_refs
    ]
    if extra_refs:
        report.error(f"references/ should only keep canonical etalons: {extra_refs}")
    for rel in REQUIRED_REFERENCES:
        if rel not in listed_refs:
            report.error(f"required reference is not listed: {rel}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-qc",
        action="store_true",
        help="Extra QC: require a non-empty description on every pose",
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
