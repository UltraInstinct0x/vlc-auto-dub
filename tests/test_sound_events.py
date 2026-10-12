"""Sound tags: placed only in speech gaps, labelled in the target language."""
from __future__ import annotations

import importlib.util

import pytest

from autodub.providers.base import Segment
from autodub.sound_events import (
    MAX_TAG_SECONDS, SoundTagger, speech_gaps, tags_from_scores, windows_for,
)


def test_gaps_exclude_speech_and_short_pauses():
    speech = [Segment(1.0, 3.0, "a"), Segment(3.5, 5.0, "b"), Segment(9.0, 10.0, "c")]
    gaps = speech_gaps(speech, 12.0)
    assert gaps[0] == (0.0, 0.95)
    assert all(not (s < 5.0 and e > 3.5) for s, e in gaps)   # 0.5 s pause ignored
    assert any(abs(s - 5.05) < 1e-9 and abs(e - 8.95) < 1e-9 for s, e in gaps)
    assert gaps[-1][1] == 12.0


def test_windows_cover_gap():
    from autodub.sound_events import HOP, WINDOW

    ws = windows_for((10.0, 10.0 + 3 * WINDOW))
    assert ws[0] == (10.0, 10.0 + WINDOW)
    assert ws[-1][1] == pytest.approx(10.0 + 3 * WINDOW)
    assert all(b - a == pytest.approx(WINDOW) for a, b in ws)
    assert ws[1][0] - ws[0][0] == pytest.approx(HOP)
    assert windows_for((1.0, 2.2)) == [(1.0, 2.2)]


def test_tags_merge_cap_label_and_cooldown():
    gaps = [(10.0, 20.0), (25.0, 30.0)]
    windows = [(10.0, 12.0), (11.0, 13.0), (12.0, 14.0), (25.0, 27.0)]
    laugh = {"Laughter": 0.8}
    scores = [laugh, laugh, laugh, laugh]
    tags = tags_from_scores(windows, scores, gaps, "tr")
    assert [t.text for t in tags] == ["[kahkaha]"]          # 2nd within cooldown
    assert tags[0].start == 10.0
    assert tags[0].end - tags[0].start <= MAX_TAG_SECONDS
    en = tags_from_scores(windows[:1], scores[:1], gaps, "en")
    assert en[0].text == "[laughter]"


def test_below_threshold_or_unmapped_labels_give_nothing():
    gaps = [(0.0, 5.0)]
    assert tags_from_scores([(0.0, 2.0)], [{"Laughter": 0.1}], gaps, "tr") == []
    assert tags_from_scores([(0.0, 2.0)], [{"Sine wave": 0.9}], gaps, "tr") == []


def test_strongest_group_wins():
    tags = tags_from_scores([(0.0, 2.0)], [{"Train": 0.5, "Music": 0.45}], [(0.0, 5.0)], "tr")
    assert [t.text for t in tags] == ["[tren]"]


@pytest.mark.skipif(importlib.util.find_spec("transformers") is None,
                    reason="transformers not installed")
def test_real_model_runs_on_audio():
    import numpy as np

    sr = 16000
    t = np.arange(int(sr * 4)) / sr
    samples = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    tagger = SoundTagger()
    scores = tagger.classify(samples, [(0.0, 2.0), (2.0, 4.0)])
    assert len(scores) == 2 and all(isinstance(s, dict) for s in scores)
    assert any(scores), "the real classifier produced no labels at all"
    # a pure tone is not one of the tagged sound classes
    assert tagger.tag(samples, [], "tr") == []
