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
             sound_tags: bool = True, use_embedded: bool = False,
             dub_volume: float | None = None, original_volume: float | None = None) -> list[str]:
    """Run the extension's own build_args() and return the argv it builds."""
    script = (
        f"dofile({os.path.join(ROOT, 'transcribe.vlc.lua')!r})\n"
        "local a = build_args(arg[1], arg[2], arg[3], arg[4], arg[5] == 'true', arg[6] == 'true',\n"
        "                     arg[7] == 'true', tonumber(arg[8]), tonumber(arg[9]))\n"
        "io.write(table.concat(a, '\\0'))\n"
    )
    out = subprocess.run([LUA, "-", video, source, target, mode,
                          "true" if in_place else "false", "true" if sound_tags else "false",
                          "true" if use_embedded else "false",
                          "" if dub_volume is None else str(dub_volume),
                          "" if original_volume is None else str(original_volume)],
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
    assert lua_args(v, "en", "tr", "both", True, use_embedded=True)[-1] == "--use-embedded-subs"
    assert "--use-embedded-subs" not in lua_args(v, "en", "tr", "both", True)
    # A separate dubbed copy carries its subtitles, so no .srt beside it.
    assert lua_args(v, "en", "tr", "both", False)[:4] == [
        v, "--output-base", "/movies/my clip", "--no-srt"]
    assert "--no-srt" in lua_args(v, "en", "tr", "dub", False)
    mixed = lua_args(v, "en", "tr", "both", True, dub_volume=0.75, original_volume=0.3)
    assert mixed[-4:] == ["--dub-volume", "0.75", "--original-volume", "0.3"]
    # Defaults are passed too (they must win over the environment), but
    # subtitles-only never carries volumes.
    assert lua_args(v, "en", "tr", "both", True, dub_volume=1.0, original_volume=0)[-4:] == [
        "--dub-volume", "1", "--original-volume", "0"]
    assert lua_args(v, "en", "tr", "subs", True, dub_volume=0.5, original_volume=0.3)[-1] \
        == "--subtitle-only"
    for argv in (lua_args(v, "auto", "tr", "both", True), lua_args(v, "en", "de", "subs", False),
                 lua_args(v, "auto", "tr", "both", True, use_embedded=True),
                 mixed):
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
    dubbed = video.replace(".mp4", "_dubbed.mp4")
    assert os.path.exists(dubbed)
    kinds = [s["codec_type"] for s in media.probe_streams(dubbed)]
    assert kinds.count("audio") == 2 and kinds.count("subtitle") == 1   # subs inside
    assert not os.path.exists(video.replace(".mp4", ".srt"))
    assert hashlib.sha256(open(video, "rb").read()).hexdigest() == before


def test_dropdown_default_from_config():
    """levels_with_default() puts the configured gain first (VLC preselects it)."""
    script = (
        f"dofile({os.path.join(ROOT, 'transcribe.vlc.lua')!r})\n"
        "local levels = { {0, 'Off'}, {0.15, 'Quiet'}, {0.3, 'Medium'} }\n"
        "local function first(p) local l = levels_with_default(levels, p, 1)[1]\n"
        "  return string.format('%g=%s/%d', l[1], l[2], #levels_with_default(levels, p, 1)) end\n"
        "io.write(first(nil), ' ', first(0.3), ' ', first('0.15'), ' ', first(0.42), ' ',\n"
        "  first(1.5), ' ', first(-1), ' ', first('loud'), ' ', first(0/0))\n"
    )
    out = subprocess.run([LUA, "-"], input=script, check=True, capture_output=True,
                         text=True).stdout
    assert out.split() == ["0=Off/3", "0.3=Medium/3", "0.15=Quiet/3", "0.42=42%/4",
                           "0=Off/3", "0=Off/3", "0=Off/3", "0=Off/3"]   # rejected by the CLI
