#!/usr/bin/env python3
"""Deterministic Russian TTS text normalizer for speakable narration."""

from __future__ import annotations

import re
from functools import lru_cache

try:
    from num2words import num2words
except ImportError:  # pragma: no cover
    num2words = None  # type: ignore[assignment]

try:
    import pymorphy3
except ImportError:  # pragma: no cover
    pymorphy3 = None  # type: ignore[assignment]


MONTHS = {
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
}

# Genitive stems for N-летний compounds (1..99).
AGE_STEMS = {
    1: "одно",
    2: "двух",
    3: "трёх",
    4: "четырёх",
    5: "пяти",
    6: "шести",
    7: "семи",
    8: "восьми",
    9: "девяти",
    10: "десяти",
    11: "одиннадцати",
    12: "двенадцати",
    13: "тринадцати",
    14: "четырнадцати",
    15: "пятнадцати",
    16: "шестнадцати",
    17: "семнадцати",
    18: "восемнадцати",
    19: "девятнадцати",
    20: "двадцати",
    21: "двадцатиодно",
    22: "двадцатидвух",
    23: "двадцатитрёх",
    24: "двадцатичетырёх",
    25: "двадцатипяти",
    26: "двадцатишести",
    27: "двадцатисеми",
    28: "двадцативосьми",
    29: "двадцатидевяти",
    30: "тридцати",
    31: "тридцатиодно",
    32: "тридцатидвух",
    33: "тридцатитрёх",
    34: "тридцатичетырёх",
    35: "тридцатипяти",
    36: "тридцатишести",
    37: "тридцатисеми",
    38: "тридцативосьми",
    39: "тридцатидевяти",
    40: "сорока",
    41: "сорокаодно",
    42: "сорокадвух",
    43: "сорокатрёх",
    44: "сорокачетырёх",
    45: "сорокапяти",
    46: "сорокашести",
    47: "сорокасеми",
    48: "сорокавосьми",
    49: "сорокадевяти",
    50: "пятидесяти",
    60: "шестидесяти",
    70: "семидесяти",
    80: "восьмидесяти",
    90: "девяноста",
}


@lru_cache(maxsize=1)
def _morph():
    if pymorphy3 is None:
        return None
    return pymorphy3.MorphAnalyzer()


def _require_num2words() -> None:
    if num2words is None:
        raise RuntimeError("num2words is required; pip install num2words")


def cardinal(n: int) -> str:
    _require_num2words()
    return num2words(n, lang="ru")


def ordinal(n: int) -> str:
    _require_num2words()
    return num2words(n, lang="ru", to="ordinal")


def inflect_phrase(phrase: str, case: str, gender: str = "masc") -> str:
    """Inflect the last adjective/numeral word of an ordinal phrase."""
    morph = _morph()
    words = phrase.split()
    if not words:
        return phrase
    if morph is None:
        return phrase
    last = words[-1]
    parses = morph.parse(last)
    if not parses:
        return phrase
    preferred = None
    for item in parses:
        if "ADJF" in item.tag and gender in item.tag:
            preferred = item
            break
    if preferred is None:
        for item in parses:
            if "ADJF" in item.tag:
                preferred = item
                break
    if preferred is None:
        preferred = parses[0]
    form = preferred.inflect({case, gender, "sing"})
    if form is None:
        form = preferred.inflect({case, gender})
    if form is None:
        form = preferred.inflect({case})
    if form is None:
        return phrase
    words[-1] = form.word
    return " ".join(words)


def ordinal_words(n: int, case: str = "nomn", gender: str = "masc") -> str:
    """Ordinal number with the grammatical form implied by Russian numeric suffixes."""
    base = ordinal(n)
    if case == "nomn" and gender == "masc":
        return base
    return inflect_phrase(base, case, gender)


def year_words(year: int, case: str = "nomn") -> str:
    """две тысячи двадцать третий / ...третьем / ...третьего"""
    base = ordinal(year)
    if case == "nomn":
        return base
    return inflect_phrase(base, case)


def day_words(day: int, case: str = "gent") -> str:
    base = ordinal(day)
    if case == "nomn":
        return base
    return inflect_phrase(base, case)


def short_year_pair(yy: int) -> str:
    """24 → двадцать четыре"""
    return cardinal(yy)


def age_stem(n: int) -> str | None:
    if n in AGE_STEMS:
        return AGE_STEMS[n]
    if n > 50 and n < 100 and (n % 10) != 0:
        tens = (n // 10) * 10
        ones = n % 10
        if tens in AGE_STEMS and ones in AGE_STEMS:
            # 55 → пятидесятипяти
            tens_stem = AGE_STEMS[tens]
            ones_stem = AGE_STEMS[ones]
            return f"{tens_stem}{ones_stem}"
    return None


def protect_tokens(text: str) -> tuple[str, dict[str, str]]:
    """Mask IDs/URLs/hashes so generic number rules do not touch them."""
    vault: dict[str, str] = {}

    patterns = [
        r"https?://\S+",
        r"\bFACT-\d+\b",
        r"\bSCRIPT-[A-Z0-9-]+\b",
        r"\bvoice-\d+\b",
        r"\b[a-f0-9]{32,64}\b",
        r"\b\d+\.\d+\.\d+\b",
    ]

    def stash(match: re.Match[str]) -> str:
        key = f"__TTS_PROTECT_{len(vault)}__"
        vault[key] = match.group(0)
        return key

    out = text
    for pattern in patterns:
        out = re.sub(pattern, stash, out, flags=re.IGNORECASE)
    return out, vault


def restore_tokens(text: str, vault: dict[str, str]) -> str:
    out = text
    for key, value in vault.items():
        out = out.replace(key, value)
    return out


def normalize_dates(text: str) -> str:
    months = "|".join(sorted(MONTHS, key=len, reverse=True))
    dash = r"[-‑–—]"

    def repl_day_year_word(match: re.Match[str]) -> str:
        day = int(match.group(1))
        month = match.group(2)
        year = int(match.group(3))
        return f"{day_words(day, 'gent')} {month} {year_words(year, 'gent')} года"

    def repl_day_year_suffix(match: re.Match[str]) -> str:
        day = int(match.group(1))
        month = match.group(2)
        year = int(match.group(3))
        return f"{day_words(day, 'gent')} {month} {year_words(year, 'gent')}"

    def repl_day_month(match: re.Match[str]) -> str:
        day = int(match.group(1))
        month = match.group(2)
        return f"{day_words(day, 'gent')} {month}"

    # Full dates first, before the generic day+month rule consumes their prefix.
    text = re.sub(
        rf"\b(\d{{1,2}})\s+({months})\s+(\d{{4}})\s+года\b",
        repl_day_year_word,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"\b(\d{{1,2}})\s+({months})\s+(\d{{4}}){dash}(?:го|ого)\b",
        repl_day_year_suffix,
        text,
        flags=re.IGNORECASE,
    )
    # Calendar days without an explicit year are ordinal/genitive in Russian.
    text = re.sub(
        rf"\b(\d{{1,2}})\s+({months})\b",
        repl_day_month,
        text,
        flags=re.IGNORECASE,
    )
    return text


def normalize_seasons(text: str) -> str:
    def season_pair(y1: int, y2: int) -> str:
        left = short_year_pair(y1 % 100)
        right = short_year_pair(y2 if y2 >= 100 else y2)
        return f"{left} — {right}"

    def with_word(match: re.Match[str]) -> str:
        return f"{match.group(1)} {season_pair(int(match.group(2)), int(match.group(3)))}"

    def bare(match: re.Match[str]) -> str:
        return season_pair(int(match.group(1)), int(match.group(2)))

    text = re.sub(r"\b([Сс]езон)\s+(\d{4})\s*/\s*(\d{2,4})\b", with_word, text)
    text = re.sub(r"\b(\d{4})\s*/\s*(\d{2,4})\b", bare, text)
    return text


def normalize_scores(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"{cardinal(int(match.group(1)))} {cardinal(int(match.group(2)))}"

    return re.sub(r"\b(\d{1,2})\s*:\s*(\d{1,2})\b", repl, text)


def normalize_years(text: str) -> str:
    def year_prep(match: re.Match[str]) -> str:
        return f"{match.group(1)} {year_words(int(match.group(2)), 'loct')} году"

    def year_prep_short(match: re.Match[str]) -> str:
        return f"{match.group(1)} {year_words(int(match.group(2)), 'loct')}"

    def year_gen_until(match: re.Match[str]) -> str:
        return f"{match.group(1)} {year_words(int(match.group(2)), 'gent')} года"

    def year_gen_bare(match: re.Match[str]) -> str:
        return f"{year_words(int(match.group(1)), 'gent')} года"

    def year_nom(match: re.Match[str]) -> str:
        return f"{year_words(int(match.group(1)), 'nomn')} год"

    text = re.sub(r"\b(в|во)\s+(\d{4})\s+году\b", year_prep, text, flags=re.IGNORECASE)
    text = re.sub(r"\b(в|во)\s+(\d{4})-м\b", year_prep_short, text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b(до|с|после|от)\s+(\d{4})\s+года\b",
        year_gen_until,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(\d{4})\s+года\b", year_gen_bare, text)
    text = re.sub(r"\b(\d{4})\s+год\b", year_nom, text)
    return text


def normalize_ordinal_suffixes(text: str) -> str:
    """Expand Russian numeric ordinals such as 8-го, 8-е, 2026-й."""
    dash = r"[-‑–—]"
    suffix_forms = {
        "го": ("gent", "masc"),
        "ого": ("gent", "masc"),
        "му": ("datv", "masc"),
        "ому": ("datv", "masc"),
        "м": ("loct", "masc"),
        "ом": ("loct", "masc"),
        "е": ("nomn", "neut"),
        "ое": ("nomn", "neut"),
        "й": ("nomn", "masc"),
        "ый": ("nomn", "masc"),
        "ий": ("nomn", "masc"),
    }
    suffixes = "|".join(sorted(suffix_forms, key=len, reverse=True))

    def repl(match: re.Match[str]) -> str:
        number = int(match.group(1))
        suffix = match.group(2).lower()
        case, gender = suffix_forms[suffix]
        return ordinal_words(number, case, gender)

    return re.sub(
        rf"\b(\d{{1,4}}){dash}({suffixes})\b",
        repl,
        text,
        flags=re.IGNORECASE,
    )


def normalize_ages(text: str) -> str:
    def hyphen_age(match: re.Match[str]) -> str:
        n = int(match.group(1))
        ending = match.group(2)  # летний / летнего / ...
        stem = age_stem(n)
        if stem is None:
            return match.group(0)
        return f"{stem}{ending}"

    def years_old(match: re.Match[str]) -> str:
        n = int(match.group(1))
        word = match.group(2)
        return f"{cardinal(n)} {word}"

    text = re.sub(
        r"\b(\d{1,2})-(летн(?:ий|его|ему|им|ем|яя|юю|ей|ие|их|ими))\b",
        hyphen_age,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(\d{1,2})\s+(лет|года|год)\b", years_old, text, flags=re.IGNORECASE)
    return text


def normalize_percentages(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        n = int(match.group(1))
        return f"{cardinal(n)} процентов"

    return re.sub(r"\b(\d{1,3})\s*%", repl, text)


def normalize_jersey(text: str) -> str:
    text = re.sub(
        r"№\s*(\d{1,2})\b",
        lambda m: f"номер {cardinal(int(m.group(1)))}",
        text,
    )
    text = re.sub(
        r"\b[Нн]омер\s+(\d{1,2})\b",
        lambda m: f"номер {cardinal(int(m.group(1)))}",
        text,
    )
    return text


def normalize_generic_numbers(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(0)
        # Skip protected leftovers and long ids.
        if raw.startswith("__TTS_PROTECT_"):
            return raw
        n = int(raw)
        # Avoid rewriting lone years that were not caught (keep as words if 19xx/20xx standalone
        # only when surrounded by spaces and not part of larger token — still convert).
        return cardinal(n)

    return re.sub(r"\b\d{1,4}\b", repl, text)


def cleanup_whitespace(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()


def normalize_russian_tts(text: str) -> str:
    """Convert machine-written numbers/markers into speakable Russian."""
    if not text:
        return text
    protected, vault = protect_tokens(text)
    out = protected
    out = normalize_dates(out)
    out = normalize_seasons(out)
    out = normalize_scores(out)
    out = normalize_years(out)
    out = normalize_ordinal_suffixes(out)
    out = normalize_ages(out)
    out = normalize_percentages(out)
    out = normalize_jersey(out)
    out = normalize_generic_numbers(out)
    out = restore_tokens(out, vault)
    out = cleanup_whitespace(out)
    return out


def apply_overrides(text: str, override: dict | None) -> str:
    """Apply replacements then optional explicit ttsText."""
    if not override:
        return text
    out = text
    for src, dst in (override.get("replacements") or {}).items():
        out = out.replace(str(src), str(dst))
    explicit = override.get("ttsText")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    return out


def build_tts_text(source_text: str, override: dict | None = None) -> str:
    """script text → normalize → replacements → explicit ttsText."""
    normalized = normalize_russian_tts(source_text)
    return apply_overrides(normalized, override)
