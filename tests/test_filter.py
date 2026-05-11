"""Shape-filter tests."""

from __future__ import annotations

import pytest

from dgcomp.vocab.filter import passes_shape


@pytest.mark.parametrize(
    "token",
    [
        "antitrust",
        "Commission",
        "non-confidential",
        "state-of-the-art",
        "Commission's",
        "O'Brien",
        "ancillary",
        "tying",
    ],
)
def test_keeps_real_words(token: str) -> None:
    assert passes_shape(token)


@pytest.mark.parametrize(
    "token",
    [
        "",  # empty
        "a",  # too short
        "ab",  # too short
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",  # too long
        "EUR",  # all-uppercase (likely heading/acronym)
        "DGCOMP",  # all-uppercase
        "BFXMZW",  # all-uppercase + no vowel
        "rxn",  # no vowel (not all-upper but still junk)
        "东山白卢",  # CJK letters — passes \\p{L} but fails ASCII shape
        "Société",  # diacritics — accepted by the tokeniser, rejected here
        "café",  # diacritic
        "1234",  # numbers
    ],
)
def test_rejects_junk(token: str) -> None:
    assert not passes_shape(token)
