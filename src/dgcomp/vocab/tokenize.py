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

# URLs and email addresses. EU decisions cite press releases and registries in
# footnotes; their path slugs ("…/prosus-sells-…-to-aspex-management") would
# otherwise leak as vocabulary *and*, worse, plant a lowercase occurrence of a
# party name that defeats the proper-noun filter in vocab/pipeline.py. We drop
# them wholesale before tokenisation. Applied *after* collapse_hyphenation so a
# URL broken across a line ("…/news-\ninsights/…") is stitched first.
_URL_RE = regex.compile(r"(?:https?://|www\.)\S+", regex.IGNORECASE)
_EMAIL_RE = regex.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+", regex.IGNORECASE)


def normalise(text: str) -> str:
    """Apply Unicode NFKC, fold curly quotes/dashes, strip markdown punctuation."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_PUNCT_FOLD)
    text = _MD_STRIP.sub(" ", text)
    return text


def collapse_hyphenation(text: str) -> str:
    """Stitch words split across line breaks: ``competit-\\nion`` → ``competition``."""
    return _HYPH_LINEBREAK.sub(r"\1\2", text)


def strip_urls(text: str) -> str:
    """Replace URLs and email addresses with a space.

    Footnote URLs are not prose: their slugs are not real vocabulary, and a
    lowercased party name inside one ("…to-aspex-management") would otherwise
    sneak a proper noun past the all-occurrences-capitalised filter.
    """
    text = _URL_RE.sub(" ", text)
    return _EMAIL_RE.sub(" ", text)


def clean(text: str) -> str:
    """Full pre-tokenisation cleanup: normalise → stitch hyphenation → drop URLs.

    URL stripping runs last so a URL split across a line break is rejoined by
    ``collapse_hyphenation`` first and then removed in one piece.
    """
    return strip_urls(collapse_hyphenation(normalise(text)))


def tokenise(text: str) -> list[str]:
    """Return word tokens preserving original case.

    Order matters: hyphenation must be collapsed *before* tokenisation, otherwise
    ``"competit-\\nion"`` yields ``["competit", "ion"]`` instead of
    ``["competition"]``.
    """
    return [m.group(0) for m in _WORD_RE.finditer(clean(text))]
