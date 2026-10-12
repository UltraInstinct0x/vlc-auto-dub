"""Robustness on realistic inputs (each succeeds or fails clearly)."""
from __future__ import annotations

import hashlib
import os
import shutil

from autodub import media
from autodub.config import build_config
from autodub.pipeline import run

from conftest import make_tone_video

import _util


def _fake_cfg(**kw):
    base = dict(stt="fake", tts="fake", translate="fake")
    base.update(kw)
    return build_config(**base)


def test_audio_only_input_produces_audio(audio_only, tmp_path):
    base = str(tmp_path / "out")
    before = hashlib.sha256(open(audio_only, "rb").read()).hexdigest()
    summary = run(audio_only, base, _fake_cfg(source_lang="en", target_lang="tr"))
    assert hashlib.sha256(open(audio_only, "rb").read()).hexdigest() == before
    assert summary["has_video"] is False
    assert summary["output_media"].endswith("_dubbed.wav")
    assert os.path.exists(summary["output_media"])
    assert media.has_audio_stream(summary["output_media"])
    assert not media.has_video_stream(summary["output_media"])
    assert _util.parse_srt(summary["output_srt"])


def test_path_with_spaces_and_non_ascii(tone_video, tmp_path):
    d = tmp_path / "a dir ünïcode ç"
    d.mkdir()
    video = str(d / "clïp Ω.mp4")
    shutil.copy(tone_video, video)
    base = str(d / "oüt put")
    summary = run(video, base, _fake_cfg(source_lang="en", target_lang="de"))
    assert os.path.exists(summary["output_media"])
    assert summary["output_media"].endswith("_dubbed.mp4")
    assert os.path.exists(summary["output_srt"])


def test_mkv_container(tmp_path):
    video = make_tone_video(str(tmp_path / "clip.mkv"), duration=4.0)
    base = str(tmp_path / "out")
    summary = run(video, base, _fake_cfg(source_lang="en"))
    assert summary["output_media"].endswith("_dubbed.mkv")
    assert media.has_video_stream(summary["output_media"])
    assert media.has_audio_stream(summary["output_media"])


def test_longer_file(tmp_path):
    video = make_tone_video(str(tmp_path / "long.mp4"), duration=30.0)
    base = str(tmp_path / "out")
    summary = run(video, base, _fake_cfg(source_lang="en", target_lang="tr"))
    assert summary["segment_count"] >= 10
    assert abs(summary["dubbed_duration"] - summary["source_duration"]) <= 0.5


def test_non_ascii_source_text(tone_video, tmp_path, monkeypatch):
    import autodub.pipeline as pipeline
    from autodub.providers.stt_fake import FakeSTT

    unicode_text = "çğıöşü ÇĞİÖŞÜ — 日本語のテスト — Ω≈ç√"
    monkeypatch.setattr(pipeline, "make_stt", lambda name: FakeSTT(text=unicode_text))
    base = str(tmp_path / "out")
    summary = run(tone_video, base, _fake_cfg(source_lang="en"))
    content = open(summary["output_srt"], encoding="utf-8").read()
    assert unicode_text in content
