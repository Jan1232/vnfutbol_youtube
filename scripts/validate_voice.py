#!/usr/bin/env python3
"""Validate MiniMax voice.json, segment WAVs and final narration."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voice_common import (
    VALID_MODELS,
    load_json,
    load_voice_config,
    render_sha256,
    segment_audio_relpath,
    settings_sha256,
    sha256_file,
    sha256_text,
    video_audio_paths,
    wav_duration_ms,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to a video folder")
    args = parser.parse_args()
    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()

    errors: list[str] = []
    paths = video_audio_paths(video_dir)
    if not paths["voice_json"].exists():
        print("ERROR voice.json does not exist")
        print("FAIL  1 error(s)")
        return 1

    try:
        payload = load_json(paths["voice_json"])
        config = load_voice_config()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR cannot load voice files: {exc}")
        print("FAIL  1 error(s)")
        return 1

    if not isinstance(payload, dict):
        errors.append("voice.json: root must be an object")
        segments: list = []
    else:
        if payload.get("version") != 1:
            errors.append("voice.json: version must be 1")
        if payload.get("provider") != "minimax":
            errors.append("voice.json: provider must be minimax")
        settings = payload.get("settings") or {}
        model = settings.get("model") or config.get("model")
        if model not in VALID_MODELS:
            errors.append(f"voice.json: invalid model `{model}`")
        voice_id = payload.get("profile") or config.get("voiceId")
        if not voice_id:
            errors.append("voice.json: profile/voiceId is missing")
        speed = settings.get("speed")
        if not isinstance(speed, (int, float)) or not (0.5 <= float(speed) <= 2.0):
            errors.append(f"voice.json: speed out of range: {speed}")

        segments = payload.get("segments")
        if not isinstance(segments, list):
            errors.append("voice.json: segments must be a list")
            segments = []

        ids: list[str] = []
        source_keys: list[str] = []
        for index, segment in enumerate(segments):
            prefix = f"segments[{index}]"
            if not isinstance(segment, dict):
                errors.append(f"{prefix}: must be an object")
                continue
            seg_id = segment.get("id")
            if not seg_id:
                errors.append(f"{prefix}: missing id")
                continue
            ids.append(seg_id)

            source = segment.get("sourceKey")
            if not source:
                errors.append(f"{seg_id}: sourceKey is missing")
            else:
                source_keys.append(source)

            if not segment.get("script"):
                errors.append(f"{seg_id}: script is missing")

            text = segment.get("text")
            tts_text = segment.get("ttsText")
            if not isinstance(text, str) or not text.strip():
                errors.append(f"{seg_id}: text must be a non-empty string")
            else:
                if segment.get("textSha256") != sha256_text(text):
                    errors.append(f"{seg_id}: textSha256 mismatch")
            if not isinstance(tts_text, str) or not tts_text.strip():
                errors.append(f"{seg_id}: ttsText must be a non-empty string")
            else:
                if segment.get("ttsTextSha256") != sha256_text(tts_text):
                    errors.append(f"{seg_id}: ttsTextSha256 mismatch")
            settings_hash = settings_sha256(config)
            if segment.get("settingsSha256") != settings_hash:
                errors.append(f"{seg_id}: settingsSha256 mismatch")
            expected_render = render_sha256(
                tts_text or "",
                settings_hash,
                segment.get("delivery") or {},
            )
            if segment.get("renderSha256") != expected_render:
                errors.append(f"{seg_id}: renderSha256 mismatch")
            if "pauseAfter" in segment and not isinstance(segment["pauseAfter"], int):
                errors.append(f"{seg_id}: pauseAfter must be an integer")

            status = segment.get("status")
            if status in {"generated", "approved"}:
                for required in ("textSha256", "ttsTextSha256", "settingsSha256", "renderSha256", "sha256"):
                    if not segment.get(required):
                        errors.append(f"{seg_id}: {required} is required for {status}")
                audio_rel = segment.get("audio")
                declared_sha = segment.get("sha256")
                if not audio_rel:
                    errors.append(f"{seg_id}: ready segment missing audio path")
                else:
                    expected_rel = segment_audio_relpath(source) if source else None
                    if expected_rel and audio_rel != expected_rel:
                        errors.append(
                            f"{seg_id}: audio `{audio_rel}` does not match "
                            f"sourceKey `{source}` (expected `{expected_rel}`)"
                        )
                if declared_sha and audio_rel:
                    audio_path = video_dir / audio_rel
                    if not audio_path.exists():
                        errors.append(f"{seg_id}: audio file missing: {audio_rel}")
                    else:
                        actual = sha256_file(audio_path)
                        if actual != declared_sha:
                            errors.append(f"{seg_id}: audio sha256 mismatch")
                        try:
                            measured = wav_duration_ms(audio_path)
                        except OSError as exc:
                            errors.append(f"{seg_id}: cannot read wav ({exc})")
                        else:
                            declared = segment.get("durationMs")
                            if declared is None:
                                errors.append(f"{seg_id}: durationMs is missing")
                            elif abs(int(declared) - measured) > 20:
                                errors.append(
                                    f"{seg_id}: durationMs {declared} != measured {measured}"
                                )

        for value, count in Counter(ids).items():
            if count > 1:
                errors.append(f"duplicate segment id: {value}")
        for value, count in Counter(source_keys).items():
            if count > 1:
                errors.append(f"duplicate sourceKey: {value}")

        if segments:
            last = segments[-1]
            if isinstance(last, dict) and last.get("pauseAfter") != 0:
                # Required after assemble; also enforced by sync for pending plans.
                if any(
                    isinstance(seg, dict) and seg.get("startMs") is not None
                    for seg in segments
                ):
                    errors.append(
                        f"{last.get('id')}: last segment pauseAfter must be 0 after assemble"
                    )
                elif last.get("pauseAfter") != 0:
                    errors.append(f"{last.get('id')}: last segment pauseAfter must be 0")

        ready = [
            seg
            for seg in segments
            if isinstance(seg, dict) and seg.get("status") in {"generated", "approved"}
        ]
        if ready and all(seg.get("startMs") is not None for seg in ready):
            cursor = 0
            for index, seg in enumerate(ready):
                start = seg.get("startMs")
                end = seg.get("endMs")
                duration = seg.get("durationMs")
                if start != cursor:
                    errors.append(f"{seg.get('id')}: startMs {start} != expected {cursor}")
                if end is None or duration is None or end != start + duration:
                    errors.append(f"{seg.get('id')}: endMs/durationMs inconsistent")
                cursor = end + (
                    0 if index == len(ready) - 1 else int(seg.get("pauseAfter") or 0)
                )

        if paths["narration"].exists():
            try:
                total = wav_duration_ms(paths["narration"])
                if ready and all(seg.get("endMs") is not None for seg in ready):
                    expected = int(ready[-1]["endMs"])
                    if abs(total - expected) > 40:
                        errors.append(
                            f"narration.wav duration {total} ms != last endMs {expected} ms"
                        )
            except OSError as exc:
                errors.append(f"narration.wav unreadable: {exc}")
        elif ready and any(seg.get("startMs") is not None for seg in ready):
            errors.append("audio/final/narration.wav is missing")

    for message in errors:
        print(f"ERROR {message}")
    if errors:
        print(f"FAIL  {len(errors)} error(s)")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
