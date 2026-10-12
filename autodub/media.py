"""ffmpeg/ffprobe wrappers.

Every external command is built as an argument **list** and run without a
shell, so paths containing spaces or quotes are safe and there is no shell
injection surface. All failures are raised as :class:`MediaError` with the
tool's own stderr in the message.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from .errors import DependencyError, MediaError

SAMPLE_RATE = 16000

# Apps started from the macOS Dock/Finder (e.g. VLC) get a minimal PATH without
# Homebrew or ~/.local/bin, so ffmpeg is "missing" there but present in a shell.
_EXTRA_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin"))


def _extend_path() -> None:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    extra = [d for d in _EXTRA_BIN_DIRS if os.path.isdir(d) and d not in parts]
    if extra:
        os.environ["PATH"] = os.pathsep.join(parts + extra)


_extend_path()


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


def has_video_stream(path: str) -> bool:
    require_binary("ffprobe")
    out = _run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v",
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


def probe_streams(path: str) -> list[dict]:
    """Return ffprobe's stream list (index, codec_type, codec_name, tags, ...)."""
    import json

    require_binary("ffprobe")
    out = _run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "stream=index,codec_type,codec_name:stream_tags=language,title,handler_name"
            ":stream_disposition=default",
            "-of", "json", path,
        ]
    ).stdout
    try:
        return json.loads(out).get("streams", [])
    except ValueError as exc:
        raise MediaError(f"could not read the streams of {path!r}") from exc


def extract_audio(video: str, out_wav: str, sample_rate: int = SAMPLE_RATE,
                  audio_index: int | None = None) -> None:
    """Extract a mono PCM WAV track from ``video``.

    ``audio_index`` selects the n-th audio stream; by default ffmpeg picks one.
    """
    require_binary("ffmpeg")
    select = ["-map", f"0:a:{audio_index}"] if audio_index is not None else []
    _run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", video, *select,
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


# Track titles written by --in-place; used to find (and replace) earlier dubs.
AUTODUB_TITLE = "AutoDub"

# Containers --in-place can rewrite, mapped to the subtitle codec each accepts.
IN_PLACE_SUBTITLE_CODEC = {
    ".mp4": "mov_text", ".m4v": "mov_text", ".mov": "mov_text",
    ".mkv": "srt",
}


def is_autodub_stream(stream: dict) -> bool:
    # Matroska keeps the track name as "title"; MP4/MOV store it as "handler_name".
    tags = stream.get("tags", {})
    return any(str(tags.get(key, "")).startswith(AUTODUB_TITLE)
               for key in ("title", "handler_name"))


def mux_tracks(src: str, out: str, *, audio: str | None, srt: str | None,
               language: str, subtitle_codec: str) -> dict:
    """Copy every stream of ``src`` to ``out`` and add the dub and subtitle tracks.

    Nothing from ``src`` is re-encoded. The new audio track (if ``audio``) is
    encoded to AAC and made the default audio track; the new subtitle track is
    added but not forced on. Earlier AutoDub tracks for the same ``language``
    are dropped so re-dubbing replaces them instead of piling up.

    Returns the stream counts the output is expected to have, for verification.
    """
    require_binary("ffmpeg")
    streams = probe_streams(src)
    dropped = [
        s for s in streams
        if is_autodub_stream(s) and s.get("tags", {}).get("language") == language
    ]
    kept = [s for s in streams if s not in dropped]
    n_audio = sum(1 for s in kept if s.get("codec_type") == "audio")
    n_subs = sum(1 for s in kept if s.get("codec_type") == "subtitle")

    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src]
    inputs = 1
    audio_input = sub_input = None
    if audio is not None:
        cmd += ["-i", audio]
        audio_input, inputs = inputs, inputs + 1
    if srt is not None:
        cmd += ["-i", srt]
        sub_input = inputs

    cmd += ["-map", "0"]
    for s in dropped:
        cmd += ["-map", f"-0:{s['index']}"]
    if audio_input is not None:
        cmd += ["-map", f"{audio_input}:a:0"]
    if sub_input is not None:
        cmd += ["-map", f"{sub_input}:s:0"]
    cmd += ["-map_metadata", "0", "-map_chapters", "0"]
    cmd += ["-c", "copy"]

    label = f"{AUTODUB_TITLE} ({language})"
    if audio_input is not None:
        cmd += [f"-c:a:{n_audio}", "aac", f"-b:a:{n_audio}", "160k"]
        for i in range(n_audio):
            cmd += [f"-disposition:a:{i}", "0"]
        cmd += [
            f"-disposition:a:{n_audio}", "default",
            f"-metadata:s:a:{n_audio}", f"language={language}",
            f"-metadata:s:a:{n_audio}", f"title={label}",
            f"-metadata:s:a:{n_audio}", f"handler_name={label}",
        ]
    if sub_input is not None:
        cmd += [
            f"-c:s:{n_subs}", subtitle_codec,
            f"-disposition:s:{n_subs}", "0",
            f"-metadata:s:s:{n_subs}", f"language={language}",
            f"-metadata:s:s:{n_subs}", f"title={label}",
            f"-metadata:s:s:{n_subs}", f"handler_name={label}",
        ]
    _run(cmd + [out])

    expected: dict[str, int] = {}
    for s in kept:
        kind = s.get("codec_type", "")
        expected[kind] = expected.get(kind, 0) + 1
    if audio_input is not None:
        expected["audio"] = expected.get("audio", 0) + 1
    if sub_input is not None:
        expected["subtitle"] = expected.get("subtitle", 0) + 1
    return {k: v for k, v in expected.items() if v}


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
