"""Sentence segmentation tests."""

from __future__ import annotations

from dgcomp.vocab.segment import segment


def test_basic_sentences() -> None:
    text = "The Commission opened an investigation. Parties cooperated. A decision was issued."
    assert segment(text) == [
        "The Commission opened an investigation.",
        "Parties cooperated.",
        "A decision was issued.",
    ]


def test_collapses_hyphenation_before_segmenting() -> None:
    text = "The competit-\nion authority acted. It published a report."
    assert segment(text) == [
        "The competition authority acted.",
        "It published a report.",
    ]


def test_does_not_split_on_lowercase_continuation() -> None:
    # Decimals and abbreviations followed by lowercase shouldn't split.
    text = "The market share was 12.5 per cent. The Commission noted this."
    assert segment(text) == [
        "The market share was 12.5 per cent.",
        "The Commission noted this.",
    ]


def test_collapses_internal_whitespace() -> None:
    text = "Multiple   spaces\tand\ttabs.   Next   sentence."
    assert segment(text) == [
        "Multiple spaces and tabs.",
        "Next sentence.",
    ]


def test_empty_input() -> None:
    assert segment("") == []
    assert segment("   \n\n  ") == []
