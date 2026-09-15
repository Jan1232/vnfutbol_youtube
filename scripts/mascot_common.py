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
IDENTITY_MASKS_PATH = MASCOT / "identity-masks.json"
IDENTITY_MASKS_DIR = MASCOT / "identity-masks"
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
LOCAL_MASCOT_WORK = ROOT / ".local-assets" / "channel" / "mascot" / "_work"
LOCAL_MASCOT_NEEDS_REVIEW = ROOT / ".local-assets" / "channel" / "mascot" / "_needs_review"
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


def load_identity_masks() -> dict:
    if not IDENTITY_MASKS_PATH.exists():
        return {"version": 1, "masks": []}
    return load_json(IDENTITY_MASKS_PATH)


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
    """Deprecated committed path — official third-party refs must not live here."""
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


def tracked_outfit_reference(outfit_id: str) -> dict:
    """Tracked official reference metadata (committed). Bytes stay under .local-assets."""
    detail = load_outfit_detail(outfit_id)
    ref = detail.get("reference")
    if isinstance(ref, dict):
        return {
            "sourceUrl": ref.get("sourceUrl") or detail.get("referenceSourceUrl"),
            "sha256": ref.get("sha256"),
        }
    return {
        "sourceUrl": detail.get("referenceSourceUrl"),
        "sha256": detail.get("referenceSha256"),
    }


def expected_reference_sha256(outfit: dict | None) -> str | None:
    if not outfit:
        return None
    outfit_id = outfit.get("id") if isinstance(outfit, dict) else None
    if not outfit_id:
        return None
    sha = tracked_outfit_reference(outfit_id).get("sha256")
    if isinstance(sha, str) and sha.strip():
        return sha.strip()
    return None


def update_tracked_outfit_reference(
    outfit_id: str,
    *,
    source_url: str | None,
    sha256: str | None,
) -> dict:
    """Persist expected reference SHA into committed outfit detail metadata."""
    path = outfit_detail_path(outfit_id)
    detail = load_json(path) if path.exists() else {"id": outfit_id}
    existing = detail.get("reference") if isinstance(detail.get("reference"), dict) else {}
    source = source_url or existing.get("sourceUrl") or detail.get("referenceSourceUrl")
    detail["reference"] = {
        "sourceUrl": source,
        "sha256": sha256 if sha256 else None,
    }
    detail["id"] = outfit_id
    write_json(path, detail)
    return detail["reference"]


def find_official_outfit_reference(outfit_id: str) -> Path | None:
    """Official kit reference under .local-assets only (never channel-assets)."""
    candidates = [
        OUTFIT_REF_CHANNEL_LOCAL / outfit_id / "reference.png",
        outfit_reference_path(outfit_id),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def verify_local_outfit_reference(outfit_id: str) -> dict:
    """Validate local reference bytes against tracked expected SHA.

    Returns keys: path, sha256, error (None | 'missing' | 'mismatch').
    """
    expected = expected_reference_sha256({"id": outfit_id})
    path = find_official_outfit_reference(outfit_id)
    if path is None:
        return {"path": None, "sha256": expected, "error": "missing"}
    actual = sha256_file(path)
    if expected and actual != expected:
        return {"path": path, "sha256": expected, "actualSha256": actual, "error": "mismatch"}
    return {"path": path, "sha256": expected or actual, "error": None}


def find_outfit_reference_image(outfit_id: str) -> Path | None:
    """Resolve official outfit reference used as Image 2 for generation."""
    return find_official_outfit_reference(outfit_id)


def current_outfit_reference_sha(outfit: dict | None) -> str | None:
    """Preferred reference SHA for cache/staleness: tracked expected, else local."""
    if not outfit:
        return None
    expected = expected_reference_sha256(outfit)
    if expected:
        return expected
    path = find_official_outfit_reference(outfit["id"])
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


def identity_mask_by_pose(pose_id: str) -> dict | None:
    for mask in load_identity_masks().get("masks", []):
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
    stable = dict(detail)
    # reference.sha256 is tracked separately for cache/reuse invalidation.
    if isinstance(stable.get("reference"), dict):
        ref = dict(stable["reference"])
        ref.pop("sha256", None)
        stable["reference"] = ref
    stable.pop("referenceSha256", None)
    return sha256_json(stable)


def outfit_fingerprint(
    outfit_id: str,
    *,
    model: str | None = None,
    reference_path: Path | None = None,
    generation_reference_sha256: str | None = None,
    consistency_reference_sha256: str | None = None,
) -> str:
    detail = load_outfit_detail(outfit_id)
    ref_sha = generation_reference_sha256
    if ref_sha is None:
        ref_sha = current_outfit_reference_sha({"id": outfit_id})
        if ref_sha is None and reference_path and reference_path.exists():
            ref_sha = sha256_file(reference_path)
        ref_sha = ref_sha or ""
    payload = {
        "outfit": detail,
        "referenceSha256": ref_sha,
        "generationReferenceSha256": ref_sha,
        "consistencyReferenceSha256": consistency_reference_sha256 or "",
        "model": model or image_model(),
        "promptVersion": PROMPT_VERSION,
    }
    return sha256_json(payload)


def variant_cache_key(
    pose: dict,
    mask: dict | None,
    outfit_id: str,
    *,
    generation_reference_sha256: str | None = None,
    consistency_reference_sha256: str | None = None,
) -> str:
    ref_sha = (
        generation_reference_sha256
        if generation_reference_sha256 is not None
        else current_outfit_reference_sha({"id": outfit_id})
    )
    return sha256_json(
        {
            "basePoseSha256": pose.get("sha256"),
            "maskSha256": mask.get("sha256") if mask else None,
            "outfitFingerprint": outfit_fingerprint(
                outfit_id,
                generation_reference_sha256=ref_sha,
                consistency_reference_sha256=consistency_reference_sha256,
            ),
            "generationReferenceSha256": ref_sha,
            "referenceSha256": ref_sha,
            "consistencyReferenceSha256": consistency_reference_sha256,
        }
    )


def pose_path(pose: dict) -> Path:
    return MASCOT / pose["file"]


def mask_path(mask: dict) -> Path:
    return MASCOT / mask["file"]


def identity_mask_path(mask: dict) -> Path:
    return MASCOT / mask["file"]


def variant_path(variant: dict) -> Path:
    return MASCOT / variant["file"]


def variant_id(pose_id: str, outfit_id: str) -> str:
    return f"{pose_id}__{outfit_id}"


def layer_destination(outfit: dict, pose_id: str) -> Path:
    return VARIANTS_DIR / outfit["id"] / "layers" / f"{pose_id}.png"


def composite_destination(outfit: dict, pose_id: str) -> Path:
    return VARIANTS_DIR / outfit["id"] / f"{pose_id}.png"


def extract_outfit_layer(
    full_edit,
    binary_mask,
    *,
    feather: int = 2,
):
    """Reusable clothing layer: RGB from full-edit, alpha = approved mask coverage.

    Feather (1-2px) only softens the mask boundary; interior RGB is never mixed
    with the original jersey.
    """
    from PIL import Image, ImageFilter

    hard = binary_mask.convert("L")
    soft = hard.filter(ImageFilter.GaussianBlur(radius=feather)) if feather else hard
    edited = full_edit.convert("RGBA")
    if edited.size != hard.size:
        raise ValueError(f"full-edit size {edited.size} != mask {hard.size}")
    layer = Image.new("RGBA", hard.size, (0, 0, 0, 0))
    epx = edited.load()
    hpx = hard.load()
    spx = soft.load()
    lpx = layer.load()
    kept = 0
    width, height = hard.size
    for y in range(height):
        for x in range(width):
            hard_v = hpx[x, y]
            if hard_v <= 0:
                continue
            # Mask coverage only (do not let translucent edit alpha thin interior).
            coverage = min(hard_v, spx[x, y])
            if coverage <= 0:
                continue
            r, g, b, _a = epx[x, y]
            lpx[x, y] = (r, g, b, coverage)
            kept += 1
    if kept == 0:
        raise ValueError("extracted outfit layer is empty")
    return layer


def compose_masked_replacement(base, layer):
    """Legacy clothing-layer composite. Prefer compose_identity_locked_final for production."""
    from PIL import Image

    base_rgba = base.convert("RGBA")
    layer_rgba = layer.convert("RGBA")
    if layer_rgba.size != base_rgba.size:
        raise ValueError(f"layer size {layer_rgba.size} != pose {base_rgba.size}")
    out = base_rgba.copy()
    bpx = base_rgba.load()
    lpx = layer_rgba.load()
    opx = out.load()
    width, height = base_rgba.size
    for y in range(height):
        for x in range(width):
            lr, lg, lb, la = lpx[x, y]
            if la <= 0:
                continue
            br, bg, bb, ba = bpx[x, y]
            if la >= 255:
                opx[x, y] = (lr, lg, lb, 255 if ba else 255)
            else:
                t = la / 255.0
                inv = 1.0 - t
                opx[x, y] = (
                    int(lr * t + br * inv + 0.5),
                    int(lg * t + bg * inv + 0.5),
                    int(lb * t + bb * inv + 0.5),
                    int(255 * t + ba * inv + 0.5),
                )
    return out


def compose_identity_locked_final(base, full_edit, identity_mask, *, feather: int = 1):
    """Production final: full-edit owns clothing geometry; paste base only in identity zones.

    Identity mask white = immutable (head/eyes/hands/fingers/exposed skin/props).
    Clothing / garment boundaries stay from the full-edit.
    """
    from PIL import Image, ImageFilter

    base_rgba = base.convert("RGBA")
    edit = full_edit.convert("RGBA")
    hard = identity_mask.convert("L")
    if edit.size != base_rgba.size or hard.size != base_rgba.size:
        raise ValueError("base, full-edit and identity mask sizes must match")
    soft = hard.filter(ImageFilter.GaussianBlur(radius=feather)) if feather else hard
    out = edit.copy()
    bpx = base_rgba.load()
    epx = edit.load()
    hpx = hard.load()
    spx = soft.load()
    opx = out.load()
    width, height = base_rgba.size
    for y in range(height):
        for x in range(width):
            hard_v = hpx[x, y]
            soft_v = spx[x, y]
            if hard_v <= 0 and soft_v <= 0:
                continue
            br, bg, bb, ba = bpx[x, y]
            er, eg, eb, ea = epx[x, y]
            coverage = max(hard_v, soft_v) if hard_v > 0 else soft_v
            if coverage >= 255:
                opx[x, y] = (br, bg, bb, ba)
            elif coverage > 0:
                t = coverage / 255.0  # how much original identity to restore
                inv = 1.0 - t
                opx[x, y] = (
                    int(br * t + er * inv + 0.5),
                    int(bg * t + eg * inv + 0.5),
                    int(bb * t + eb * inv + 0.5),
                    int(ba * t + ea * inv + 0.5),
                )
    return out


def full_edit_destination(outfit: dict, pose_id: str) -> Path:
    return VARIANTS_DIR / outfit["id"] / "full-edits" / f"{pose_id}.png"


def compose_from_full_edit(base, full_edit, binary_mask, *, feather: int = 2):
    layer = extract_outfit_layer(full_edit, binary_mask, feather=feather)
    return layer, compose_masked_replacement(base, layer)


def recompute_composite_sha256(pose: dict, layer_file: Path) -> str:
    from PIL import Image
    import io

    base = Image.open(pose_path(pose)).convert("RGBA")
    layer = Image.open(layer_file).convert("RGBA")
    if layer.size != base.size:
        raise ValueError(f"layer size {layer.size} != pose {base.size}")
    composed = compose_masked_replacement(base, layer)
    buf = io.BytesIO()
    composed.save(buf, format="PNG")
    return sha256_bytes(buf.getvalue())


def hashes_current(
    pose: dict,
    mask: dict | None,
    outfit: dict,
    *,
    generation_reference_sha256: str | None = None,
    consistency_reference_sha256: str | None = None,
) -> dict:
    ref_sha = (
        generation_reference_sha256
        if generation_reference_sha256 is not None
        else current_outfit_reference_sha(outfit)
    )
    return {
        "basePoseSha256": pose.get("sha256"),
        "maskSha256": mask.get("sha256") if mask else None,
        "outfitSpecSha256": outfit_spec_sha256(outfit),
        "outfitFingerprint": outfit_fingerprint(
            outfit["id"],
            generation_reference_sha256=ref_sha,
            consistency_reference_sha256=consistency_reference_sha256,
        ),
        "generationReferenceSha256": ref_sha,
        "referenceSha256": ref_sha,
        "consistencyReferenceSha256": consistency_reference_sha256,
    }


def variant_core_stale(variant: dict, pose: dict, mask: dict | None, outfit: dict) -> bool:
    """Pose/mask/reference staleness without preferred-consistency lookup (no recursion)."""
    expected_ref = current_outfit_reference_sha(outfit)
    stored_ref = variant.get("referenceSha256") or variant.get("generationReferenceSha256")
    if stored_ref != expected_ref:
        if expected_ref is not None or stored_ref:
            return True
    stored_consistency = variant.get("consistencyReferenceSha256")
    expected_fp = outfit_fingerprint(
        outfit["id"],
        generation_reference_sha256=expected_ref,
        consistency_reference_sha256=stored_consistency,
    )
    if variant.get("basePoseSha256") != pose.get("sha256"):
        return True
    if (mask.get("sha256") if mask else None) != variant.get("maskSha256"):
        return True
    if variant.get("outfitFingerprint"):
        return variant.get("outfitFingerprint") != expected_fp
    return variant.get("outfitSpecSha256") != outfit_spec_sha256(outfit)


def variant_files_integrity(variant: dict, pose: dict) -> bool:
    layer_rel = variant.get("file")
    if not layer_rel:
        return False
    layer_file = MASCOT / layer_rel
    if not layer_file.exists():
        return False
    expected_sha = variant.get("sha256")
    if expected_sha and sha256_file(layer_file) != expected_sha:
        return False
    composite_rel = variant.get("compositeFile")
    if not composite_rel:
        return False
    composite_file = MASCOT / composite_rel
    if not composite_file.exists():
        return False
    try:
        recomputed = recompute_composite_sha256(pose, layer_file)
    except Exception:  # noqa: BLE001
        return False
    if sha256_file(composite_file) != recomputed:
        return False
    stored_comp = variant.get("compositeSha256")
    if stored_comp and stored_comp != recomputed:
        return False
    return True


def find_same_outfit_mascot_composite(
    outfit_id: str,
    *,
    exclude_pose: str | None = None,
) -> dict | None:
    """Deterministic consistency anchor: reusable same-outfit composite + sha256."""
    outfit = outfit_by_id(outfit_id)
    if outfit is None:
        return None
    candidates: list[tuple[str, dict, Path]] = []
    for variant in load_variants().get("variants", []):
        if variant.get("outfit") != outfit_id:
            continue
        if exclude_pose and variant.get("basePose") == exclude_pose:
            continue
        if variant.get("status") not in REUSABLE_VARIANT_STATUSES:
            continue
        pose = pose_by_id(variant.get("basePose") or "")
        mask = mask_by_pose(variant.get("basePose") or "")
        if pose is None or mask is None:
            continue
        if variant_core_stale(variant, pose, mask, outfit):
            continue
        if not variant_files_integrity(variant, pose):
            continue
        composite_rel = variant.get("compositeFile")
        path = MASCOT / composite_rel
        vid = variant.get("id") or variant_id(variant.get("basePose"), outfit_id)
        candidates.append((vid, variant, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    vid, variant, path = candidates[0]
    return {
        "variantId": vid,
        "path": path,
        "sha256": variant.get("compositeSha256") or sha256_file(path),
    }


def variant_is_stale(variant: dict, pose: dict, mask: dict | None, outfit: dict) -> bool:
    if variant_core_stale(variant, pose, mask, outfit):
        return True
    stored_consistency = variant.get("consistencyReferenceSha256")
    if stored_consistency:
        anchor = find_same_outfit_mascot_composite(outfit["id"], exclude_pose=pose.get("id"))
        current_consistency = anchor.get("sha256") if anchor else None
        if stored_consistency != current_consistency:
            return True
    return False


def variant_is_reusable(variant: dict | None, pose: dict, mask: dict | None, outfit: dict) -> bool:
    if variant is None:
        return False
    if variant.get("status") not in REUSABLE_VARIANT_STATUSES:
        return False
    if variant_is_stale(variant, pose, mask, outfit):
        return False
    return variant_files_integrity(variant, pose)


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
