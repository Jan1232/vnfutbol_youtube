"""Shared helpers for the mascot outfit pipeline."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASCOT = ROOT / "channel-assets" / "mascot"
POSES_PATH = MASCOT / "poses.json"
OUTFITS_PATH = MASCOT / "outfits.json"
OUTFITS_DIR = MASCOT / "outfits"
MASKS_PATH = MASCOT / "pose-masks.json"
VARIANTS_PATH = MASCOT / "variants.json"
VARIANTS_DIR = MASCOT / "variants"

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
VARIANT_STATUSES = {
    "generated",
    "needs-review",
    "approved",
    "approved-auto",
    "rejected",
    "stale",
}
REUSABLE_VARIANT_STATUSES = {"approved", "approved-auto"}
DEFAULT_OUTFIT = "default-home"
FORMAL_OUTFIT = "suit-navy"
OUTFIT_REF_ROOT = ROOT / ".local-assets" / "shared" / "mascot-outfit-references"
OUTFIT_REF_CHANNEL_LOCAL = ROOT / ".local-assets" / "channel" / "mascot" / "outfit-references"
OUTFIT_REF_RIGHTS = "official visual reference; do not commit third-party image"
POLICY_MATCH_REFERENCE = "match-reference"
POLICY_OMIT = "omit"
PROMPT_VERSION = "mascot-outfit-auto-v1"
DEFAULT_IMAGE_MODEL = "gpt-image-2.5-sunburst-2026-09-08"
DEFAULT_IMAGE_QUALITY = "high"
DEFAULT_VISION_QA_MODEL = "gpt-5.6-luna"
DEFAULT_MAX_ATTEMPTS = 3


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


def load_dotenv_file() -> None:
    """Load KEY=VALUE pairs from repo .env without printing secrets."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def openai_api_key() -> str | None:
    load_dotenv_file()
    key = os.environ.get("OPENAI_API_KEY")
    if key and key.strip():
        return key.strip()
    return None


def image_model() -> str:
    load_dotenv_file()
    return os.environ.get("OPENAI_IMAGE_MODEL", DEFAULT_IMAGE_MODEL).strip() or DEFAULT_IMAGE_MODEL


def image_quality() -> str:
    load_dotenv_file()
    return (
        os.environ.get("OPENAI_IMAGE_QUALITY", DEFAULT_IMAGE_QUALITY).strip()
        or DEFAULT_IMAGE_QUALITY
    )


def vision_qa_model() -> str:
    load_dotenv_file()
    return (
        os.environ.get("OPENAI_VISION_QA_MODEL", DEFAULT_VISION_QA_MODEL).strip()
        or DEFAULT_VISION_QA_MODEL
    )


def max_generation_attempts() -> int:
    load_dotenv_file()
    raw = os.environ.get("MAX_GENERATION_ATTEMPTS", str(DEFAULT_MAX_ATTEMPTS))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS
    return max(1, value)


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


def outfit_detail_path(outfit_id: str) -> Path:
    return OUTFITS_DIR / outfit_id / "outfit.json"


def load_outfit_detail(outfit_id: str) -> dict:
    """Merge catalog row with per-outfit generation detail when present."""
    catalog = outfit_by_id(outfit_id) or {"id": outfit_id}
    detail_path = outfit_detail_path(outfit_id)
    detail = load_json(detail_path) if detail_path.exists() else {}
    merged = dict(catalog)
    merged.update(detail)
    merged["id"] = outfit_id
    return merged


def channel_outfit_reference_path(outfit_id: str) -> Path:
    return OUTFITS_DIR / outfit_id / "reference.png"


def outfit_reference_dir(outfit_id: str) -> Path:
    return OUTFIT_REF_ROOT / outfit_id


def outfit_reference_path(outfit_id: str) -> Path:
    """Preferred local writable path used by import_outfit_reference."""
    return outfit_reference_dir(outfit_id) / "reference.png"


def outfit_reference_meta_path(outfit_id: str) -> Path:
    return outfit_reference_dir(outfit_id) / "meta.json"


def outfit_requires_reference(outfit: dict | None) -> bool:
    if not outfit:
        return False
    detail = load_outfit_detail(outfit["id"]) if outfit.get("id") else outfit
    return bool(detail.get("referenceRequired", outfit.get("referenceRequired")))


def find_official_outfit_reference(outfit_id: str) -> Path | None:
    """Stable official kit reference only (used for fingerprints)."""
    candidates = [
        channel_outfit_reference_path(outfit_id),
        OUTFIT_REF_CHANNEL_LOCAL / outfit_id / "reference.png",
        outfit_reference_path(outfit_id),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def find_outfit_reference_image(outfit_id: str) -> Path | None:
    """Resolve Image C for generation. Prefer approved mascot composite, then official ref."""
    for variant in load_variants().get("variants", []):
        if variant.get("outfit") != outfit_id:
            continue
        if variant.get("status") not in REUSABLE_VARIANT_STATUSES:
            continue
        composite = variant.get("compositeFile")
        if composite:
            path = MASCOT / composite
            if path.exists():
                return path
        composed = VARIANTS_DIR / outfit_id / f"{variant.get('basePose')}.png"
        if composed.exists():
            return composed
    return find_official_outfit_reference(outfit_id)


def current_outfit_reference_sha(outfit: dict | None) -> str | None:
    if not outfit:
        return None
    path = find_official_outfit_reference(outfit["id"])
    if path is None:
        # Fall back to whatever generation would use, but prefer official.
        path = find_outfit_reference_image(outfit["id"])
    if path is None:
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
    detail = load_outfit_detail(outfit["id"]) if outfit.get("id") else outfit
    return sha256_json(detail)


def outfit_fingerprint(
    outfit_id: str,
    *,
    model: str | None = None,
    reference_path: Path | None = None,
) -> str:
    detail = load_outfit_detail(outfit_id)
    ref = reference_path or find_official_outfit_reference(outfit_id)
    ref_sha = sha256_file(ref) if ref and ref.exists() else ""
    payload = {
        "outfit": detail,
        "referenceSha256": ref_sha,
        "model": model or image_model(),
        "promptVersion": PROMPT_VERSION,
    }
    return sha256_json(payload)


def variant_cache_key(pose: dict, mask: dict | None, outfit_id: str) -> str:
    return sha256_json(
        {
            "basePoseSha256": pose.get("sha256"),
            "maskSha256": mask.get("sha256") if mask else None,
            "outfitFingerprint": outfit_fingerprint(outfit_id),
        }
    )


def pose_path(pose: dict) -> Path:
    return MASCOT / pose["file"]


def mask_path(mask: dict) -> Path:
    return MASCOT / mask["file"]


def variant_path(variant: dict) -> Path:
    return MASCOT / variant["file"]


def variant_id(pose_id: str, outfit_id: str) -> str:
    return f"{pose_id}__{outfit_id}"


def layer_destination(outfit: dict, pose_id: str) -> Path:
    return VARIANTS_DIR / outfit["id"] / "layers" / f"{pose_id}.png"


def composite_destination(outfit: dict, pose_id: str) -> Path:
    return VARIANTS_DIR / outfit["id"] / f"{pose_id}.png"


def hashes_current(pose: dict, mask: dict | None, outfit: dict) -> dict:
    return {
        "basePoseSha256": pose.get("sha256"),
        "maskSha256": mask.get("sha256") if mask else None,
        "outfitSpecSha256": outfit_spec_sha256(outfit),
        "outfitFingerprint": outfit_fingerprint(outfit["id"]),
    }


def variant_is_stale(variant: dict, pose: dict, mask: dict | None, outfit: dict) -> bool:
    current = hashes_current(pose, mask, outfit)
    if variant.get("basePoseSha256") != current["basePoseSha256"]:
        return True
    if variant.get("maskSha256") != current["maskSha256"]:
        return True
    # Prefer fingerprint when present; fall back to outfitSpecSha256 for legacy rows.
    if variant.get("outfitFingerprint"):
        return variant.get("outfitFingerprint") != current["outfitFingerprint"]
    return variant.get("outfitSpecSha256") != current["outfitSpecSha256"]


def variant_is_reusable(variant: dict | None, pose: dict, mask: dict | None, outfit: dict) -> bool:
    if variant is None:
        return False
    if variant.get("status") not in REUSABLE_VARIANT_STATUSES:
        return False
    return not variant_is_stale(variant, pose, mask, outfit)


def entities_by_id(video_dir: Path) -> dict[str, dict]:
    path = video_dir / "context" / "entities.json"
    if not path.exists():
        return {}
    data = load_json(path)
    return {item["id"]: item for item in data.get("entities", []) if "id" in item}


def load_visual_style(video_dir: Path) -> dict:
    path = video_dir / "context" / "visual-style.json"
    if not path.exists():
        return {}
    return load_json(path)


def resolve_mascot_outfit(
    intent: str,
    mascot: dict,
    entity: dict | None = None,
    visual_style: dict | None = None,
) -> str:
    """Deterministic outfit resolver. No natural-language analysis."""
    if intent == "explicit":
        outfit = mascot.get("outfit") or mascot.get("explicitOutfit")
        if not outfit:
            raise ValueError("explicit outfit is required for outfitIntent=explicit")
        return outfit

    style = ((visual_style or {}).get("mascotOutfits")) or {}
    style_map = {
        "current-club": style.get("currentClub"),
        "national-team": style.get("nationalTeam"),
        "formal": style.get("formal"),
        "default": style.get("default"),
    }
    if style_map.get(intent):
        return style_map[intent]

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


# Backwards-compatible alias used by older scripts.
def resolve_outfit(intent: str, mascot: dict, entity: dict | None) -> str:
    return resolve_mascot_outfit(intent, mascot, entity, visual_style=None)
