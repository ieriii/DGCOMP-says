"""Small tests for CLI defaults and date bounds."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from dgcomp.cli import DEFAULT_INSTRUMENTS, _exclusive_until, _instruments, _post_entries
from dgcomp.sources.client import InstrumentType
from dgcomp.vocab.store import VocabEntry


def test_default_backfill_instruments_are_all_five() -> None:
    assert DEFAULT_INSTRUMENTS == [
        InstrumentType.MERGERS,
        InstrumentType.ANTITRUST,
        InstrumentType.STATE_AID,
        InstrumentType.DMA,
        InstrumentType.FOREIGN_SUBSIDIES,
    ]
    assert _instruments("") == DEFAULT_INSTRUMENTS


def test_single_instrument_filter() -> None:
    assert _instruments("DMA") == [InstrumentType.DMA]


def test_cli_until_dates_are_inclusive() -> None:
    assert _exclusive_until(date(2026, 4, 29)) == date(2026, 4, 30)


def _entry(word: str = "forge") -> VocabEntry:
    return VocabEntry(
        word_lower=word,
        display_form=word.title(),
        first_seen_at="2026-04-30",
        case_id="M.1",
        case_type="M",
        case_title="A / B",
        doc_url="https://example.test/doc.pdf",
        sentence="A sentence.",
    )


def test_post_entries_sends_one_digest_for_a_batch(mocker) -> None:
    sent_batches: list[list[VocabEntry]] = []

    class FakePublisher:
        def __init__(self, **_: object) -> None:
            pass

        def post(self, entries: list[VocabEntry]) -> bool:
            sent_batches.append(list(entries))
            return True

        def close(self) -> None:
            pass

    store = SimpleNamespace(marked=[])

    def mark_posted(word_lower: str, channels: list[str]) -> None:
        store.marked.append((word_lower, channels))

    store.mark_posted = mark_posted
    mocker.patch("dgcomp.cli.ButtondownPublisher", FakePublisher)

    _post_entries(
        SimpleNamespace(buttondown_api_key="key"),
        store,
        [_entry("alpha"), _entry("beta")],
    )

    # ONE batch of two, not two separate emails.
    assert len(sent_batches) == 1
    assert [e.word_lower for e in sent_batches[0]] == ["alpha", "beta"]
    # Each word still individually marked posted in the DB.
    assert store.marked == [("alpha", ["buttondown"]), ("beta", ["buttondown"])]


def test_post_entries_with_no_new_words_does_not_post(mocker) -> None:
    publisher = mocker.patch("dgcomp.cli.ButtondownPublisher")

    _post_entries(
        SimpleNamespace(buttondown_api_key="key"),
        SimpleNamespace(mark_posted=lambda *_: None),
        [],
    )

    publisher.assert_not_called()
