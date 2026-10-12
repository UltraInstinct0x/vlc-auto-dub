"""Subtitle model and SRT writer with validation."""
from __future__ import annotations

from dataclasses import dataclass

from .errors import InputError


@dataclass
class Cue:
    start: float
    end: float
    text: str


def format_timestamp(seconds: float) -> str:
    """Seconds -> ``HH:MM:SS,mmm``."""
    if seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def validate_cues(cues: list[Cue]) -> None:
    """Raise :class:`InputError` unless cues are ordered and non-overlapping."""
    prev_end = -1.0
    for i, cue in enumerate(cues):
        if cue.end <= cue.start:
            raise InputError(
                f"cue {i + 1} has non-positive duration ({cue.start:.3f} -> {cue.end:.3f})"
            )
        if cue.start < prev_end - 1e-6:
            raise InputError(
                f"cue {i + 1} starts ({cue.start:.3f}) before the previous cue ends ({prev_end:.3f})"
            )
        prev_end = cue.end


def write_srt(cues: list[Cue], path: str) -> None:
    """Validate then write an SRT file (UTF-8)."""
    validate_cues(cues)
    with open(path, "w", encoding="utf-8") as fh:
        for i, cue in enumerate(cues, 1):
            fh.write(f"{i}\n")
            fh.write(f"{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}\n")
            fh.write(f"{cue.text.strip()}\n\n")
