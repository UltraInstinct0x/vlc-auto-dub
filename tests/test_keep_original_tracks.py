"""The separate dubbed copy (no --in-place) keeps every original track.

``<base>_dubbed<ext>`` used to hold only the first video stream and the dub,
silently dropping the file's own subtitles, other audio tracks and chapters.
It now has the --in-place layout: everything from the original, plus the dub
as the default audio track.
"""
from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

import main as cli
from autodub import media
from autodub.errors import MediaError

from conftest import make_tone_video

FAKES = ["--stt", "fake", "--tts", "fake", "--translate", "fake"]


def _sha(path) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _rich_video(tmp_path, name: str = "film.mp4") -> str:
    """Test-only video with a subtitle track, a second audio track and a chapter."""
    base = make_tone_video(str(tmp_path / f"base_{name}"))
    srt = tmp_path / "in.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:02,000\nHello\n", encoding="utf-8")
    chapters = tmp_path / "chapters.txt"
    chapters.write_text(";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\n"
                        "title=Opening\n", encoding="utf-8")
    out = str(tmp_path / name)
    sub_codec = "srt" if name.endswith(".mkv") else "mov_text"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", base, "-i", str(srt), "-i", str(chapters),
        "-f", "lavfi", "-i", "sine=frequency=660:duration=4",
        "-map", "0:v", "-map", "0:a", "-map", "3:a", "-map", "1:s",
        "-map_chapters", "2", "-c:v", "copy", "-c:a", "aac", "-c:s", sub_codec,
        "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=spa",
        "-metadata:s:s:0", "language=eng", "-shortest", out,
    ], check=True)
    return out


def _streams(path: str) -> list[dict]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type:stream_tags=language,title,handler_name:stream_disposition=default",
         "-show_chapters", "-of", "json", path],
        check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    return data["streams"], data.get("chapters", [])


@pytest.mark.parametrize("name", ["film.mp4", "film.mkv"])
@pytest.mark.parametrize("mode", [[], ["--dub-only"]])
def test_dubbed_copy_keeps_everything_and_defaults_to_the_dub(tmp_path, name, mode):
    video = _rich_video(tmp_path, name)
    before = _sha(video)
    code = cli.main([video, "--output-base", str(tmp_path / "o"), "--target-lang", "tr",
                     "--source-lang", "en", *FAKES, *mode])
    assert code == 0
    assert _sha(video) == before                       # input untouched

    streams, chapters = _streams(str(tmp_path / f"o_dubbed{name[-4:]}"))
    kinds = [s["codec_type"] for s in streams]
    assert kinds.count("video") == 1 and kinds.count("subtitle") == 1
    audio = [s for s in streams if s["codec_type"] == "audio"]
    assert [a["tags"].get("language") for a in audio] == ["eng", "spa", "tur"]
    dub = audio[-1]
    assert media.is_autodub_stream(dub) and dub["disposition"]["default"] == 1
    assert all(a["disposition"]["default"] == 0 for a in audio[:-1])
    assert [c["tags"]["title"] for c in chapters] == ["Opening"]


def test_redubbing_a_dubbed_file_replaces_its_autodub_track(tmp_path):
    video = _rich_video(tmp_path, "film.mkv")
    assert cli.main([video, "--in-place", "--target-lang", "tr", "--source-lang", "en",
                     *FAKES]) == 0
    assert cli.main([video, "--output-base", str(tmp_path / "o"), "--target-lang", "tr",
                     "--source-lang", "en", *FAKES]) == 0
    streams, _ = _streams(str(tmp_path / "o_dubbed.mkv"))
    titles = [s.get("tags", {}).get("title", "") for s in streams if s["codec_type"] == "audio"]
    assert titles.count("AutoDub (tur)") == 1           # replaced, not duplicated


def test_falls_back_to_video_and_dub_when_tracks_cannot_be_kept(tmp_path, monkeypatch, capsys):
    def refuse(*_a, **_k):
        raise MediaError("ffmpeg failed: codec not currently supported in container")
    monkeypatch.setattr(media, "mux_tracks", refuse)
    video = _rich_video(tmp_path)
    code = cli.main([video, "--output-base", str(tmp_path / "o"), *FAKES])
    assert code == 0
    assert "could not keep the original tracks in o_dubbed.mp4" in capsys.readouterr().err
    streams, _ = _streams(str(tmp_path / "o_dubbed.mp4"))
    kinds = [s["codec_type"] for s in streams]
    # The old layout: video + the dub only (MP4 may add a chapter "data" track).
    assert kinds.count("video") == 1 and kinds.count("audio") == 1
    assert "subtitle" not in kinds


def test_container_that_cannot_hold_the_tracks_still_produces_a_copy(tmp_path, capsys):
    """A container outside the --in-place list (AVI) still gets a playable copy."""
    base = make_tone_video(str(tmp_path / "base.mp4"))
    avi = str(tmp_path / "clip.avi")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", base, "-c:v", "mpeg4",
                    "-c:a", "mp3", avi], check=True)
    code = cli.main([avi, "--output-base", str(tmp_path / "o"), *FAKES])
    assert code == 0, capsys.readouterr().err
    kinds = [s["codec_type"] for s in _streams(str(tmp_path / "o_dubbed.avi"))[0]]
    assert "video" in kinds and "audio" in kinds
