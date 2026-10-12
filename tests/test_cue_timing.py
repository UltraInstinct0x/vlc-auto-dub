"""Cue shaping from word timestamps: cues hug speech, split at pauses."""
from __future__ import annotations

from autodub.providers.stt_whisper import MAX_CUE_CHARS, words_to_cues


def w(start, end, text):
    return (start, end, text)


def test_cue_ends_at_last_word_not_at_next_cue():
    # "Raise your arms." then 14 s of silence, then the next line.
    cues = words_to_cues([w(89.9, 90.2, " Raise"), w(90.2, 90.4, " your"), w(90.4, 90.9, " arms."),
                          w(104.9, 105.3, " Okay.")])
    assert [c.text for c in cues] == ["Raise your arms.", "Okay."]
    assert cues[0].start == 89.9
    assert cues[0].end <= 91.2          # last word + small pad, not 104.9
    assert cues[1].start == 104.9


def test_pause_splits_and_pad_never_overlaps():
    cues = words_to_cues([w(0.0, 0.5, " Hello"), w(0.5, 1.0, " there"),
                          w(1.8, 2.2, " Next"), w(2.2, 2.6, " one")])
    assert len(cues) == 2
    assert cues[0].end < cues[1].start


def test_sentence_end_splits_on_small_gap():
    cues = words_to_cues([w(0.0, 0.4, " Stop."), w(0.7, 1.0, " Now")])
    assert [c.text for c in cues] == ["Stop.", "Now"]


def test_long_run_is_split_for_readability():
    words = [w(i * 0.3, i * 0.3 + 0.28, " word") for i in range(60)]
    cues = words_to_cues(words)
    assert len(cues) > 1
    assert all(len(c.text) <= MAX_CUE_CHARS for c in cues)
    assert all(c.end - c.start <= 6.6 for c in cues)


def test_no_words_no_cues():
    assert words_to_cues([]) == []
