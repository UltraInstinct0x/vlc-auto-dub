"""Runtime configuration: file + environment, with documented defaults.

Precedence (lowest to highest): built-in defaults < config file < CLI flags.
Environment variables ``AUTODUB_STT`` etc. override the built-in default only
when no config file value is present, keeping CLI flags authoritative.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .errors import InputError

# Defaults are documented in README/design.md.
DEFAULT_STT = "whisper"
DEFAULT_TRANSLATE = "nllb"
DEFAULT_TTS = "piper"
# Assembled audio may differ from the source by at most this many seconds.
DEFAULT_DURATION_TOLERANCE = 0.5
# Dub loudness (1.0 = as synthesized) and how loud the original speech stays
# under it (0.0 = the dub replaces it, the historical behaviour).
DEFAULT_DUB_VOLUME = 1.0
DEFAULT_ORIGINAL_VOLUME = 0.0
MAX_DUB_VOLUME = 3.0


@dataclass
class Config:
    stt: str = DEFAULT_STT
    translate: str = DEFAULT_TRANSLATE
    tts: str = DEFAULT_TTS
    voice: str | None = None
    source_lang: str | None = None
    target_lang: str | None = None
    subtitle_only: bool = False
    keep_workdir: bool = False
    in_place: bool = False
    dub_only: bool = False
    whisper_model: str | None = None
    sound_tags: bool = True
    use_embedded_subs: bool = False
    dub_volume: float = DEFAULT_DUB_VOLUME
    original_volume: float = DEFAULT_ORIGINAL_VOLUME
    duration_tolerance: float = DEFAULT_DURATION_TOLERANCE


def _volume(value, name: str, maximum: float) -> float:
    """Parse a linear gain (1.0 = unchanged) and check it is in range."""
    try:
        gain = float(value)
    except (TypeError, ValueError):
        raise InputError(f"{name} must be a number, got {value!r}") from None
    if not 0.0 <= gain <= maximum:
        raise InputError(f"{name} must be between 0 and {maximum:g}, got {gain:g}")
    return gain


def _load_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith(".json"):
        return json.loads(text)
    # Plain ``key = value`` lines; ``#`` starts a comment.
    out: dict = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def build_config(
    *,
    config_path: str | None = None,
    stt: str | None = None,
    translate: str | None = None,
    tts: str | None = None,
    voice: str | None = None,
    source_lang: str | None = None,
    target_lang: str | None = None,
    subtitle_only: bool = False,
    keep_workdir: bool = False,
    in_place: bool = False,
    dub_only: bool = False,
    whisper_model: str | None = None,
    sound_tags: bool | None = None,
    use_embedded_subs: bool = False,
    dub_volume: float | None = None,
    original_volume: float | None = None,
) -> Config:
    data: dict = {}
    if config_path:
        data = _load_file(config_path)

    def pick(cli_value, file_key, env_key, default):
        if cli_value is not None:
            return cli_value
        if file_key in data:
            return data[file_key]
        return os.environ.get(env_key, default)

    return Config(
        stt=pick(stt, "stt", "AUTODUB_STT", DEFAULT_STT),
        translate=pick(translate, "translate", "AUTODUB_TRANSLATE", DEFAULT_TRANSLATE),
        tts=pick(tts, "tts", "AUTODUB_TTS", DEFAULT_TTS),
        voice=pick(voice, "voice", "AUTODUB_VOICE", None),
        source_lang=source_lang,
        target_lang=target_lang,
        subtitle_only=subtitle_only,
        keep_workdir=keep_workdir,
        in_place=in_place,
        dub_only=dub_only,
        whisper_model=pick(whisper_model, "whisper_model", "AUTODUB_WHISPER_MODEL", None),
        sound_tags=str(pick(sound_tags, "sound_tags", "AUTODUB_SOUND_TAGS", True)).lower()
        not in ("0", "false", "no", "off"),
        use_embedded_subs=use_embedded_subs,
        dub_volume=_volume(pick(dub_volume, "dub_volume", "AUTODUB_DUB_VOLUME",
                                DEFAULT_DUB_VOLUME), "dub volume", MAX_DUB_VOLUME),
        original_volume=_volume(pick(original_volume, "original_volume",
                                     "AUTODUB_ORIGINAL_VOLUME", DEFAULT_ORIGINAL_VOLUME),
                                "original volume", 1.0),
    )
