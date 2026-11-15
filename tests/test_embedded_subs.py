"""Unit tests for reading subtitle tracks already in the file."""
from __future__ import annotations

from autodub import embedded_subs as es
from autodub.providers.base import Segment


def _stream(i, codec="subrip", lang=None, **disp):
    s = {"index": i, "codec_type": "subtitle", "codec_name": codec,
         "tags": {"language": lang} if lang else {}, "disposition": disp}
    return s


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
