"""Deterministic TTS fake: writes a valid PCM WAV tone (no engine, no network).

The tone length scales with text length so timing behaviour is exercised, but
it is a fixed synthesised waveform -- a test double, not real speech.
"""
from __future__ import annotations

import math
import wave

SAMPLE_RATE = 16000


class FakeTTS:
    def __init__(self, voice: str | None = None, seconds_per_char: float = 0.08,
                 base_seconds: float = 0.2):
        self.voice = voice
        self.seconds_per_char = seconds_per_char
        self.base_seconds = base_seconds

    def synthesize(self, text: str, out_path: str, voice: str | None) -> None:
        duration = self.base_seconds + self.seconds_per_char * max(len(text), 1)
        n = int(duration * SAMPLE_RATE)
        frames = bytearray()
        for i in range(n):
            value = int(0.3 * 32767 * math.sin(2 * math.pi * 220.0 * i / SAMPLE_RATE))
            frames += int(value).to_bytes(2, "little", signed=True)
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(bytes(frames))
