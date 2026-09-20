#!/usr/bin/env python3
"""Official MiniMax HTTP T2A client. Never logs the API key."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voice_common import load_dotenv, load_voice_config

load_dotenv()

API_URL = "https://api.minimax.io/v1/t2a_v2"
ENV_KEY = "MINIMAX_API_KEY"

# Do not retry these MiniMax / HTTP failures.
NON_RETRYABLE_HTTP = {400, 401, 403, 404, 422}
NON_RETRYABLE_BASE = {1004, 2013, 2042}  # auth / invalid params family


class MiniMaxTTSError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        status_code: int | None = None,
        status_msg: str | None = None,
        trace_id: str | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.status_code = status_code
        self.status_msg = status_msg
        self.trace_id = trace_id
        self.retryable = retryable


class MiniMaxTTS:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        config: dict | None = None,
        api_url: str = API_URL,
        timeout: int = 120,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get(ENV_KEY, "")
        self.config = config if config is not None else load_voice_config()
        self.api_url = api_url
        self.timeout = timeout

    def require_api_key(self) -> str:
        if not self.api_key:
            raise MiniMaxTTSError(
                f"{ENV_KEY} is not set",
                retryable=False,
            )
        return self.api_key

    def build_payload(self, text: str, settings: dict | None = None) -> dict[str, Any]:
        cfg = {**self.config, **(settings or {})}
        voice = cfg.get("voiceSetting") or {}
        audio = cfg.get("audioSetting") or {}
        payload: dict[str, Any] = {
            "model": cfg.get("model", "speech-2.8-hd"),
            "text": text,
            "stream": False,
            "language_boost": cfg.get("languageBoost", "Russian"),
            "output_format": cfg.get("outputFormat", "hex"),
            "subtitle_enable": bool(cfg.get("subtitleEnable", False)),
            "voice_setting": {
                "voice_id": cfg.get("voiceId"),
                "speed": voice.get("speed", 1.05),
                "vol": voice.get("vol", 1),
                "pitch": voice.get("pitch", 0),
            },
            "audio_setting": {
                "sample_rate": audio.get("sampleRate", 32000),
                "bitrate": audio.get("bitrate", 128000),
                "format": audio.get("format", "wav"),
                "channel": audio.get("channel", 1),
            },
        }
        pronunciation = cfg.get("pronunciation") or {}
        tones = pronunciation.get("tone") or []
        if tones:
            payload["pronunciation_dict"] = {"tone": list(tones)}
        if cfg.get("voiceModify"):
            payload["voice_modify"] = cfg["voiceModify"]
        return payload

    def _post(self, payload: dict) -> tuple[int, dict]:
        key = self.require_api_key()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.api_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                http_status = response.getcode()
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"raw": raw}
            raise MiniMaxTTSError(
                f"HTTP {exc.code}",
                http_status=exc.code,
                status_code=(data.get("base_resp") or {}).get("status_code"),
                status_msg=(data.get("base_resp") or {}).get("status_msg") or raw[:300],
                trace_id=data.get("trace_id"),
                retryable=exc.code not in NON_RETRYABLE_HTTP,
            ) from exc
        except urllib.error.URLError as exc:
            raise MiniMaxTTSError(f"network error: {exc.reason}", retryable=True) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MiniMaxTTSError(
                "response is not JSON",
                http_status=http_status,
                retryable=False,
            ) from exc
        return http_status, data

    def synthesize(
        self,
        text: str,
        output_path: str | Path,
        settings: dict | None = None,
        *,
        retries: int = 3,
    ) -> dict[str, Any]:
        if not text or not str(text).strip():
            raise MiniMaxTTSError("text is empty", retryable=False)

        payload = self.build_payload(text, settings)
        delays = [2, 4, 8]
        last_error: MiniMaxTTSError | None = None
        attempts = max(1, retries)

        for attempt in range(attempts):
            try:
                http_status, data = self._post(payload)
                base = data.get("base_resp") or {}
                status_code = base.get("status_code")
                status_msg = base.get("status_msg")
                trace_id = data.get("trace_id")
                if status_code not in (0, None):
                    raise MiniMaxTTSError(
                        f"MiniMax status_code={status_code}",
                        http_status=http_status,
                        status_code=status_code,
                        status_msg=status_msg,
                        trace_id=trace_id,
                        retryable=status_code not in NON_RETRYABLE_BASE,
                    )
                audio_hex = (data.get("data") or {}).get("audio")
                if not audio_hex:
                    raise MiniMaxTTSError(
                        "response missing data.audio",
                        http_status=http_status,
                        status_code=status_code,
                        status_msg=status_msg,
                        trace_id=trace_id,
                        retryable=False,
                    )
                audio_bytes = bytes.fromhex(audio_hex)
                out = Path(output_path)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(audio_bytes)
                extra = data.get("extra_info") or {}
                return {
                    "path": str(out),
                    "bytes": len(audio_bytes),
                    "http_status": http_status,
                    "trace_id": trace_id,
                    "extra_info": extra,
                    "characters": extra.get("usage_characters") or extra.get("word_count"),
                    "audio_length_ms": extra.get("audio_length"),
                }
            except MiniMaxTTSError as exc:
                last_error = exc
                if not exc.retryable or attempt >= attempts - 1:
                    self._print_error(exc)
                    raise
                delay = delays[min(attempt, len(delays) - 1)]
                print(
                    f"WARN  MiniMax retry {attempt + 1}/{attempts} in {delay}s "
                    f"(http={exc.http_status} code={exc.status_code} msg={exc.status_msg})"
                )
                time.sleep(delay)

        assert last_error is not None
        self._print_error(last_error)
        raise last_error

    @staticmethod
    def _print_error(exc: MiniMaxTTSError) -> None:
        print(
            "ERROR MiniMax TTS failed\n"
            f"  HTTP status: {exc.http_status}\n"
            f"  MiniMax status_code: {exc.status_code}\n"
            f"  status_msg: {exc.status_msg}\n"
            f"  trace_id: {exc.trace_id}"
        )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()
    client = MiniMaxTTS()
    meta = client.synthesize(args.text, args.output, retries=args.retries)
    print(f"OK    wrote {meta['path']} ({meta['bytes']} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
