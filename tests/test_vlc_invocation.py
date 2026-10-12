"""Proves the VLC extension drives a working CLI.

VLC's own Lua host is not available here, so we do not claim the extension ran
inside VLC. Instead the real ``build_args`` from transcribe.vlc.lua is executed
with a standalone Lua interpreter, and the argv it returns is fed to the real
CLI (with offline provider fakes appended).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess

import pytest

import main as cli
from autodub import media

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LUA = shutil.which("luajit") or shutil.which("lua")
FAKES = ["--stt", "fake", "--tts", "fake", "--translate", "fake"]

pytestmark = pytest.mark.skipif(LUA is None, reason="lua/luajit required")


def lua_args(video: str, source: str, target: str, mode: str, in_place: bool,
             sound_tags: bool = True) -> list[str]:
    """Run the extension's own build_args() and return the argv it builds."""
    script = (
        f"dofile({os.path.join(ROOT, 'transcribe.vlc.lua')!r})\n"
        "local a = build_args(arg[1], arg[2], arg[3], arg[4], arg[5] == 'true', arg[6] == 'true')\n"
        "io.write(table.concat(a, '\\0'))\n"
    )
    out = subprocess.run([LUA, "-", video, source, target, mode,
                          "true" if in_place else "false", "true" if sound_tags else "false"],
                         input=script, check=True, capture_output=True, text=True).stdout
    return out.split("\0")


def test_argv_shapes():
    v = "/movies/my clip.mp4"
    assert lua_args(v, "auto", "tr", "both", True) == [v, "--in-place", "--target-lang", "tr"]
    assert lua_args(v, "en", "tr", "dub", True) == [
        v, "--in-place", "--source-lang", "en", "--target-lang", "tr", "--dub-only"]
    assert lua_args(v, "en", "same", "subs", False) == [
        v, "--output-base", "/movies/my clip", "--source-lang", "en", "--subtitle-only"]
    assert lua_args(v, "en", "tr", "subs", True, sound_tags=False)[-1] == "--no-sound-tags"
    assert "--no-sound-tags" not in lua_args(v, "en", "tr", "dub", True, sound_tags=False)
    for argv in (lua_args(v, "auto", "tr", "both", True), lua_args(v, "en", "de", "subs", False)):
        cli.build_parser().parse_args(argv)  # every shape parses


def test_extension_argv_runs_the_real_cli_in_place(tone_video, tmp_path, capsys):
    video = str(tmp_path / "my clip.mp4")
    shutil.copy(tone_video, video)
    code = cli.main(lua_args(video, "auto", "tr", "both", True) + FAKES)
    assert code == 0, capsys.readouterr().err
    kinds = [s["codec_type"] for s in media.probe_streams(video)]
    assert kinds.count("audio") == 2 and kinds.count("subtitle") == 1


def test_extension_argv_runs_the_real_cli_sidecar(tone_video, tmp_path, capsys):
    video = str(tmp_path / "clip.mp4")
    shutil.copy(tone_video, video)
    before = hashlib.sha256(open(video, "rb").read()).hexdigest()
    code = cli.main(lua_args(video, "en", "tr", "both", False) + FAKES)
    assert code == 0, capsys.readouterr().err
    assert os.path.exists(video.replace(".mp4", ".srt"))
    assert os.path.exists(video.replace(".mp4", "_dubbed.mp4"))
    assert hashlib.sha256(open(video, "rb").read()).hexdigest() == before
