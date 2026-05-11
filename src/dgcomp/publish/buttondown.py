"""Buttondown email publisher — one HTTP call per word.

Buttondown's API auto-detects markdown, so the body is plain markdown.
We send with ``status="about_to_send"`` plus the
``X-Buttondown-Live-Dangerously`` header so the email goes out to subscribers
immediately rather than landing as a draft.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import httpx

from dgcomp.vocab.store import VocabEntry

logger = logging.getLogger(__name__)

API_URL = "https://api.buttondown.com/v1/emails"


class _Poster(Protocol):
    def post(
        self, url: str, *, json: dict, headers: dict
    ) -> httpx.Response: ...


@dataclass(slots=True)
class ButtondownPublisher:
    api_key: str
    http: _Poster | None = None

    def __post_init__(self) -> None:
        if self.http is None:
            self.http = httpx.Client(timeout=15.0)

    def close(self) -> None:
        if isinstance(self.http, httpx.Client):
            self.http.close()

    def post(self, entry: VocabEntry) -> bool:
        """Send one email. Returns True on success."""
        assert self.http is not None
        resp = self.http.post(
            API_URL,
            json={
                "subject": format_subject(entry),
                "body": format_body(entry),
                "status": "about_to_send",
            },
            headers={
                "Authorization": f"Token {self.api_key}",
                "X-Buttondown-Live-Dangerously": "true",
            },
        )
        if resp.status_code >= 400:
            logger.error("buttondown send failed (%s): %s", resp.status_code, resp.text)
            return False
        return True


def format_subject(entry: VocabEntry) -> str:
    return entry.display_form


def format_body(entry: VocabEntry) -> str:
    """Render::

        # {display_form}

        First seen in [{case_id} {case_title}]({doc_url}), {long-form date}.
    """
    case_label = (
        f"{entry.case_id} {entry.case_title}" if entry.case_title else entry.case_id
    )
    return (
        f"# {entry.display_form}\n\n"
        f"First seen in [{case_label}]({entry.doc_url}), "
        f"{_format_date(entry.first_seen_at)}.\n"
    )


def _format_date(iso_date: str) -> str:
    try:
        d = date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    return f"{d.day} {d.strftime('%B %Y')}"
