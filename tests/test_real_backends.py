"""Real-backend end-to-end: real local STT (faster-whisper) and real local TTS
(espeak-ng). The audio fixture is synthesized speech, so recognition quality is
NOT asserted -- only that a real model produced real segments and a real engine
produced real audio, end to end, with the input unchanged.

Skips (rather than fakes) if a backend is not installed on the host.
"""
from __future__ import annotations

import hashlib
import importlib.util
import shutil

import pytest

from autodub import media
from autodub.config import build_config
from autodub.pipeline import run

import _util

_HAS_WHISPER = importlib.util.find_spec("faster_whisper") is not None
_HAS_ESPEAK = shutil.which("espeak-ng") is not None


@pytest.mark.skipif(not _HAS_WHISPER, reason="faster-whisper not installed")
def test_real_stt_then_real_tts(speech_video, tmp_path):
    base = str(tmp_path / "real")
    cfg = build_config(stt="whisper", tts="espeak", source_lang="en")
    before = hashlib.sha256(open(speech_video, "rb").read()).hexdigest()

    summary = run(speech_video, base, cfg)

    assert hashlib.sha256(open(speech_video, "rb").read()).hexdigest() == before
    assert summary["segment_count"] >= 1, "real STT returned no segments"
    assert media.has_audio_stream(summary["output_video"])
    cues = _util.parse_srt(summary["output_srt"])
    _util.assert_monotonic_nonoverlapping(cues)
    assert abs(summary["dubbed_duration"] - summary["source_duration"]) <= 0.5


@pytest.mark.skipif(
    importlib.util.find_spec("argostranslate") is None, reason="argostranslate not installed"
)
def test_real_translation_en_fr():
    from autodub.providers.translate_argos import ArgosTranslator

    out = ArgosTranslator().translate("Hello, this is a test.", "en", "fr")
    assert out and out.lower() != "hello, this is a test."
    assert isinstance(out, str)
