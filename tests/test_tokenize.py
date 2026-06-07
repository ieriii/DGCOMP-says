"""Tokeniser tests."""

from __future__ import annotations

import pytest

from dgcomp.vocab.tokenize import (
    collapse_hyphenation,
    normalise,
    strip_urls,
    tokenise,
)


def test_returns_words_not_characters() -> None:
    """A regression here would split text into per-character tokens."""
    tokens = tokenise("antitrust")
    assert tokens == ["antitrust"]
    assert "a" not in tokens
    assert "t" not in tokens


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Plain words
        (
            "The Commission opened an investigation.",
            ["The", "Commission", "opened", "an", "investigation"],
        ),
        # Diacritics preserved
        ("Société Générale", ["Société", "Générale"]),
        # Internal apostrophes
        ("Commission's conduct", ["Commission's", "conduct"]),
        # Hyphenated compounds
        (
            "non-confidential state-of-the-art version",
            ["non-confidential", "state-of-the-art", "version"],
        ),
        # PDF line-break hyphenation
        ("competit-\nion authority", ["competition", "authority"]),
        # Curly quotes don't leak into tokens
        ("\u201CMarket share\u201D", ["Market", "share"]),
        # Numbers excluded
        ("EUR 1,000,000", ["EUR"]),
        # Single chars excluded
        ("a b c", []),
        # Markdown formatting stripped
        ("# Heading\n\n**bold** *italic*", ["Heading", "bold", "italic"]),
        # En/em dashes folded to hyphen and don't break words; trailing
        # apostrophes stripped (Parties' → Parties); internal apostrophes
        # kept (Commission's stays as-is).
        (
            "vis-à-vis the Parties\u2019 conduct",
            ["vis-à-vis", "the", "Parties", "conduct"],
        ),
        ("Commission\u2019s response", ["Commission's", "response"]),
        ("O'Brien arrived", ["O'Brien", "arrived"]),
        # Empty / whitespace
        ("", []),
        ("   \n\t  ", []),
    ],
)
def test_tokenise_parametrised(text: str, expected: list[str]) -> None:
    assert tokenise(text) == expected


def test_normalise_folds_curly_quotes() -> None:
    assert normalise("\u2019\u2018\u201C\u201D") == "''\"\""


def test_normalise_strips_nbsp() -> None:
    assert normalise("a\u00A0b") == "a b"


def test_collapse_hyphenation_only_when_lowercase_continues() -> None:
    # Real word split across a line.
    assert collapse_hyphenation("competit-\nion") == "competition"
    # Don't merge across capitalised line continuations (likely a heading break).
    assert collapse_hyphenation("page-\nNUMBER") == "page-\nNUMBER"


def test_dictionary_pollution_examples_caught() -> None:
    """Examples of noisy PDF text that should not pollute token output."""
    # No per-character split.
    assert "a" not in tokenise("antitrust")
    # URL fragment — letters get tokenised as one word; that's fine, the LLM
    # validator rejects them later. Here we just confirm no per-character split.
    tokens = tokenise("Europahttpeceuropaeu")
    assert tokens == ["Europahttpeceuropaeu"]
    # Currency artefacts: € is not a letter, so ``€mio`` → ``mio``.
    assert tokenise("€mio") == ["mio"]
    # CJK characters: \p{L} matches them, so they survive tokenisation;
    # downstream filter excludes them via the ASCII-letter shape check.
    assert tokenise("东山白卢") == ["东山白卢"]


# --- URL / email stripping ---


def test_strip_urls_removes_links_and_emails() -> None:
    assert strip_urls("see https://example.com/foo-bar here") == "see   here"
    assert strip_urls("visit www.example.com/x now") == "visit   now"
    assert strip_urls("mail to john.doe@example.eu please") == "mail to   please"


def test_url_slug_does_not_leak_into_tokens() -> None:
    text = "Prosus’ press release, available here: https://www.prosus.com/news/foo-bar-baz."
    tokens = tokenise(text)
    assert tokens == ["Prosus", "press", "release", "available", "here"]
    for junk in ("foo", "bar", "baz", "prosus.com", "https"):
        assert junk not in tokens


def test_url_split_across_a_line_break_is_still_stripped() -> None:
    """The real M.11936 footnote: a press-release URL hyphen-broken across a
    line. Its slug embeds a lowercase party name ('…to-aspex-management') which
    must NOT survive as a token, or it unmasks the proper noun 'Aspex'."""
    text = (
        "sold a stake to Aspex. (3) Prosus’ Press Release, available here: "
        "https://www.prosus.com/news-\n"
        "insights/2026/prosus-sells-5-percent-interest-in-delivery-hero-to-aspex-management."
    )
    tokens = tokenise(text)
    # The lowercase slug occurrence ('…to-aspex-management') must be gone; only
    # the capitalised body mention survives. (If the slug leaked, the lowercase
    # 'aspex' would unmask the proper noun in the pipeline's occurrence map.)
    assert "aspex" not in tokens
    assert tokens.count("Aspex") == 1
