"""Pipeline tests with a mocked Anthropic client."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from dgcomp.vocab.pipeline import DocumentMeta, process_document
from dgcomp.vocab.store import VocabStore
from dgcomp.vocab.validate import Validator


@dataclass
class FakeAnthropic:
    """Parses the words out of the batch prompt and returns true/false based
    on ``rejected_words``.
    """

    rejected_words: set[str] = field(default_factory=set)
    calls: int = 0

    def messages_create(
        self, *, model: str, prompt: str, max_tokens: int
    ) -> str:
        self.calls += 1
        words = re.findall(r'^\d+\.\s+"([^"]+)"', prompt, flags=re.MULTILINE)
        keep = [w.lower() not in self.rejected_words for w in words]
        return json.dumps({"keep": keep})


@pytest.fixture
def store(tmp_path: Path):
    with VocabStore(tmp_path / "v.sqlite") as s:
        yield s


def _meta() -> DocumentMeta:
    return DocumentMeta(
        case_id="M.10847",
        case_type="M",
        case_title="ALPHA / BRAVO",
        decision_date="2024-01-15",
        doc_url="https://competition-cases.ec.europa.eu/cases/M.10847",
    )


def test_inserts_new_words_and_returns_them(store: VocabStore) -> None:
    text = (
        "The Commission opened an antitrust investigation. The Parties cooperated. "
        "the commission also noted that the parties cooperated fully."
    )
    fake = FakeAnthropic()
    v = Validator(store=store, client=fake, model="haiku")

    inserted = process_document(text=text, meta=_meta(), store=store, validator=v)
    words = {e.word_lower for e in inserted}
    assert {"antitrust", "investigation", "commission", "parties", "cooperated"} <= words


def test_skips_words_already_in_vocab(store: VocabStore) -> None:
    fake = FakeAnthropic()
    v = Validator(store=store, client=fake, model="haiku")

    process_document(
        text="The Commission opened an antitrust investigation.",
        meta=_meta(), store=store, validator=v,
    )
    process_document(
        text="Another antitrust investigation followed. another concern arose.",
        meta=_meta(), store=store, validator=v,
    )
    words = {e.word_lower for e in store.recent_words()}
    assert "another" in words
    assert "followed" in words


def test_llm_rejection_keeps_word_out(store: VocabStore) -> None:
    fake = FakeAnthropic(rejected_words={"ompetit"})
    v = Validator(store=store, client=fake, model="haiku")

    inserted = process_document(
        text="The ompetit investigation was opened.",
        meta=_meta(), store=store, validator=v,
    )
    words = {e.word_lower for e in inserted}
    assert "ompetit" not in words
    assert "investigation" in words


def test_does_not_re_validate_within_same_document(store: VocabStore) -> None:
    """A word that appears in 5 sentences only goes to the LLM once per document."""
    text = " ".join(["The antitrust matter is antitrust."] * 5)
    fake = FakeAnthropic()
    v = Validator(store=store, client=fake, model="haiku")

    process_document(text=text, meta=_meta(), store=store, validator=v)
    # All candidates judged in a single batch call.
    assert fake.calls == 1


def test_filtering_happens_before_llm(store: VocabStore) -> None:
    """Shape filter rejects junk pre-LLM."""
    text = "AAAA BBB cooperation."
    fake = FakeAnthropic()
    v = Validator(store=store, client=fake, model="haiku")

    process_document(text=text, meta=_meta(), store=store, validator=v)
    # AAAA / BBB rejected by shape; only "cooperation" reaches the LLM.
    assert fake.calls == 1


def test_drops_proper_noun_with_single_capitalised_occurrence(
    store: VocabStore,
) -> None:
    """A name that appears once, mid-sentence, capitalised, in an address
    footer is dropped without consulting the LLM."""
    text = (
        "The Commission approved the merger. "
        "The notifying party has its registered office in Nijverdal."
    )
    fake = FakeAnthropic()
    v = Validator(store=store, client=fake, model="haiku")

    process_document(text=text, meta=_meta(), store=store, validator=v)
    words = {e.word_lower for e in store.recent_words()}
    assert "nijverdal" not in words


def test_drops_proper_noun_with_many_capitalised_occurrences(
    store: VocabStore,
) -> None:
    """A party name that recurs many times but is always capitalised is still
    a proper noun and still dropped."""
    text = (
        "Bremner notified the transaction. Bremner is incorporated in the UK. "
        "The Commission reviewed Bremner's submissions and Bremner's market data."
    )
    fake = FakeAnthropic()
    v = Validator(store=store, client=fake, model="haiku")

    process_document(text=text, meta=_meta(), store=store, validator=v)
    words = {e.word_lower for e in store.recent_words()}
    assert "bremner" not in words


def test_keeps_word_capitalised_at_sentence_start_but_lowercase_elsewhere(
    store: VocabStore,
) -> None:
    """A real English novelty that happens to debut at sentence-start (and
    thus appears capitalised once) is kept as long as it also appears
    lowercase somewhere in the document body."""
    text = (
        "Decarbonisation of the steel sector is at stake. "
        "The Commission noted that decarbonisation requires investment, and "
        "that further decarbonisation depends on access to green hydrogen."
    )
    fake = FakeAnthropic()
    v = Validator(store=store, client=fake, model="haiku")

    process_document(text=text, meta=_meta(), store=store, validator=v)
    words = {e.word_lower for e in store.recent_words()}
    assert "decarbonisation" in words


def test_chunks_above_chunk_size(store: VocabStore) -> None:
    words = [
        "antitrust", "concertation", "tying", "foreclosure", "merger",
        "undertaking", "ancillary", "remedies", "cartel", "rebate",
        "exclusionary", "abuse", "dominance", "pricing", "predatory",
        "leniency", "infringement", "investigation", "commitments",
        "acquisition", "concentration", "joint", "venture", "vertical",
        "horizontal", "downstream", "upstream", "switching", "lock",
        "buyer", "seller", "wholesale", "retail", "platform", "ecosystem",
        "interoperability", "gatekeeper", "essential", "facility", "leverage",
    ]
    text = ". ".join(words) + "."
    fake = FakeAnthropic()
    v = Validator(store=store, client=fake, model="haiku")

    process_document(
        text=text, meta=_meta(), store=store, validator=v, chunk_size=10
    )
    # ~40 unique candidates with chunk_size=10 → 4 batch calls.
    assert 3 <= fake.calls <= 5
