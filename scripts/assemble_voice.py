#!/usr/bin/env python3
"""Assemble segment WAVs + pauseAfter silence into audio/final/narration.wav."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voice_common import (
    concat_wavs,
    load_json,
    load_voice_config,
    segment_wav_path,
    video_audio_paths,
    write_json,
)


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def assemble(video_dir: Path) -> int:
    paths = video_audio_paths(video_dir)
    payload = load_json(paths["voice_json"])
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("voice.json has no segments")

    config = load_voice_config()
    audio_setting = config.get("audioSetting") or {}
    sample_rate = int(audio_setting.get("sampleRate") or payload.get("settings", {}).get("sampleRate") or 32000)
    channels = int(audio_setting.get("channel") or payload.get("settings", {}).get("channel") or 1)

    sources: list[tuple[Path | None, int]] = []
    cursor = 0
    for index, segment in enumerate(segments):
        if segment.get("status") not in {"generated", "approved"}:
            raise ValueError(f"{segment.get('id')}: status must be generated or approved")
        wav = (
            video_dir / segment["audio"]
            if segment.get("audio")
            else segment_wav_path(video_dir, segment["id"])
        )
        if not wav.exists():
            raise FileNotFoundError(f"missing audio for {segment.get('id')}: {wav}")
        duration = segment.get("durationMs")
        if duration is None:
            from voice_common import wav_duration_ms

            duration = wav_duration_ms(wav)
            segment["durationMs"] = duration
        segment["startMs"] = cursor
        segment["endMs"] = cursor + int(duration)
        cursor = segment["endMs"]
        pause = int(segment.get("pauseAfter") or 0)
        if index == len(segments) - 1:
            pause = 0
        sources.append((wav, pause))
        cursor += pause

    total_ms = concat_wavs(
        sources,
        paths["narration"],
        sample_rate=sample_rate,
        channels=channels,
    )
    write_json(paths["voice_json"], payload)
    print(f"OK    {paths['narration']} ({total_ms} ms)")
    return total_ms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Path to a video folder")
    args = parser.parse_args()
    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()
    try:
        assemble(video_dir)
    except (OSError, ValueError, FileNotFoundError) as exc:
        return fail(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
