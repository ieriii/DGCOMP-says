"""LLM validator tests — Anthropic client is mocked."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from dgcomp.vocab.store import VocabStore
from dgcomp.vocab.validate import Validator, _parse


@dataclass
class FakeAnthropic:
    """Returns canned batch responses; counts calls."""

    response: str = '{"keep": [true]}'
    calls: int = field(default=0)

    def messages_create(
        self, *, model: str, prompt: str, max_tokens: int
    ) -> str:
        self.calls += 1
        return self.response


@pytest.fixture
def store(tmp_path: Path):
    with VocabStore(tmp_path / "v.sqlite") as s:
        yield s


# --- validate() ---


def test_empty_returns_empty(store: VocabStore) -> None:
    fake = FakeAnthropic()
    v = Validator(store=store, client=fake, model="haiku")
    assert v.validate([]) == []
    assert fake.calls == 0


def test_one_call_for_many_words(store: VocabStore) -> None:
    fake = FakeAnthropic(response='{"keep": [true, false, true]}')
    v = Validator(store=store, client=fake, model="haiku")
    out = v.validate(
        [("antitrust", "s1"), ("ompetit", "s2"), ("Brussels", "s3")]
    )
    assert out == [True, False, True]
    assert fake.calls == 1
    assert store.cache_lookup("antitrust", "s1") is True
    assert store.cache_lookup("ompetit", "s2") is False
    assert store.cache_lookup("brussels", "s3") is True


def test_uses_cache_first(store: VocabStore) -> None:
    fake = FakeAnthropic(response='{"keep": [true]}')
    v = Validator(store=store, client=fake, model="haiku")
    store.cache_store("antitrust", "s1", True)
    store.cache_store("ompetit", "s2", False)
    out = v.validate(
        [("antitrust", "s1"), ("ompetit", "s2"), ("Brussels", "s3")]
    )
    assert out == [True, False, True]
    # Only one item ("Brussels") needed an LLM call.
    assert fake.calls == 1


def test_chunks_when_above_chunk_size(store: VocabStore) -> None:
    replies = iter(['{"keep": [true, false]}', '{"keep": [true]}'])

    @dataclass
    class StreamingFake:
        calls: int = 0

        def messages_create(
            self, *, model: str, prompt: str, max_tokens: int
        ) -> str:
            self.calls += 1
            return next(replies)

    fake = StreamingFake()
    v = Validator(store=store, client=fake, model="haiku")
    out = v.validate([("a", "s1"), ("b", "s2"), ("c", "s3")], chunk_size=2)
    assert out == [True, False, True]
    assert fake.calls == 2


def test_failure_drops_chunk_without_caching(store: VocabStore) -> None:
    @dataclass
    class FailingClient:
        def messages_create(
            self, *, model: str, prompt: str, max_tokens: int
        ) -> str:
            raise RuntimeError("API down")

    v = Validator(store=store, client=FailingClient(), model="haiku")
    out = v.validate([("antitrust", "s1"), ("merger", "s2")])
    assert out == [False, False]
    assert store.cache_lookup("antitrust", "s1") is None
    assert store.cache_lookup("merger", "s2") is None


def test_size_mismatch_retries_items_individually(store: VocabStore) -> None:
    fake = FakeAnthropic(response='{"keep": [true]}')
    v = Validator(store=store, client=fake, model="haiku")
    out = v.validate([("a", "s"), ("b", "s"), ("c", "s")])
    assert out == [True, True, True]


def test_extra_verdicts_are_ignored(store: VocabStore) -> None:
    fake = FakeAnthropic(response='```json\n{"keep": [true, false]}\n```')
    v = Validator(store=store, client=fake, model="haiku")
    out = v.validate([("a", "s")])
    assert out == [True]


def test_single_item_retryable_errors_are_retried(
    store: VocabStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    class OverloadedError(Exception):
        status_code = 529

    replies = iter(
        [OverloadedError("overloaded"), OverloadedError("overloaded"), '{"keep": [true]}']
    )

    @dataclass
    class FlakyClient:
        calls: int = 0

        def messages_create(
            self, *, model: str, prompt: str, max_tokens: int
        ) -> str:
            self.calls += 1
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

    sleeps: list[int] = []
    monkeypatch.setattr("dgcomp.vocab.validate.time.sleep", sleeps.append)

    fake = FlakyClient()
    v = Validator(store=store, client=fake, model="haiku")

    assert v.validate([("a", "s")]) == [True]
    assert fake.calls == 3
    assert sleeps == [5]


# --- _parse() ---


def test_parse_handles_chatty_models() -> None:
    assert _parse('{"keep": [true, false]}') == [True, False]
    assert _parse('Sure! {"keep": [true]}') == [True]
    assert _parse('```json\n{"keep": [true]}\n```') == [True]
    assert _parse('{"Smiling": [true]}') == [True]


def test_parse_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        _parse("not json")
    with pytest.raises(ValueError):
        _parse('{"other": "field"}')
