"""Non-speech sound tags for subtitles: [laughter], [screaming], [train], ...

Whisper suppresses non-speech sounds and VAD drops them, so they are detected
separately with an AudioSet classifier (MIT's AST, 527 sound classes, BSD-3).
Only the gaps *between* speech cues are analysed: that keeps it fast and means
tags never overlap dialogue. Tags go to the subtitles only, never to the dub.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import DependencyError, ProviderError
from .progress import progress
from .providers.base import Segment

MODEL_ID = "MIT/ast-finetuned-audioset-10-10-0.4593"
SAMPLE_RATE = 16000
# AST always pads its input to ~10 s, so tiny windows waste compute; 5 s with a
# 2.5 s hop is a balance between speed and where a tag lands.
WINDOW = 5.0          # seconds of audio per classification
HOP = 2.5
MIN_GAP = 1.0         # ignore gaps shorter than this
MAX_TAG_SECONDS = 4.0
REPEAT_COOLDOWN = 20.0  # don't repeat the same tag within this many seconds
MARGIN = 0.05


@dataclass(frozen=True)
class Group:
    labels: frozenset
    tr: str
    en: str
    threshold: float = 0.3


def _g(labels, tr, en, threshold=0.3) -> Group:
    return Group(frozenset(labels), tr, en, threshold)


GROUPS = [
    _g({"Laughter", "Belly laugh", "Giggle", "Chuckle, chortle", "Snicker", "Baby laughter"},
       "kahkaha", "laughter"),
    _g({"Screaming", "Yell", "Bellow", "Battle cry", "Shout"}, "çığlık", "screaming"),
    _g({"Crying, sobbing", "Baby cry, infant cry", "Whimper"}, "ağlama", "crying"),
    _g({"Wail, moan", "Groan"}, "inleme", "moaning"),
    _g({"Gasp", "Pant", "Breathing"}, "nefes nefese", "heavy breathing", 0.4),
    _g({"Sigh"}, "iç çekme", "sighs"),
    _g({"Whispering"}, "fısıltı", "whispering"),
    _g({"Cough"}, "öksürük", "coughing"),
    _g({"Applause", "Clapping"}, "alkış", "applause"),
    _g({"Cheering"}, "tezahürat", "cheering"),
    _g({"Slap, smack"}, "şaplak", "slap"),
    _g({"Walk, footsteps"}, "ayak sesleri", "footsteps", 0.4),
    _g({"Knock"}, "kapı çalınıyor", "knocking"),
    _g({"Door", "Sliding door"}, "kapı", "door", 0.4),
    _g({"Telephone bell ringing", "Telephone", "Ringtone"}, "telefon çalıyor", "phone ringing"),
    _g({"Dog", "Bark", "Yip"}, "köpek havlıyor", "dog barking"),
    _g({"Train", "Train whistle", "Train horn", "Railroad car, train wagon",
        "Train wheels squealing", "Subway, metro, underground"}, "tren", "train"),
    _g({"Siren", "Police car (siren)", "Ambulance (siren)",
        "Fire engine, fire truck (siren)", "Civil defense siren"}, "siren", "siren"),
    _g({"Vehicle horn, car horn, honking"}, "korna", "car horn"),
    _g({"Thunder", "Thunderstorm"}, "gök gürültüsü", "thunder"),
    _g({"Rain", "Rain on surface"}, "yağmur", "rain", 0.4),
    _g({"Gunshot, gunfire", "Machine gun", "Cap gun"}, "silah sesi", "gunshots"),
    _g({"Explosion"}, "patlama", "explosion"),
    _g({"Music", "Background music", "Soundtrack music", "Theme music"}, "müzik", "music", 0.4),
]


def tag_text(group: Group, lang: str | None) -> str:
    return f"[{group.tr if lang == 'tr' else group.en}]"


def speech_gaps(cues: list[Segment], total: float) -> list[tuple[float, float]]:
    """Intervals with no speech cue, shrunk by a small margin on each side."""
    gaps, cursor = [], 0.0
    for cue in sorted(cues, key=lambda c: c.start):
        if cue.start - cursor >= MIN_GAP:
            gaps.append((cursor + (MARGIN if cursor else 0.0), cue.start - MARGIN))
        cursor = max(cursor, cue.end)
    if total - cursor >= MIN_GAP:
        gaps.append((cursor + MARGIN, total))
    return gaps


def windows_for(gap: tuple[float, float]) -> list[tuple[float, float]]:
    start, end = gap
    if end - start <= WINDOW:
        return [(start, end)]
    out, t = [], start
    while t + WINDOW <= end + 1e-6:
        out.append((t, t + WINDOW))
        t += HOP
    if out[-1][1] < end - 0.25:
        out.append((end - WINDOW, end))
    return out


def tags_from_scores(windows: list[tuple[float, float]], scores: list[dict],
                     gaps: list[tuple[float, float]], lang: str | None) -> list[Segment]:
    """Turn per-window label scores into tag cues confined to their gap."""
    hits: list[tuple[float, float, Group]] = []
    for (start, end), label_scores in zip(windows, scores):
        best, best_score = None, 0.0
        for group in GROUPS:
            s = max((label_scores.get(label, 0.0) for label in group.labels), default=0.0)
            if s >= group.threshold and s > best_score:
                best, best_score = group, s
        if best is not None:
            hits.append((start, end, best))

    # Merge consecutive windows of the same group.
    merged: list[list] = []
    for start, end, group in hits:
        if merged and merged[-1][2] is group and start <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end, group])

    tags: list[Segment] = []
    last_seen: dict[str, float] = {}
    for start, end, group in merged:
        gap = next((g for g in gaps if g[0] - 1e-6 <= start < g[1]), None)
        if gap is None:
            continue
        end = min(end, gap[1], start + MAX_TAG_SECONDS)
        if end - start < 0.5:
            continue
        if start - last_seen.get(group.en, -1e9) < REPEAT_COOLDOWN:
            last_seen[group.en] = end
            continue
        last_seen[group.en] = end
        tags.append(Segment(round(start, 3), round(end, 3), tag_text(group, lang)))
    return tags


class SoundTagger:
    def __init__(self):
        self._model = None
        self._extractor = None
        self._device = "cpu"

    def _load(self):
        if self._model is None:
            try:
                import torch  # noqa: F401
                from transformers import ASTFeatureExtractor, ASTForAudioClassification
            except ImportError as exc:  # pragma: no cover
                raise DependencyError(
                    "sound tags need 'transformers' and 'torch' "
                    "(pip install -r requirements.txt), or pass --no-sound-tags"
                ) from exc
            import os
            import warnings

            import torch
            from transformers.utils import logging as hf_logging

            # keep the job log readable: no download bars or mel-filter warnings
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            hf_logging.set_verbosity_error()
            hf_logging.disable_progress_bar()
            warnings.filterwarnings("ignore", message="At least one mel filter")
            self._device = "mps" if torch.backends.mps.is_available() else "cpu"
            try:
                self._extractor = ASTFeatureExtractor.from_pretrained(MODEL_ID)
                self._model = ASTForAudioClassification.from_pretrained(MODEL_ID).eval()
                self._model.to(self._device)
            except Exception as exc:  # noqa: BLE001
                raise ProviderError(f"could not load sound-tag model {MODEL_ID}: {exc}") from exc
        return self._model, self._extractor

    def classify(self, samples, windows: list[tuple[float, float]]) -> list[dict]:
        import torch

        model, extractor = self._load()
        labels = model.config.id2label
        out: list[dict] = []
        reported = 0
        for i in range(0, len(windows), 16):
            pct = int(100 * i / len(windows))
            if pct >= reported + 10:
                reported = pct - pct % 10
                progress(f"detecting sound tags {reported}%")
            chunk = windows[i:i + 16]
            audio = [samples[int(s * SAMPLE_RATE):int(e * SAMPLE_RATE)] for s, e in chunk]
            inputs = extractor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt")
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            with torch.no_grad():
                probs = torch.sigmoid(model(**inputs).logits).cpu()
            for row in probs:
                out.append({labels[j]: float(p) for j, p in enumerate(row) if p >= 0.1})
        return out

    def tag(self, samples, speech: list[Segment], lang: str | None) -> list[Segment]:
        total = len(samples) / SAMPLE_RATE
        gaps = speech_gaps(speech, total)
        windows = [w for gap in gaps for w in windows_for(gap)]
        if not windows:
            return []
        return tags_from_scores(windows, self.classify(samples, windows), gaps, lang)
