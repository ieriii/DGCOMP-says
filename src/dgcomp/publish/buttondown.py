"""Buttondown email publisher — one HTTP call per send.

A "send" is one email containing one or more new words. With the cron firing
every 2 hours, a tick that finds N words posts a single digest email; a tick
that finds 1 word posts a single-word email; a tick that finds 0 sends nothing.

Body is markdown (Buttondown auto-detects). The send is immediate, not draft —
hence ``status="about_to_send"`` plus the ``X-Buttondown-Live-Dangerously``
confirmation header.
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

    def post(self, entries: list[VocabEntry]) -> bool:
        """Send one email containing every entry. Returns True on success.

        Empty input is a no-op that returns True (nothing to send is success).
        """
        if not entries:
            return True
        assert self.http is not None
        resp = self.http.post(
            API_URL,
            json={
                "subject": format_subject(entries),
                "body": format_body(entries),
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


def format_subject(entries: list[VocabEntry]) -> str:
    """One word → just the word. Two or more → ``N new words``."""
    if len(entries) == 1:
        return entries[0].display_form
    return f"{len(entries)} new words"


def format_body(entries: list[VocabEntry]) -> str:
    """Render each entry as a section; separate with a markdown horizontal rule."""
    return "\n\n---\n\n".join(_format_one(e) for e in entries) + "\n"


def _format_one(entry: VocabEntry) -> str:
    case_label = (
        f"{entry.case_id} {entry.case_title}" if entry.case_title else entry.case_id
    )
    return (
        f"# {entry.display_form}\n\n"
        f"First seen in [{case_label}]({entry.doc_url}), "
        f"{_format_date(entry.first_seen_at)}."
    )


def _format_date(iso_date: str) -> str:
    try:
        d = date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    return f"{d.day} {d.strftime('%B %Y')}"
