#!/usr/bin/env python3
"""Regression: Shorts timeline canvas comes from metadata, not old timeline.json."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from asset_prep_common import write_json
from build_timeline import build


def assert_true(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def test_fresh_shorts_canvas_from_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp_raw:
        video = Path(tmp_raw) / "shorts-pilot"
        for name in (
            "assets",
            "scenes",
            "audio",
            "context",
            "script",
            "research",
            "factcheck",
            "renders",
        ):
            (video / name).mkdir(parents=True)

        write_json(
            video / "metadata.json",
            {
                "slug": "shorts-pilot",
                "title": "Shorts Pilot",
                "status": "timeline",
                "format": "shorts",
                "width": 1080,
                "height": 1920,
                "fps": 30,
                "hardMaxNarrationSec": 72,
                "createdAt": "2026-01-01T00:00:00+00:00",
            },
        )
        write_json(video / "context" / "entities.json", {"version": 1, "entities": []})
        write_json(video / "assets" / "mascot-generation.json", {"version": 1, "jobs": []})
        write_json(
            video / "assets" / "assets.json",
            {"version": 2, "video": "shorts-pilot", "assets": []},
        )
        write_json(
            video / "assets" / "prepared-assets.json",
            {"version": 1, "video": "shorts-pilot", "assets": []},
        )
        write_json(
            video / "scenes" / "visual-plan.json",
            {
                "version": 1,
                "video": "shorts-pilot",
                "scenes": [
                    {
                        "id": "scene-01",
                        "scriptRefs": ["SCRIPT-001"],
                        "primaryType": "TEXT",
                        "layout": "full",
                        "mascot": None,
                        "outfitIntent": None,
                        "supportingVisual": {"type": "TEXT", "assetId": None},
                        "overlay": None,
                        "animation": "hardCut",
                        "assetRequests": [],
                    }
                ],
            },
        )
        write_json(
            video / "audio" / "voice.json",
            {
                "version": 1,
                "segments": [
                    {
                        "id": "voice-001",
                        "sourceKey": "SCRIPT-001:000",
                        "script": "SCRIPT-001",
                        "text": "Тест.",
                        "status": "generated",
                        "durationMs": 1000,
                        "startMs": 0,
                        "endMs": 1000,
                        "pauseAfter": 0,
                    }
                ],
            },
        )
        # Poison: if builder reads old timeline, it would stay landscape.
        write_json(
            video / "scenes" / "timeline.json",
            {
                "version": 1,
                "fps": 30,
                "width": 1920,
                "height": 1080,
                "scenes": [],
                "totalDuration": 1.0,
            },
        )
        (video / "script" / "script.md").write_text(
            "### SCRIPT-001\n\nТекст:\n\nТест.\n", encoding="utf-8"
        )
        (video / "research" / "research.md").write_text("# r\n", encoding="utf-8")
        (video / "factcheck" / "factcheck.md").write_text("# f\n", encoding="utf-8")

        rc = build(video, allow_placeholders=True)
        assert_true(rc == 0, f"build failed rc={rc}")
        payload = json.loads((video / "scenes" / "timeline.json").read_text(encoding="utf-8"))
        assert_true(payload["width"] == 1080, payload)
        assert_true(payload["height"] == 1920, payload)
        assert_true(payload["fps"] == 30, payload)
        assert_true(payload["width"] < payload["height"], "shorts must be portrait")


def main() -> int:
    try:
        test_fresh_shorts_canvas_from_metadata()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  {exc}")
        return 1
    print("OK    fresh_shorts_canvas_from_metadata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
