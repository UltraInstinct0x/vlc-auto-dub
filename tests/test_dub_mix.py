"""Dub loudness and voice-over mixing (--dub-volume, --original-volume).

The fixtures make the levels measurable: the fake TTS writes a 220 Hz tone and
the test video's audio is a 440 Hz tone, so the strength of each frequency in
the output says how loud the dub and the original speech are.
"""
from __future__ import annotations

import subprocess

import numpy as np
import pytest

import main as cli
from autodub import media
from autodub.config import build_config
from autodub.errors import InputError

FAKES = ["--stt", "fake", "--tts", "fake", "--translate", "fake"]
DUB_HZ, ORIGINAL_HZ = 220.0, 440.0


def tone_amplitude(samples: np.ndarray, hz: float, rate: int = media.SAMPLE_RATE) -> float:
    """Peak amplitude of the ``hz`` component (Hann-windowed DFT)."""
    window = np.hanning(len(samples))
    spectrum = np.abs(np.fft.rfft(samples * window))
    freqs = np.fft.rfftfreq(len(samples), 1 / rate)
    k = int(np.argmin(np.abs(freqs - hz)))
    return float(2 * spectrum[max(k - 2, 0):k + 3].max() / window.sum())


def steady(samples: np.ndarray, rate: int = media.SAMPLE_RATE) -> np.ndarray:
    """0.5 s .. 3.5 s: skips encoder padding and the short tail cue at the edges."""
    return samples[int(0.5 * rate):int(3.5 * rate)]


def _tone(path, hz: float, seconds: float, amplitude: float) -> str:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"aevalsrc={amplitude}*sin(2*PI*{hz}*t):s={media.SAMPLE_RATE}:d={seconds}",
                    "-ac", "1", "-acodec", "pcm_s16le", str(path)], check=True)
    return str(path)


def _dubbed_samples(tmp_path, video, *extra) -> np.ndarray:
    tmp_path.mkdir(parents=True, exist_ok=True)
    code = cli.main([video, "--output-base", str(tmp_path / "o"), *FAKES, *extra])
    assert code == 0
    return steady(media.read_samples(str(tmp_path / "o_dubbed.mp4")))


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


# --- pipeline --------------------------------------------------------------

def test_default_replaces_speech_and_skips_mixing(tone_video, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("mix_segment must not run with default volumes")
    monkeypatch.setattr(media, "mix_segment", boom)
    samples = _dubbed_samples(tmp_path, tone_video)
    # The fake TTS clip fills ~1.2 s of each 2 s slot, so its mean strength is ~0.17.
    assert tone_amplitude(samples, DUB_HZ) > 0.1
    assert tone_amplitude(samples, ORIGINAL_HZ) < 0.01      # original speech fully replaced


def test_original_volume_keeps_original_speech_audible(tone_video, tmp_path):
    source = tone_amplitude(steady(media.read_samples(tone_video)), ORIGINAL_HZ)
    samples = _dubbed_samples(tmp_path, tone_video, "--original-volume", "0.5")
    assert tone_amplitude(samples, ORIGINAL_HZ) == pytest.approx(0.5 * source, rel=0.05)
    assert tone_amplitude(samples, DUB_HZ) > 0.1            # the dub is still there            # the dub is still there


def test_dub_volume_end_to_end(tone_video, tmp_path):
    full = tone_amplitude(_dubbed_samples(tmp_path / "a", tone_video), DUB_HZ)
    half = tone_amplitude(_dubbed_samples(tmp_path / "b", tone_video, "--dub-volume", "0.5"),
                          DUB_HZ)
    assert half == pytest.approx(0.5 * full, rel=0.1)


def test_cli_reports_the_mix(tone_video, tmp_path, capsys):
    _dubbed_samples(tmp_path, tone_video, "--original-volume", "0.3", "--dub-volume", "1.2")
    assert "mix: dub 1.2x, original speech under it 0.3x" in capsys.readouterr().out


# --- configuration ---------------------------------------------------------

@pytest.mark.parametrize("flag,value,message", [
    ("--original-volume", "1.5", "original volume must be between 0 and 1"),
    ("--original-volume", "-0.1", "original volume must be between 0 and 1"),
    ("--dub-volume", "4", "dub volume must be between 0 and 3"),
])
def test_out_of_range_volumes_are_rejected(tone_video, tmp_path, capsys, flag, value, message):
    code = cli.main([tone_video, "--output-base", str(tmp_path / "o"), *FAKES, flag, value])
    assert code == 1
    assert message in capsys.readouterr().err
    assert not (tmp_path / "o_dubbed.mp4").exists()


def test_volumes_from_config_file_and_environment(tmp_path, monkeypatch):
    cfg = tmp_path / "autodub.conf"
    cfg.write_text("original_volume = 0.25\n", encoding="utf-8")
    monkeypatch.setenv("AUTODUB_DUB_VOLUME", "0.8")
    config = build_config(config_path=str(cfg))
    assert (config.original_volume, config.dub_volume) == (0.25, 0.8)
    assert build_config(config_path=str(cfg), original_volume=0.0).original_volume == 0.0
    monkeypatch.setenv("AUTODUB_DUB_VOLUME", "loud")
    with pytest.raises(InputError, match="dub volume must be a number"):
        build_config()


def test_defaults_are_unchanged():
    config = build_config()
    assert (config.dub_volume, config.original_volume) == (1.0, 0.0)
