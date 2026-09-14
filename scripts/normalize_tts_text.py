#!/usr/bin/env python3
"""CLI for Russian TTS text normalization."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voice_normalizer import normalize_russian_tts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="?", help="Text to normalize")
    parser.add_argument("--file", help="Read text from a UTF-8 file")
    args = parser.parse_args()
    if args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        raw = args.text
    else:
        parser.error("pass text or --file")
    print(normalize_russian_tts(raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
