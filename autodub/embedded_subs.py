"""Use a text subtitle track already inside the input instead of transcribing.

Transcription is by far the slowest stage. When the file carries a text
subtitle track (SubRip, ASS/SSA, mov_text, WebVTT), its cues already give the
spoken lines and their timing, so they can be dubbed directly. Bitmap tracks
(PGS, VobSub, DVB) hold pictures, not text, and are never used.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from . import media
from .languages import _ISO639_2
from .providers.base import Segment

TEXT_SUBTITLE_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text", "tx3g"}

# 3-letter track tags -> 2-letter codes the translators and voices use.
# Both ISO 639-2/B (what we write) and 639-2/T (what many muxers write).
_TO_ISO1 = {v: k for k, v in _ISO639_2.items()}
_TO_ISO1.update({
    "deu": "de", "fra": "fr", "nld": "nl", "zho": "zh", "ces": "cs", "ell": "el",
    "fas": "fa", "ron": "ro", "slk": "sk", "sqi": "sq", "alb": "sq", "isl": "is",
    "ice": "is", "msa": "ms", "may": "ms", "nob": "no", "nno": "no",
})


@dataclass
class EmbeddedTrack:
    index: int            # absolute ffprobe stream index (for -map 0:<index>)
    language: str | None  # 2-letter code, or None when untagged/unknown
    codec: str
    title: str


def iso1(tag: str | None) -> str | None:
    """Map a language tag (``eng``, ``en``, ``pt-BR``) to a 2-letter code.

    ``None`` means untagged (missing or ``und``). A 3-letter code we have no
    2-letter form for (``tam``) is returned as it is: a known language we can't
    name, which is not the same as no language.
    """
    if not tag:
        return None
    tag = str(tag).strip().lower().replace("_", "-").split("-")[0]
    if tag in ("", "und"):
        return None
    return _TO_ISO1.get(tag, tag)


def usable_tracks(streams: list[dict]) -> list[tuple[dict, EmbeddedTrack]]:
    """Text subtitle tracks that carry the full dialogue, whatever their language.

    Forced tracks (only the foreign-language bits of a film) and our own AutoDub
    tracks from an earlier run are left out.
    """
    out = []
    for s in streams:
        if s.get("codec_type") != "subtitle":
            continue
        if s.get("codec_name", "") not in TEXT_SUBTITLE_CODECS or media.is_autodub_stream(s):
            continue
        if s.get("disposition", {}).get("forced"):
            continue
        tags = s.get("tags", {})
        out.append((s, EmbeddedTrack(int(s["index"]), iso1(tags.get("language")),
                                     s.get("codec_name", ""), str(tags.get("title", "")))))
    return out


def find_track(streams: list[dict], source_code: str | None, target_code: str | None,
               *, allow_untagged: bool = True) -> EmbeddedTrack | None:
    """Pick the best usable text subtitle track, or ``None``.

    Preference: a track already in the target language (no translation needed),
    then one in the spoken language, then, when the spoken language is known and
    ``allow_untagged``, an untagged one (assumed to be in it). A track in any
    other language is never used. Within that, full tracks beat
    SDH/hearing-impaired ones, and the default track beats the rest.
    """
    source, target = iso1(source_code), iso1(target_code)
    ranked = []
    for order, (s, track) in enumerate(usable_tracks(streams)):
        if target and track.language == target:
            lang_rank = 0
        elif source and track.language == source:
            lang_rank = 1
        elif source and track.language is None and allow_untagged:
            lang_rank = 2
        else:
            continue
        disp = s.get("disposition", {})
        ranked.append(((lang_rank, 1 if disp.get("hearing_impaired") else 0,
                        0 if disp.get("default") else 1, order), track))
    if not ranked:
        return None
    return min(ranked, key=lambda kt: kt[0])[1]


_TAG_RE = re.compile(r"<[^>]*>|\{[^}]*\}")             # HTML-ish and ASS override tags
_SOUND_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)")       # [music], (sighs)
_SUNG_RE = re.compile(r"[♪♫][^♪♫]*[♪♫]")               # ♪ lyrics ♪, maybe over two lines
_HASH_SUNG_RE = re.compile(r"^#.*#$|^[#\s]+$")          # # lyrics #
_DASH_RE = re.compile(r"^[-‐–—]\s*(?=\D)")              # "- Hi" (but not "-5 degrees")
_LABEL_RE = re.compile(r"^([^\W\d_][\w .'’&#-]{0,30}):\s*")  # JOHN:, MAN 2:
_TS_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})")


def clean_text(text: str) -> str:
    """Strip formatting and anything not spoken; return the text on one line.

    Sung lines (♪) go too: the dub then leaves the original singing in place.
    """
    text = text.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    text = _TAG_RE.sub("", text)
    text = _SOUND_RE.sub(" ", text)
    text = _SUNG_RE.sub(" ", text)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if "♪" in line or "♫" in line or _HASH_SUNG_RE.match(line):
            continue
        line = _DASH_RE.sub("", line)
        label = _LABEL_RE.match(line)
        if label and label.group(1).isupper():
            line = line[label.end():]
        line = _DASH_RE.sub("", line).strip()
        if line:
            lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _seconds(ts: str) -> float:
    h, m, s, ms = _TS_RE.match(ts.strip()).groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(text: str) -> list[Segment]:
    segments = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        timing = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing is None:
            continue
        start, _, end = lines[timing].partition("-->")
        try:
            seg = Segment(_seconds(start), _seconds(end.split()[0]),
                          clean_text("\n".join(lines[timing + 1:])))
        except (AttributeError, IndexError):
            continue
        segments.append(seg)
    return segments


def normalize(segments: list[Segment]) -> list[Segment]:
    """Order cues and make them non-overlapping, as the dub timeline requires.

    Cues starting at (nearly) the same time are merged; a cue that overlaps the
    next is cut short at the next cue's start. Empty or zero-length cues go.
    """
    out: list[Segment] = []
    for seg in sorted((s for s in segments if s.text and s.end > s.start),
                      key=lambda s: (s.start, s.end)):
        if out and seg.start < out[-1].end:
            prev = out[-1]
            if seg.start - prev.start < 0.3:
                prev.text = f"{prev.text} {seg.text}"
                prev.end = max(prev.end, seg.end)
                continue
            prev.end = seg.start
        out.append(Segment(round(seg.start, 3), round(seg.end, 3), seg.text))
    return [s for s in out if s.end - s.start > 1e-3]


def extract_segments(input_path: str, track: EmbeddedTrack, workdir: str) -> list[Segment]:
    """Convert the chosen track to SRT with ffmpeg and return clean segments."""
    srt = os.path.join(workdir, "embedded.srt")
    media.require_binary("ffmpeg")
    media._run(["ffmpeg", "-y", "-v", "error", "-i", input_path,
                "-map", f"0:{track.index}", "-c:s", "srt", srt])
    with open(srt, encoding="utf-8", errors="replace") as fh:
        return normalize(parse_srt(fh.read()))
