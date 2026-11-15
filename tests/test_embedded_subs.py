"""Dubbing from a subtitle track already in the file (--use-embedded-subs)."""
from __future__ import annotations

import os
import subprocess

import pytest

import main as cli
from autodub import embedded_subs as es
from autodub import media
from autodub.providers.base import Segment
from autodub.providers.stt_fake import FakeSTT

from _util import assert_monotonic_nonoverlapping, parse_srt
from conftest import make_tone_video

FAKES = ["--stt", "fake", "--tts", "fake", "--translate", "fake"]

SRT = """1
00:00:00,200 --> 00:00:01,200
<i>Hello there.</i>

2
00:00:01,500 --> 00:00:02,600
[door slams]
- How are you?

3
00:00:02,600 --> 00:00:03,000
♪ ♪

4
00:00:03,000 --> 00:00:03,800
{\\an8}Fine, thanks.
"""


def _with_subs(tmp_path, name: str, codec: str, language: str | None,
               srt_text: str = SRT, forced: bool = False) -> str:
    """Tone video (test-only) with one text subtitle track muxed in."""
    base = make_tone_video(str(tmp_path / f"base_{name}"))
    srt = tmp_path / f"in_{name}.srt"
    srt.write_text(srt_text, encoding="utf-8")
    out = str(tmp_path / name)
    meta = ["-metadata:s:s:0", f"language={language}"] if language else []
    disp = ["-disposition:s:0", "forced"] if forced else []
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", base, "-i", str(srt),
                    "-map", "0", "-map", "1", "-c", "copy", "-c:s", codec, *meta, *disp, out],
                   check=True)
    return out


def _subtitle_texts(video: str, title: str) -> list[str]:
    """Texts of the subtitle stream whose track name starts with ``title``."""
    stream = next(s for s in media.probe_streams(video)
                  if s.get("codec_type") == "subtitle"
                  and any(str(s.get("tags", {}).get(k, "")).startswith(title)
                          for k in ("title", "handler_name")))
    out = video + f".{stream['index']}.srt"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video,
                    "-map", f"0:{stream['index']}", "-c:s", "srt", out], check=True)
    return [c[2] for c in parse_srt(out)]


@pytest.fixture
def stt_must_not_run(monkeypatch):
    def boom(self, audio_path, language):
        raise AssertionError("STT ran although an embedded subtitle track was usable")
    monkeypatch.setattr(FakeSTT, "transcribe", boom)


# --- units -----------------------------------------------------------------

def test_iso1():
    assert es.iso1("eng") == "en" and es.iso1("ger") == "de" and es.iso1("deu") == "de"
    assert es.iso1("pt-BR") == "pt" and es.iso1("und") is None and es.iso1(None) is None


def test_clean_text_drops_formatting_and_sound_lines():
    assert es.clean_text("<i>Hello</i>") == "Hello"
    assert es.clean_text("{\\an8}Top\\Nline") == "Top line"
    assert es.clean_text("[door slams]\n- How are you?") == "- How are you?"
    assert es.clean_text("♪ ♪") == ""
    assert es.clean_text("I (laughs) know") == "I know"


def test_normalize_orders_merges_and_clips():
    segs = es.normalize([
        Segment(5.0, 6.0, "c"), Segment(0.0, 3.0, "a"), Segment(0.1, 2.0, "a2"),
        Segment(2.5, 4.0, "b"), Segment(7.0, 7.0, "zero"), Segment(8.0, 9.0, ""),
    ])
    assert [(s.start, s.end, s.text) for s in segs] == [
        (0.0, 2.5, "a a2"), (2.5, 4.0, "b"), (5.0, 6.0, "c")]


def _stream(i, codec="subrip", lang=None, **disp):
    s = {"index": i, "codec_type": "subtitle", "codec_name": codec,
         "tags": {"language": lang} if lang else {}, "disposition": disp}
    return s


def test_find_track_preference():
    streams = [
        {"index": 0, "codec_type": "video"},
        _stream(1, "hdmv_pgs_subtitle", "tur"),          # bitmap: unusable
        _stream(2, lang="eng", forced=1),                # forced: skipped
        _stream(3, lang="eng", hearing_impaired=1),
        _stream(4, lang="eng"),
        _stream(5, "ass", lang="spa"),
        {"index": 6, "codec_type": "subtitle", "codec_name": "subrip",
         "tags": {"language": "tur", "title": "AutoDub (tur)"}, "disposition": {}},
    ]
    assert es.find_track(streams, None, "es").index == 5    # already in the target
    assert es.find_track(streams, "en", "tr").index == 4    # spoken language, non-SDH
    assert es.find_track(streams, None, "tr").index == 4    # any; AutoDub/bitmap ignored
    assert es.find_track(streams[:2], None, None) is None


# --- end to end ------------------------------------------------------------

@pytest.mark.usefixtures("stt_must_not_run")
def test_sidecar_translates_from_track_language(tmp_path, capsys):
    video = _with_subs(tmp_path, "film.mkv", "srt", "eng")
    code = cli.main([video, "--output-base", str(tmp_path / "out"),
                     "--use-embedded-subs", "--target-lang", "tr", *FAKES])
    err = capsys.readouterr()
    assert code == 0, err.err
    assert "embedded subtitles" in err.out and "translation: yes" in err.out
    cues = parse_srt(str(tmp_path / "out.srt"))
    assert_monotonic_nonoverlapping(cues)
    assert [c[2] for c in cues] == ["[tr] Hello there.", "[tr] - How are you?",
                                    "[tr] Fine, thanks."]
    assert os.path.exists(tmp_path / "out_dubbed.mkv")


@pytest.mark.usefixtures("stt_must_not_run")
def test_in_place_mp4_mov_text(tmp_path, capsys):
    video = _with_subs(tmp_path, "clip.mp4", "mov_text", "eng")
    code = cli.main([video, "--in-place", "--use-embedded-subs", *FAKES])
    assert code == 0, capsys.readouterr().err
    kinds = [s["codec_type"] for s in media.probe_streams(video)]
    assert kinds.count("audio") == 2 and kinds.count("subtitle") == 2


def test_falls_back_to_stt_without_a_track(tone_video, tmp_path, capsys):
    code = cli.main([tone_video, "--output-base", str(tmp_path / "o"),
                     "--use-embedded-subs", *FAKES])
    err = capsys.readouterr().err
    assert code == 0, err
    assert "no text subtitle track" in err
    assert parse_srt(str(tmp_path / "o.srt"))[0][2] == "fake segment"


def test_untagged_track_needs_spoken_language_to_translate(tmp_path, capsys):
    video = _with_subs(tmp_path, "untagged.mkv", "srt", None)
    code = cli.main([video, "--output-base", str(tmp_path / "o"),
                     "--use-embedded-subs", "--target-lang", "tr", *FAKES])
    err = capsys.readouterr().err
    assert code == 0, err
    assert "no language tag" in err          # fell back to STT, said why


@pytest.mark.usefixtures("stt_must_not_run")
def test_untagged_track_used_when_spoken_language_given(tmp_path, capsys):
    video = _with_subs(tmp_path, "untagged2.mkv", "srt", None)
    code = cli.main([video, "--output-base", str(tmp_path / "o"), "--use-embedded-subs",
                     "--source-lang", "en", "--target-lang", "tr", *FAKES])
    assert code == 0, capsys.readouterr().err
    assert parse_srt(str(tmp_path / "o.srt"))[0][2] == "[tr] Hello there."


# --- parsing edge cases ----------------------------------------------------

def test_parse_srt_variants():
    text = (
        "00:00:01.000 --> 00:00:02.000\r\nno index, dot millis\r\n\r\n"   # WebVTT-ish
        "7\n00:00:03,000 --> 00:00:04,500 X1:10 X2:20\npositioned\nsecond line\n\n"
        "8\nnot a timestamp --> nope\nbroken\n\n"                          # skipped
        "9\n00:00:05,000 --> 00:00:06,000\n\n"                             # empty text
    )
    segs = es.parse_srt(text)
    assert [(s.start, s.end, s.text) for s in segs] == [
        (1.0, 2.0, "no index, dot millis"),
        (3.0, 4.5, "positioned second line"),
        (5.0, 6.0, ""),
    ]
    assert len(es.normalize(segs)) == 2  # the empty cue is dropped


def test_clean_text_more_cases():
    assert es.clean_text("A\\hB") == "A B"
    assert es.clean_text("(whispers)") == ""
    assert es.clean_text("[MAN] Hi") == "Hi"
    assert es.clean_text("  spaced   out \n  text ") == "spaced out text"


def test_normalize_contained_and_nearly_simultaneous():
    segs = es.normalize([Segment(0.0, 5.0, "outer"), Segment(1.0, 2.0, "inner"),
                         Segment(6.0, 7.0, "x"), Segment(6.2, 6.8, "y")])
    assert [(s.start, s.end, s.text) for s in segs] == [
        (0.0, 1.0, "outer"), (1.0, 2.0, "inner"), (6.0, 7.0, "x y")]


def test_find_track_honours_default_and_order():
    streams = [_stream(2, lang="eng"), _stream(3, lang="eng", default=1),
               _stream(4, "webvtt"), _stream(5, "dvd_subtitle", "eng")]
    assert es.find_track(streams, "en", None).index == 3
    assert es.find_track([streams[2], streams[3]], None, None).index == 4
    assert es.find_track([streams[3]], None, None) is None


# --- CLI / config ----------------------------------------------------------

def test_help_and_default_off(capsys):
    from autodub.config import build_config
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "--use-embedded-subs" in capsys.readouterr().out
    assert build_config().use_embedded_subs is False
    assert cli.build_parser().parse_args(["x.mp4", "--in-place"]).use_embedded_subs is False


# --- more end to end -------------------------------------------------------

@pytest.mark.usefixtures("stt_must_not_run")
def test_ass_track_is_converted(tmp_path, capsys):
    video = _with_subs(tmp_path, "styled.mkv", "ass", "eng")
    assert media.probe_streams(video)[2]["codec_name"] == "ass"
    code = cli.main([video, "--output-base", str(tmp_path / "o"), "--subtitle-only",
                     "--use-embedded-subs", *FAKES])
    assert code == 0, capsys.readouterr().err
    assert [c[2] for c in parse_srt(str(tmp_path / "o.srt"))] == [
        "Hello there.", "- How are you?", "Fine, thanks."]


@pytest.mark.usefixtures("stt_must_not_run")
def test_track_in_target_language_skips_translation(tmp_path, capsys):
    video = _with_subs(tmp_path, "es.mkv", "srt", "spa")
    code = cli.main([video, "--output-base", str(tmp_path / "o"), "--subtitle-only",
                     "--use-embedded-subs", "--source-lang", "en", "--target-lang", "es",
                     *FAKES])
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "translation: no" in out.out
    assert parse_srt(str(tmp_path / "o.srt"))[0][2] == "Hello there."  # no "[es]" prefix


def test_track_without_speech_falls_back_and_keeps_user_language(tmp_path, capsys):
    only_sounds = "1\n00:00:00,500 --> 00:00:01,500\n[music]\n\n2\n00:00:02,000 --> 00:00:03,000\n♪\n"
    video = _with_subs(tmp_path, "music.mkv", "srt", "fre", srt_text=only_sounds)
    code = cli.main([video, "--output-base", str(tmp_path / "o"), "--use-embedded-subs",
                     "--source-lang", "en", "--target-lang", "fr", *FAKES])
    err = capsys.readouterr().err
    assert code == 0, err
    assert "no usable text" in err
    # The track's language (fr) must not leak into the fallback: the speech is
    # still en, so en -> fr translation must happen (a leak would make it fr -> fr).
    assert parse_srt(str(tmp_path / "o.srt"))[0][2] == "[fr] fake segment"


def test_forced_only_track_is_not_used(tmp_path, capsys):
    video = _with_subs(tmp_path, "forced.mkv", "srt", "eng", forced=True)
    code = cli.main([video, "--output-base", str(tmp_path / "o"), "--use-embedded-subs",
                     *FAKES])
    err = capsys.readouterr().err
    assert code == 0, err
    assert "no text subtitle track" in err


@pytest.mark.usefixtures("stt_must_not_run")
def test_rerun_in_place_reads_the_original_track(tmp_path, capsys):
    video = _with_subs(tmp_path, "twice.mkv", "srt", "eng")
    # The second "tr" run would prefer the AutoDub (tur) track from the first run
    # (it is already in the target language) if earlier dubs were not excluded.
    for target in ("tr", "tr", "de"):
        code = cli.main([video, "--in-place", "--use-embedded-subs",
                         "--target-lang", target, *FAKES])
        out = capsys.readouterr()
        assert code == 0, out.err
        assert "embedded subtitles (track #2)" in out.out
    # The German track was translated from the English original, not the Turkish dub.
    assert _subtitle_texts(video, "AutoDub (ger)")[0] == "[de] Hello there."
    assert _subtitle_texts(video, "AutoDub (tur)")[0] == "[tr] Hello there."


@pytest.mark.usefixtures("stt_must_not_run")
def test_dub_only(tmp_path, capsys):
    video = _with_subs(tmp_path, "dub.mkv", "srt", "eng")
    code = cli.main([video, "--output-base", str(tmp_path / "o"), "--dub-only",
                     "--use-embedded-subs", *FAKES])
    assert code == 0, capsys.readouterr().err
    assert os.path.exists(tmp_path / "o_dubbed.mkv")
    assert not os.path.exists(tmp_path / "o.srt")
