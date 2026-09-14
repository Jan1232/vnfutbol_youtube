"""Shared helpers for the mascot outfit pipeline. No network, no AI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASCOT = ROOT / "channel-assets" / "mascot"
POSES_PATH = MASCOT / "poses.json"
OUTFITS_PATH = MASCOT / "outfits.json"
MASKS_PATH = MASCOT / "pose-masks.json"
VARIANTS_PATH = MASCOT / "variants.json"

OUTFIT_INTENTS = {
    "auto",
    "current-club",
    "national-team",
    "explicit",
    "formal",
    "default",
}
VARIANT_POLICIES = {"reuse-only", "reuse-else-generate"}
MASK_STATUSES = {"generated", "approved", "rejected"}
VARIANT_STATUSES = {"generated", "needs-review", "approved", "rejected", "stale"}
DEFAULT_OUTFIT = "default-home"
FORMAL_OUTFIT = "suit-navy"
OUTFIT_REF_ROOT = ROOT / ".local-assets" / "shared" / "mascot-outfit-references"
OUTFIT_REF_RIGHTS = "official visual reference; do not commit third-party image"
POLICY_MATCH_REFERENCE = "match-reference"
POLICY_OMIT = "omit"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(payload) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(canonical.encode("utf-8"))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_poses() -> dict:
    return load_json(POSES_PATH)


def load_outfits() -> dict:
    return load_json(OUTFITS_PATH)


def load_masks() -> dict:
    if not MASKS_PATH.exists():
        return {"version": 1, "masks": []}
    return load_json(MASKS_PATH)


def load_variants() -> dict:
    if not VARIANTS_PATH.exists():
        return {"version": 1, "variants": []}
    return load_json(VARIANTS_PATH)


def pose_by_id(pose_id: str) -> dict | None:
    for pose in load_poses().get("poses", []):
        if pose.get("id") == pose_id:
            return pose
    return None


def outfit_by_id(outfit_id: str) -> dict | None:
    for outfit in load_outfits().get("outfits", []):
        if outfit.get("id") == outfit_id:
            return outfit
    return None


def outfit_reference_dir(outfit_id: str) -> Path:
    return OUTFIT_REF_ROOT / outfit_id


def outfit_reference_path(outfit_id: str) -> Path:
    return outfit_reference_dir(outfit_id) / "reference.png"


def outfit_reference_meta_path(outfit_id: str) -> Path:
    return outfit_reference_dir(outfit_id) / "meta.json"


def outfit_requires_reference(outfit: dict | None) -> bool:
    return bool(outfit and outfit.get("referenceRequired"))


def current_outfit_reference_sha(outfit: dict | None) -> str | None:
    if not outfit_requires_reference(outfit):
        return None
    path = outfit_reference_path(outfit["id"])
    if not path.exists():
        return None
    return sha256_file(path)


def load_outfit_reference_meta(outfit_id: str) -> dict | None:
    path = outfit_reference_meta_path(outfit_id)
    if not path.exists():
        return None
    return load_json(path)


def mask_by_pose(pose_id: str) -> dict | None:
    for mask in load_masks().get("masks", []):
        if mask.get("basePose") == pose_id:
            return mask
    return None


def variant_by_pair(pose_id: str, outfit_id: str) -> dict | None:
    for variant in load_variants().get("variants", []):
        if variant.get("basePose") == pose_id and variant.get("outfit") == outfit_id:
            return variant
    return None


def outfit_spec_sha256(outfit: dict) -> str:
    return sha256_json(outfit)


def pose_path(pose: dict) -> Path:
    return MASCOT / pose["file"]


def mask_path(mask: dict) -> Path:
    return MASCOT / mask["file"]


def variant_path(variant: dict) -> Path:
    return MASCOT / variant["file"]


def variant_id(pose_id: str, outfit_id: str) -> str:
    return f"{pose_id}__{outfit_id}"


def layer_destination(outfit: dict, pose_id: str) -> Path:
    slug = outfit.get("slug") or outfit["id"]
    variant = outfit.get("variant") or "home"
    kind = outfit.get("type")
    if kind == "club":
        return MASCOT / "clubs" / slug / variant / f"{pose_id}.png"
    if kind == "national-team":
        return MASCOT / "national-teams" / slug / variant / f"{pose_id}.png"
    if kind == "formal":
        return MASCOT / "formal" / outfit["id"] / f"{pose_id}.png"
    raise ValueError(f"No library destination for outfit type `{kind}`")


def hashes_current(pose: dict, mask: dict | None, outfit: dict) -> dict:
    return {
        "basePoseSha256": pose.get("sha256"),
        "maskSha256": mask.get("sha256") if mask else None,
        "outfitSpecSha256": outfit_spec_sha256(outfit),
    }


def variant_is_stale(variant: dict, pose: dict, mask: dict | None, outfit: dict) -> bool:
    current = hashes_current(pose, mask, outfit)
    return (
        variant.get("basePoseSha256") != current["basePoseSha256"]
        or variant.get("maskSha256") != current["maskSha256"]
        or variant.get("outfitSpecSha256") != current["outfitSpecSha256"]
    )


def entities_by_id(video_dir: Path) -> dict[str, dict]:
    path = video_dir / "context" / "entities.json"
    if not path.exists():
        return {}
    data = load_json(path)
    return {item["id"]: item for item in data.get("entities", []) if "id" in item}


def resolve_outfit(intent: str, mascot: dict, entity: dict | None) -> str:
    if intent == "explicit":
        outfit = mascot.get("explicitOutfit")
        if not outfit:
            raise ValueError("explicitOutfit is required for outfitIntent=explicit")
        return outfit
    if intent == "national-team":
        if not entity or not entity.get("nationalTeam", {}).get("outfit"):
            raise ValueError("entity.nationalTeam.outfit is required")
        return entity["nationalTeam"]["outfit"]
    if intent == "current-club":
        if not entity or not entity.get("currentClub", {}).get("outfit"):
            raise ValueError("entity.currentClub.outfit is required")
        return entity["currentClub"]["outfit"]
    if intent == "formal":
        return FORMAL_OUTFIT
    if intent == "default":
        return DEFAULT_OUTFIT
    if intent == "auto":
        raise ValueError("outfitIntent=auto is unresolved; AI must pick a concrete intent")
    raise ValueError(f"invalid outfitIntent `{intent}`")
