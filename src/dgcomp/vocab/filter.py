"""Cheap deterministic filter applied before the LLM validator.

Every check here is free; if a token survives all of them it goes to Haiku
(see ``vocab/validate.py``). Order is deliberate: cheapest checks first.
"""

from __future__ import annotations

import regex

_VOWEL_RE = regex.compile(r"[aeiouyAEIOUY]")
_ASCII_LETTER_RE = regex.compile(r"^[A-Za-z][A-Za-z'\-]*[A-Za-z]$")

MIN_LEN = 3
MAX_LEN = 30


def passes_shape(token: str) -> bool:
    """Return True if a token passes the cheap shape filter.

    Rejects:
      - length < 3 or > 30 (single chars, suspiciously long strings)
      - all-uppercase tokens (almost always headings or acronyms)
      - tokens with no vowel (e.g. ``BFXMZW`` from OCR)
      - non-ASCII-letter tokens (CJK characters, mathematical symbols)

    Diacritic words like ``Société`` are rejected here. We accept this — the
    bot is English-only and PDF text-extraction occasionally mis-types ASCII
    diacritics into Unicode-letter forms; the LLM stage would also reject
    them as foreign words.
    """
    if not (MIN_LEN <= len(token) <= MAX_LEN):
        return False
    if token.isupper():
        return False
    if not _VOWEL_RE.search(token):
        return False
    return _ASCII_LETTER_RE.match(token) is not None
