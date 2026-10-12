import subprocess

import pytest

from autodub import media
from autodub.errors import DependencyError, InputError
from autodub.config import build_config
from autodub.pipeline import run
import main as cli


def test_require_binary_missing():
    with pytest.raises(DependencyError):
        media.require_binary("definitely-not-a-program-xyz")


def test_input_without_audio_stream(tmp_path, capsys):
    no_audio = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x240:rate=10:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(no_audio)],
        check=True,
    )
    with pytest.raises(InputError):
        run(str(no_audio), str(tmp_path / "out"), build_config(stt="fake", tts="fake"))


def test_provider_failure_is_clear(tmp_path, tone_video, monkeypatch):
    from autodub.providers import stt_fake

    def boom(self, audio_path, language):
        raise InputError("simulated provider failure")

    monkeypatch.setattr(stt_fake.FakeSTT, "transcribe", boom)
    with pytest.raises(InputError):
        run(tone_video, str(tmp_path / "out"), build_config(stt="fake", tts="fake"))
