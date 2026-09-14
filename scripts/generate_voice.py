#!/usr/bin/env python3
"""Build voice.json from script.md and synthesize missing/stale MiniMax segments."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble_voice import assemble
from minimax_tts import MiniMaxTTS, MiniMaxTTSError
from voice_common import (
    apply_interjection,
    build_segments_from_blocks,
    classify_segment,
    load_dotenv,
    load_json,
    load_voice_config,
    parse_script_blocks,
    segment_wav_path,
    settings_fingerprint,
    settings_sha256,
    sha256_file,
    sha256_text,
    video_audio_paths,
    wav_duration_ms,
    write_json,
)

load_dotenv()


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def merge_segments(existing: list[dict], built: list[dict]) -> list[dict]:
    by_key = {
        item.get("sourceKey"): item
        for item in existing
        if isinstance(item, dict) and item.get("sourceKey")
    }
    merged: list[dict] = []
    for segment in built:
        old = by_key.get(segment["sourceKey"])
        if old is None:
            merged.append(segment)
            continue

        updated = dict(segment)
        updated["delivery"] = old.get("delivery") or {}
        if old.get("scene") is not None:
            updated["scene"] = old.get("scene")
        if isinstance(old.get("pauseAfter"), int) and segment.get("pauseAfter") != 0:
            # Keep manual pause overrides, but never override forced trailing 0.
            updated["pauseAfter"] = old["pauseAfter"]

        text_changed = (old.get("text") or "") != segment["text"]
        settings_changed = old.get("settingsSha256") != segment["settingsSha256"]
        if text_changed or settings_changed:
            updated["status"] = "stale" if old.get("audio") else "pending"
            updated["audio"] = None
            updated["durationMs"] = None
            updated["sha256"] = None
            updated["startMs"] = None
            updated["endMs"] = None
        else:
            for key in (
                "audio",
                "durationMs",
                "sha256",
                "status",
                "startMs",
                "endMs",
                "textSha256",
                "settingsSha256",
            ):
                if old.get(key) is not None:
                    updated[key] = old[key]
            if updated.get("status") not in {
                "pending",
                "generating",
                "generated",
                "stale",
                "failed",
                "approved",
            }:
                updated["status"] = "pending"

        updated["sourceKey"] = segment["sourceKey"]
        updated["textSha256"] = sha256_text(updated["text"])
        updated["settingsSha256"] = segment["settingsSha256"]
        updated["characters"] = len(updated["text"])
        updated["provider"] = segment["provider"]
        merged.append(updated)
    if merged:
        merged[-1]["pauseAfter"] = 0
    return merged


def sync_voice_json(video_dir: Path, config: dict) -> dict:
    paths = video_audio_paths(video_dir)
    script_path = video_dir / "script" / "script.md"
    if not script_path.exists():
        raise FileNotFoundError(f"missing {script_path}")
    blocks = parse_script_blocks(script_path.read_text(encoding="utf-8"))
    if not blocks:
        raise ValueError("script.md has no SCRIPT blocks with Текст")

    built = build_segments_from_blocks(blocks, config)
    if not built:
        raise ValueError("script.md produced zero voice segments")

    if paths["voice_json"].exists():
        current = load_json(paths["voice_json"])
        if not isinstance(current, dict):
            current = {}
        existing = current.get("segments")
        if not isinstance(existing, list):
            existing = current.get("items") if isinstance(current.get("items"), list) else []
        segments = merge_segments(existing, built)
    else:
        segments = built
        if segments:
            segments[-1]["pauseAfter"] = 0

    fingerprint = settings_fingerprint(config)
    payload = {
        "version": 1,
        "provider": config.get("provider", "minimax"),
        "profile": config.get("voiceId"),
        "settings": {
            "model": fingerprint["model"],
            "speed": fingerprint["speed"],
            "pitch": fingerprint["pitch"],
            "volume": fingerprint["volume"],
            "sampleRate": fingerprint["sampleRate"],
            "bitrate": fingerprint["bitrate"],
            "format": fingerprint["format"],
            "channel": fingerprint["channel"],
        },
        "segments": segments,
    }
    write_json(paths["voice_json"], payload)
    return payload


def update_assets_manifest(video_dir: Path, narration_rel: str, status: str) -> None:
    assets_path = video_dir / "assets" / "assets.json"
    if not assets_path.exists():
        return
    payload = load_json(assets_path)
    assets = payload.setdefault("assets", [])
    entry = {
        "id": "narration",
        "type": "AUDIO",
        "source": "generated",
        "status": status,
        "provider": "minimax",
        "file": narration_rel,
        "usedInScenes": [],
        "tags": ["voice", "narration"],
        "sourceUrl": None,
        "license": None,
        "author": None,
    }
    replaced = False
    for index, asset in enumerate(assets):
        if asset.get("id") == "narration":
            assets[index] = {**asset, **entry}
            replaced = True
            break
    if not replaced:
        assets.append(entry)
    write_json(assets_path, payload)


def synthesize_plan(video_dir: Path, payload: dict, config: dict) -> list[tuple[str, dict]]:
    plan = []
    for segment in payload.get("segments") or []:
        label = classify_segment(segment, video_dir, config)
        plan.append((label, segment))
    return plan


def run_synthesis(
    video_dir: Path,
    payload: dict,
    config: dict,
    *,
    dry_run: bool,
    retries: int,
    assemble_final: bool,
) -> int:
    paths = video_audio_paths(video_dir)
    paths["segments"].mkdir(parents=True, exist_ok=True)
    paths["previews"].mkdir(parents=True, exist_ok=True)
    paths["final"].mkdir(parents=True, exist_ok=True)

    plan = synthesize_plan(video_dir, payload, config)
    counts = {"REUSE": 0, "GENERATE": 0, "STALE": 0, "MISSING": 0}
    for label, segment in plan:
        counts[label] = counts.get(label, 0) + 1
        print(f"{label:8} {segment['id']}  {segment['text'][:72]}")

    to_generate = [seg for label, seg in plan if label in {"GENERATE", "STALE", "MISSING"}]
    print(
        f"PLAN   total={len(plan)} reuse={counts['REUSE']} "
        f"generate={counts['GENERATE'] + counts['STALE'] + counts['MISSING']} "
        f"(missing={counts['MISSING']} stale={counts['STALE']} generate={counts['GENERATE']})"
    )

    if dry_run:
        print("OK    dry-run complete; no API calls")
        return 0

    if not config.get("enabled", True):
        return fail("voice config has enabled=false")

    client = MiniMaxTTS(config=config)
    generated = 0
    reused = counts["REUSE"]
    failed = 0
    total_chars = 0

    segments = payload["segments"]
    by_id = {seg["id"]: seg for seg in segments}

    for segment in to_generate:
        seg_id = segment["id"]
        out = segment_wav_path(video_dir, segment)
        rel = out.relative_to(video_dir).as_posix()
        by_id[seg_id]["status"] = "generating"
        write_json(paths["voice_json"], payload)
        speak = apply_interjection(segment["text"], segment.get("delivery"))
        try:
            meta = client.synthesize(speak, out, retries=retries)
            duration = wav_duration_ms(out)
            by_id[seg_id].update(
                {
                    "status": "generated",
                    "audio": rel,
                    "durationMs": duration,
                    "characters": len(segment["text"]),
                    "sha256": sha256_file(out),
                    "textSha256": sha256_text(segment["text"]),
                    "settingsSha256": settings_sha256(config),
                    "provider": {
                        "model": config.get("model"),
                        "voiceId": config.get("voiceId"),
                    },
                }
            )
            generated += 1
            total_chars += len(segment["text"])
            print(f"OK    {seg_id} -> {rel} ({duration} ms)")
        except MiniMaxTTSError:
            by_id[seg_id]["status"] = "failed"
            failed += 1
            write_json(paths["voice_json"], payload)
            print(f"FAIL  {seg_id}")
        write_json(paths["voice_json"], payload)

    # Refresh reuse metadata if file exists but duration missing.
    for segment in segments:
        if classify_segment(segment, video_dir, config) != "REUSE":
            continue
        path = (
            video_dir / segment["audio"]
            if segment.get("audio")
            else segment_wav_path(video_dir, segment)
        )
        if not segment.get("audio"):
            segment["audio"] = path.relative_to(video_dir).as_posix()
        if segment.get("durationMs") is None and path.exists():
            segment["durationMs"] = wav_duration_ms(path)
        if segment.get("sha256") is None and path.exists():
            segment["sha256"] = sha256_file(path)
        if segment.get("status") not in {"generated", "approved"}:
            segment["status"] = "generated"
        total_chars += len(segment.get("text") or "")

    write_json(paths["voice_json"], payload)

    narration_ms = None
    if assemble_final and failed == 0 and all(
        classify_segment(seg, video_dir, config) == "REUSE"
        or (seg.get("status") in {"generated", "approved"} and seg.get("audio"))
        for seg in segments
    ):
        narration_ms = assemble(video_dir)
        update_assets_manifest(
            video_dir,
            paths["narration"].relative_to(video_dir).as_posix(),
            "generated",
        )

    fingerprint = settings_fingerprint(config)
    print(
        "SUMMARY\n"
        f"  segments: {len(segments)}\n"
        f"  reused: {reused}\n"
        f"  generated: {generated}\n"
        f"  failed: {failed}\n"
        f"  total characters: {total_chars}\n"
        f"  model: {fingerprint['model']}\n"
        f"  voiceId: {fingerprint['voiceId']}\n"
        f"  speed: {fingerprint['speed']}\n"
        f"  output: {paths['narration'] if narration_ms is not None else '(not assembled)'}"
    )
    if narration_ms is not None:
        print(f"  narration durationMs: {narration_ms}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to a video folder")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--no-assemble",
        action="store_true",
        help="Skip final narration.wav after synthesis",
    )
    args = parser.parse_args()

    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()
    if not video_dir.is_dir():
        return fail(f"video folder does not exist: {video_dir}")

    try:
        config = load_voice_config()
        payload = sync_voice_json(video_dir, config)
    except (OSError, ValueError, FileNotFoundError) as exc:
        return fail(str(exc))

    return run_synthesis(
        video_dir,
        payload,
        config,
        dry_run=args.dry_run,
        retries=args.retries,
        assemble_final=not args.no_assemble,
    )


if __name__ == "__main__":
    sys.exit(main())
