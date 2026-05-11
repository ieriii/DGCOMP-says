"""Sentence segmentation.

Sentences are needed for two things:
  1. Context shown in the Buttondown email body.
  2. Cache key for the LLM validator (a word + sentence pair).

The implementation is deliberately simple: split on sentence-ending punctuation
followed by whitespace and a capital letter. This misses some edge cases
(e.g., "Mr. Smith") but those are rare in EU decisions and not worth the
weight of a heavyweight NLP segmenter.
"""

from __future__ import annotations

import regex

from dgcomp.vocab.tokenize import collapse_hyphenation, normalise

_SENTENCE_RE = regex.compile(r"(?<=[.!?])\s+(?=\p{Lu})")
_WHITESPACE_RUN = regex.compile(r"\s+")


def segment(text: str) -> list[str]:
    """Return cleaned sentences from raw extraction output."""
    text = collapse_hyphenation(normalise(text))
    sentences = _SENTENCE_RE.split(text)
    return [_WHITESPACE_RUN.sub(" ", s).strip() for s in sentences if s.strip()]
