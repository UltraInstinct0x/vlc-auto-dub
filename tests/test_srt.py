from autodub.subtitles import Cue, format_timestamp, validate_cues, write_srt
from autodub.errors import InputError
import pytest


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(1.5) == "00:00:01,500"
    assert format_timestamp(3661.25) == "01:01:01,250"


def test_validate_rejects_reversed():
    with pytest.raises(InputError):
        validate_cues([Cue(5.0, 5.0, "x")])


def test_validate_rejects_overlap():
    with pytest.raises(InputError):
        validate_cues([Cue(0.0, 3.0, "a"), Cue(2.0, 4.0, "b")])


def test_write_srt_roundtrip(tmp_path):
    cues = [Cue(0.0, 2.0, "hello"), Cue(2.0, 4.0, "world")]
    out = tmp_path / "o.srt"
    write_srt(cues, str(out))
    text = out.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:02,000\nhello" in text
    assert "2\n00:00:02,000 --> 00:00:04,000\nworld" in text
