"""Tiny SRT parser used by tests to assert timing properties."""
from __future__ import annotations

import re

_TS = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def _to_seconds(ts: str) -> float:
    h, m, s, ms = _TS.match(ts).groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(path: str) -> list[tuple[float, float, str]]:
    text = open(path, encoding="utf-8").read().strip()
    cues = []
    for block in re.split(r"\n\s*\n", text):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        start, _, end = lines[1].partition(" --> ")
        body = "\n".join(lines[2:]).strip()
        cues.append((_to_seconds(start.strip()), _to_seconds(end.strip()), body))
    return cues


def assert_monotonic_nonoverlapping(cues: list[tuple[float, float, str]]) -> None:
    prev_end = -1.0
    for i, (start, end, _text) in enumerate(cues):
        assert end > start, f"cue {i} has non-positive duration"
        assert start >= prev_end - 1e-6, f"cue {i} overlaps the previous cue"
        prev_end = end
