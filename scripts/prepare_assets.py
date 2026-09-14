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
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None  # type: ignore
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

    payload = {
        "version": 1,
        "video": video_dir.name,
        "generatedAt": utc_now(),
        "localRoot": rel_to_repo(dirs["root"]),
        "assets": records,
    }
    write_json(paths["prepared"], payload)
    prep["stage"] = "planned"
    write_json(paths["prep"], prep)
    print(f"OK    prepared-assets.json records={len(records)} localRoot={dirs['root']}")
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


def cmd_discover(video_dir: Path) -> int:
    """Best-effort candidate discovery. No auth bypass. Offline-safe failure."""
    prep = load_asset_prep(video_dir)
    dirs = ensure_local_dirs(video_dir, prep)
    payload = load_prepared(video_dir)
    assets_payload = load_json(video_paths(video_dir)["assets"])
    by_asset = assets_by_id(assets_payload)
    discovered = 0
    for record in payload.get("assets") or []:
        if record.get("status") not in {"NEEDS_SOURCE_FILE", "NEEDS_SELECTION"}:
            continue
        asset = by_asset.get(record["id"]) or {}
        url = asset.get("sourceUrl") or record.get("sourceUrl")
        if not url:
            continue
        if "youtube.com" in url or "youtu.be" in url:
            ytdlp = shutil.which("yt-dlp")
            if not ytdlp:
                record["notes"] = "yt-dlp missing; video metadata discovery skipped"
                continue
            try:
                proc = subprocess.run(
                    [ytdlp, "--skip-download", "--print", "%(title)s\t%(duration)s", url],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.returncode == 0:
                    record["notes"] = f"yt-dlp metadata: {proc.stdout.strip()[:200]}"
                    discovered += 1
                else:
                    record["notes"] = f"yt-dlp failed: {proc.stderr.strip()[:200]}"
            except Exception as exc:  # noqa: BLE001
                record["notes"] = f"yt-dlp error: {exc}"
            continue
        # Image pages: do not scrape aggressively; leave NEEDS_SOURCE_FILE
        record.setdefault("candidates", [])
        cand_dir = dirs["candidates"] / record["id"]
        cand_dir.mkdir(parents=True, exist_ok=True)
        record["notes"] = (
            "page discovery is best-effort; place chosen file in inbox/ "
            f"or candidates/{record['id']}/"
        )
    payload["generatedAt"] = utc_now()
    write_json(video_paths(video_dir)["prepared"], payload)
    print(f"OK    discover notes updated; network candidates={discovered}")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to a video folder")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--fetch-external", action="store_true")
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
    ]
    if sum(bool(x) for x in flags) != 1:
        parser.error(
            "specify exactly one of --plan --status --discover --ingest --prepare --fetch-external"
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
    return cmd_fetch_external(video_dir)


if __name__ == "__main__":
    sys.exit(main())
