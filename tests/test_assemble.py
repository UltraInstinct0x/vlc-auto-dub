import subprocess

import pytest

from autodub import media


def _dur(path):
    return media.duration(path)


@pytest.fixture
def tone(tmp_path):
    out = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3", "-ac", "1", "-ar", "16000", str(out)],
        check=True,
    )
    return str(out)


def test_fit_speeds_up_long_clip(tone, tmp_path):
    out = tmp_path / "fit.wav"
    media.fit_segment(tone, window=1.0, out_wav=str(out))
    assert abs(_dur(str(out)) - 1.0) < 0.05


def test_fit_pads_short_clip(tone, tmp_path):
    short = tmp_path / "short.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tone, "-t", "0.5", str(short)], check=True)
    out = tmp_path / "fit.wav"
    media.fit_segment(str(short), window=2.0, out_wav=str(out))
    assert abs(_dur(str(out)) - 2.0) < 0.05
