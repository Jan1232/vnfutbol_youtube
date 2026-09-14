#!/usr/bin/env python3
"""Prepare local media for a video without committing third-party bytes."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asset_prep_common import (
    PREP_STATUSES,
    ROOT,
    assets_by_id,
    ensure_local_dirs,
    load_asset_prep,
    load_json,
    local_root,
    sha256_file,
    utc_now,
    video_paths,
    visual_plan_asset_ids,
    write_json,
)
from mascot_common import DEFAULT_OUTFIT, variant_by_pair

try:
    from PIL import Image, ImageDraw, ImageOps
except ImportError:  # pragma: no cover
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageOps = None  # type: ignore


PRESERVE_FIELDS = (
    "sourcePath",
    "preparedPath",
    "sourceSha256",
    "sha256",
    "width",
    "height",
    "durationMs",
    "clipStartMs",
    "clipEndMs",
    "crop",
    "selectionNotes",
    "candidates",
    "previewPath",
)


def rel_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def load_prepared(video_dir: Path) -> dict:
    path = video_paths(video_dir)["prepared"]
    if path.exists():
        return load_json(path)
    prep = load_asset_prep(video_dir)
    return {
        "version": 1,
        "video": video_dir.name,
        "generatedAt": None,
        "localRoot": (prep.get("paths") or {}).get("localRoot"),
        "assets": [],
    }


def prepared_by_id(payload: dict) -> dict[str, dict]:
    return {
        item["id"]: item
        for item in payload.get("assets", [])
        if isinstance(item, dict) and item.get("id")
    }


def scenes_for_asset(plan: dict, asset_id: str) -> list[str]:
    scenes: list[str] = []
    for scene in plan.get("scenes") or []:
        requested = set(scene.get("assetRequests") or [])
        mascot = scene.get("mascot") or {}
        if asset_id in requested or mascot.get("assetId") == asset_id:
            scenes.append(scene["id"])
            continue
        supporting = scene.get("supportingVisual") or {}
        if supporting.get("assetId") == asset_id:
            scenes.append(scene["id"])
        for aid in supporting.get("assetIds") or []:
            if aid == asset_id:
                scenes.append(scene["id"])
    return sorted(set(scenes))


def merge_preserve(old: dict | None, new: dict) -> dict:
    if not old:
        return new
    merged = dict(new)
    # Preserve READY selections unless caller overwrote with explicit new hashes/paths
    for field in PRESERVE_FIELDS:
        if field in old and merged.get(field) in (None, [], {}):
            merged[field] = old[field]
    if old.get("status") in {"READY", "READY_MASCOT", "READY_RENDER_SPEC"} and new.get(
        "status"
    ) in {"NEEDS_SOURCE_FILE", "NEEDS_SELECTION", "MISSING"}:
        # Keep ready unless source hash changed
        if old.get("sourceSha256") and new.get("sourceSha256"):
            if old["sourceSha256"] == new["sourceSha256"]:
                merged["status"] = old["status"]
                for field in PRESERVE_FIELDS:
                    if field in old:
                        merged[field] = old[field]
        elif old.get("status") == "READY_RENDER_SPEC" and new.get("status") == "READY_RENDER_SPEC":
            merged["status"] = "READY_RENDER_SPEC"
        elif old.get("status") == "READY_MASCOT" and new.get("status") == "READY_MASCOT":
            merged["status"] = "READY_MASCOT"
        elif not new.get("sourceSha256") and old.get("preparedPath"):
            merged["status"] = old["status"]
            for field in PRESERVE_FIELDS:
                if field in old:
                    merged[field] = old[field]
    if old.get("clipStartMs") is not None and new.get("clipStartMs") is None:
        merged["clipStartMs"] = old["clipStartMs"]
        merged["clipEndMs"] = old.get("clipEndMs")
        if old.get("status") == "READY" and merged.get("preparedPath"):
            merged["status"] = "READY"
    return merged


def load_source_reuse(video_dir: Path) -> dict | None:
    path = video_dir / "assets" / "source-reuse.json"
    if not path.exists():
        return None
    return load_json(path)


def apply_source_reuse(records: list[dict], reuse: dict | None) -> list[str]:
    """Annotate derived/render-preferred records. Returns asset ids moved to NEEDS_SELECTION."""
    if not reuse:
        return []
    by_id = {r["id"]: r for r in records}
    moved: list[str] = []

    for pref in reuse.get("renderInsteadOfExternalPreferred") or []:
        asset_id = pref.get("assetId")
        rec = by_id.get(asset_id)
        if not rec:
            continue
        if rec.get("status") in {"READY", "READY_RENDER_SPEC"} and rec.get("preparedPath"):
            continue
        if rec.get("status") == "NEEDS_SOURCE_FILE" or not rec.get("preparedPath"):
            prev = rec.get("status")
            rec["status"] = "READY_RENDER_SPEC"
            rec["derive"] = "render-preferred"
            rec["notes"] = pref.get("reason") or "prefer renderer-owned graphic"
            if prev == "NEEDS_SOURCE_FILE":
                # Not NEEDS_SELECTION — report separately as render preferred
                pass

    for group in reuse.get("groups") or []:
        group_id = group.get("id")
        primary_id = group.get("primaryAsset")
        primary = by_id.get(primary_id)
        for output in group.get("outputs") or []:
            asset_id = output.get("assetId")
            rec = by_id.get(asset_id)
            if not rec:
                continue
            derive = output.get("derive") or ""
            rec["sourceGroup"] = group_id
            rec["derive"] = derive
            if asset_id != primary_id:
                rec["derivedFrom"] = primary_id
            if output.get("selection"):
                rec["selectionNotes"] = output["selection"]

            # Prefer official still over video-frame fallback when a still was already selected.
            if "fallback" in derive and rec.get("status") == "READY" and rec.get("preparedPath"):
                continue

            primary_ready = bool(
                primary
                and primary.get("sourcePath")
                and primary.get("sourceSha256")
                and Path(ROOT / primary["sourcePath"]).exists()
            )
            if asset_id == primary_id:
                continue

            if primary_ready:
                # Share the same source bytes by path/hash — do not copy.
                prev = rec.get("status")
                rec["sourcePath"] = primary["sourcePath"]
                rec["sourceSha256"] = primary["sourceSha256"]
                rec["primarySourceUrl"] = primary.get("sourceUrl")
                if rec.get("clipStartMs") is None and (
                    "video" in derive or "frame" in derive or "excerpt" in derive
                ):
                    rec["status"] = "NEEDS_SELECTION"
                    rec["notes"] = (
                        f"derived from {primary_id} via {derive}; "
                        "clip/frame timestamp not selected"
                    )
                    if prev == "NEEDS_SOURCE_FILE":
                        moved.append(asset_id)
                elif "image-crop" in derive and not rec.get("preparedPath"):
                    rec["status"] = "NEEDS_SELECTION"
                    rec["notes"] = (
                        f"derived from {primary_id} via {derive}; crop not selected"
                    )
                    if prev == "NEEDS_SOURCE_FILE":
                        moved.append(asset_id)
            else:
                if rec.get("status") == "NEEDS_SOURCE_FILE":
                    rec["notes"] = (
                        f"awaits primary source `{primary_id}` ({derive}); "
                        "do not duplicate source bytes"
                    )
    return moved


def distinct_source_files_needed(records: list[dict], reuse: dict | None) -> list[str]:
    """Count unique editor source files still required after reuse grouping."""
    by_id = {r["id"]: r for r in records}
    covered: set[str] = set()
    needed: list[str] = []

    if reuse:
        for pref in reuse.get("renderInsteadOfExternalPreferred") or []:
            covered.add(pref.get("assetId"))
        for group in reuse.get("groups") or []:
            primary = group.get("primaryAsset")
            outputs = [o.get("assetId") for o in group.get("outputs") or []]
            for oid in outputs:
                covered.add(oid)
            prec = by_id.get(primary)
            if prec and prec.get("status") in {
                "NEEDS_SOURCE_FILE",
                "NEEDS_SELECTION",
                "MISSING",
            }:
                if primary not in needed:
                    needed.append(primary)
            elif prec and prec.get("status") not in {
                "READY",
                "READY_RENDER_SPEC",
                "READY_MASCOT",
            }:
                if primary not in needed:
                    needed.append(primary)

    for rec in records:
        if rec.get("type") == "MASCOT" or rec.get("id") == "narration":
            continue
        if rec.get("status") not in {"NEEDS_SOURCE_FILE", "NEEDS_SELECTION", "MISSING"}:
            continue
        if rec["id"] in covered:
            continue
        if rec.get("status") == "READY_RENDER_SPEC":
            continue
        needed.append(rec["id"])
    return needed


def classify_plan_record(
    asset_id: str,
    asset: dict | None,
    prep: dict,
    video_dir: Path,
    plan: dict,
) -> dict:
    render_ids = set(prep.get("renderOnlyAssetIds") or [])
    external_ids = set(prep.get("externalAssetIds") or [])
    used = scenes_for_asset(plan, asset_id)
    record: dict[str, Any] = {
        "id": asset_id,
        "type": (asset or {}).get("type"),
        "status": "MISSING",
        "sourcePath": None,
        "preparedPath": None,
        "sourceSha256": None,
        "sha256": None,
        "width": None,
        "height": None,
        "durationMs": None,
        "clipStartMs": None,
        "clipEndMs": None,
        "sourceUrl": (asset or {}).get("sourceUrl"),
        "rightsStatus": (asset or {}).get("rightsStatus"),
        "usedInScenes": used,
        "notes": None,
    }

    if asset is None:
        record["status"] = "MISSING"
        record["notes"] = "asset id not found in assets.json"
        return record

    if asset_id == "narration" or asset.get("type") == "AUDIO":
        rel = asset.get("file")
        if rel:
            path = video_dir / rel
            if path.exists():
                record["status"] = "READY"
                record["preparedPath"] = rel.replace("\\", "/")
                record["sourcePath"] = rel.replace("\\", "/")
                record["sha256"] = sha256_file(path)
                record["sourceSha256"] = record["sha256"]
                record["notes"] = "channel-owned narration"
                return record
        record["status"] = "NEEDS_SOURCE_FILE"
        record["notes"] = "narration file missing"
        return record

    if asset_id in render_ids or asset.get("source") == "render":
        spec = asset.get("renderSpec")
        if isinstance(spec, str) and spec.strip():
            record["status"] = "READY_RENDER_SPEC"
            record["notes"] = "renderer-owned; no download required"
        else:
            record["status"] = "BLOCKED"
            record["notes"] = "render-only asset missing renderSpec"
        return record

    if asset.get("type") == "MASCOT":
        mascot = asset.get("mascot") or {}
        pose = mascot.get("basePose")
        outfit = mascot.get("resolvedOutfit")
        if not pose or not outfit:
            record["status"] = "BLOCKED"
            record["notes"] = "mascot missing basePose/resolvedOutfit"
            return record
        if outfit == DEFAULT_OUTFIT:
            record["status"] = "READY_MASCOT"
            record["notes"] = "default-home uses approved base pose"
            record["mascot"] = {"basePose": pose, "outfit": outfit, "mode": "base-pose"}
            return record
        variant = variant_by_pair(pose, outfit)
        if variant and variant.get("status") == "approved":
            record["status"] = "READY_MASCOT"
            record["notes"] = "approved outfit variant reusable"
            record["mascot"] = {
                "basePose": pose,
                "outfit": outfit,
                "variant": variant.get("id") or f"{pose}__{outfit}",
            }
            return record
        record["status"] = "BLOCKED"
        record["notes"] = (
            f"mascot variant pending/missing for {pose} + {outfit}; "
            "do not invent approved variants"
        )
        record["mascot"] = {"basePose": pose, "outfit": outfit, "mode": "pending"}
        return record

    if asset_id in external_ids or asset.get("downloadToPublicRepo") is False:
        record["status"] = "NEEDS_SOURCE_FILE"
        record["notes"] = "external media; drop file into inbox/ or run --fetch-external"
        return record

    # Library / generated channel-owned
    file_rel = asset.get("file")
    if file_rel:
        path = (ROOT / file_rel) if not Path(file_rel).is_absolute() else Path(file_rel)
        if not path.exists() and (video_dir / file_rel).exists():
            path = video_dir / file_rel
        if path.exists():
            record["status"] = "READY"
            record["sourcePath"] = rel_to_repo(path)
            record["preparedPath"] = rel_to_repo(path)
            record["sha256"] = sha256_file(path)
            record["sourceSha256"] = record["sha256"]
            return record
    record["status"] = "NEEDS_SOURCE_FILE"
    record["notes"] = "no local source file yet"
    return record


def cmd_plan(video_dir: Path) -> int:
    prep = load_asset_prep(video_dir)
    dirs = ensure_local_dirs(video_dir, prep)
    paths = video_paths(video_dir)
    plan = load_json(paths["visual_plan"])
    assets_payload = load_json(paths["assets"])
    by_id = assets_by_id(assets_payload)

    required_ids: list[str] = []
    seen: set[str] = set()
    for asset_id in visual_plan_asset_ids(plan):
        if asset_id not in seen:
            seen.add(asset_id)
            required_ids.append(asset_id)
    for asset_id in prep.get("renderOnlyAssetIds") or []:
        if asset_id not in seen:
            seen.add(asset_id)
            required_ids.append(asset_id)
    for asset_id in prep.get("externalAssetIds") or []:
        if asset_id not in seen:
            seen.add(asset_id)
            required_ids.append(asset_id)
    if "narration" in by_id and "narration" not in seen:
        required_ids.insert(0, "narration")
        seen.add("narration")
    for asset in assets_payload.get("assets") or []:
        if asset.get("type") == "MASCOT" and asset.get("id") not in seen:
            required_ids.append(asset["id"])
            seen.add(asset["id"])

    existing = load_prepared(video_dir)
    old_by_id = prepared_by_id(existing)
    records = []
    for asset_id in required_ids:
        fresh = classify_plan_record(asset_id, by_id.get(asset_id), prep, video_dir, plan)
        merged = merge_preserve(old_by_id.get(asset_id), fresh)
        # Re-evaluate READY from local files if previously READY
        if merged.get("status") == "READY" and merged.get("preparedPath"):
            prep_path = ROOT / merged["preparedPath"]
            if not prep_path.exists():
                # fall back to fresh classification
                merged = fresh
        records.append(merged)

    reuse = load_source_reuse(video_dir)
    moved = apply_source_reuse(records, reuse)
    needed = distinct_source_files_needed(records, reuse)

    payload = {
        "version": 1,
        "video": video_dir.name,
        "generatedAt": utc_now(),
        "localRoot": rel_to_repo(dirs["root"]),
        "assets": records,
        "sourceReuse": {
            "movedToNeedsSelection": moved,
            "distinctSourceFilesNeeded": needed,
            "distinctSourceFileCount": len(needed),
        },
    }
    write_json(paths["prepared"], payload)
    prep["stage"] = "planned"
    write_json(paths["prep"], prep)
    print(
        f"OK    prepared-assets.json records={len(records)} localRoot={dirs['root']} "
        f"distinct_sources_needed={len(needed)} moved_to_needs_selection={len(moved)}"
    )
    return 0


def status_counts(payload: dict) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {status: [] for status in sorted(PREP_STATUSES)}
    for item in payload.get("assets") or []:
        status = item.get("status") or "MISSING"
        buckets.setdefault(status, []).append(item["id"])
    return buckets


def cmd_status(video_dir: Path) -> int:
    payload = load_prepared(video_dir)
    buckets = status_counts(payload)
    total = len(payload.get("assets") or [])
    print(f"STATUS video={video_dir.name} total={total}")
    for status, ids in buckets.items():
        if not ids:
            continue
        print(f"{status:20} {len(ids)}")
        for asset_id in ids:
            print(f"  - {asset_id}")
    return 0


def probe_media(path: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {"width": None, "height": None, "durationMs": None}
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"} and Image is not None:
        try:
            with Image.open(path) as img:
                meta["width"], meta["height"] = img.size
            return meta
        except OSError as exc:
            meta["probeError"] = str(exc)
            return meta
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return meta
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(proc.stdout)
        for stream in data.get("streams") or []:
            if stream.get("width") and meta["width"] is None:
                meta["width"] = int(stream["width"])
                meta["height"] = int(stream.get("height") or 0)
            if stream.get("codec_type") == "video" and stream.get("duration"):
                meta["durationMs"] = int(float(stream["duration"]) * 1000)
        fmt = data.get("format") or {}
        if meta["durationMs"] is None and fmt.get("duration"):
            meta["durationMs"] = int(float(fmt["duration"]) * 1000)
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as exc:
        meta["probeError"] = str(exc)
    return meta


def ingest_inbox_file(video_dir: Path, path: Path, record: dict, dirs: dict[str, Path]) -> dict:
    stem = path.stem
    # Accept asset-id.ext or exact names
    asset_id = record["id"]
    if stem != asset_id and not stem.startswith(asset_id):
        # Still allow if filename equals asset id with extension already checked by caller
        pass
    digest = sha256_file(path)
    ext = path.suffix.lower() or ".bin"
    dest = dirs["source"] / f"{asset_id}{ext}"
    if dest.exists():
        existing = sha256_file(dest)
        if existing != digest:
            raise ValueError(
                f"{asset_id}: inbox file hash differs from existing source "
                f"({existing[:12]}… vs {digest[:12]}…); refusing silent overwrite"
            )
    else:
        shutil.copy2(path, dest)
    meta = probe_media(dest)
    record["sourcePath"] = rel_to_repo(dest)
    record["sourceSha256"] = digest
    record["width"] = meta.get("width")
    record["height"] = meta.get("height")
    record["durationMs"] = meta.get("durationMs")
    if record.get("type") == "VIDEO":
        if record.get("clipStartMs") is not None and record.get("clipEndMs") is not None:
            record["status"] = "NEEDS_SELECTION"
            record["notes"] = "source ingested; clip range present — run --prepare"
        else:
            record["status"] = "NEEDS_SELECTION"
            record["notes"] = "source ingested; clip timestamps not selected"
    else:
        record["status"] = "NEEDS_SELECTION"
        record["notes"] = "source ingested; run --prepare to normalize"
    return record


def cmd_ingest(video_dir: Path) -> int:
    prep = load_asset_prep(video_dir)
    dirs = ensure_local_dirs(video_dir, prep)
    payload = load_prepared(video_dir)
    by_id = prepared_by_id(payload)
    if not by_id:
        cmd_plan(video_dir)
        payload = load_prepared(video_dir)
        by_id = prepared_by_id(payload)

    inbox_files = [p for p in dirs["inbox"].iterdir() if p.is_file()]
    if not inbox_files:
        print("OK    inbox empty")
        return 0

    updated = 0
    for path in sorted(inbox_files):
        asset_id = path.stem
        # Allow asset-id_extra.ext → prefer longest matching prepared id
        match = None
        if asset_id in by_id:
            match = asset_id
        else:
            candidates = [aid for aid in by_id if asset_id.startswith(aid) or aid.startswith(asset_id)]
            if len(candidates) == 1:
                match = candidates[0]
            elif path.stem in by_id:
                match = path.stem
        if match is None:
            print(f"SKIP  unrecognized inbox file: {path.name}")
            continue
        try:
            by_id[match] = ingest_inbox_file(video_dir, path, dict(by_id[match]), dirs)
            updated += 1
            print(f"INGEST {match} <- {path.name} sha256={by_id[match]['sourceSha256'][:12]}…")
        except ValueError as exc:
            print(f"ERROR {exc}")
            return 1

    payload["assets"] = list(by_id.values())
    payload["generatedAt"] = utc_now()
    write_json(video_paths(video_dir)["prepared"], payload)
    print(f"OK    ingested={updated}")
    return 0


def prepare_image(record: dict, dirs: dict[str, Path], prep: dict) -> dict:
    if Image is None:
        raise RuntimeError("Pillow is required for image preparation")
    source = ROOT / record["sourcePath"]
    if not source.exists():
        raise FileNotFoundError(record["sourcePath"])
    with Image.open(source) as img:
        fixed = ImageOps.exif_transpose(img)
        rgba = fixed.convert("RGBA")
        width, height = rgba.size
        dest = dirs["prepared"] / f"{record['id']}.png"
        rgba.save(dest, format="PNG", optimize=True)
        preview = dirs["previews"] / f"{record['id']}-preview.jpg"
        rgb = rgba.convert("RGB")
        rgb.thumbnail((960, 540))
        rgb.save(preview, format="JPEG", quality=85)
    record["preparedPath"] = rel_to_repo(dest)
    record["previewPath"] = rel_to_repo(preview)
    record["sha256"] = sha256_file(dest)
    record["width"] = width
    record["height"] = height
    record["crop"] = record.get("crop") or {"mode": "non-destructive-metadata"}
    record["status"] = "READY"
    record["notes"] = "image prepared; original preserved in source/"
    return record


def prepare_video(record: dict, dirs: dict[str, Path], prep: dict) -> dict:
    source = ROOT / record["sourcePath"]
    if not source.exists():
        raise FileNotFoundError(record["sourcePath"])
    start = record.get("clipStartMs")
    end = record.get("clipEndMs")
    if start is None or end is None:
        record["status"] = "NEEDS_SELECTION"
        record["notes"] = "video source present but clipStartMs/clipEndMs not set"
        return record
    if end <= start:
        raise ValueError(f"{record['id']}: clipEndMs must be > clipStartMs")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")
    cfg = prep.get("videoPrep") or {}
    width = int(cfg.get("width") or 1920)
    height = int(cfg.get("height") or 1080)
    fps = int(cfg.get("fps") or 30)
    dest = dirs["prepared"] / f"{record['id']}.mp4"
    start_s = start / 1000.0
    duration_s = (end - start) / 1000.0
    max_s = float(cfg.get("maxPreparedExcerptSeconds") or 8)
    if duration_s > max_s:
        duration_s = max_s
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start_s:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration_s:.3f}",
        "-an",
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {record['id']}: {proc.stderr[-500:]}")
    record["preparedPath"] = rel_to_repo(dest)
    record["sha256"] = sha256_file(dest)
    record["width"] = width
    record["height"] = height
    record["durationMs"] = int(duration_s * 1000)
    record["status"] = "READY"
    record["notes"] = "prepared excerpt; source audio stripped"
    return record


def cmd_prepare(video_dir: Path) -> int:
    prep = load_asset_prep(video_dir)
    dirs = ensure_local_dirs(video_dir, prep)
    payload = load_prepared(video_dir)
    updated = 0
    for record in payload.get("assets") or []:
        if record.get("status") in {"READY_RENDER_SPEC", "READY_MASCOT", "MISSING", "BLOCKED"}:
            continue
        if not record.get("sourcePath"):
            continue
        source = ROOT / record["sourcePath"]
        if not source.exists():
            continue
        try:
            if record.get("type") == "VIDEO" or source.suffix.lower() in {
                ".mp4",
                ".mov",
                ".mkv",
                ".webm",
            }:
                prepare_video(record, dirs, prep)
            else:
                prepare_image(record, dirs, prep)
            updated += 1
            print(f"PREP  {record['id']} -> {record.get('status')}")
        except Exception as exc:  # noqa: BLE001 - surface per-asset failures
            print(f"ERROR {record['id']}: {exc}")
            return 1
    payload["generatedAt"] = utc_now()
    write_json(video_paths(video_dir)["prepared"], payload)
    print(f"OK    prepared={updated}")
    return 0


def _extract_image_urls(html: str, page_url: str) -> list[str]:
    import re
    from urllib.parse import urljoin

    found: list[str] = []
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<img[^>]+src=["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, html, flags=re.IGNORECASE):
            url = urljoin(page_url, match.strip())
            if url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) or "image" in url.lower():
                if url not in found:
                    found.append(url)
    return found[:12]


def _download_candidate(url: str, dest: Path) -> bool:
    try:
        req = Request(url, headers={"User-Agent": "vnfutbol-asset-prep/1.0"})
        with urlopen(req, timeout=25) as resp:  # noqa: S310 - public discovery only
            data = resp.read(8 * 1024 * 1024)
            ctype = (resp.headers.get("Content-Type") or "").lower()
        if "html" in ctype and not url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return False
        if len(data) < 2048:
            return False
        dest.write_bytes(data)
        return True
    except Exception:  # noqa: BLE001
        return False


def _make_contact_sheet(candidate_files: list[Path], out_path: Path) -> None:
    if Image is None or not candidate_files:
        return
    thumbs = []
    for path in candidate_files[:9]:
        try:
            with Image.open(path) as img:
                im = img.convert("RGB")
                im.thumbnail((320, 180))
                thumbs.append(im)
        except OSError:
            continue
    if not thumbs:
        return
    cols = min(3, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 320, rows * 180), (20, 20, 24))
    for index, thumb in enumerate(thumbs):
        x = (index % cols) * 320
        y = (index // cols) * 180
        sheet.paste(thumb, (x, y))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, format="JPEG", quality=85)


def cmd_discover(video_dir: Path) -> int:
    """Best-effort candidate discovery. No auth/DRM bypass. No full video download."""
    prep = load_asset_prep(video_dir)
    dirs = ensure_local_dirs(video_dir, prep)
    payload = load_prepared(video_dir)
    assets_payload = load_json(video_paths(video_dir)["assets"])
    by_asset = assets_by_id(assets_payload)
    discovered = 0
    moved_selection = 0
    for record in payload.get("assets") or []:
        if record.get("status") not in {"NEEDS_SOURCE_FILE", "NEEDS_SELECTION"}:
            continue
        # Derived assets waiting on a primary do not need independent page scrapes
        if record.get("derivedFrom") and record.get("status") == "NEEDS_SOURCE_FILE":
            continue
        asset = by_asset.get(record["id"]) or {}
        url = asset.get("sourceUrl") or record.get("sourceUrl")
        page = asset.get("referencePage") or url
        if not page:
            continue
        if "youtube.com" in page or "youtu.be" in page:
            ytdlp = shutil.which("yt-dlp")
            if not ytdlp:
                record["notes"] = "yt-dlp missing; video metadata discovery skipped"
                continue
            try:
                proc = subprocess.run(
                    [ytdlp, "--skip-download", "--print", "%(title)s\t%(duration)s", page],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.returncode == 0:
                    record["notes"] = f"yt-dlp metadata: {proc.stdout.strip()[:200]}"
                    record["discovery"] = {"type": "video-metadata", "raw": proc.stdout.strip()[:300]}
                    discovered += 1
                else:
                    record["notes"] = f"yt-dlp failed: {proc.stderr.strip()[:200]}"
            except Exception as exc:  # noqa: BLE001
                record["notes"] = f"yt-dlp error: {exc}"
            continue

        cand_dir = dirs["candidates"] / record["id"]
        cand_dir.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        try:
            req = Request(page, headers={"User-Agent": "vnfutbol-asset-prep/1.0"})
            with urlopen(req, timeout=30) as resp:  # noqa: S310
                html = resp.read(2 * 1024 * 1024).decode("utf-8", errors="ignore")
            image_urls = _extract_image_urls(html, page)
            for index, image_url in enumerate(image_urls):
                ext = Path(urlparse(image_url).path).suffix.lower() or ".jpg"
                if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
                    ext = ".jpg"
                dest = cand_dir / f"candidate-{index:02d}{ext}"
                if dest.exists() or _download_candidate(image_url, dest):
                    if dest.exists() and dest.stat().st_size > 2048:
                        saved.append(rel_to_repo(dest))
            preview = dirs["previews"] / f"{record['id']}-candidates.jpg"
            files = [ROOT / p for p in saved]
            _make_contact_sheet([p for p in files if p.exists()], preview)
            record["candidates"] = saved
            if saved:
                prev = record.get("status")
                record["status"] = "NEEDS_SELECTION"
                record["previewPath"] = rel_to_repo(preview) if preview.exists() else None
                record["notes"] = (
                    f"discovered {len(saved)} candidate image(s); "
                    "select one explicitly before prepare"
                )
                discovered += len(saved)
                if prev == "NEEDS_SOURCE_FILE":
                    moved_selection += 1
            else:
                record["notes"] = "no usable public image candidates discovered"
        except Exception as exc:  # noqa: BLE001
            record["notes"] = f"discovery failed: {exc}"
            record.setdefault("candidates", [])

    payload["generatedAt"] = utc_now()
    write_json(video_paths(video_dir)["prepared"], payload)
    print(
        f"OK    discover candidates_saved={discovered} "
        f"moved_to_needs_selection={moved_selection}"
    )
    return 0


def cmd_fetch_external(video_dir: Path) -> int:
    """Explicit opt-in download into source/. Never called by --plan/--status."""
    prep = load_asset_prep(video_dir)
    dirs = ensure_local_dirs(video_dir, prep)
    payload = load_prepared(video_dir)
    assets_payload = load_json(video_paths(video_dir)["assets"])
    by_asset = assets_by_id(assets_payload)
    fetched = 0
    for record in payload.get("assets") or []:
        if record.get("status") != "NEEDS_SOURCE_FILE":
            continue
        if record.get("type") == "VIDEO":
            print(f"SKIP  {record['id']}: video fetch requires manual/yt-dlp inbox drop")
            continue
        asset = by_asset.get(record["id"]) or {}
        url = asset.get("sourceUrl")
        if not url or not url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            print(f"SKIP  {record['id']}: no direct image URL")
            continue
        dest = dirs["source"] / f"{record['id']}{Path(urlparse(url).path).suffix or '.jpg'}"
        try:
            req = Request(url, headers={"User-Agent": "vnfutbol-asset-prep/1.0"})
            with urlopen(req, timeout=60) as resp:  # noqa: S310 - explicit editor opt-in
                data = resp.read()
            dest.write_bytes(data)
            digest = sha256_file(dest)
            record["sourcePath"] = rel_to_repo(dest)
            record["sourceSha256"] = digest
            meta = probe_media(dest)
            record["width"] = meta.get("width")
            record["height"] = meta.get("height")
            record["status"] = "NEEDS_SELECTION"
            record["notes"] = "fetched by --fetch-external; run --prepare"
            fetched += 1
            print(f"FETCH {record['id']}")
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR {record['id']}: fetch failed: {exc}")
    payload["generatedAt"] = utc_now()
    write_json(video_paths(video_dir)["prepared"], payload)
    print(f"OK    fetched={fetched}")
    return 0


def candidate_entries(record: dict) -> list[dict[str, Any]]:
    """Stable C1..Cn labels sorted by stored candidate path/url."""
    raw = [str(c) for c in (record.get("candidates") or []) if c]
    ordered = sorted(raw)
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(ordered, start=1):
        path = ROOT / item if not Path(item).is_absolute() else Path(item)
        hint = Path(item).name
        if item.startswith("http://") or item.startswith("https://"):
            hint = urlparse(item).netloc or hint
        width = height = None
        if path.exists() and path.is_file() and Image is not None:
            try:
                with Image.open(path) as img:
                    width, height = img.size
            except OSError:
                pass
        entries.append(
            {
                "label": f"C{index}",
                "path": item,
                "resolved": path if path.exists() else None,
                "hint": hint,
                "width": width,
                "height": height,
            }
        )
    return entries


def review_board_assets(payload: dict) -> list[dict]:
    assets: list[dict] = []
    for record in payload.get("assets") or []:
        if record.get("status") != "NEEDS_SELECTION":
            continue
        entries = candidate_entries(record)
        if entries or record.get("discovery"):
            assets.append(record)
    return assets


def _thumb_preserve(path: Path, max_size: tuple[int, int]) -> Image.Image | None:
    if Image is None:
        return None
    try:
        with Image.open(path) as img:
            im = img.convert("RGBA")
            im.thumbnail(max_size, Image.Resampling.LANCZOS)
            return im
    except OSError:
        return None


def build_candidate_review_boards(video_dir: Path) -> list[Path]:
    if Image is None:
        raise RuntimeError("Pillow is required for --candidate-review")
    prep = load_asset_prep(video_dir)
    dirs = ensure_local_dirs(video_dir, prep)
    payload = load_prepared(video_dir)
    assets = review_board_assets(payload)
    if not assets:
        raise RuntimeError("no NEEDS_SELECTION assets with candidates/metadata to review")

    page_w = 1400
    max_page_h = 9000
    margin = 24
    thumb_max = (280, 200)
    section_gap = 28
    try:
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None

    pages: list[Image.Image] = []
    canvas = Image.new("RGB", (page_w, max_page_h), (16, 18, 22))
    draw = ImageDraw.Draw(canvas)
    y = margin

    def flush_page() -> None:
        nonlocal canvas, draw, y
        cropped = canvas.crop((0, 0, page_w, max(y + margin, margin + 100)))
        pages.append(cropped)
        canvas = Image.new("RGB", (page_w, max_page_h), (16, 18, 22))
        draw = ImageDraw.Draw(canvas)
        y = margin

    for record in assets:
        entries = candidate_entries(record)
        selection = record.get("selectionNotes") or record.get("selection") or ""
        header_lines = [record["id"]]
        if selection:
            header_lines.append(f"selection: {selection}")
        header_h = 22 * len(header_lines) + 8
        cols = 4
        cell_w = (page_w - 2 * margin) // cols
        cell_h = thumb_max[1] + 48
        rows_needed = max(1, (len(entries) + cols - 1) // cols) if entries else 1
        section_h = header_h + rows_needed * cell_h + section_gap
        if y + section_h > max_page_h - margin and y > margin:
            flush_page()

        for line in header_lines:
            draw.text((margin, y), line[:110], fill=(245, 245, 245), font=font)
            y += 22
        y += 8

        if not entries:
            meta = record.get("discovery") or {}
            card = Image.new("RGB", (page_w - 2 * margin, 90), (36, 40, 48))
            card_draw = ImageDraw.Draw(card)
            card_draw.text(
                (12, 12),
                f"metadata only: {meta.get('type') or 'unknown'}",
                fill=(220, 220, 220),
                font=font,
            )
            raw = str(meta.get("raw") or record.get("notes") or "")[:120]
            card_draw.text((12, 40), raw, fill=(180, 180, 180), font=font)
            canvas.paste(card, (margin, y))
            y += 90 + section_gap
            continue

        for index, entry in enumerate(entries):
            col = index % cols
            row = index // cols
            x = margin + col * cell_w
            cy = y + row * cell_h
            label = entry["label"]
            draw.rectangle(
                [x, cy, x + cell_w - 8, cy + cell_h - 8],
                outline=(70, 74, 84),
                width=1,
            )
            draw.text((x + 8, cy + 6), label, fill=(255, 210, 80), font=font)
            thumb = None
            if entry["resolved"] is not None:
                thumb = _thumb_preserve(entry["resolved"], thumb_max)
            if thumb is not None:
                tx = x + 8 + (cell_w - 16 - thumb.width) // 2
                ty = cy + 24
                canvas.paste(thumb.convert("RGB"), (tx, ty), thumb if thumb.mode == "RGBA" else None)
            else:
                draw.text((x + 8, cy + 40), "no image thumb", fill=(160, 160, 160), font=font)
            dims = ""
            if entry["width"] and entry["height"]:
                dims = f"{entry['width']}x{entry['height']}"
            footer = f"{dims}  {entry['hint']}".strip()
            draw.text((x + 8, cy + cell_h - 28), footer[:40], fill=(170, 170, 170), font=font)
        y += rows_needed * cell_h + section_gap

    flush_page()

    out_paths: list[Path] = []
    if len(pages) == 1:
        out = dirs["previews"] / "asset-candidate-review.png"
        pages[0].save(out, format="PNG")
        out_paths.append(out)
    else:
        for index, page in enumerate(pages, start=1):
            out = dirs["previews"] / f"asset-candidate-review-{index:02d}.png"
            page.save(out, format="PNG")
            out_paths.append(out)
    return out_paths


def cmd_candidate_review(video_dir: Path) -> int:
    try:
        paths = build_candidate_review_boards(video_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR {exc}")
        return 1
    for path in paths:
        print(f"OK    candidate-review {path}")
    return 0


def parse_select_candidate(spec: str) -> tuple[str, str]:
    if "=" not in spec:
        raise ValueError("expected --select-candidate assetId=C#")
    asset_id, label = spec.split("=", 1)
    asset_id = asset_id.strip()
    label = label.strip().upper()
    if not asset_id or not label.startswith("C"):
        raise ValueError("expected --select-candidate assetId=C#")
    return asset_id, label


def select_candidate(video_dir: Path, spec: str) -> int:
    asset_id, label = parse_select_candidate(spec)
    prep = load_asset_prep(video_dir)
    dirs = ensure_local_dirs(video_dir, prep)
    payload = load_prepared(video_dir)
    by_id = prepared_by_id(payload)
    record = by_id.get(asset_id)
    if record is None:
        print(f"ERROR unknown asset `{asset_id}`")
        return 1
    if record.get("status") != "NEEDS_SELECTION":
        print(f"ERROR {asset_id}: status is {record.get('status')}, expected NEEDS_SELECTION")
        return 1
    entries = {e["label"]: e for e in candidate_entries(record)}
    entry = entries.get(label)
    if entry is None:
        print(
            f"ERROR {asset_id}: unknown candidate `{label}`; "
            f"valid={','.join(sorted(entries))}"
        )
        return 1
    src_path = entry["resolved"]
    if src_path is None or not src_path.exists():
        print(f"ERROR {asset_id}: candidate file missing for {label}: {entry['path']}")
        return 1

    # Enforce local-assets boundary
    local = dirs["root"].resolve()
    try:
        src_path.resolve().relative_to(local)
    except ValueError:
        print(f"ERROR {asset_id}: candidate is outside .local-assets/: {src_path}")
        return 1

    digest = sha256_file(src_path)
    ext = src_path.suffix.lower() or ".bin"
    dest = dirs["source"] / f"{asset_id}{ext}"
    if dest.exists():
        existing = sha256_file(dest)
        if existing != digest:
            print(
                f"ERROR {asset_id}: selected candidate differs from existing source "
                f"({existing[:12]}… vs {digest[:12]}…); refusing silent overwrite"
            )
            return 1
    else:
        shutil.copy2(src_path, dest)

    record["sourcePath"] = rel_to_repo(dest)
    record["sourceSha256"] = digest
    record["selectedCandidate"] = label
    record["selectedCandidatePath"] = entry["path"]
    record["candidateProvenance"] = {
        "label": label,
        "path": entry["path"],
        "sourceUrl": record.get("sourceUrl"),
    }
    meta = probe_media(dest)
    record["width"] = meta.get("width")
    record["height"] = meta.get("height")
    record["durationMs"] = meta.get("durationMs")

    is_video = record.get("type") == "VIDEO" or ext in {".mp4", ".mov", ".mkv", ".webm"}
    if is_video:
        if record.get("clipStartMs") is None or record.get("clipEndMs") is None:
            record["status"] = "NEEDS_SELECTION"
            record["notes"] = (
                f"candidate {label} selected as source; "
                "clipStartMs/clipEndMs still required (do not invent timestamps)"
            )
        else:
            prepare_video(record, dirs, prep)
    else:
        prepare_image(record, dirs, prep)

    # Rewrite assets list preserving order
    for index, item in enumerate(payload.get("assets") or []):
        if item.get("id") == asset_id:
            payload["assets"][index] = record
            break
    payload["generatedAt"] = utc_now()
    write_json(video_paths(video_dir)["prepared"], payload)
    print(f"OK    selected {asset_id}={label} status={record.get('status')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to a video folder")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--fetch-external", action="store_true")
    parser.add_argument("--candidate-review", action="store_true")
    parser.add_argument(
        "--select-candidate",
        type=str,
        default=None,
        help="Explicit selection like assetId=C3 (not auto-run)",
    )
    args = parser.parse_args()
    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()

    flags = [
        args.plan,
        args.status,
        args.discover,
        args.ingest,
        args.prepare,
        args.fetch_external,
        args.candidate_review,
        bool(args.select_candidate),
    ]
    if sum(bool(x) for x in flags) != 1:
        parser.error(
            "specify exactly one of --plan --status --discover --ingest --prepare "
            "--fetch-external --candidate-review --select-candidate"
        )

    if args.plan:
        return cmd_plan(video_dir)
    if args.status:
        return cmd_status(video_dir)
    if args.discover:
        return cmd_discover(video_dir)
    if args.ingest:
        return cmd_ingest(video_dir)
    if args.prepare:
        return cmd_prepare(video_dir)
    if args.candidate_review:
        return cmd_candidate_review(video_dir)
    if args.select_candidate:
        return select_candidate(video_dir, args.select_candidate)
    return cmd_fetch_external(video_dir)


if __name__ == "__main__":
    sys.exit(main())
