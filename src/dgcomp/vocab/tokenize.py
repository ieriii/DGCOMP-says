"""Regex tokeniser.

Preserves original case and handles edge cases that show up in EU decision
PDFs: hyphenated compounds, apostrophes, diacritics, ligatures, and line-break
hyphenation.
"""

from __future__ import annotations

import unicodedata

import regex

# Unicode-aware: \p{L} matches any letter (incl. diacritics).
# Word: starts and ends with a letter; may contain internal apostrophes/hyphens.
_WORD_RE = regex.compile(r"\b\p{L}[\p{L}'\-]*\p{L}\b")

# Curly quotes / dashes / NBSP that commonly appear in PDF text extraction.
_PUNCT_FOLD = str.maketrans(
    {
        "\u2019": "'",
        "\u2018": "'",
        "\u201C": '"',
        "\u201D": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00A0": " ",
    }
)

# Markdown formatting characters Docling may leave around words.
_MD_STRIP = regex.compile(r"[#*_`>\[\]]")

# PDF hyphenation: "competit-\nion" → "competition" (only when next line is lowercase).
_HYPH_LINEBREAK = regex.compile(r"(\p{Ll})-\n(\p{Ll})")


def normalise(text: str) -> str:
    """Apply Unicode NFKC, fold curly quotes/dashes, strip markdown punctuation."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_PUNCT_FOLD)
    text = _MD_STRIP.sub(" ", text)
    return text


def collapse_hyphenation(text: str) -> str:
    """Stitch words split across line breaks: ``competit-\\nion`` → ``competition``."""
    return _HYPH_LINEBREAK.sub(r"\1\2", text)


def tokenise(text: str) -> list[str]:
    """Return word tokens preserving original case.

    Order matters: hyphenation must be collapsed *before* tokenisation, otherwise
    ``"competit-\\nion"`` yields ``["competit", "ion"]`` instead of
    ``["competition"]``.
    """
    text = collapse_hyphenation(normalise(text))
    return [m.group(0) for m in _WORD_RE.finditer(text)]
