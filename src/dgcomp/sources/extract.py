"""PDF text extraction via Jina Reader.

One backend, one HTTP call. ``GET https://r.jina.ai/<pdf_url>`` returns clean
markdown for the PDF in a few seconds. No local download, no OCR setup, no
PyTorch. Free, no API key required.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

import httpx
import regex

JINA_BASE = "https://r.jina.ai/"
log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractedDoc:
    text: str
    pages: int


def extract(pdf_url: str, *, timeout: float = 60.0, attempts: int = 6) -> ExtractedDoc:
    """Markdownify a PDF directly from its URL via Jina Reader."""
    for attempt in range(attempts):
        try:
            r = httpx.get(JINA_BASE + pdf_url, timeout=timeout)
        except httpx.RequestError as exc:
            if attempt == attempts - 1:
                raise
            _sleep_before_retry(attempt, f"Jina request failed for {pdf_url}: {exc}")
            continue

        if r.status_code == 429 or r.status_code >= 500:
            if attempt == attempts - 1:
                r.raise_for_status()
            delay = _retry_delay(attempt, r.headers.get("Retry-After"))
            log.warning(
                "Jina returned %s for %s; retrying in %.1fs",
                r.status_code,
                pdf_url,
                delay,
            )
            time.sleep(delay)
            continue

        r.raise_for_status()
        break
    raw = r.text

    pages = _parse_pages_header(raw)
    body = _split_after_marker(raw, "Markdown Content:")
    text = _strip_markdown(body)
    return ExtractedDoc(text=text, pages=pages)


def _sleep_before_retry(attempt: int, message: str) -> None:
    delay = _retry_delay(attempt, None)
    log.warning("%s; retrying in %.1fs", message, delay)
    time.sleep(delay)


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return min(120.0, 10.0 * (attempt + 1))


_PAGES_RE = re.compile(r"^Number of Pages:\s*(\d+)\s*$", re.MULTILINE)


def _parse_pages_header(raw: str) -> int:
    m = _PAGES_RE.search(raw[:2000])
    return int(m.group(1)) if m else 0


def _split_after_marker(raw: str, marker: str) -> str:
    idx = raw.find(marker)
    if idx < 0:
        return raw
    return raw[idx + len(marker):].lstrip("\n")


def _strip_markdown(md: str) -> str:
    text = regex.sub(r"^#{1,6}\s+", "", md, flags=regex.MULTILINE)
    text = regex.sub(r"[*_`]", "", text)
    return text
