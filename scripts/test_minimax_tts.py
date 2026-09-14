#!/usr/bin/env python3
"""Offline MiniMax TTS contract tests. Use --live for one short API call."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from minimax_tts import MiniMaxTTS, MiniMaxTTSError
from voice_common import (
    ROOT,
    apply_interjection,
    canonical_json,
    load_dotenv,
    load_voice_config,
    parse_script_blocks,
    settings_fingerprint,
    settings_sha256,
    sha256_text,
    video_audio_paths,
)

load_dotenv()


def fail(message: str) -> int:
    print(f"ERROR {message}")
    return 1


def run_offline() -> int:
    config = load_voice_config()
    assert config.get("provider") == "minimax"
    assert config.get("model") == "speech-2.8-hd"
    assert config.get("voiceId") == "Russian_Articulate_Tutor_v1"
    assert config.get("voiceSetting", {}).get("speed") == 1.26
    assert config.get("audioSetting", {}).get("format") == "wav"
    print("OK    config")

    key = os.environ.get("MINIMAX_API_KEY")
    print(f"OK    environment MINIMAX_API_KEY={'set' if key else 'missing'}")

    client = MiniMaxTTS(config=config, api_key="test-key-not-used")
    payload = client.build_payload("Проверяем озвучку для ВСЕ НА ФУТБОЛ.")
    assert payload["model"] == "speech-2.8-hd"
    assert payload["stream"] is False
    assert payload["language_boost"] == "Russian"
    assert payload["output_format"] == "hex"
    assert payload["voice_setting"]["voice_id"] == "Russian_Articulate_Tutor_v1"
    assert payload["voice_setting"]["speed"] == 1.26
    assert payload["voice_setting"]["pitch"] == 0
    assert payload["voice_setting"]["vol"] == 1
    assert payload["audio_setting"]["format"] == "wav"
    assert payload["audio_setting"]["sample_rate"] == 32000
    assert "voice_modify" not in payload
    print("OK    request payload")

    sample = (
        "### SCRIPT-001\n\nТекст:\n\nФинал чемпионата мира 2026 года.\n\n"
        "Связанные факты:\n- FACT-001\n\n"
        "### SCRIPT-002\n\nТекст:\n\nС одной стороны — 39-летний Лионель Месси.\n"
    )
    blocks = parse_script_blocks(sample)
    assert len(blocks) == 2
    assert blocks[0]["text"] == "Финал чемпионата мира 2026 года."
    print("OK    text segmentation")

    fp = settings_fingerprint(config)
    assert settings_sha256(config) == sha256_text(canonical_json(fp))
    assert apply_interjection("Текст.", {"interjection": "sighs"}) == "(sighs) Текст."
    print("OK    hashes")

    video = ROOT / "videos" / "lamine-yamal-new-messi"
    paths = video_audio_paths(video)
    assert paths["segments"].name == "segments"
    assert paths["narration"].as_posix().endswith("audio/final/narration.wav")
    print("OK    paths")
    print("PASS  offline tests")
    return 0


def run_live() -> int:
    if not os.environ.get("MINIMAX_API_KEY"):
        return fail("MINIMAX_API_KEY is not set; export it before --live")
    config = load_voice_config()
    video = ROOT / "videos" / "lamine-yamal-new-messi"
    out = video_audio_paths(video)["test"] / "minimax-test.wav"
    client = MiniMaxTTS(config=config)
    try:
        meta = client.synthesize(
            "Проверяем озвучку для ВСЕ НА ФУТБОЛ.",
            out,
            retries=3,
        )
    except MiniMaxTTSError:
        return 1
    print(f"OK    live wrote {meta['path']} ({meta['bytes']} bytes)")
    print("PASS  live test")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    code = run_offline()
    if code != 0:
        return code
    if args.live:
        return run_live()
    return 0


if __name__ == "__main__":
    sys.exit(main())
