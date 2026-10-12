"""Real local TTS via the espeak-ng CLI (small, no model download).

``voice`` is an espeak-ng voice name or language code (e.g. ``en``, ``tr``,
``fr``); it defaults to ``en``.
"""
from __future__ import annotations

import subprocess

from ..errors import DependencyError, ProviderError


class EspeakTTS:
    def __init__(self, voice: str | None = None, speed: int = 150):
        self.voice = voice or "en"
        self.speed = speed

    def synthesize(self, text: str, out_path: str, voice: str | None) -> None:
        chosen = voice or self.voice
        try:
            subprocess.run(
                ["espeak-ng", "-v", chosen, "-s", str(self.speed), "-w", out_path, text],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
        except FileNotFoundError as exc:
            raise DependencyError(
                "provider 'espeak' needs the 'espeak-ng' program "
                "(sudo apt-get install espeak-ng)"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise ProviderError(f"espeak-ng failed: {(exc.stderr or '').strip()}") from exc
