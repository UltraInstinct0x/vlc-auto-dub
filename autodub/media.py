"""ffmpeg/ffprobe wrappers.

Every external command is built as an argument **list** and run without a
shell, so paths containing spaces or quotes are safe and there is no shell
injection surface. All failures are raised as :class:`MediaError` with the
tool's own stderr in the message.
"""
from __future__ import annotations

import shutil
import subprocess

from .errors import DependencyError, MediaError

SAMPLE_RATE = 16000


def require_binary(name: str) -> str:
    """Return the path to ``name`` or raise an actionable DependencyError."""
    path = shutil.which(name)
    if not path:
        raise DependencyError(
            f"required program {name!r} was not found on PATH; install it "
            f"(e.g. `sudo apt-get install ffmpeg`)"
        )
    return path


def _run(cmd: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - guarded by require_binary
        raise DependencyError(f"could not execute {cmd[0]!r}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or "").strip().splitlines()
        detail = " | ".join(tail[-3:]) if tail else "no stderr"
        raise MediaError(f"{cmd[0]} failed: {detail}") from exc
    return result


def has_audio_stream(path: str) -> bool:
    require_binary("ffprobe")
    out = _run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "csv=p=0", path,
        ]
    ).stdout.strip()
    return bool(out)


def duration(path: str) -> float:
    require_binary("ffprobe")
    out = _run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
        ]
    ).stdout.strip()
    try:
        return float(out)
    except ValueError as exc:
        raise MediaError(f"could not read duration of {path!r}") from exc


def extract_audio(video: str, out_wav: str, sample_rate: int = SAMPLE_RATE) -> None:
    """Extract a mono PCM WAV track from ``video``."""
    require_binary("ffmpeg")
    _run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", video,
            "-vn", "-ac", "1", "-ar", str(sample_rate),
            "-acodec", "pcm_s16le", out_wav,
        ]
    )


def read_samples(wav: str, sample_rate: int = SAMPLE_RATE):
    """Return a float32 numpy array of mono samples decoded via ffmpeg.

    faster-whisper's own decoder is bypassed (its PyAV call is incompatible
    with newer ``av`` releases); we decode to raw float32 and pass the array.
    """
    import numpy as np  # imported lazily so non-STT paths do not need numpy

    require_binary("ffmpeg")
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", wav,
            "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return np.frombuffer(result.stdout, dtype=np.float32)


def fit_segment(src: str, window: float, out_wav: str, sample_rate: int = SAMPLE_RATE) -> None:
    """Make ``src`` occupy exactly ``window`` seconds (speed up if too long).

    The clip is sped up when it is longer than the window (at most 2x per
    ``atempo`` step, chained for larger factors), then padded and trimmed so
    it never overflows its slot.
    """
    require_binary("ffmpeg")
    src_dur = duration(src)
    filters: list[str] = []
    if src_dur > window and window > 0:
        factor = src_dur / window
        while factor > 2.0:  # atempo is only valid in [0.5, 2.0]
            filters.append("atempo=2.0")
            factor /= 2.0
        filters.append(f"atempo={max(0.5, factor):.5f}")
    filters.append(f"apad=whole_dur={window:.5f}")
    filters.append(f"atrim=0:{window:.5f}")
    _run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", src,
            "-af", ",".join(filters), "-ac", "1", "-ar", str(sample_rate),
            "-acodec", "pcm_s16le", out_wav,
        ]
    )


def slice_audio(src: str, start: float, dur: float, out_wav: str,
                sample_rate: int = SAMPLE_RATE) -> None:
    """Copy ``[start, start+dur)`` of ``src`` to ``out_wav`` as PCM."""
    require_binary("ffmpeg")
    _run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", src,
            "-ss", f"{start:.5f}", "-t", f"{dur:.5f}",
            "-ac", "1", "-ar", str(sample_rate),
            "-acodec", "pcm_s16le", out_wav,
        ]
    )


def concat_audio(parts: list[str], out_wav: str, list_file: str,
                 sample_rate: int = SAMPLE_RATE) -> None:
    """Concatenate PCM WAV parts via the ffmpeg concat demuxer."""
    require_binary("ffmpeg")
    with open(list_file, "w", encoding="utf-8") as fh:
        for part in parts:
            escaped = part.replace("'", "'\\''")
            fh.write(f"file '{escaped}'\n")
    _run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
            "-i", list_file, "-ac", "1", "-ar", str(sample_rate),
            "-acodec", "pcm_s16le", out_wav,
        ]
    )


def mux(video: str, audio: str, out_video: str) -> None:
    """Mux a new audio track onto the original video stream (video copied)."""
    require_binary("ffmpeg")
    _run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", video, "-i", audio,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-shortest", out_video,
        ]
    )
