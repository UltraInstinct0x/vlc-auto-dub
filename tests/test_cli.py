import hashlib

import pytest

import main as cli


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_help_lists_options(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--output-base", "--source-lang", "--target-lang", "--stt",
                 "--tts", "--subtitle-only", "--keep-workdir", "--config"):
        assert flag in out


def test_missing_input_exits_nonzero(capsys):
    code = cli.main(["/no/such/file.mp4", "--output-base", "/tmp/out"])
    assert code == 1
    assert "input file not found" in capsys.readouterr().err


def test_unknown_provider_exits_nonzero(tone_video, tmp_path, capsys):
    code = cli.main([
        tone_video, "--output-base", str(tmp_path / "o"),
        "--stt", "bogus", "--tts", "fake",
    ])
    assert code == 1
    assert "unknown STT provider" in capsys.readouterr().err


def test_refuses_to_overwrite_input(tone_video, tmp_path, capsys):
    import shutil
    # craft input named <base>_dubbed.mp4 so output_video == input
    victim = tmp_path / "clip_dubbed.mp4"
    shutil.copy(tone_video, victim)
    code = cli.main([str(victim), "--output-base", str(tmp_path / "clip"),
                     "--stt", "fake", "--tts", "fake"])
    assert code == 1
    assert "overwrite the input" in capsys.readouterr().err
    assert victim.exists()
