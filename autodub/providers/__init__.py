"""Provider registry: look providers up by name with a clear error."""
from __future__ import annotations

from ..errors import InputError
from .stt_fake import FakeSTT
from .stt_whisper import WhisperSTT
from .translate_argos import ArgosTranslator
from .translate_fake import FakeTranslator
from .translate_http import HttpTranslator
from .translate_nllb import NllbTranslator
from .tts_espeak import EspeakTTS
from .tts_fake import FakeTTS
from .tts_piper import PiperTTS

STT_PROVIDERS = {"whisper": WhisperSTT, "fake": FakeSTT}
TRANSLATE_PROVIDERS = {"nllb": NllbTranslator, "argos": ArgosTranslator, "http": HttpTranslator, "fake": FakeTranslator}
TTS_PROVIDERS = {"piper": PiperTTS, "espeak": EspeakTTS, "fake": FakeTTS}


def _make(registry: dict, name: str, kind: str, **kwargs):
    if name not in registry:
        available = ", ".join(sorted(registry))
        raise InputError(f"unknown {kind} provider {name!r}; available: {available}")
    return registry[name](**kwargs)


def make_stt(name: str, model: str | None = None):
    if name == "whisper" and model:
        return _make(STT_PROVIDERS, name, "STT", model_size=model)
    return _make(STT_PROVIDERS, name, "STT")


def make_translator(name: str):
    return _make(TRANSLATE_PROVIDERS, name, "translation")


def make_tts(name: str, voice: str | None = None):
    return _make(TTS_PROVIDERS, name, "TTS", voice=voice)
