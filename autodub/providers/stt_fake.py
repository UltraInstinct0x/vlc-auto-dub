"""Deterministic STT fake (no model, no network). Used by unit/e2e tests."""
from __future__ import annotations

from .base import Segment


class FakeSTT:
    """Return evenly-spaced segments covering the audio duration.

    ``segment_seconds`` controls the slice length; a fixed phrase is used so
    tests are fully deterministic. This is a test double, never a model.
    """

    def __init__(self, segment_seconds: float = 2.0, text: str = "fake segment"):
        self.segment_seconds = segment_seconds
        self.text = text
        self.detected_language: str | None = None

    def transcribe(self, audio_path: str, language: str | None) -> list[Segment]:
        from ..media import duration

        self.detected_language = language or "en"  # deterministic "detection"
        total = duration(audio_path)
        segments: list[Segment] = []
        t = 0.0
        while t < total - 1e-6:
            end = min(t + self.segment_seconds, total)
            start_r, end_r = round(t, 3), round(end, 3)
            if end_r > start_r:  # skip a sub-millisecond tail that rounds to zero length
                segments.append(Segment(start_r, end_r, self.text))
            t = end
        return segments
