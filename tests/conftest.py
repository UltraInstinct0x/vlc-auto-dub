"""Shared test fixtures.

All media here is **synthesized by ffmpeg/espeak-ng** and clearly test-only:
a colour test pattern plus a tone or generated speech. It is not real
production media and recognition quality is never asserted from it.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
HAVE_ESPEAK = shutil.which("espeak-ng") is not None


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def make_tone_video(path: str, duration: float = 4.0, size: str = "320x240") -> str:
    """A video with a synthesized 440 Hz tone as its audio track."""
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate=15:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path,
    ])
    return path


def make_speech_video(path: str, text: str = "hello world", duration: float = 3.0) -> str:
    """A video whose audio is synthesized speech from espeak-ng (test-only)."""
    wav = path + ".speech.wav"
    _run(["espeak-ng", "-v", "en", "-s", "150", "-w", wav, text])
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=15:duration={duration}",
        "-i", wav,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path,
    ])
    return path


@pytest.fixture(scope="session")
def tone_video(tmp_path_factory) -> str:
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg not available")
    out = str(tmp_path_factory.mktemp("media") / "tone.mp4")
    return make_tone_video(out)


@pytest.fixture(scope="session")
def speech_video(tmp_path_factory) -> str:
    if not (HAVE_FFMPEG and HAVE_ESPEAK):
        pytest.skip("ffmpeg + espeak-ng required for the speech fixture")
    out = str(tmp_path_factory.mktemp("media") / "speech.mp4")
    return make_speech_video(
        out, text="the quick brown fox jumps over the lazy dog", duration=4.0
    )
