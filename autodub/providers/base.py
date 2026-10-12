"""Provider interfaces (protocols) and the Segment record."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Segment:
    start: float
    end: float
    text: str


class STT(Protocol):
    def transcribe(self, audio_path: str, language: str | None) -> list[Segment]:
        ...


class Translator(Protocol):
    def translate(self, text: str, source: str, target: str) -> str:
        ...


class TTS(Protocol):
    def synthesize(self, text: str, out_path: str, voice: str | None) -> None:
        ...
