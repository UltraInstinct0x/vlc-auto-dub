"""Runtime configuration: file + environment, with documented defaults.

Precedence (lowest to highest): built-in defaults < config file < CLI flags.
Environment variables ``AUTODUB_STT`` etc. override the built-in default only
when no config file value is present, keeping CLI flags authoritative.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

# Defaults are documented in README/design.md.
DEFAULT_STT = "whisper"
DEFAULT_TRANSLATE = "argos"
DEFAULT_TTS = "piper"
# Assembled audio may differ from the source by at most this many seconds.
DEFAULT_DURATION_TOLERANCE = 0.5


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
    duration_tolerance: float = DEFAULT_DURATION_TOLERANCE


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
    )
