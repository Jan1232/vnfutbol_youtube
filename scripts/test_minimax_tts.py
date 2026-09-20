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
    build_segments_from_blocks,
    canonical_json,
    load_dotenv,
    load_voice_config,
    pack_utterances,
    parse_script_blocks,
    sanitize_source_key_filename,
    segment_audio_relpath,
    segment_wav_path,
    settings_fingerprint,
    settings_sha256,
    sha256_text,
    split_sentences,
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
    assert config.get("voiceId") == "moss_audio_6246e496-b4e2-11f1-bf36-dabba993c40d"
    assert config.get("voiceSetting", {}).get("speed") == 1.0
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
    assert payload["voice_setting"]["voice_id"] == "moss_audio_6246e496-b4e2-11f1-bf36-dabba993c40d"
    assert payload["voice_setting"]["speed"] == 1.0
    assert payload["voice_setting"]["pitch"] == 0
    assert payload["voice_setting"]["vol"] == 1
    assert payload["audio_setting"]["format"] == "wav"
    assert payload["audio_setting"]["sample_rate"] == 32000
    assert "voice_modify" not in payload
    print("OK    request payload")

    sample = (
        "### SCRIPT-001\n\nТекст:\n\nФинал чемпионата мира 2026 года.\n\n"
        "Связанные факты:\n- FACT-001\n\n"
        "### SCRIPT-002\n\nТекст:\n\n"
        "С одной стороны — 39-летний Лионель Месси. "
        "С другой — 19-летний Ламин Ямаль. "
        "То есть футбол буквально поставил нового претендента на место рядом с настоящей легендой.\n"
    )
    blocks = parse_script_blocks(sample)
    assert len(blocks) == 2
    sentences = split_sentences(blocks[1]["text"])
    assert len(sentences) == 3
    packed = pack_utterances(sentences)
    assert 1 <= len(packed) <= 3
    assert all(len(u) <= 320 or u == max(sentences, key=len) for u in packed)
    segments = build_segments_from_blocks(blocks, config)
    assert segments[0]["sourceKey"] == "SCRIPT-001:000"
    assert segments[0]["id"] == "voice-001"
    assert any(seg["script"] == "SCRIPT-002" for seg in segments)
    assert len({seg["sourceKey"] for seg in segments}) == len(segments)
    again = build_segments_from_blocks(blocks, config)
    assert [seg["sourceKey"] for seg in segments] == [seg["sourceKey"] for seg in again]
    print("OK    text segmentation")

    # Storage identity must follow sourceKey, not voice-NNN order.
    early_one = (
        "Первая реплика про Ямаля, путь из района Rocafonda и ранний выход "
        "во взрослый футбол Barcelona уже в пятнадцать лет."
    )
    early_two = (
        "Дополнительная ранняя реплика нужна только чтобы увеличить число "
        "utterances в SCRIPT-001 и тем самым сдвинуть последующие voice id."
    )
    late_one = (
        "Вторая реплика номер один про финал чемпионата мира и встречу "
        "молодого таланта с настоящей легендой на большом поле."
    )
    late_two = (
        "Вторая реплика номер два про сравнение карьерных траекторий "
        "и почему одного ярлыка недостаточно для исторического вердикта."
    )
    before = (
        f"### SCRIPT-001\n\nТекст:\n\n{early_one}\n\n"
        f"### SCRIPT-002\n\nТекст:\n\n{late_one} {late_two}\n"
    )
    after = (
        f"### SCRIPT-001\n\nТекст:\n\n{early_one} {early_two}\n\n"
        f"### SCRIPT-002\n\nТекст:\n\n{late_one} {late_two}\n"
    )
    segs_before = build_segments_from_blocks(parse_script_blocks(before), config)
    segs_after = build_segments_from_blocks(parse_script_blocks(after), config)
    before_s2 = [s for s in segs_before if s["script"] == "SCRIPT-002"]
    after_s2 = [s for s in segs_after if s["script"] == "SCRIPT-002"]
    assert len([s for s in segs_after if s["script"] == "SCRIPT-001"]) > len(
        [s for s in segs_before if s["script"] == "SCRIPT-001"]
    )
    assert [s["sourceKey"] for s in before_s2] == [s["sourceKey"] for s in after_s2]
    assert [s["sourceKey"] for s in before_s2] == ["SCRIPT-002:000", "SCRIPT-002:001"]
    assert sanitize_source_key_filename("SCRIPT-006:001") == "script-006_001"
    assert segment_audio_relpath("SCRIPT-006:001") == "audio/segments/script-006_001.wav"
    before_paths = [segment_audio_relpath(s["sourceKey"]) for s in before_s2]
    after_paths = [segment_audio_relpath(s["sourceKey"]) for s in after_s2]
    assert before_paths == after_paths == [
        "audio/segments/script-002_000.wav",
        "audio/segments/script-002_001.wav",
    ]
    assert before_s2[0]["id"] != after_s2[0]["id"]
    assert segment_wav_path(Path("/tmp/video"), after_s2[0]).name == "script-002_000.wav"
    print("OK    sourceKey storage identity")

    # merge_segments must persist delivery before renderSha256 compare.
    from generate_voice import merge_segments
    from voice_common import apply_tts_fields

    overrides = {"version": 1, "overrides": {}}
    sample = (
        "### SCRIPT-001\n\nТекст:\n\nФинал чемпионата мира.\n\n"
        "Связанные факты:\n"
    )
    built = build_segments_from_blocks(parse_script_blocks(sample), config, overrides)
    assert len(built) == 1
    existing = dict(built[0])
    existing["delivery"] = {"interjection": "sighs"}
    apply_tts_fields(existing, config, overrides)
    existing.update(
        {
            "status": "generated",
            "audio": "audio/segments/script-001_000.wav",
            "sha256": "0" * 64,
            "durationMs": 1200,
            "startMs": 0,
            "endMs": 1200,
        }
    )
    sighs_render = existing["renderSha256"]
    fresh_built = build_segments_from_blocks(parse_script_blocks(sample), config, overrides)
    merged = merge_segments([existing], fresh_built, config, overrides)
    assert merged[0]["delivery"] == {"interjection": "sighs"}
    assert merged[0]["status"] == "generated"
    assert merged[0]["audio"] == "audio/segments/script-001_000.wav"
    assert merged[0]["renderSha256"] == sighs_render
    assert merged[0]["sha256"] == "0" * 64

    changed = dict(merged[0])
    changed["delivery"] = {"interjection": "laughs"}
    # Keep previous sighs render hash on disk record; delivery edit alone.
    changed["renderSha256"] = sighs_render
    merged2 = merge_segments([changed], fresh_built, config, overrides)
    assert merged2[0]["delivery"] == {"interjection": "laughs"}
    assert merged2[0]["renderSha256"] != sighs_render
    assert merged2[0]["status"] == "stale"
    assert merged2[0]["audio"] is None
    print("OK    merge delivery/renderSha256")

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
