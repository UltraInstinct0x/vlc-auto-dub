"""Language-code validation and normalisation.

We accept ISO 639-1/639-2 style primary subtags with an optional region
(``en``, ``tr``, ``pt-BR``). We normalise to ``language[-REGION]`` with a
lowercase language subtag. We deliberately do not ship a full code table;
a code is either well-formed or rejected with a clear message.
"""
from __future__ import annotations

import re

from .errors import InputError

_CODE_RE = re.compile(r"^([A-Za-z]{2,3})(?:[-_]([A-Za-z]{2}|[0-9]{3}))?$")


def normalize_code(code: str) -> str:
    """Validate and normalise a language code, or raise :class:`InputError`."""
    if not code or not code.strip():
        raise InputError("language code is empty")
    m = _CODE_RE.match(code.strip())
    if not m:
        raise InputError(
            f"invalid language code {code!r}: expected a code like 'en', 'tr' or 'pt-BR'"
        )
    lang = m.group(1).lower()
    region = m.group(2)
    return f"{lang}-{region.upper()}" if region else lang


def primary_subtag(code: str) -> str:
    """Return just the primary subtag (``pt-BR`` -> ``pt``)."""
    return normalize_code(code).split("-")[0]


# ISO 639-1 -> ISO 639-2/B, the form Matroska and MP4 track tags use.
_ISO639_2 = {
    "ar": "ara", "bg": "bul", "ca": "cat", "cs": "cze", "da": "dan", "de": "ger",
    "el": "gre", "en": "eng", "es": "spa", "et": "est", "fa": "per", "fi": "fin",
    "fr": "fre", "he": "heb", "hi": "hin", "hr": "hrv", "hu": "hun", "id": "ind",
    "it": "ita", "ja": "jpn", "ko": "kor", "lt": "lit", "lv": "lav", "nl": "dut",
    "no": "nor", "pl": "pol", "pt": "por", "ro": "rum", "ru": "rus", "sk": "slo",
    "sl": "slv", "sr": "srp", "sv": "swe", "th": "tha", "tr": "tur", "uk": "ukr",
    "vi": "vie", "zh": "chi",
}


def track_language(code: str | None) -> str:
    """Return the 3-letter track language tag for ``code`` (``und`` if unknown)."""
    if not code:
        return "und"
    primary = primary_subtag(code)
    if len(primary) == 3:
        return primary
    return _ISO639_2.get(primary, "und")
