"""SQLite vocabulary store tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dgcomp.vocab.store import VocabEntry, VocabStore


@pytest.fixture
def store(tmp_path: Path):
    with VocabStore(tmp_path / "vocab.sqlite") as s:
        yield s


def _entry(word_lower: str = "antitrust", date: str = "2024-01-15") -> VocabEntry:
    return VocabEntry(
        word_lower=word_lower,
        display_form=word_lower.title(),
        first_seen_at=date,
        case_id="M.10847",
        case_type="M",
        case_title="ALPHA / BRAVO",
        doc_url="https://competition-cases.ec.europa.eu/cases/M.10847",
        sentence=f"The Parties' conduct constituted {word_lower}.",
    )


def test_add_and_has_word(store: VocabStore) -> None:
    e = _entry()
    assert store.add_word(e) is True
    assert store.has_word("antitrust")
    # Idempotent: re-insert returns False.
    assert store.add_word(e) is False


def test_pop_oldest_unposted_returns_oldest(store: VocabStore) -> None:
    store.add_word(_entry("forge", "2024-03-01"))
    store.add_word(_entry("antitrust", "2024-01-15"))
    store.add_word(_entry("monopsony", "2024-02-10"))
    first = store.pop_oldest_unposted()
    assert first is not None
    assert first.word_lower == "antitrust"


def test_mark_posted_excludes_from_unposted_queue(store: VocabStore) -> None:
    store.add_word(_entry("antitrust", "2024-01-15"))
    store.add_word(_entry("forge", "2024-03-01"))

    first = store.pop_oldest_unposted()
    assert first is not None and first.word_lower == "antitrust"

    store.mark_posted("antitrust", ["buttondown"])

    next_unposted = store.pop_oldest_unposted()
    assert next_unposted is not None and next_unposted.word_lower == "forge"


def test_pop_oldest_unposted_respects_since(store: VocabStore) -> None:
    store.add_word(_entry("antitrust", "2024-01-15"))
    store.add_word(_entry("forge", "2026-04-01"))

    # Posting cutoff = launch date; the old word is in the DB but not eligible.
    eligible = store.pop_oldest_unposted(since="2026-01-01")
    assert eligible is not None
    assert eligible.word_lower == "forge"


def test_recent_words_orders_descending(store: VocabStore) -> None:
    store.add_word(_entry("antitrust", "2024-01-15"))
    store.add_word(_entry("forge", "2026-04-01"))
    store.add_word(_entry("monopsony", "2025-02-10"))

    rows = store.recent_words(limit=10)
    assert [r.word_lower for r in rows] == ["forge", "monopsony", "antitrust"]


def test_source_doc_idempotent(store: VocabStore) -> None:
    store.record_doc(
        doc_id="M.10847",
        case_id="M.10847",
        url="https://competition-cases.ec.europa.eu/cases/M.10847",
        sha256_hex="abc",
        decision_date="2024-01-15",
        pages=120,
    )
    assert store.has_doc("M.10847")
    # REPLACE is fine — same primary key, doesn't error.
    store.record_doc(
        doc_id="M.10847",
        case_id="M.10847",
        url="https://competition-cases.ec.europa.eu/cases/M.10847",
        sha256_hex="abc",
        decision_date="2024-01-15",
        pages=120,
    )


def test_llm_cache_roundtrip(store: VocabStore) -> None:
    word = "antitrust"
    sentence = "The Commission opened an antitrust investigation."
    assert store.cache_lookup(word, sentence) is None
    store.cache_store(word, sentence, keep=True)
    assert store.cache_lookup(word, sentence) is True
    # Different sentence is a different cache key.
    assert store.cache_lookup(word, "Different context") is None


def test_llm_cache_can_overwrite(store: VocabStore) -> None:
    word = "ompetit"
    sentence = "fragment in scan"
    store.cache_store(word, sentence, keep=False)
    store.cache_store(word, sentence, keep=True)  # human override
    assert store.cache_lookup(word, sentence) is True
