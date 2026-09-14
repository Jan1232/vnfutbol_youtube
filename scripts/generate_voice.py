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
    apply_tts_fields,
    build_segments_from_blocks,
    classify_segment,
    ensure_voice_overrides,
    load_dotenv,
    load_json,
    load_voice_config,
    load_voice_overrides,
    parse_script_blocks,
    render_sha256,
    segment_audio_relpath,
    segment_wav_path,
    settings_fingerprint,
    settings_sha256,
    sha256_file,
    sha256_text,
    video_audio_paths,
    wav_duration_ms,
    write_json,
)
from voice_normalizer import build_tts_text, normalize_russian_tts

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
            updated["pauseAfter"] = old["pauseAfter"]

        text_changed = (old.get("text") or "") != segment["text"]
        tts_changed = (old.get("ttsText") or "") != segment.get("ttsText")
        settings_changed = old.get("settingsSha256") != segment.get("settingsSha256")
        render_changed = old.get("renderSha256") != segment.get("renderSha256")
        if text_changed or tts_changed or settings_changed or render_changed:
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

        # Always refresh speakable fields/hashes from current script+overrides.
        for key in (
            "ttsText",
            "textSha256",
            "ttsTextSha256",
            "settingsSha256",
            "renderSha256",
            "characters",
            "provider",
            "sourceKey",
        ):
            if key in segment:
                updated[key] = segment[key]
        merged.append(updated)
    if merged:
        merged[-1]["pauseAfter"] = 0
    return merged


def sync_voice_json(video_dir: Path, config: dict) -> dict:
    paths = video_audio_paths(video_dir)
    ensure_voice_overrides(video_dir)
    overrides = load_voice_overrides(video_dir)
    script_path = video_dir / "script" / "script.md"
    if not script_path.exists():
        raise FileNotFoundError(f"missing {script_path}")
    blocks = parse_script_blocks(script_path.read_text(encoding="utf-8"))
    if not blocks:
        raise ValueError("script.md has no SCRIPT blocks with Текст")

    built = build_segments_from_blocks(blocks, config, overrides)
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
        # Re-apply TTS fields after merge so delivery changes refresh renderSha256.
        for segment in segments:
            apply_tts_fields(segment, config, overrides)
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


def resolve_target_segment(payload: dict, *, source_key: str | None, segment_id: str | None) -> dict:
    segments = payload.get("segments") or []
    if source_key:
        match = next((s for s in segments if s.get("sourceKey") == source_key), None)
        if match is None:
            raise ValueError(f"unknown sourceKey `{source_key}`")
        return match
    if segment_id:
        match = next((s for s in segments if s.get("id") == segment_id), None)
        if match is None:
            raise ValueError(f"unknown segment id `{segment_id}`")
        return match
    raise ValueError("pass --source-key or --segment")


def show_segment(video_dir: Path, segment: dict, config: dict, overrides: dict) -> None:
    override = (overrides.get("overrides") or {}).get(segment.get("sourceKey") or "")
    normalized = normalize_russian_tts(segment.get("text") or "")
    tts = segment.get("ttsText") or build_tts_text(segment.get("text") or "", override)
    audio = segment.get("audio") or segment_audio_relpath(segment["sourceKey"])
    label = classify_segment(segment, video_dir, config)
    print(f"ID:\n{segment.get('id')}\n")
    print(f"sourceKey:\n{segment.get('sourceKey')}\n")
    print(f"TEXT:\n{segment.get('text')}\n")
    print(f"NORMALIZED:\n{normalized}\n")
    print(f"TTS TEXT:\n{tts}\n")
    print(f"AUDIO:\n{audio}\n")
    print(f"STATUS:\n{segment.get('status')} ({label})")


def synthesize_one(
    video_dir: Path,
    payload: dict,
    config: dict,
    segment: dict,
    *,
    retries: int,
) -> None:
    paths = video_audio_paths(video_dir)
    out = segment_wav_path(video_dir, segment)
    rel = out.relative_to(video_dir).as_posix()
    segment["status"] = "generating"
    write_json(paths["voice_json"], payload)
    speak = apply_interjection(segment.get("ttsText") or segment.get("text") or "", segment.get("delivery"))
    client = MiniMaxTTS(config=config)
    meta = client.synthesize(speak, out, retries=retries)
    duration = wav_duration_ms(out)
    settings_hash = settings_sha256(config)
    tts_text = segment.get("ttsText") or ""
    segment.update(
        {
            "status": "generated",
            "audio": rel,
            "durationMs": duration,
            "characters": len(segment.get("text") or ""),
            "sha256": sha256_file(out),
            "textSha256": sha256_text(segment.get("text") or ""),
            "ttsTextSha256": sha256_text(tts_text),
            "settingsSha256": settings_hash,
            "renderSha256": render_sha256(tts_text, settings_hash, segment.get("delivery") or {}),
            "provider": {
                "model": config.get("model"),
                "voiceId": config.get("voiceId"),
            },
        }
    )
    write_json(paths["voice_json"], payload)
    print(f"OK    {segment['id']} ({segment['sourceKey']}) -> {rel} ({duration} ms) [{meta.get('bytes')} bytes]")


def run_synthesis(
    video_dir: Path,
    payload: dict,
    config: dict,
    *,
    dry_run: bool,
    retries: int,
    assemble_final: bool,
    only_source_key: str | None = None,
    only_segment_id: str | None = None,
    force: bool = False,
) -> int:
    paths = video_audio_paths(video_dir)
    paths["segments"].mkdir(parents=True, exist_ok=True)
    paths["previews"].mkdir(parents=True, exist_ok=True)
    paths["final"].mkdir(parents=True, exist_ok=True)

    segments = payload["segments"]
    if only_source_key or only_segment_id:
        target = resolve_target_segment(
            payload, source_key=only_source_key, segment_id=only_segment_id
        )
        label = classify_segment(target, video_dir, config)
        print(
            f"{label:8} {target['id']} {target.get('sourceKey')}  "
            f"{(target.get('ttsText') or target.get('text') or '')[:72]}"
        )
        if dry_run:
            print("OK    dry-run complete; no API calls")
            return 0
        if label == "REUSE" and not force:
            print("OK    REUSE; pass --force to regenerate")
            return 0
        if not config.get("enabled", True):
            return fail("voice config has enabled=false")
        try:
            synthesize_one(video_dir, payload, config, target, retries=retries)
        except MiniMaxTTSError:
            target["status"] = "failed"
            write_json(paths["voice_json"], payload)
            return 1
        if assemble_final and all(
            seg.get("status") in {"generated", "approved"} and seg.get("audio")
            for seg in segments
        ):
            narration_ms = assemble(video_dir)
            update_assets_manifest(
                video_dir,
                paths["narration"].relative_to(video_dir).as_posix(),
                "generated",
            )
            print(f"OK    reassembled narration ({narration_ms} ms)")
        return 0

    plan = [(classify_segment(seg, video_dir, config), seg) for seg in segments]
    counts = {"REUSE": 0, "GENERATE": 0, "STALE": 0, "MISSING": 0}
    for label, segment in plan:
        counts[label] = counts.get(label, 0) + 1
        preview = segment.get("ttsText") or segment.get("text") or ""
        print(f"{label:8} {segment['id']}  {preview[:72]}")

    to_generate = []
    for label, seg in plan:
        if force:
            to_generate.append(seg)
        elif label in {"GENERATE", "STALE", "MISSING"}:
            to_generate.append(seg)
    print(
        f"PLAN   total={len(plan)} reuse={counts['REUSE']} "
        f"generate={len(to_generate)} "
        f"(missing={counts['MISSING']} stale={counts['STALE']})"
    )

    if dry_run:
        print("OK    dry-run complete; no API calls")
        return 0

    if not config.get("enabled", True):
        return fail("voice config has enabled=false")

    generated = 0
    failed = 0
    total_chars = 0
    by_id = {seg["id"]: seg for seg in segments}

    for segment in to_generate:
        try:
            synthesize_one(video_dir, payload, config, by_id[segment["id"]], retries=retries)
            generated += 1
            total_chars += len(segment.get("text") or "")
        except MiniMaxTTSError:
            by_id[segment["id"]]["status"] = "failed"
            failed += 1
            write_json(paths["voice_json"], payload)
            print(f"FAIL  {segment['id']}")

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
        f"  reused: {counts['REUSE']}\n"
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
    parser.add_argument("--no-assemble", action="store_true")
    parser.add_argument("--source-key", help="Generate/show only this sourceKey")
    parser.add_argument("--segment", help="Alias: voice-014 → resolve sourceKey")
    parser.add_argument("--force", action="store_true", help="Regenerate even if REUSE")
    parser.add_argument("--show", action="store_true", help="Inspect text/ttsText/status")
    args = parser.parse_args()

    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()
    if not video_dir.is_dir():
        return fail(f"video folder does not exist: {video_dir}")

    try:
        config = load_voice_config()
        payload = sync_voice_json(video_dir, config)
        overrides = load_voice_overrides(video_dir)
    except (OSError, ValueError, FileNotFoundError) as exc:
        return fail(str(exc))

    if args.show:
        try:
            target = resolve_target_segment(
                payload, source_key=args.source_key, segment_id=args.segment
            )
        except ValueError as exc:
            return fail(str(exc))
        show_segment(video_dir, target, config, overrides)
        return 0

    return run_synthesis(
        video_dir,
        payload,
        config,
        dry_run=args.dry_run,
        retries=args.retries,
        assemble_final=not args.no_assemble,
        only_source_key=args.source_key,
        only_segment_id=args.segment,
        force=args.force,
    )


if __name__ == "__main__":
    sys.exit(main())
