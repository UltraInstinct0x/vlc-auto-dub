"""Real local STT via faster-whisper (CPU, int8).

Audio is decoded to a float32 numpy array with ffmpeg first: faster-whisper
1.2.1's bundled decoder calls ``av.open(..., metadata_errors=...)``, which
PyAV 19 rejects, so we bypass it by passing samples directly.

Timing: Whisper's segment boundaries absorb surrounding silence (a segment
often ends exactly where the next begins). We run with VAD and word
timestamps and rebuild cues from the words themselves, splitting at pauses
and at a readable length, so each cue starts at its first word and ends at its
last.
"""
from __future__ import annotations

from ..errors import DependencyError, ProviderError
from .base import Segment

DEFAULT_MODEL = "large-v3"

# Cue shaping (readable subtitles; standard broadcast-ish limits).
PAUSE_SPLIT = 0.7      # a silence this long between words starts a new cue
MAX_CUE_SECONDS = 6.0
MAX_CUE_CHARS = 84     # ~two lines of 42 characters
END_PAD = 0.2          # keep the cue up briefly after the last word


def words_to_cues(words: list[tuple[float, float, str]]) -> list[Segment]:
    """Group ``(start, end, word)`` triples into tight, readable cues."""
    cues: list[Segment] = []
    current: list[tuple[float, float, str]] = []

    def flush() -> None:
        if current:
            text = "".join(w for _s, _e, w in current).strip()
            if text:
                cues.append(Segment(current[0][0], current[-1][1], text))
            current.clear()

    for start, end, word in words:
        if current:
            gap = start - current[-1][1]
            length = len("".join(w for _s, _e, w in current)) + len(word)
            sentence_end = current[-1][2].rstrip().endswith((".", "?", "!"))
            too_long = start - current[0][0] > MAX_CUE_SECONDS or length > MAX_CUE_CHARS
            if gap >= PAUSE_SPLIT or too_long or (sentence_end and gap > 0.25):
                flush()
        current.append((start, end, word))
    flush()

    # Pad ends a little, never into the next cue.
    for i, cue in enumerate(cues):
        limit = cues[i + 1].start - 0.05 if i + 1 < len(cues) else cue.end + END_PAD
        cue.end = round(max(cue.end, min(cue.end + END_PAD, limit)), 3)
        cue.start = round(cue.start, 3)
    return cues


class WhisperSTT:
    def __init__(self, model_size: str = DEFAULT_MODEL, device: str = "cpu",
                 compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self.detected_language: str | None = None

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
            seg_iter, info = model.transcribe(
                samples,
                language=language,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                word_timestamps=True,
                # Prevents the repetition/hallucination loops Whisper falls into
                # on music, noise and non-speech sounds.
                condition_on_previous_text=False,
            )
            words: list[tuple[float, float, str]] = []
            for seg in seg_iter:
                for w in seg.words or []:
                    if w.word.strip():
                        words.append((float(w.start), float(w.end), w.word))
            self.detected_language = language or getattr(info, "language", None)
        except Exception as exc:  # noqa: BLE001 - surfaced as a clear provider error
            raise ProviderError(f"whisper transcription failed: {exc}") from exc
        return words_to_cues(words)
