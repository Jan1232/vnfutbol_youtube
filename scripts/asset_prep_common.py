#!/usr/bin/env python3
"""Shared helpers for asset prep / timeline gate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

PREP_STATUSES = {
    "READY",
    "READY_RENDER_SPEC",
    "READY_MASCOT",
    "NEEDS_SELECTION",
    "NEEDS_SOURCE_FILE",
    "MISSING",
    "BLOCKED",
    "BLOCKED_GENERATION",
    "NEEDS_REVIEW",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def video_paths(video_dir: Path) -> dict[str, Path]:
    return {
        "root": video_dir,
        "assets": video_dir / "assets" / "assets.json",
        "prep": video_dir / "assets" / "asset-prep.json",
        "prepared": video_dir / "assets" / "prepared-assets.json",
        "queue": video_dir / "assets" / "mascot-generation.json",
        "visual_plan": video_dir / "scenes" / "visual-plan.json",
        "timeline": video_dir / "scenes" / "timeline.json",
        "voice": video_dir / "audio" / "voice.json",
        "entities": video_dir / "context" / "entities.json",
        "metadata": video_dir / "metadata.json",
    }


def load_asset_prep(video_dir: Path) -> dict:
    path = video_paths(video_dir)["prep"]
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    return load_json(path)


def local_root(video_dir: Path, prep: dict | None = None) -> Path:
    prep = prep or load_asset_prep(video_dir)
    rel = (prep.get("paths") or {}).get("localRoot") or f".local-assets/{video_dir.name}"
    path = ROOT / rel if not Path(rel).is_absolute() else Path(rel)
    return path


def ensure_local_dirs(video_dir: Path, prep: dict | None = None) -> dict[str, Path]:
    prep = prep or load_asset_prep(video_dir)
    root = local_root(video_dir, prep)
    dirs = {
        "root": root,
        "inbox": root / "inbox",
        "source": root / "source",
        "candidates": root / "candidates",
        "prepared": root / "prepared",
        "previews": root / "previews",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def assets_by_id(assets_payload: dict) -> dict[str, dict]:
    return {
        item["id"]: item
        for item in assets_payload.get("assets", [])
        if isinstance(item, dict) and item.get("id")
    }


def visual_plan_asset_ids(plan: dict) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for scene in plan.get("scenes") or []:
        for asset_id in scene.get("assetRequests") or []:
            if asset_id and asset_id not in seen:
                seen.add(asset_id)
                ids.append(asset_id)
        mascot = scene.get("mascot") or {}
        mid = mascot.get("assetId")
        if mid and mid not in seen:
            seen.add(mid)
            ids.append(mid)
    return ids


def stable_pick(candidates: list[str], seed: str) -> str:
    if not candidates:
        raise ValueError("no candidates")
    ordered = sorted(candidates)
    digest = sha256_text(seed)
    index = int(digest[:16], 16) % len(ordered)
    return ordered[index]
