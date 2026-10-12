"""Real local TTS via piper (ONNX, CPU). Voice models download on demand."""
from __future__ import annotations

import os
import wave
from pathlib import Path

from ..errors import DependencyError, ProviderError

DEFAULT_VOICE = "en_US-lessac-medium"


def default_cache_dir() -> Path:
    base = os.environ.get("AUTODUB_PIPER_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "vlc-auto-dub", "piper"
    )
    return Path(base)


class PiperTTS:
    def __init__(self, voice: str | None = None, cache_dir: str | None = None):
        self.voice = voice or DEFAULT_VOICE
        self.cache_dir = Path(cache_dir) if cache_dir else default_cache_dir()
        self._loaded = None

    def _ensure_model(self) -> Path:
        model = self.cache_dir / f"{self.voice}.onnx"
        if model.exists():
            return model
        try:
            from piper.download_voices import download_voice
        except ImportError as exc:  # pragma: no cover
            raise DependencyError(
                "provider 'piper' needs the 'piper-tts' package (pip install piper-tts)"
            ) from exc
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            download_voice(self.voice, self.cache_dir)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"could not download piper voice {self.voice!r}: {exc}"
            ) from exc
        if not model.exists():
            raise ProviderError(f"piper voice {self.voice!r} not found after download")
        return model

    def _load(self):
        if self._loaded is None:
            try:
                from piper import PiperVoice
            except ImportError as exc:  # pragma: no cover
                raise DependencyError(
                    "provider 'piper' needs the 'piper-tts' package (pip install piper-tts)"
                ) from exc
            self._loaded = PiperVoice.load(str(self._ensure_model()))
        return self._loaded

    def synthesize(self, text: str, out_path: str, voice: str | None) -> None:
        if voice and voice != self.voice:
            self.voice = voice
            self._loaded = None
        model = self._load()
        try:
            with wave.open(out_path, "wb") as wav_file:
                model.synthesize_wav(text, wav_file)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"piper synthesis failed: {exc}") from exc
