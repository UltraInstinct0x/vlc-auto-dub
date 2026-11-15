"""media.mix_segment: dub gain and laying the original speech under the dub.

The levels are measurable: the dub is a 220 Hz tone and the original a 440 Hz
tone, so the strength of each frequency in the output gives its gain.
"""
from __future__ import annotations

import subprocess

import numpy as np
import pytest

from autodub import media

DUB_HZ, ORIGINAL_HZ = 220.0, 440.0


def tone_amplitude(samples: np.ndarray, hz: float, rate: int = media.SAMPLE_RATE) -> float:
    """Peak amplitude of the ``hz`` component (Hann-windowed DFT)."""
    window = np.hanning(len(samples))
    spectrum = np.abs(np.fft.rfft(samples * window))
    freqs = np.fft.rfftfreq(len(samples), 1 / rate)
    k = int(np.argmin(np.abs(freqs - hz)))
    return float(2 * spectrum[max(k - 2, 0):k + 3].max() / window.sum())


def _tone(path, hz: float, seconds: float, amplitude: float) -> str:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"aevalsrc={amplitude}*sin(2*PI*{hz}*t):s={media.SAMPLE_RATE}:d={seconds}",
                    "-ac", "1", "-acodec", "pcm_s16le", str(path)], check=True)
    return str(path)


# --- mix_segment -----------------------------------------------------------

def test_dub_volume_scales_and_keeps_length(tmp_path):
    dub = _tone(tmp_path / "dub.wav", DUB_HZ, 1.5, 0.4)
    out = str(tmp_path / "out.wav")
    media.mix_segment(dub, out, dub_volume=0.5)
    assert abs(media.duration(out) - 1.5) < 0.01
    assert tone_amplitude(media.read_samples(out), DUB_HZ) == pytest.approx(0.2, rel=0.05)


def test_original_is_mixed_under_the_dub_at_its_gain(tmp_path):
    dub = _tone(tmp_path / "dub.wav", DUB_HZ, 1.0, 0.4)
    longer_original = _tone(tmp_path / "orig.wav", ORIGINAL_HZ, 3.0, 0.5)
    out = str(tmp_path / "out.wav")
    media.mix_segment(dub, out, dub_volume=0.5, original_wav=longer_original,
                      original_volume=0.3)
    samples = media.read_samples(out)
    assert abs(media.duration(out) - 1.0) < 0.01           # the dub's slot, not the original's
    assert tone_amplitude(samples, DUB_HZ) == pytest.approx(0.2, rel=0.05)
    assert tone_amplitude(samples, ORIGINAL_HZ) == pytest.approx(0.15, rel=0.05)


def test_mix_never_clips(tmp_path):
    dub = _tone(tmp_path / "dub.wav", DUB_HZ, 1.0, 0.9)
    orig = _tone(tmp_path / "orig.wav", ORIGINAL_HZ, 1.0, 0.9)
    out = str(tmp_path / "out.wav")
    media.mix_segment(dub, out, dub_volume=1.5, original_wav=orig, original_volume=1.0)
    assert np.abs(media.read_samples(out)).max() <= 0.98
