#!/usr/bin/env python3
"""Review / approve / reject imported mascot outfit full edits. No auto-promote."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asset_prep_common import ensure_local_dirs, load_asset_prep, load_json, write_json
from mascot_common import (
    hashes_current,
    mask_by_pose,
    outfit_by_id,
    pose_by_id,
    pose_path,
    sha256_file,
)


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def load_queue(video_dir: Path) -> tuple[Path, dict]:
    path = video_dir / "assets" / "mascot-generation.json"
    return path, load_json(path)


def jobs_by_status(queue: dict, status: str | None = None) -> list[dict]:
    jobs = list(queue.get("jobs") or [])
    if status is None:
        return jobs
    return [j for j in jobs if j.get("status") == status]


def cmd_status(video_dir: Path) -> int:
    _, queue = load_queue(video_dir)
    jobs = jobs_by_status(queue)
    counts: dict[str, int] = {}
    for job in jobs:
        counts[job.get("status") or "unknown"] = counts.get(job.get("status") or "unknown", 0) + 1
    print(f"STATUS jobs={len(jobs)} " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for job in jobs:
        print(
            f"{job.get('status', '?'):14} {job.get('id')} "
            f"{job.get('basePose')} + {job.get('outfit')}"
        )
    return 0


def _fit(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (28, 28, 32, 255))
    copy = img.convert("RGBA")
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    ox = (size[0] - copy.width) // 2
    oy = (size[1] - copy.height) // 2
    canvas.alpha_composite(copy, (ox, oy))
    return canvas


def _checker(size: tuple[int, int], cell: int = 16) -> Image.Image:
    img = Image.new("RGBA", size, (40, 40, 44, 255))
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            if ((x // cell) + (y // cell)) % 2 == 0:
                px[x, y] = (55, 55, 60, 255)
    return img


def build_contact_sheet(video_dir: Path) -> Path:
    _, queue = load_queue(video_dir)
    review_jobs = jobs_by_status(queue, "needs-review")
    if not review_jobs:
        raise RuntimeError("no needs-review jobs for contact sheet")
    prep = load_asset_prep(video_dir) if (video_dir / "assets" / "asset-prep.json").exists() else {
        "paths": {"localRoot": f".local-assets/{video_dir.name}"}
    }
    dirs = ensure_local_dirs(video_dir, prep)
    panel = (280, 320)
    label_h = 48
    top = 20
    bottom = 20
    gap = 8
    cols = 4
    rows = len(review_jobs)
    width = 20 + cols * panel[0] + 20
    height = top + rows * (label_h + panel[1] + gap) + bottom
    sheet = Image.new("RGB", (width, height), (16, 18, 22))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None

    y = top
    for job in review_jobs:
        pose = pose_by_id(job["basePose"])
        label = (
            f"{job['id']}  pose={job['basePose']}  outfit={job['outfit']}  "
            f"status={job.get('status')}"
        )
        draw.text((20, y), label, fill=(240, 240, 240), font=font)
        panel_y = y + label_h

        panels: list[Image.Image] = []
        # 1 base pose
        if pose:
            panels.append(_fit(Image.open(pose_path(pose)), panel))
        else:
            panels.append(Image.new("RGBA", panel, (60, 20, 20, 255)))
        # 2 full edit
        full_path = video_dir / job["targetFullEdit"]
        if full_path.exists():
            panels.append(_fit(Image.open(full_path), panel))
        else:
            panels.append(Image.new("RGBA", panel, (40, 40, 40, 255)))
        # 3 layer on checker
        layer_path = video_dir / job["targetLayer"]
        if layer_path.exists():
            bg = _checker(panel)
            layer = Image.open(layer_path).convert("RGBA")
            layer.thumbnail(panel, Image.Resampling.LANCZOS)
            ox = (panel[0] - layer.width) // 2
            oy = (panel[1] - layer.height) // 2
            bg.alpha_composite(layer, (ox, oy))
            panels.append(bg)
        else:
            panels.append(Image.new("RGBA", panel, (40, 40, 40, 255)))
        # 4 composed
        if pose and layer_path.exists():
            base = Image.open(pose_path(pose)).convert("RGBA")
            layer = Image.open(layer_path).convert("RGBA")
            if layer.size == base.size:
                panels.append(_fit(Image.alpha_composite(base, layer), panel))
            else:
                panels.append(Image.new("RGBA", panel, (60, 40, 20, 255)))
        else:
            panels.append(Image.new("RGBA", panel, (40, 40, 40, 255)))

        for index, panel_img in enumerate(panels):
            x = 20 + index * panel[0]
            sheet.paste(panel_img.convert("RGB"), (x, panel_y))
        y = panel_y + panel[1] + gap

    out = dirs["previews"] / "mascot-variant-review.png"
    sheet.save(out, format="PNG")
    return out


def cmd_contact_sheet(video_dir: Path) -> int:
    try:
        out = build_contact_sheet(video_dir)
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc))
    print(f"OK    contact-sheet {out}")
    return 0


def approve_jobs(video_dir: Path, job_ids: list[str]) -> int:
    queue_path, queue = load_queue(video_dir)
    by_id = {j["id"]: j for j in queue.get("jobs") or []}
    errors: list[str] = []
    updated = 0
    for job_id in job_ids:
        job_id = job_id.strip()
        if not job_id:
            continue
        job = by_id.get(job_id)
        if job is None:
            errors.append(f"{job_id}: missing")
            continue
        if job.get("status") != "needs-review":
            errors.append(f"{job_id}: status={job.get('status')} (need needs-review)")
            continue
        pose = pose_by_id(job["basePose"])
        outfit = outfit_by_id(job["outfit"])
        mask = mask_by_pose(job["basePose"])
        if pose is None or outfit is None or mask is None:
            errors.append(f"{job_id}: pose/outfit/mask missing")
            continue
        current = hashes_current(pose, mask, outfit)
        stale = False
        for key in ("basePoseSha256", "maskSha256", "outfitSpecSha256"):
            if job.get(key) != current[key]:
                errors.append(f"{job_id}: stale {key}")
                stale = True
                break
        if stale:
            continue
        full = video_dir / job["targetFullEdit"]
        layer = video_dir / job["targetLayer"]
        if not full.exists() or not layer.exists():
            errors.append(f"{job_id}: missing full-edit or layer file")
            continue
        if job.get("fullEditSha256") and sha256_file(full) != job.get("fullEditSha256"):
            errors.append(f"{job_id}: full-edit hash mismatch")
            continue
        if job.get("layerSha256") and sha256_file(layer) != job.get("layerSha256"):
            errors.append(f"{job_id}: layer hash mismatch")
            continue
        img = Image.open(layer).convert("RGBA")
        if not any(px[3] > 0 for px in img.getdata()):
            errors.append(f"{job_id}: layer has zero alpha")
            continue
        job["status"] = "approved"
        job.pop("rejectedReason", None)
        updated += 1
        print(f"APPROVED {job_id}")
    if errors:
        for message in errors:
            print(f"ERROR {message}")
        return 1
    write_json(queue_path, queue)
    print(f"OK    updated={updated}")
    return 0


def reject_jobs(video_dir: Path, job_ids: list[str], reason: str | None) -> int:
    if not reason:
        return fail("--reason is required for reject")
    queue_path, queue = load_queue(video_dir)
    by_id = {j["id"]: j for j in queue.get("jobs") or []}
    updated = 0
    for job_id in job_ids:
        job_id = job_id.strip()
        job = by_id.get(job_id)
        if job is None:
            return fail(f"unknown job `{job_id}`")
        job["status"] = "rejected"
        job["rejectedReason"] = reason
        # Preserve outputs; do not delete.
        updated += 1
        print(f"REJECTED {job_id}")
    write_json(queue_path, queue)
    print(f"OK    updated={updated}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--contact-sheet", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--approve", type=str, default=None)
    parser.add_argument("--reject", type=str, default=None)
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
        return approve_jobs(video_dir, args.approve.split(","))
    return reject_jobs(video_dir, args.reject.split(","), args.reason)


if __name__ == "__main__":
    sys.exit(main())
