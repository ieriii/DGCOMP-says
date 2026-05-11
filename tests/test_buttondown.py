"""Buttondown publisher tests with a mocked HTTP client."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from dgcomp.publish.buttondown import (
    API_URL,
    ButtondownPublisher,
    format_body,
    format_subject,
)
from dgcomp.vocab.store import VocabEntry


def _entry(**overrides: object) -> VocabEntry:
    base: dict[str, object] = dict(
        word_lower="forge",
        display_form="Forging",
        first_seen_at="2026-04-12",
        case_id="M.10847",
        case_type="M",
        case_title="ALPHA / BRAVO",
        doc_url="https://ec.europa.eu/competition/mergers/cases1/202615/M_10847_98.pdf",
        sentence="The Parties forge a new vertical relationship through the merger.",
    )
    base.update(overrides)
    return VocabEntry(**base)  # type: ignore[arg-type]


def test_subject_is_just_the_word() -> None:
    assert format_subject(_entry()) == "Forging"


def test_body_has_word_as_heading_and_one_line_source() -> None:
    body = format_body(_entry())
    assert body.startswith("# Forging\n\n")
    assert (
        "First seen in [M.10847 ALPHA / BRAVO]"
        "(https://ec.europa.eu/competition/mergers/cases1/202615/M_10847_98.pdf), "
        "12 April 2026."
    ) in body


def test_body_falls_back_to_case_id_when_title_missing() -> None:
    body = format_body(_entry(case_title=""))
    assert "First seen in [M.10847](" in body
    assert "M.10847 ALPHA" not in body


@dataclass
class FakeHttp:
    posts: list[tuple[str, dict, dict]] = field(default_factory=list)
    status_code: int = 201
    body: str = ""

    def post(self, url: str, *, json: dict, headers: dict) -> httpx.Response:
        self.posts.append((url, json, headers))
        return httpx.Response(self.status_code, text=self.body)


def test_post_succeeds_with_2xx() -> None:
    fake = FakeHttp(status_code=201)
    pub = ButtondownPublisher(api_key="secret", http=fake)

    assert pub.post(_entry()) is True
    assert len(fake.posts) == 1

    url, body, headers = fake.posts[0]
    assert url == API_URL
    assert body["subject"] == "Forging"
    assert "Forging" in body["body"]
    # Sends immediately, not as a draft.
    assert body["status"] == "about_to_send"
    assert headers["Authorization"] == "Token secret"
    assert headers["X-Buttondown-Live-Dangerously"] == "true"


def test_post_fails_with_4xx() -> None:
    fake = FakeHttp(status_code=403, body="forbidden")
    pub = ButtondownPublisher(api_key="secret", http=fake)
    assert pub.post(_entry()) is False
