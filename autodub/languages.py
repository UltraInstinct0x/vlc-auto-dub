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
