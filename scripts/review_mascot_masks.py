#!/usr/bin/env python3
"""Review / approve / reject clothing masks that block mascot pairs for a video."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asset_prep_common import ensure_local_dirs, load_asset_prep, load_json, write_json
from mascot_common import (
    MASCOT,
    MASKS_PATH,
    load_masks,
    load_poses,
    mask_by_pose,
    mask_path,
    pose_by_id,
    pose_path,
    sha256_file,
)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def blocked_pose_outfits(video_dir: Path) -> dict[str, list[str]]:
    """Unique basePose -> required outfits for BLOCKED prepared mascot records."""
    prepared_path = video_dir / "assets" / "prepared-assets.json"
    assets_path = video_dir / "assets" / "assets.json"
    by_pose: dict[str, set[str]] = defaultdict(set)
    if prepared_path.exists():
        for item in load_json(prepared_path).get("assets") or []:
            if item.get("status") != "BLOCKED":
                continue
            mascot = item.get("mascot") or {}
            pose = mascot.get("basePose")
            outfit = mascot.get("outfit")
            if pose and outfit:
                by_pose[pose].add(outfit)
    if not by_pose and assets_path.exists():
        for asset in load_json(assets_path).get("assets") or []:
            if asset.get("type") != "MASCOT":
                continue
            mascot = asset.get("mascot") or {}
            pose = mascot.get("basePose")
            outfit = mascot.get("resolvedOutfit")
            if pose and outfit and outfit != "default-home":
                by_pose[pose].add(outfit)
    return {pose: sorted(outfits) for pose, outfits in sorted(by_pose.items())}


def mask_integrity(pose_id: str) -> tuple[str, str]:
    """Return (state, detail). state in ok|missing|hash_mismatch|stale_pose|no_mask."""
    pose = pose_by_id(pose_id)
    if pose is None or not pose.get("approved"):
        return "no_pose", f"approved pose `{pose_id}` missing"
    mask = mask_by_pose(pose_id)
    if mask is None:
        return "no_mask", "mask entry missing from pose-masks.json"
    path = mask_path(mask)
    if not path.exists():
        return "missing", f"mask file missing: {mask.get('file')}"
    digest = sha256_file(path)
    if digest != mask.get("sha256"):
        return "hash_mismatch", f"file sha256 {digest[:12]}… != manifest {str(mask.get('sha256'))[:12]}…"
    if mask.get("basePoseSha256") != pose.get("sha256"):
        return "stale_pose", "basePoseSha256 does not match current approved pose"
    return "ok", mask.get("status") or "unknown"


def cmd_status(video_dir: Path) -> int:
    mapping = blocked_pose_outfits(video_dir)
    if not mapping:
        print("OK    no blocked mascot masks for this video")
        return 0
    print(f"STATUS blocked_poses={len(mapping)}")
    for pose, outfits in mapping.items():
        state, detail = mask_integrity(pose)
        print(f"{pose:24} outfits={','.join(outfits)} mask={state} ({detail})")
    return 0


def mask_contact_sheet_metrics(row_count: int) -> dict[str, int]:
    """Layout metrics for the mask review contact sheet."""
    panel_w, panel_h = 320, 360
    label_h = 56
    top_margin = 20
    bottom_margin = 20
    row_gap = 8
    cols = 3
    row_step = label_h + panel_h + row_gap
    width = cols * panel_w + 40
    height = top_margin + row_count * row_step + bottom_margin
    return {
        "panel_w": panel_w,
        "panel_h": panel_h,
        "label_h": label_h,
        "top_margin": top_margin,
        "bottom_margin": bottom_margin,
        "row_gap": row_gap,
        "row_step": row_step,
        "cols": cols,
        "width": width,
        "height": height,
    }


def _fit(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (24, 24, 28, 255))
    copy = img.convert("RGBA")
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    ox = (size[0] - copy.width) // 2
    oy = (size[1] - copy.height) // 2
    canvas.alpha_composite(copy, (ox, oy))
    return canvas


def build_contact_sheet(video_dir: Path) -> Path:
    if Image is None:
        raise RuntimeError("Pillow is required for --contact-sheet")
    mapping = blocked_pose_outfits(video_dir)
    if not mapping:
        raise RuntimeError("no blocked poses to review")
    prep = load_asset_prep(video_dir)
    dirs = ensure_local_dirs(video_dir, prep)
    rows = len(mapping)
    metrics = mask_contact_sheet_metrics(rows)
    panel = (metrics["panel_w"], metrics["panel_h"])
    label_h = metrics["label_h"]
    sheet = Image.new("RGB", (metrics["width"], metrics["height"]), (18, 18, 22))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None

    y = metrics["top_margin"]
    for pose_id, outfits in mapping.items():
        pose = pose_by_id(pose_id)
        mask = mask_by_pose(pose_id)
        state, detail = mask_integrity(pose_id)
        label = f"{pose_id}  outfits: {', '.join(outfits)}  [{state}]"
        draw.text((20, y), label, fill=(240, 240, 240), font=font)
        draw.text((20, y + 18), detail[:90], fill=(180, 180, 180), font=font)
        panel_y = y + label_h

        panels: list[Image.Image] = []
        if pose and pose_path(pose).exists():
            base = Image.open(pose_path(pose))
            panels.append(_fit(base, panel))
        else:
            panels.append(Image.new("RGBA", panel, (60, 20, 20, 255)))

        if mask and mask_path(mask).exists():
            mask_img = Image.open(mask_path(mask))
            panels.append(_fit(mask_img, panel))
            base_rgba = (
                Image.open(pose_path(pose)).convert("RGBA")
                if pose
                else Image.new("RGBA", panel)
            )
            mask_rgba = mask_img.convert("L")
            alpha = mask_rgba.point(lambda p: 140 if p > 16 else 0)
            red = Image.new("RGBA", base_rgba.size, (220, 40, 40, 255))
            red.putalpha(alpha)
            composed = Image.alpha_composite(base_rgba, red)
            panels.append(_fit(composed, panel))
        else:
            panels.append(Image.new("RGBA", panel, (40, 40, 40, 255)))
            panels.append(Image.new("RGBA", panel, (40, 40, 40, 255)))

        for index, panel_img in enumerate(panels):
            x = 20 + index * panel[0]
            sheet.paste(panel_img.convert("RGB"), (x, panel_y))
        y = panel_y + panel[1] + metrics["row_gap"]

    # Final content bottom must leave bottom margin intact (no clipping).
    if y > metrics["height"] - metrics["bottom_margin"]:
        raise RuntimeError(
            f"contact sheet height too small: content_end={y} "
            f"height={metrics['height']} bottom_margin={metrics['bottom_margin']}"
        )

    out = dirs["previews"] / "mascot-mask-review.png"
    sheet.save(out, format="PNG")
    return out


def cmd_contact_sheet(video_dir: Path) -> int:
    try:
        out = build_contact_sheet(video_dir)
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc))
    print(f"OK    contact-sheet {out}")
    return 0


def update_mask_status(pose_ids: list[str], status: str, reason: str | None) -> int:
    payload = load_masks()
    masks = payload.get("masks") or []
    by_pose = {m.get("basePose"): m for m in masks}
    errors: list[str] = []
    updated = 0
    for pose_id in pose_ids:
        pose_id = pose_id.strip()
        if not pose_id:
            continue
        mask = by_pose.get(pose_id)
        if mask is None:
            errors.append(f"{pose_id}: mask entry missing")
            continue
        if status == "approved":
            state, detail = mask_integrity(pose_id)
            if state != "ok":
                errors.append(f"{pose_id}: cannot approve ({state}: {detail})")
                continue
            mask["status"] = "approved"
            mask.pop("rejectedReason", None)
        elif status == "rejected":
            if not reason:
                errors.append(f"{pose_id}: --reason is required for reject")
                continue
            if mask.get("status") == "rejected":
                # Never silently regenerate; just update reason if provided
                mask["rejectedReason"] = reason
            else:
                mask["status"] = "rejected"
                mask["rejectedReason"] = reason
        else:
            errors.append(f"{pose_id}: invalid status {status}")
            continue
        updated += 1
        print(f"{status.upper():8} {pose_id}")
    if errors:
        for message in errors:
            print(f"ERROR {message}")
        return 1
    write_json(MASKS_PATH, payload)
    print(f"OK    updated={updated}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to a video folder")
    parser.add_argument("--contact-sheet", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--approve", type=str, default=None, help="Comma-separated pose ids")
    parser.add_argument("--reject", type=str, default=None, help="Comma-separated pose ids")
    parser.add_argument("--reason", type=str, default=None)
    args = parser.parse_args()
    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()

    modes = [args.contact_sheet, args.status, bool(args.approve), bool(args.reject)]
    if sum(bool(x) for x in modes) != 1:
        parser.error("specify exactly one of --contact-sheet --status --approve --reject")

    if args.contact_sheet:
        return cmd_contact_sheet(video_dir)
    if args.status:
        return cmd_status(video_dir)
    if args.approve:
        return update_mask_status(args.approve.split(","), "approved", None)
    return update_mask_status(args.reject.split(","), "rejected", args.reason)


if __name__ == "__main__":
    sys.exit(main())
