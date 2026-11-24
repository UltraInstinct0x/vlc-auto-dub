"""--in-place: tracks are added to the input file itself, atomically.

Real ffmpeg does all media work; provider fakes keep the run offline and
deterministic. Fixtures carry two labelled original audio tracks so "every
original track is kept" is actually exercised.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys

import pytest

from autodub import media, pipeline
from autodub.config import build_config
from autodub.errors import InputError, MediaError
from autodub.pipeline import run

import main as cli
from conftest import make_tone_video

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")

FAKES = dict(stt="fake", translate="fake", tts="fake")


def _sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _two_track_video(path: str) -> str:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=4",
            "-map", "0", "-map", "1", "-map", "2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=fre",
            path,
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    return path


@pytest.fixture(params=["mp4", "mkv"])
def video(request, tmp_path) -> str:
    return _two_track_video(str(tmp_path / f"my clip.{request.param}"))


def _streams(path: str, kind: str) -> list[dict]:
    return [s for s in media.probe_streams(path) if s.get("codec_type") == kind]


def _lang(stream: dict) -> str | None:
    return stream.get("tags", {}).get("language")


def test_adds_default_dub_and_subtitle_keeping_originals(video):
    summary = run(video, None, build_config(source_lang="en", target_lang="tr",
                                            in_place=True, **FAKES))
    assert summary["output_media"] == os.path.abspath(video)

    audio = _streams(video, "audio")
    assert [_lang(s) for s in audio] == ["eng", "fre", "tur"]
    assert [s["disposition"]["default"] for s in audio] == [0, 0, 1]
    assert media.is_autodub_stream(audio[2])

    subs = _streams(video, "subtitle")
    assert [_lang(s) for s in subs] == ["tur"]
    expected_codec = "mov_text" if video.endswith(".mp4") else "subrip"
    assert subs[0]["codec_name"] == expected_codec
    assert len(_streams(video, "video")) == 1

    # No sidecar files and no leftover temp files.
    assert sorted(os.listdir(os.path.dirname(video))) == [os.path.basename(video)]


def test_redub_same_language_replaces_and_new_language_adds(video):
    cfg = dict(source_lang="en", in_place=True, **FAKES)
    run(video, None, build_config(target_lang="tr", **cfg))
    run(video, None, build_config(target_lang="tr", **cfg))
    assert [_lang(s) for s in _streams(video, "audio")] == ["eng", "fre", "tur"]
    assert [_lang(s) for s in _streams(video, "subtitle")] == ["tur"]

    run(video, None, build_config(target_lang="de", **cfg))
    audio = _streams(video, "audio")
    assert [_lang(s) for s in audio] == ["eng", "fre", "tur", "ger"]
    assert [s["disposition"]["default"] for s in audio] == [0, 0, 0, 1]


def test_dub_only_adds_no_subtitle(video):
    run(video, None, build_config(source_lang="en", target_lang="tr", in_place=True,
                                  dub_only=True, **FAKES))
    assert [_lang(s) for s in _streams(video, "audio")] == ["eng", "fre", "tur"]
    assert _streams(video, "subtitle") == []


def test_subtitle_only_adds_no_audio(video):
    run(video, None, build_config(source_lang="en", target_lang="de", in_place=True,
                                  subtitle_only=True, **FAKES))
    assert [_lang(s) for s in _streams(video, "audio")] == ["eng", "fre"]
    assert [_lang(s) for s in _streams(video, "subtitle")] == ["ger"]


def test_failed_verification_leaves_original_untouched(video, monkeypatch):
    before = _sha(video)

    def broken(*_args, **_kwargs):
        raise MediaError("simulated verification failure")

    monkeypatch.setattr(pipeline, "_verify_rewrite", broken)
    with pytest.raises(MediaError):
        run(video, None, build_config(source_lang="en", target_lang="tr",
                                      in_place=True, **FAKES))
    assert _sha(video) == before
    assert os.listdir(os.path.dirname(video)) == [os.path.basename(video)]


def test_unsupported_container_is_rejected(tmp_path):
    avi = str(tmp_path / "clip.avi")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=size=160x120:rate=15:duration=2", "-f", "lavfi",
                    "-i", "sine=duration=2", "-shortest", avi], check=True)
    before = _sha(avi)
    with pytest.raises(InputError, match="--in-place supports"):
        run(avi, None, build_config(in_place=True, **FAKES))
    assert _sha(avi) == before


def test_auto_source_translates_from_detected_language(video):
    summary = run(video, None, build_config(target_lang="tr", in_place=True, **FAKES))
    assert summary["detected_language"] == "en"
    assert summary["translated"] is True


def test_default_mode_still_writes_sidecars_and_keeps_input(tone_video, tmp_path):
    base = str(tmp_path / "out")
    before = _sha(tone_video)
    summary = run(tone_video, base, build_config(source_lang="en", target_lang="tr", **FAKES))
    assert _sha(tone_video) == before
    assert os.path.exists(summary["output_media"])
    assert os.path.exists(summary["output_srt"])          # unchanged default
    assert summary["subtitles_embedded"] is True           # and inside the copy too


def test_no_srt_leaves_only_the_self_contained_copy(tone_video, tmp_path):
    base = str(tmp_path / "out")
    summary = run(tone_video, base, build_config(source_lang="en", target_lang="tr",
                                                 write_srt=False, **FAKES))
    assert summary["subtitles_embedded"] is True and summary["output_srt"] is None
    assert not os.path.exists(base + ".srt")


def test_dub_only_sidecar_mode_writes_no_srt(tone_video, tmp_path):
    base = str(tmp_path / "out")
    summary = run(tone_video, base, build_config(source_lang="en", target_lang="tr",
                                                 dub_only=True, **FAKES))
    assert os.path.exists(summary["output_media"])
    assert not os.path.exists(base + ".srt")


def test_cli_flag_rules(capsys):
    with pytest.raises(SystemExit):
        cli.main(["x.mp4"])  # neither --output-base nor --in-place
    assert "--output-base is required" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["x.mp4", "--in-place", "--dub-only", "--subtitle-only"])
    assert "cannot be combined" in capsys.readouterr().err


def test_ffmpeg_found_with_minimal_gui_path(video, tmp_path):
    """VLC launched from the Dock has PATH=/usr/bin:/bin; ffmpeg must still be found."""
    if not any(os.path.exists(os.path.join(d, "ffmpeg")) for d in media._EXTRA_BIN_DIRS):
        pytest.skip("ffmpeg is not in one of the fallback directories on this host")
    env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin"}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable,
         os.path.join(root, "main.py"), video, "--in-place", "--source-lang", "en",
         "--target-lang", "tr", "--stt", "fake", "--tts", "fake", "--translate", "fake"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


# --- no language chosen (auto-detect, no translation) -----------------------

@pytest.mark.parametrize("ext", ["mkv", "mp4"])
def test_tracks_are_tagged_with_the_detected_language(tmp_path, ext):
    """Used to tag 'und' and, for MKV, fail: Matroska drops an 'und' tag."""
    video = make_tone_video(str(tmp_path / f"clip.{ext}"))
    summary = run(video, None, build_config(in_place=True, **FAKES))   # no languages
    assert summary["detected_language"] == "en" and summary["translated"] is False
    ours = [s for s in media.probe_streams(video) if media.is_autodub_stream(s)]
    assert sorted(s["codec_type"] for s in ours) == ["audio", "subtitle"]
    assert {media.stream_language(s) for s in ours} == {"eng"}


def test_undetected_language_still_works_on_mkv(tmp_path, monkeypatch):
    """Nothing detected: the tracks stay 'und', which Matroska stores as no tag."""
    import autodub.pipeline as pipeline
    from autodub.providers.stt_fake import FakeSTT

    class SilentDetector(FakeSTT):
        def transcribe(self, audio_path, language):
            segments = super().transcribe(audio_path, language)
            self.detected_language = None
            return segments

    monkeypatch.setattr(pipeline, "make_stt", lambda name, model=None: SilentDetector())
    video = make_tone_video(str(tmp_path / "clip.mkv"))
    for _ in range(2):          # re-running replaces the earlier 'und' tracks
        summary = run(video, None, build_config(in_place=True, **FAKES))
        assert summary["track_language"] == "und"
    ours = [s for s in media.probe_streams(video) if media.is_autodub_stream(s)]
    assert sorted(s["codec_type"] for s in ours) == ["audio", "subtitle"]


# --- dubs tagged "und" by earlier versions ----------------------------------

def _with_und_dub(tmp_path, ext, monkeypatch) -> str:
    """A file holding the 'und' AutoDub tracks an earlier version wrote."""
    import autodub.pipeline as pipeline

    video = make_tone_video(str(tmp_path / f"clip.{ext}"))
    with monkeypatch.context() as m:
        m.setattr(pipeline, "track_language", lambda code: "und")
        run(video, None, build_config(in_place=True, **FAKES))
    ours = [s for s in media.probe_streams(video) if media.is_autodub_stream(s)]
    assert {media.stream_language(s) for s in ours} == {"und"} and len(ours) == 2
    return video


@pytest.mark.parametrize("ext", ["mkv", "mp4"])
def test_untranslated_run_replaces_und_tracks(tmp_path, ext, monkeypatch):
    video = _with_und_dub(tmp_path, ext, monkeypatch)
    run(video, None, build_config(in_place=True, **FAKES))
    ours = [s for s in media.probe_streams(video) if media.is_autodub_stream(s)]
    assert sorted(s["codec_type"] for s in ours) == ["audio", "subtitle"]
    assert {media.stream_language(s) for s in ours} == {"eng"}


def test_translated_run_keeps_und_tracks(tmp_path, monkeypatch):
    """An 'und' dub is in the spoken language, so a Turkish one adds to it."""
    video = _with_und_dub(tmp_path, "mp4", monkeypatch)
    run(video, None, build_config(in_place=True, target_lang="tr", **FAKES))
    ours = [s for s in media.probe_streams(video) if media.is_autodub_stream(s)]
    assert sorted(media.stream_language(s) for s in ours) == ["tur", "tur", "und", "und"]
