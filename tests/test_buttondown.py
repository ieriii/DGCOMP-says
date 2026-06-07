"""Buttondown publisher tests with a mocked HTTP client."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from dgcomp.publish.buttondown import (
    API_URL,
    CASE_BASE,
    ButtondownPublisher,
    case_link,
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


# --- single-word email ---


def test_single_subject_is_just_the_word() -> None:
    assert format_subject([_entry()]) == "Forging"


def test_single_body_has_word_as_heading_and_one_line_source() -> None:
    body = format_body([_entry()])
    assert body.startswith("# Forging\n\n")
    # Subscriber link points at the stable case page, NOT the volatile PDF
    # attachment URL the word was extracted from (which rots — see case_link).
    assert (
        "First seen in [M.10847 ALPHA / BRAVO]"
        "(https://competition-cases.ec.europa.eu/cases/M.10847), "
        "12 April 2026."
    ) in body
    # The rot-prone attachment URL never reaches subscribers.
    assert "cases1/202615" not in body
    # No separator when there's only one entry.
    assert "---" not in body


def test_link_uses_stable_case_page_regardless_of_doc_url() -> None:
    # Even with a now-dead legacy attachment URL stored, the email links to the
    # stable per-case page derived from the case id.
    body = format_body(
        [
            _entry(
                case_id="M.11936",
                case_title="NASPERS / JUST EAT TAKEAWAY",
                doc_url="https://ec.europa.eu/competition/mergers/cases1/202623/M_11936_1710.pdf",
            )
        ]
    )
    assert "(https://competition-cases.ec.europa.eu/cases/M.11936)" in body
    assert "ec.europa.eu/competition" not in body


def test_case_link_falls_back_for_malformed_case_id() -> None:
    assert case_link("M.11936", "fallback") == (
        "https://competition-cases.ec.europa.eu/cases/M.11936"
    )
    # Each instrument prefix is recognised.
    for cid in ("AT.40000", "SA.15796", "DMA.100018", "FS.100011"):
        assert case_link(cid, "fallback") == f"{CASE_BASE}/{cid}"
    # Unrecognised id → keep whatever provenance URL we had.
    assert case_link("", "fallback") == "fallback"
    assert case_link("garbage", "fallback") == "fallback"


def test_body_falls_back_to_case_id_when_title_missing() -> None:
    body = format_body([_entry(case_title="")])
    assert "First seen in [M.10847](" in body
    assert "M.10847 ALPHA" not in body


# --- digest email (N > 1) ---


def test_digest_subject_announces_count() -> None:
    entries = [
        _entry(word_lower="forge", display_form="Forging"),
        _entry(word_lower="slump", display_form="Slumps"),
        _entry(word_lower="parry", display_form="Parrying"),
    ]
    assert format_subject(entries) == "3 new words"


def test_digest_body_has_one_section_per_word_separated_by_hr() -> None:
    entries = [
        _entry(word_lower="forge", display_form="Forging"),
        _entry(word_lower="slump", display_form="Slumps", case_id="M.999"),
    ]
    body = format_body(entries)
    assert "# Forging" in body
    assert "# Slumps" in body
    # Each entry has its own section, separated by a markdown horizontal rule.
    assert body.count("# ") == 2
    assert "\n\n---\n\n" in body
    # Sections appear in input order.
    assert body.index("# Forging") < body.index("# Slumps")


# --- HTTP wiring ---


@dataclass
class FakeHttp:
    posts: list[tuple[str, dict, dict]] = field(default_factory=list)
    status_code: int = 201
    body: str = ""

    def post(self, url: str, *, json: dict, headers: dict) -> httpx.Response:
        self.posts.append((url, json, headers))
        return httpx.Response(self.status_code, text=self.body)


def test_post_sends_one_email_for_a_batch() -> None:
    fake = FakeHttp(status_code=201)
    pub = ButtondownPublisher(api_key="secret", http=fake)
    entries = [
        _entry(word_lower="forge", display_form="Forging"),
        _entry(word_lower="slump", display_form="Slumps"),
    ]

    assert pub.post(entries) is True
    # Crucially: ONE POST, not two.
    assert len(fake.posts) == 1

    url, body, headers = fake.posts[0]
    assert url == API_URL
    assert body["subject"] == "2 new words"
    assert "Forging" in body["body"]
    assert "Slumps" in body["body"]
    assert body["status"] == "about_to_send"
    assert headers["Authorization"] == "Token secret"
    assert headers["X-Buttondown-Live-Dangerously"] == "true"


def test_post_with_empty_list_is_a_noop() -> None:
    fake = FakeHttp()
    pub = ButtondownPublisher(api_key="secret", http=fake)
    assert pub.post([]) is True
    assert fake.posts == []


def test_post_fails_with_4xx() -> None:
    fake = FakeHttp(status_code=403, body="forbidden")
    pub = ButtondownPublisher(api_key="secret", http=fake)
    assert pub.post([_entry()]) is False
