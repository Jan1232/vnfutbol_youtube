#!/usr/bin/env python3
"""Export local provider-agnostic generation packs for pending mascot outfit jobs.

No AI/API calls. Does not alter queue status except freezing outfitReferenceSha256.
Never aliases barcelona-home.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asset_prep_common import ensure_local_dirs, load_asset_prep, load_json, write_json
from build_mascot_outfit_prompt import build_prompt
from mascot_common import (
    DEFAULT_OUTFIT,
    MASCOT,
    hashes_current,
    mask_by_pose,
    mask_path,
    outfit_by_id,
    outfit_reference_path,
    outfit_requires_reference,
    pose_by_id,
    pose_path,
    sha256_file,
    variant_by_pair,
)


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def verify_job_inputs(job: dict) -> tuple[dict, dict, dict]:
    pose = pose_by_id(job["basePose"])
    outfit = outfit_by_id(job["outfit"])
    mask = mask_by_pose(job["basePose"])
    if pose is None:
        raise ValueError(f"{job['id']}: unknown pose `{job['basePose']}`")
    if outfit is None:
        raise ValueError(f"{job['id']}: unknown outfit `{job['outfit']}`")
    if mask is None:
        raise ValueError(f"{job['id']}: missing clothing mask for `{job['basePose']}`")
    if outfit["id"] == DEFAULT_OUTFIT:
        raise ValueError(f"{job['id']}: default-home must not be exported as a generation job")
    if mask.get("status") != "approved":
        raise ValueError(f"{job['id']}: clothing mask is not approved")
    if not pose.get("approved"):
        raise ValueError(f"{job['id']}: base pose is not approved")

    pose_file = pose_path(pose)
    mask_file = mask_path(mask)
    canon = MASCOT / job["canonicalReference"]
    if not pose_file.exists():
        raise ValueError(f"{job['id']}: missing base pose file")
    if not mask_file.exists():
        raise ValueError(f"{job['id']}: missing clothing mask file")
    if not canon.exists():
        raise ValueError(f"{job['id']}: missing canonical reference")

    if sha256_file(pose_file) != pose.get("sha256"):
        raise ValueError(f"{job['id']}: base pose hash mismatch")
    if sha256_file(mask_file) != mask.get("sha256"):
        raise ValueError(f"{job['id']}: clothing mask hash mismatch")
    if mask.get("basePoseSha256") != pose.get("sha256"):
        raise ValueError(f"{job['id']}: clothing mask stale vs pose")

    current = hashes_current(pose, mask, outfit)
    for key in ("basePoseSha256", "maskSha256", "outfitSpecSha256"):
        if job.get(key) != current[key]:
            raise ValueError(f"{job['id']}: frozen {key} no longer matches library")
    return pose, outfit, mask


def resolve_outfit_reference(job: dict, outfit: dict) -> str | None:
    if not outfit_requires_reference(outfit):
        return None
    ref_path = outfit_reference_path(outfit["id"])
    if not ref_path.exists():
        raise ValueError(
            f"{job['id']}: missing local outfit reference for `{outfit['id']}` "
            f"(expected {ref_path}). Import with scripts/import_outfit_reference.py"
        )
    ref_sha = sha256_file(ref_path)
    frozen = job.get("outfitReferenceSha256")
    if frozen and frozen != ref_sha:
        raise ValueError(
            f"{job['id']}: frozen outfitReferenceSha256 no longer matches local reference; "
            "re-run ensure_mascot_variants"
        )
    return ref_sha


def pack_hashes_match(pack_job: dict, job: dict, ref_sha: str | None) -> bool:
    old = pack_job.get("hashes") or {}
    expected = {
        "basePoseSha256": job.get("basePoseSha256"),
        "maskSha256": job.get("maskSha256"),
        "outfitSpecSha256": job.get("outfitSpecSha256"),
        "outfitReferenceSha256": ref_sha,
    }
    for key, value in expected.items():
        if old.get(key) != value:
            return False
    return True


def export_job(video_dir: Path, job: dict, packs_root: Path, *, force: bool = False) -> Path:
    if job.get("outfit") == DEFAULT_OUTFIT:
        raise ValueError(f"{job['id']}: refusing to export default-home as outfit generation")
    # Explicit guard: barcelona-home is a distinct outfit, never skip/alias.
    if job.get("outfit") == "barcelona-home":
        existing = variant_by_pair(job["basePose"], "barcelona-home")
        if existing and existing.get("status") == "approved":
            raise ValueError(
                f"{job['id']}: barcelona-home already has approved variant; "
                "re-run ensure_mascot_variants instead of aliasing to default-home"
            )

    pose, outfit, mask = verify_job_inputs(job)
    ref_sha = resolve_outfit_reference(job, outfit)
    pack_dir = packs_root / job["id"]
    job_meta_path = pack_dir / "job.json"
    if job_meta_path.exists() and not force:
        old_meta = json.loads(job_meta_path.read_text(encoding="utf-8"))
        if not pack_hashes_match(old_meta, job, ref_sha):
            raise ValueError(
                f"{job['id']}: stale generation pack hashes do not match the queue; "
                "re-export with --force to rebuild"
            )

    if pack_dir.exists() and force:
        shutil.rmtree(pack_dir)
    output_dir = pack_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(MASCOT / job["canonicalReference"], pack_dir / "canonical-reference.png")
    shutil.copy2(pose_path(pose), pack_dir / "base-pose.png")
    shutil.copy2(mask_path(mask), pack_dir / "clothing-mask.png")
    if ref_sha is not None:
        shutil.copy2(outfit_reference_path(outfit["id"]), pack_dir / "outfit-reference.png")
    (pack_dir / "prompt.txt").write_text(build_prompt(job), encoding="utf-8")

    pack_meta = {
        "jobId": job["id"],
        "asset": job.get("asset"),
        "basePose": job["basePose"],
        "outfit": job["outfit"],
        "status": job.get("status"),
        "hashes": {
            "basePoseSha256": job.get("basePoseSha256"),
            "maskSha256": job.get("maskSha256"),
            "outfitSpecSha256": job.get("outfitSpecSha256"),
            "outfitReferenceSha256": ref_sha,
        },
        "outfitReferenceSha256": ref_sha,
        "expectedFullEdit": "output/full-edit.png",
        "targetFullEdit": job.get("targetFullEdit"),
        "targetLayer": job.get("targetLayer"),
        "inputs": {
            "canonicalReference": job.get("canonicalReference"),
            "basePoseFile": job.get("basePoseFile"),
            "clothingMask": job.get("clothingMask"),
            "outfitReference": (
                f".local-assets/shared/mascot-outfit-references/{outfit['id']}/reference.png"
                if ref_sha
                else None
            ),
        },
        "note": (
            "barcelona-home is a distinct outfit and must never be aliased to default-home"
            if job.get("outfit") == "barcelona-home"
            else None
        ),
    }
    write_json(pack_dir / "job.json", pack_meta)
    job["outfitReferenceSha256"] = ref_sha
    return pack_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--all", action="store_true", help="Export every pending job")
    parser.add_argument("--job", type=str, default=None, help="Export one job id")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild packs even when existing pack hashes do not match the queue",
    )
    args = parser.parse_args()
    if not args.all and not args.job:
        parser.error("pass --all or --job JOB_ID")

    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()

    queue_path = video_dir / "assets" / "mascot-generation.json"
    queue = load_json(queue_path)
    jobs = list(queue.get("jobs") or [])
    if args.job:
        jobs = [j for j in jobs if j.get("id") == args.job]
        if not jobs:
            return fail(f"unknown job `{args.job}`")

    pending = [j for j in jobs if j.get("status") == "pending"]
    if not pending:
        return fail("no pending jobs to export")

    # Keep barcelona-home jobs; never drop them.
    barcelona = [j for j in pending if j.get("outfit") == "barcelona-home"]
    prep = load_asset_prep(video_dir) if (video_dir / "assets" / "asset-prep.json").exists() else {
        "paths": {"localRoot": f".local-assets/{video_dir.name}"}
    }
    dirs = ensure_local_dirs(video_dir, prep)
    packs_root = dirs["root"] / "mascot-generation"
    packs_root.mkdir(parents=True, exist_ok=True)

    exported: list[Path] = []
    queue_jobs = list(queue.get("jobs") or [])
    by_id = {item["id"]: item for item in queue_jobs}
    for job in pending:
        try:
            path = export_job(video_dir, job, packs_root, force=args.force)
            exported.append(path)
            if job["id"] in by_id:
                by_id[job["id"]]["outfitReferenceSha256"] = job.get("outfitReferenceSha256")
            print(f"OK    exported {job['id']} outfit={job['outfit']} -> {path}")
        except ValueError as exc:
            return fail(str(exc))

    write_json(queue_path, {"version": 1, "jobs": queue_jobs})
    print(
        f"OK    packs={len(exported)} pending={len(pending)} "
        f"barcelona_home={len(barcelona)} (queue status unchanged)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
