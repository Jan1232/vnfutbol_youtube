#!/usr/bin/env python3
"""Unit tests for normalize_russian_tts."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voice_normalizer import normalize_russian_tts

CASES = {
    "2002 год": "две тысячи второй год",
    "в 2002 году": "в две тысячи втором году",
    "до 2002 года": "до две тысячи второго года",
    "2026 года": "две тысячи двадцать шестого года",
    "29 апреля 2023 года": "двадцать девятого апреля две тысячи двадцать третьего года",
    "15 лет": "пятнадцать лет",
    "19-летний": "девятнадцатилетний",
    "39-летнего": "тридцатидевятилетнего",
    "1:0": "один ноль",
    "2:1": "два один",
    "77%": "семьдесят семь процентов",
    "2024/25": "двадцать четыре — двадцать пять",
    "сезон 2025/26": "сезон двадцать пять — двадцать шесть",
    "В 2025-м": "В две тысячи двадцать пятом",
    "№10": "номер десять",
    "11 ноября 2022-го": "одиннадцатого ноября две тысячи двадцать второго",
    "6 ноября": "шестого ноября",
    "8-го": "восьмого",
    "9-го": "девятого",
    "исправил дату на 8-е": "исправил дату на восьмое",
    "25 января 2022 года": "двадцать пятого января две тысячи двадцать второго года",
    "2022-го": "две тысячи двадцать второго",
    "2023-м": "две тысячи двадцать третьем",
    "2026-й": "две тысячи двадцать шестой",
}


def main() -> int:
    failed = 0
    for src, expected in CASES.items():
        got = normalize_russian_tts(src)
        if got != expected:
            print(f"FAIL  {src!r}\n  expected: {expected!r}\n  got:      {got!r}")
            failed += 1
        else:
            print(f"OK    {src!r} -> {got!r}")
    # Conservatism: do not rewrite IDs
    protected = normalize_russian_tts("См. FACT-001 и SCRIPT-004")
    if "FACT-001" not in protected or "SCRIPT-004" not in protected:
        print(f"FAIL  protected ids corrupted: {protected!r}")
        failed += 1
    else:
        print("OK    protected ids")
    if failed:
        print(f"FAIL  {failed} case(s)")
        return 1
    print("PASS  voice normalizer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
