"""Real local STT via faster-whisper (CPU, int8).

Audio is decoded to a float32 numpy array with ffmpeg first: faster-whisper
1.2.1's bundled decoder calls ``av.open(..., metadata_errors=...)``, which
PyAV 19 rejects, so we bypass it by passing samples directly.
"""
from __future__ import annotations

from ..errors import DependencyError, ProviderError
from .base import Segment


class WhisperSTT:
    def __init__(self, model_size: str = "tiny", device: str = "cpu",
                 compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:  # pragma: no cover
                raise DependencyError(
                    "provider 'whisper' needs the 'faster-whisper' package "
                    "(pip install faster-whisper)"
                ) from exc
            self._model = WhisperModel(
                self.model_size, device=self.device, compute_type=self.compute_type
            )
        return self._model

    def transcribe(self, audio_path: str, language: str | None) -> list[Segment]:
        from ..media import read_samples

        model = self._load()
        samples = read_samples(audio_path)
        try:
            seg_iter, _info = model.transcribe(
                samples, language=language, beam_size=1, vad_filter=False
            )
            segments = [
                Segment(float(s.start), float(s.end), s.text.strip())
                for s in seg_iter
            ]
        except Exception as exc:  # noqa: BLE001 - surfaced as a clear provider error
            raise ProviderError(f"whisper transcription failed: {exc}") from exc
        return [s for s in segments if s.text]
