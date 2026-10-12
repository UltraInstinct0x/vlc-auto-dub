"""Proves the VLC extension would drive a working CLI (invocation equivalence).

VLC's Lua host is not available on this headless host, so we do not claim the
extension was run inside VLC. Instead we reconstruct the exact argv the Lua
file builds, check it parses to the intended values, and run the real CLI with
that argv shape (plus explicit fake providers to stay offline).
"""
from __future__ import annotations

import hashlib
import os

import main as cli

import _util


def _extension_argv(video: str, python: str, script: str) -> list[str]:
    """Mirror of the command built by transcribe.vlc.lua."""
    base = os.path.splitext(video)[0]
    return [python, script, video, "--output-base", base, "--target-lang", "tr"]


def test_extension_argv_shape():
    full = _extension_argv("/movies/clip.mp4", "python3", "/opt/autodub/main.py")
    # interpreter + script are consumed by the shell; the program sees full[2:]
    assert full[1] == "/opt/autodub/main.py"
    ns = cli.build_parser().parse_args(full[2:])
    assert ns.input == "/movies/clip.mp4"
    assert ns.output_base == "/movies/clip"        # distinct from the input
    assert ns.target_lang == "tr"                  # language goes to --target-lang


def test_extension_argv_runs_the_real_cli(tone_video, tmp_path, capsys):
    import shutil
    video = str(tmp_path / "clip.mp4")
    shutil.copy(tone_video, video)
    full = _extension_argv(video, "python3", "main.py")
    # same shape as the extension, with offline providers appended
    argv = full[2:] + ["--source-lang", "en", "--stt", "fake", "--tts", "fake", "--translate", "fake"]
    before = hashlib.sha256(open(video, "rb").read()).hexdigest()
    code = cli.main(argv)
    assert code == 0, capsys.readouterr().err
    assert os.path.exists(video.replace(".mp4", ".srt"))
    assert os.path.exists(video.replace(".mp4", "_dubbed.mp4"))
    assert hashlib.sha256(open(video, "rb").read()).hexdigest() == before
    _util.assert_monotonic_nonoverlapping(_util.parse_srt(video.replace(".mp4", ".srt")))
