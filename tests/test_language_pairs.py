"""Language generality: arbitrary ISO-ish codes, on-demand packs, clear errors.

- real argos packs must work for a NON en->tr pair (en->de) and for en->tr;
- an unsupported pair must raise a clear, actionable error (never produce
  source-language audio labelled as the target);
- TTS voice selection must follow the target language with a documented
  fallback.
"""
from __future__ import annotations

import importlib.util

import pytest

from autodub.errors import ProviderError
from autodub.voices import (
    DEFAULT_PIPER_VOICE,
    effective_voice,
)
from autodub.config import build_config
from autodub.pipeline import run

_HAS_ARGOS = importlib.util.find_spec("argostranslate") is not None


@pytest.mark.skipif(not _HAS_ARGOS, reason="argostranslate not installed")
@pytest.mark.parametrize("source,target,text", [
    ("en", "de", "Good morning, the meeting starts at nine."),
    ("en", "tr", "Good morning, the meeting starts at nine."),
    ("de", "en", "Guten Morgen, das Meeting beginnt um neun Uhr."),
])
def test_real_argos_pairs(source, target, text):
    from autodub.providers.translate_argos import ArgosTranslator

    out = ArgosTranslator().translate(text, source, target)
    assert out and out.lower() != text.lower(), f"no {source}->{target} translation produced"
    assert isinstance(out, str)


@pytest.mark.skipif(not _HAS_ARGOS, reason="argostranslate not installed")
def test_unsupported_pair_raises_actionable_error(monkeypatch):
    import argostranslate.package as pkg
    from autodub.providers.translate_argos import ArgosTranslator

    # Deterministic: force the package index to report no packages at all.
    monkeypatch.setattr(pkg, "update_package_index", lambda: None)
    monkeypatch.setattr(pkg, "get_available_packages", lambda: [])

    with pytest.raises(ProviderError) as exc:
        ArgosTranslator().translate("hello", "en", "zz")
    msg = str(exc.value)
    assert "'en'" in msg and "'zz'" in msg
    assert "argospm" in msg  # names the exact install command


def test_unsupported_pair_does_not_emit_target_audio(tone_video, tmp_path, monkeypatch):
    """A failing translation aborts the run and leaves no output to mistake for a dub."""
    from autodub.providers import translate_fake
    import autodub.pipeline as pipeline

    class BoomTranslator:
        def translate(self, text, source, target):
            raise ProviderError(f"no translation available for {source}->{target}")

    monkeypatch.setattr(pipeline, "make_translator", lambda name: BoomTranslator())
    base = tmp_path / "out"
    with pytest.raises(ProviderError):
        run(tone_video, str(base), build_config(
            stt="fake", tts="fake", source_lang="en", target_lang="zz"))
    # nothing that could be mistaken for a finished target-language dub
    assert not (tmp_path / "out_dubbed.mp4").exists()
    assert not (tmp_path / "out.srt").exists()


def test_voice_follows_target_language():
    # espeak uses the language code directly
    assert effective_voice("espeak", "de") == ("de", None)
    # piper maps to a real voice
    assert effective_voice("piper", "de") == ("de_DE-thorsten-medium", None)
    assert effective_voice("piper", "tr") == ("tr_TR-dfki-medium", None)
    # documented fallback for an unmapped language
    voice, warning = effective_voice("piper", "xx")
    assert voice == DEFAULT_PIPER_VOICE
    assert warning and "xx" in warning


def test_http_backend_is_off_by_default(monkeypatch):
    """The external backend must refuse unless explicitly configured."""
    from autodub.providers.translate_http import HttpTranslator
    from autodub.errors import DependencyError

    monkeypatch.delenv("AUTODUB_TRANSLATE_URL", raising=False)
    monkeypatch.delenv("AUTODUB_TRANSLATE_KEY", raising=False)
    with pytest.raises(DependencyError) as exc:
        HttpTranslator().translate("hello", "en", "de")
    assert "AUTODUB_TRANSLATE_URL" in str(exc.value)
