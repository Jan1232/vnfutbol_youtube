#!/usr/bin/env python3
"""Shared helpers for MiniMax voice generation."""

from __future__ import annotations

import hashlib
import json
import re
import wave
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VOICE_CONFIG_PATH = ROOT / "channel-assets" / "voice" / "minimax.json"
ENV_PATH = ROOT / ".env"


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from .env into os.environ if not already set.

    Never prints values. .env must stay gitignored.
    """
    import os

    env_file = path or ENV_PATH
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


VALID_MODELS = {
    "speech-2.8-hd",
    "speech-2.8-turbo",
    "speech-2.6-hd",
    "speech-2.6-turbo",
    "speech-02-hd",
    "speech-02-turbo",
    "speech-01-hd",
    "speech-01-turbo",
}

SEGMENT_STATUSES = {
    "pending",
    "generating",
    "generated",
    "stale",
    "failed",
    "approved",
}

SCRIPT_BLOCK_RE = re.compile(
    r"^###\s+(SCRIPT-[A-Z0-9-]+)\s*$",
    re.MULTILINE,
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_voice_config(path: Path | None = None) -> dict:
    config_path = path or VOICE_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"missing voice config: {config_path}")
    data = load_json(config_path)
    if not isinstance(data, dict):
        raise ValueError("voice config root must be an object")
    return data


def settings_fingerprint(config: dict) -> dict:
    voice = config.get("voiceSetting") or {}
    audio = config.get("audioSetting") or {}
    return {
        "provider": config.get("provider", "minimax"),
        "model": config.get("model"),
        "voiceId": config.get("voiceId"),
        "speed": voice.get("speed"),
        "pitch": voice.get("pitch"),
        "volume": voice.get("vol", voice.get("volume")),
        "sampleRate": audio.get("sampleRate"),
        "bitrate": audio.get("bitrate"),
        "format": audio.get("format"),
        "channel": audio.get("channel"),
    }


def settings_sha256(config: dict) -> str:
    return sha256_text(canonical_json(settings_fingerprint(config)))


def video_audio_paths(video_dir: Path) -> dict[str, Path]:
    audio = video_dir / "audio"
    return {
        "audio": audio,
        "voice_json": audio / "voice.json",
        "segments": audio / "segments",
        "previews": audio / "previews",
        "final": audio / "final",
        "narration": audio / "final" / "narration.wav",
        "test": audio / "test",
    }


def segment_wav_path(video_dir: Path, segment_id: str) -> Path:
    return video_audio_paths(video_dir)["segments"] / f"{segment_id}.wav"


def wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
    if rate <= 0:
        raise ValueError(f"invalid sample rate in {path}")
    return int(round(frames * 1000 / rate))


def write_silence_wav(
    path: Path,
    duration_ms: int,
    *,
    sample_rate: int = 32000,
    channels: int = 1,
    sample_width: int = 2,
) -> None:
    frames = max(0, int(round(sample_rate * duration_ms / 1000)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00" * frames * channels * sample_width)


def read_wav_params(path: Path) -> tuple[int, int, int, bytes]:
    with wave.open(str(path), "rb") as handle:
        return (
            handle.getnchannels(),
            handle.getsampwidth(),
            handle.getframerate(),
            handle.readframes(handle.getnframes()),
        )


def concat_wavs(
    sources: list[tuple[Path | None, int]],
    output: Path,
    *,
    sample_rate: int,
    channels: int = 1,
    sample_width: int = 2,
) -> int:
    """Concatenate WAV files and optional silence gaps.

    sources: list of (wav_path_or_None, silence_ms_after)
    """
    chunks: list[bytes] = []
    total_frames = 0
    for wav_path, silence_ms in sources:
        if wav_path is not None:
            ch, width, rate, data = read_wav_params(wav_path)
            if (ch, width, rate) != (channels, sample_width, sample_rate):
                raise ValueError(
                    f"{wav_path}: expected {channels}ch/{sample_width}b/"
                    f"{sample_rate}Hz, got {ch}/{width}/{rate}"
                )
            chunks.append(data)
            total_frames += len(data) // (channels * sample_width)
        if silence_ms > 0:
            frames = int(round(sample_rate * silence_ms / 1000))
            chunks.append(b"\x00" * frames * channels * sample_width)
            total_frames += frames

    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(sample_rate)
        handle.writeframes(b"".join(chunks))
    return int(round(total_frames * 1000 / sample_rate))


def parse_script_blocks(script_text: str) -> list[dict]:
    matches = list(SCRIPT_BLOCK_RE.finditer(script_text))
    blocks: list[dict] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(script_text)
        body = script_text[start:end].strip()
        script_id = match.group(1)
        ctype = "narration"
        position = None
        type_match = re.search(r"^type:\s*(\w+)\s*$", body, re.MULTILINE | re.IGNORECASE)
        if type_match:
            raw_type = type_match.group(1).strip()
            ctype = "CTA" if raw_type.upper() == "CTA" else raw_type.lower()
        pos_match = re.search(r"^position:\s*(\w+)\s*$", body, re.MULTILINE | re.IGNORECASE)
        if pos_match:
            position = pos_match.group(1).strip().lower()
        text_match = re.search(
            r"Текст:\s*\n(.*?)(?:\n\s*Связанные факты:|\Z)",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if not text_match:
            continue
        text = " ".join(text_match.group(1).strip().split())
        if not text:
            continue
        blocks.append(
            {
                "scriptId": script_id,
                "type": "CTA" if ctype == "CTA" else "narration",
                "position": position,
                "text": text,
            }
        )
    return blocks


SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")


def split_sentences(text: str) -> list[str]:
    """Deterministic sentence split. Never cuts inside a sentence."""
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return []
    parts = SENTENCE_RE.split(cleaned)
    return [part.strip() for part in parts if part.strip()]


def pack_utterances(
    sentences: list[str],
    *,
    prefer_min: int = 40,
    prefer_max: int = 220,
    hard_max: int = 320,
) -> list[str]:
    """Pack 1–3 sentences into utterances. Prefer 40–220 chars, never >320 unless one sentence is longer."""
    if not sentences:
        return []
    utterances: list[str] = []
    buf: list[str] = []

    def buf_text() -> str:
        return " ".join(buf)

    def flush() -> None:
        if buf:
            utterances.append(buf_text())
            buf.clear()

    for sentence in sentences:
        if not buf:
            buf.append(sentence)
            continue
        candidate = f"{buf_text()} {sentence}"
        if len(buf) >= 3 or len(candidate) > hard_max:
            flush()
            buf.append(sentence)
            continue
        current_len = len(buf_text())
        if len(candidate) <= prefer_max:
            buf.append(sentence)
            continue
        if current_len < prefer_min and len(candidate) <= hard_max:
            buf.append(sentence)
            continue
        flush()
        buf.append(sentence)
    flush()
    return utterances


def utterances_from_block(block: dict) -> list[str]:
    return pack_utterances(split_sentences(block.get("text") or ""))


def source_key(script_id: str, utterance_index: int) -> str:
    return f"{script_id}:{utterance_index:03d}"


def default_pause_after_utterance(
    text: str,
    *,
    is_last: bool,
    is_cta: bool,
    script_boundary: bool,
) -> int:
    """Pause between voice segments (not SCRIPT blocks)."""
    if is_last:
        return 0
    if is_cta:
        return 320
    if text.endswith("?"):
        return 300
    if len(text) < 40:
        return 350
    if script_boundary:
        return 400
    return 150


def build_segments_from_blocks(blocks: list[dict], config: dict) -> list[dict]:
    """SCRIPT blocks → semantic utterances → sequential voice-NNN with stable sourceKey."""
    built: list[dict] = []
    voice_index = 1
    for block_index, block in enumerate(blocks):
        utterances = utterances_from_block(block)
        if not utterances:
            continue
        for utt_index, text in enumerate(utterances):
            is_last = (
                block_index == len(blocks) - 1 and utt_index == len(utterances) - 1
            )
            script_boundary = utt_index == len(utterances) - 1 and block_index < len(blocks) - 1
            pause = default_pause_after_utterance(
                text,
                is_last=is_last,
                is_cta=block.get("type") == "CTA",
                script_boundary=script_boundary,
            )
            built.append(
                build_segment(
                    text=text,
                    script_id=block["scriptId"],
                    source_key=source_key(block["scriptId"], utt_index),
                    voice_index=voice_index,
                    config=config,
                    pause_after=pause,
                    seg_type=block.get("type") or "narration",
                    position=block.get("position"),
                )
            )
            voice_index += 1
    return built


def build_segment(
    *,
    text: str,
    script_id: str,
    source_key: str,
    voice_index: int,
    config: dict,
    pause_after: int,
    seg_type: str = "narration",
    position: str | None = None,
) -> dict:
    segment: dict[str, Any] = {
        "id": f"voice-{voice_index:03d}",
        "sourceKey": source_key,
        "script": script_id,
        "type": seg_type,
        "text": text,
        "pauseAfter": pause_after,
        "scene": None,
        "status": "pending",
        "audio": None,
        "durationMs": None,
        "characters": len(text),
        "sha256": None,
        "textSha256": sha256_text(text),
        "settingsSha256": settings_sha256(config),
        "provider": {
            "model": config.get("model"),
            "voiceId": config.get("voiceId"),
        },
        "delivery": {},
    }
    if seg_type == "CTA" and position:
        segment["position"] = position
    return segment


def classify_segment(segment: dict, video_dir: Path, config: dict) -> str:
    audio_rel = segment.get("audio")
    path = video_dir / audio_rel if audio_rel else segment_wav_path(video_dir, segment["id"])
    expected_text = sha256_text(segment.get("text") or "")
    expected_settings = settings_sha256(config)
    status = segment.get("status")

    if status == "failed":
        return "STALE"
    if not path.exists():
        return "MISSING"

    text_ok = segment.get("textSha256") == expected_text
    settings_ok = segment.get("settingsSha256") == expected_settings
    declared_sha = segment.get("sha256")
    file_ok = bool(declared_sha) and sha256_file(path) == declared_sha
    status_ok = status in {"generated", "approved"}

    if status_ok and text_ok and settings_ok and file_ok:
        return "REUSE"

    # Audio exists but hashes missing/mismatch, or status not ready → STALE
    return "STALE"


def apply_interjection(text: str, delivery: dict | None) -> str:
    if not delivery:
        return text
    tag = delivery.get("interjection")
    if not tag:
        return text
    clean = tag.strip().strip("()")
    if f"({clean})" in text:
        return text
    return f"({clean}) {text}"
