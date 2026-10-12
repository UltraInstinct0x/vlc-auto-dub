"""TTS voice selection that follows the target language.

Policy
------
- ``espeak``: the target language code *is* the espeak-ng voice (espeak-ng
  ships ``de``, ``fr``, ``es``, ``tr``, ``ru``, ``it`` ...). If espeak-ng does
  not ship it, the provider raises a clear error rather than guessing.
- ``piper``: a small map of known language -> voice. A language not in the map
  falls back to the default English voice, and the run records a warning so the
  fallback is never silent.
- other providers (e.g. the test fake): no voice selection.
"""
from __future__ import annotations

DEFAULT_PIPER_VOICE = "en_US-lessac-medium"
DEFAULT_ESPEAK_VOICE = "en"

# Verified against the rhasspy/piper-voices index (medium quality, one per lang).
PIPER_VOICE_BY_LANG = {
    "en": "en_US-lessac-medium",
    "de": "de_DE-thorsten-medium",
    "fr": "fr_FR-siwis-medium",
    "es": "es_ES-davefx-medium",
    "it": "it_IT-paola-medium",
    "tr": "tr_TR-dfki-medium",
    "ru": "ru_RU-dmitri-medium",
    "pt": "pt_BR-faber-medium",
}


def effective_voice(provider: str, lang: str | None) -> tuple[str | None, str | None]:
    """Return ``(voice, warning)`` for ``provider`` targeting ``lang``.

    ``warning`` is a human-readable note when a documented fallback was used.
    """
    if provider == "espeak":
        return (lang or DEFAULT_ESPEAK_VOICE), None
    if provider == "piper":
        if lang and lang in PIPER_VOICE_BY_LANG:
            return PIPER_VOICE_BY_LANG[lang], None
        if not lang:
            return DEFAULT_PIPER_VOICE, None
        return (
            DEFAULT_PIPER_VOICE,
            f"no piper voice mapped for language {lang!r}; using {DEFAULT_PIPER_VOICE}",
        )
    return None, None
