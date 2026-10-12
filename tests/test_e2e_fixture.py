"""Genuine end-to-end run on an ffmpeg-synthesized fixture.

Real ffmpeg does every media step (extract, fit, assemble, mux); provider
fakes stand in for STT/translate/TTS so the test is deterministic and offline.
The assertions are about the real media glue: streams present, timing within
tolerance, monotonic non-overlapping subtitles, and an unchanged input.
"""
from __future__ import annotations

import hashlib

from autodub import media
from autodub.config import build_config
from autodub.pipeline import run

import _util


def _sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_end_to_end_fixture(tone_video, tmp_path):
    base = str(tmp_path / "out")
    cfg = build_config(stt="fake", translate="fake", tts="fake",
                       source_lang="en", target_lang="tr")

    before = _sha(tone_video)
    summary = run(tone_video, base, cfg)
    after = _sha(tone_video)

    # R3: the source is untouched.
    assert after == before
    assert summary["input"] != summary["output_video"]

    # R2: a real output video exists with both streams.
    out_video = summary["output_video"]
    assert out_video.endswith("_dubbed.mp4")
    assert media.has_audio_stream(out_video)
    assert media.duration(out_video) > 0

    # R2.3/R6: translation ran through the fake and marked the run translated.
    assert summary["translated"] is True

    # R2.7/R4.3: subtitles parse, are ordered and non-overlapping.
    cues = _util.parse_srt(summary["output_srt"])
    assert cues, "expected at least one cue"
    _util.assert_monotonic_nonoverlapping(cues)
    assert all(text.startswith("[tr]") for _s, _e, text in cues)

    # R4.2: assembled audio within tolerance of the source.
    assert abs(summary["dubbed_duration"] - summary["source_duration"]) <= 0.5


def test_subtitle_only(tone_video, tmp_path):
    base = str(tmp_path / "sub")
    summary = run(tone_video, base, build_config(stt="fake", subtitle_only=True))
    assert summary["mode"] == "subtitle-only"
    assert _util.parse_srt(summary["output_srt"])
    import os
    assert not os.path.exists(summary["output_video"])
