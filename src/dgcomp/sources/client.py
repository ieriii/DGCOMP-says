"""Client for the EU competition cases search-api.

    POST https://api.tech.ec.europa.eu/search-api/prod/rest/search
        ?text=*&pageNumber=N&pageSize=100&apiKey=CS_PROD_ODSE_PROD

Multipart body with three JSON parts: query (Elasticsearch), displayFields,
sort. We filter ``metadataType=METADATA_DECISION_ATTACHMENT`` and
``language=en`` to get the published English decision PDFs. Date filter uses
``decisionAdoptionDate`` (always populated; ``attachmentDocumentDate`` is null
on 95%+ of attachments).

PDF URL = ``https://ec.europa.eu/competition/<subpath>/<attachmentLink>``.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
API_KEY = "CS_PROD_ODSE_PROD"
PDF_BASE = "https://ec.europa.eu/competition"

PAGE_SIZE = 100
PAGE_SOFT_CAP = 2500  # split a yearly window into months when results approach this


class InstrumentType(StrEnum):
    ANTITRUST = "AT"
    MERGERS = "M"
    STATE_AID = "SA"
    DMA = "DMA"
    FOREIGN_SUBSIDIES = "FS"

    @property
    def api_value(self) -> str:
        return _API_VALUE[self]

    @property
    def subpath(self) -> str:
        return _SUBPATH[self]


_API_VALUE = {
    InstrumentType.ANTITRUST: "AT",
    InstrumentType.MERGERS: "M",
    InstrumentType.STATE_AID: "SA",
    InstrumentType.DMA: "InstrumentDMA",
    InstrumentType.FOREIGN_SUBSIDIES: "InstrumentFS",
}

_SUBPATH = {
    InstrumentType.ANTITRUST: "antitrust",
    InstrumentType.MERGERS: "mergers",
    InstrumentType.STATE_AID: "state_aid",
    InstrumentType.DMA: "digital_markets_act",
    InstrumentType.FOREIGN_SUBSIDIES: "foreign_subsidies",
}

_DISPLAY_FIELDS = [
    "caseNumber",
    "caseInstrument",
    "caseTitle",
    "attachmentLink",
    "attachmentDocumentDate",
    "decisionAdoptionDate",
]


@dataclass(frozen=True, slots=True)
class DecisionDoc:
    case_id: str               # "M.12367"
    case_type: InstrumentType
    title: str                 # "LIBERTY GLOBAL / TELEFONICA / ..."
    decision_date: date
    pdf_url: str
    attachment_link: str       # relative path; stable doc_id

    @property
    def doc_id(self) -> str:
        return f"{self.case_id}::{self.attachment_link}"


class CompetitionCasesClient:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self.http = httpx.Client(
            timeout=timeout, headers={"User-Agent": "DGCOMP-says/0.1"}
        )

    def close(self) -> None:
        self.http.close()

    def search(
        self,
        *,
        instrument: InstrumentType,
        date_from: date,
        date_to: date,
    ) -> Iterator[DecisionDoc]:
        """Yield English decision attachments for ``instrument`` over a date range."""
        for start, end in _yearly(date_from, date_to):
            yield from self._fetch(instrument, start, end)

    def _fetch(
        self, instrument: InstrumentType, gte: date, lt: date
    ) -> Iterator[DecisionDoc]:
        query = _query(instrument, gte, lt)
        first = self._post(query, page=1)
        total = first.get("totalResults", 0)

        # The API caps at ~3000 results per query. If a yearly window crosses
        # the soft cap, recurse by month. Empirical peak density is ~920/year
        # (state aid, 2020), so monthly granularity is enough today — but if
        # a month itself ever crosses the cap we'd silently lose data, hence
        # the warning below.
        if total >= PAGE_SOFT_CAP:
            if (lt - gte).days > 31:
                for sub_start, sub_end in _monthly(gte, lt):
                    yield from self._fetch(instrument, sub_start, sub_end)
                return
            logger.warning(
                "window %s..%s has %d results — exceeds soft cap %d, some "
                "results may be silently truncated. Consider adding finer "
                "splitting if this fires.",
                gte, lt, total, PAGE_SOFT_CAP,
            )

        for doc in _flatten(first.get("results", []), instrument):
            yield doc
        for page in range(2, -(-total // PAGE_SIZE) + 1):
            time.sleep(0.3)
            data = self._post(query, page=page)
            for doc in _flatten(data.get("results", []), instrument):
                yield doc

    def _post(self, query: dict, page: int) -> dict:
        files = {
            "query": ("q.json", json.dumps(query), "application/json"),
            "displayFields": (
                "df.json", json.dumps(_DISPLAY_FIELDS), "application/json"
            ),
            "sort": (
                "s.json",
                json.dumps([{"field": "caseNumberPart", "order": "ASCENDING"}]),
                "application/json",
            ),
        }
        params = {
            "text": "*",
            "pageNumber": page,
            "pageSize": PAGE_SIZE,
            "apiKey": API_KEY,
        }
        for attempt in range(4):
            try:
                r = self.http.post(API_URL, params=params, files=files)
            except httpx.RequestError as exc:
                if attempt == 3:
                    raise
                logger.warning(
                    "search API request failed on attempt %d/4: %s; retrying",
                    attempt + 1,
                    exc,
                )
                time.sleep(1.5**attempt)
                continue
            if r.status_code < 500:
                r.raise_for_status()
                return r.json()
            time.sleep(1.5**attempt)
        r.raise_for_status()
        return {}


# --- helpers ---


def _query(instrument: InstrumentType, gte: date, lt: date) -> dict:
    return {
        "bool": {
            "must": [
                {"term": {"caseInstrument": instrument.api_value}},
                {"term": {"metadataType": "METADATA_DECISION_ATTACHMENT"}},
                {"term": {"language": "en"}},
                {
                    "range": {
                        "decisionAdoptionDate": {
                            "gte": _to_ms(gte), "lt": _to_ms(lt)
                        }
                    }
                },
            ]
        }
    }


def _to_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def _first(values: list | None) -> str | None:
    return values[0] if values else None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _flatten(
    results: list[dict], instrument: InstrumentType
) -> Iterator[DecisionDoc]:
    for res in results:
        md = res.get("metadata", {})
        case_number = _first(md.get("caseNumber"))
        link = _first(md.get("attachmentLink"))
        if not case_number or not link:
            continue
        link = link.strip()
        decision_date = (
            _parse_date(_first(md.get("decisionAdoptionDate")))
            or _parse_date(_first(md.get("attachmentDocumentDate")))
        )
        if decision_date is None:
            continue
        yield DecisionDoc(
            case_id=case_number,
            case_type=instrument,
            title=_first(md.get("caseTitle")) or "",
            decision_date=decision_date,
            pdf_url=f"{PDF_BASE}/{instrument.subpath}/{link}",
            attachment_link=link,
        )


def _yearly(date_from: date, date_to: date) -> Iterator[tuple[date, date]]:
    cur = date_from
    while cur < date_to:
        nxt = date(cur.year + 1, 1, 1)
        yield cur, min(nxt, date_to)
        cur = nxt


def _monthly(gte: date, lt: date) -> Iterator[tuple[date, date]]:
    cur = gte
    while cur < lt:
        nxt = (
            date(cur.year + 1, 1, 1)
            if cur.month == 12
            else date(cur.year, cur.month + 1, 1)
        )
        yield cur, min(nxt, lt)
        cur = nxt
