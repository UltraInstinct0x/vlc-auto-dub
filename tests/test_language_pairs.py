"""Language generality: arbitrary ISO-ish codes, on-demand packs, clear errors.

The real-argos tests establish their own precondition: they install/verify the
required pack and **fail loudly** (never skip) if it cannot be made available.
"""
from __future__ import annotations

import os

import pytest

from autodub.errors import DependencyError, ProviderError
from autodub.voices import DEFAULT_PIPER_VOICE, effective_voice
from autodub.config import build_config
from autodub.pipeline import run


def _require_argos():
    try:
        import argostranslate  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        pytest.fail(f"argostranslate is required for these tests: {exc}")


def ensure_argos_pair(source: str, target: str) -> None:
    """Guarantee the argos pack for ``source->target`` is installed and resolves.

    Fails the test with a clear, actionable message if it cannot be installed;
    never silently skips or passes.
    """
    _require_argos()
    import argostranslate.package as pkg
    from argostranslate.translate import (
        get_installed_languages,
        get_translation_from_codes,
    )

    def resolves() -> bool:
        get_installed_languages.cache_clear()
        try:
            get_translation_from_codes(source, target)
            return True
        except Exception:
            return False

    if resolves():
        return

    try:
        pkg.update_package_index()
        available = [
            p for p in pkg.get_available_packages()
            if p.from_code == source and p.to_code == target
        ]
    except Exception as exc:
        pytest.fail(
            f"cannot reach the argos package index to install "
            f"translate-{source}_{target}: {exc}. Install manually: "
            f"argospm install translate-{source}_{target}"
        )
    if not available:
        pytest.fail(
            f"argos pack translate-{source}_{target} is not in the index. "
            f"Install manually: argospm install translate-{source}_{target}"
        )
    pkg.install_from_path(available[0].download())
    if not resolves():
        pytest.fail(
            f"installed translate-{source}_{target} but it still does not resolve; "
            f"the install may be corrupt."
        )


@pytest.mark.parametrize("source,target,text", [
    ("en", "de", "Good morning, the meeting starts at nine."),
    ("en", "tr", "Good morning, the meeting starts at nine."),
    ("de", "en", "Guten Morgen, das Meeting beginnt um neun Uhr."),
])
def test_real_argos_pairs(source, target, text):
    ensure_argos_pair(source, target)
    from autodub.providers.translate_argos import ArgosTranslator

    out = ArgosTranslator().translate(text, source, target)
    assert out and out.strip().lower() != text.strip().lower(), (
        f"argos returned the {source}->{target} source text unchanged"
    )
    assert isinstance(out, str)


def test_noop_translation_is_rejected(tone_video, tmp_path, monkeypatch):
    """A translation that returns the source text verbatim must fail loudly."""
    import autodub.pipeline as pipeline

    class IdentityTranslator:
        def translate(self, text, source, target):
            return text  # the dangerous silent no-op

    monkeypatch.setattr(pipeline, "make_translator", lambda name: IdentityTranslator())
    base = tmp_path / "out"
    with pytest.raises(ProviderError) as exc:
        run(tone_video, str(base), build_config(
            stt="fake", tts="fake", source_lang="en", target_lang="de"))
    msg = str(exc.value)
    assert "'en'" in msg and "'de'" in msg and "argospm" in msg
    # and nothing was written that could be mistaken for a target-language dub
    assert not (tmp_path / "out.srt").exists()
    assert not (tmp_path / "out_dubbed.mp4").exists()


def test_unsupported_pair_raises_actionable_error(monkeypatch):
    _require_argos()
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
    import autodub.pipeline as pipeline

    class BoomTranslator:
        def translate(self, text, source, target):
            raise ProviderError(f"no translation available for {source}->{target}")

    monkeypatch.setattr(pipeline, "make_translator", lambda name: BoomTranslator())
    base = tmp_path / "out"
    with pytest.raises(ProviderError):
        run(tone_video, str(base), build_config(
            stt="fake", tts="fake", source_lang="en", target_lang="zz"))
    assert not (tmp_path / "out_dubbed.mp4").exists()
    assert not (tmp_path / "out.srt").exists()


def test_voice_follows_target_language():
    assert effective_voice("espeak", "de") == ("de", None)
    assert effective_voice("piper", "de") == ("de_DE-thorsten-medium", None)
    assert effective_voice("piper", "tr") == ("tr_TR-dfki-medium", None)
    voice, warning = effective_voice("piper", "xx")
    assert voice == DEFAULT_PIPER_VOICE
    assert warning and "xx" in warning


def test_http_backend_is_off_by_default(monkeypatch):
    """The external backend must refuse unless explicitly configured."""
    from autodub.providers.translate_http import HttpTranslator

    monkeypatch.delenv("AUTODUB_TRANSLATE_URL", raising=False)
    monkeypatch.delenv("AUTODUB_TRANSLATE_KEY", raising=False)
    with pytest.raises(DependencyError) as exc:
        HttpTranslator().translate("hello", "en", "de")
    assert "AUTODUB_TRANSLATE_URL" in str(exc.value)
