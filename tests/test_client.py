"""Tests for sources/client.py — the EU search-api client."""

from __future__ import annotations

import logging
from datetime import UTC, date

import httpx
import pytest

from dgcomp.sources.client import (
    CompetitionCasesClient,
    InstrumentType,
    _flatten,
    _monthly,
    _query,
    _to_ms,
    _yearly,
)


def _result(
    *,
    case_number: str = "M.10847",
    title: str = "FOO / BAR",
    attachment_link: str = "cases1/202615/M_10847_98.pdf",
    decision_date: str | None = "2024-06-15T13:00:00.000+0000",
    document_date: str | None = "2024-06-10T22:00:00.000+0000",
) -> dict:
    """Build an API-shaped result. Only the metadata fields the client uses."""
    md = {
        "caseNumber": [case_number],
        "caseInstrument": ["M"],
        "caseTitle": [title],
        "attachmentLink": [attachment_link],
    }
    if decision_date is not None:
        md["decisionAdoptionDate"] = [decision_date]
    if document_date is not None:
        md["attachmentDocumentDate"] = [document_date]
    return {"metadata": md}


def test_flatten_builds_correct_pdf_url() -> None:
    docs = list(_flatten([_result()], InstrumentType.MERGERS))
    assert len(docs) == 1
    d = docs[0]
    assert d.case_id == "M.10847"
    assert d.case_type is InstrumentType.MERGERS
    assert d.title == "FOO / BAR"
    assert d.decision_date == date(2024, 6, 15)
    assert d.pdf_url == (
        "https://ec.europa.eu/competition/mergers/cases1/202615/M_10847_98.pdf"
    )


def test_flatten_falls_back_to_document_date_when_decision_date_missing() -> None:
    r = _result(decision_date=None)
    docs = list(_flatten([r], InstrumentType.MERGERS))
    assert docs[0].decision_date == date(2024, 6, 10)


def test_flatten_skips_record_with_no_dates() -> None:
    r = _result(decision_date=None, document_date=None)
    assert list(_flatten([r], InstrumentType.MERGERS)) == []


def test_flatten_skips_record_with_no_attachment_link() -> None:
    r = _result(attachment_link="")
    r["metadata"]["attachmentLink"] = []
    assert list(_flatten([r], InstrumentType.MERGERS)) == []


def test_subpath_per_instrument() -> None:
    assert InstrumentType.ANTITRUST.subpath == "antitrust"
    assert InstrumentType.MERGERS.subpath == "mergers"
    assert InstrumentType.STATE_AID.subpath == "state_aid"
    assert InstrumentType.DMA.subpath == "digital_markets_act"
    assert InstrumentType.FOREIGN_SUBSIDIES.subpath == "foreign_subsidies"


def test_query_uses_search_api_instrument_values() -> None:
    dma = _query(InstrumentType.DMA, date(2024, 1, 1), date(2025, 1, 1))
    fs = _query(
        InstrumentType.FOREIGN_SUBSIDIES, date(2024, 1, 1), date(2025, 1, 1)
    )

    assert dma["bool"]["must"][0] == {"term": {"caseInstrument": "InstrumentDMA"}}
    assert fs["bool"]["must"][0] == {"term": {"caseInstrument": "InstrumentFS"}}


def test_to_ms_converts_to_utc_milliseconds() -> None:
    # 2024-01-01 UTC midnight = 1704067200000 ms
    assert _to_ms(date(2024, 1, 1)) == 1704067200000


def test_monthly() -> None:
    months = list(_monthly(date(2024, 1, 1), date(2024, 4, 1)))
    assert months == [
        (date(2024, 1, 1), date(2024, 2, 1)),
        (date(2024, 2, 1), date(2024, 3, 1)),
        (date(2024, 3, 1), date(2024, 4, 1)),
    ]


def test_monthly_rolls_over_year() -> None:
    months = list(_monthly(date(2024, 11, 15), date(2025, 2, 1)))
    assert months == [
        (date(2024, 11, 15), date(2024, 12, 1)),
        (date(2024, 12, 1), date(2025, 1, 1)),
        (date(2025, 1, 1), date(2025, 2, 1)),
    ]


def test_yearly() -> None:
    windows = list(_yearly(date(2024, 1, 1), date(2026, 1, 1)))
    assert windows == [
        (date(2024, 1, 1), date(2025, 1, 1)),
        (date(2025, 1, 1), date(2026, 1, 1)),
    ]


# --- 3000-result cap handling ---


def _stub_post(client: CompetitionCasesClient, totals_by_window: dict):
    """Patch ``client._post`` to return canned ``totalResults`` per window.

    Keys in ``totals_by_window`` are (gte, lt) tuples. Returns the list of
    (gte, lt) windows actually queried.
    """
    from datetime import datetime as _dt

    calls: list[tuple[date, date]] = []

    def fake_post(self, query: dict, page: int) -> dict:
        rng = query["bool"]["must"][3]["range"]["decisionAdoptionDate"]
        gte = _dt.fromtimestamp(rng["gte"] / 1000, tz=UTC).date()
        lt = _dt.fromtimestamp(rng["lt"] / 1000, tz=UTC).date()
        calls.append((gte, lt))
        return {
            "totalResults": totals_by_window.get((gte, lt), 0),
            "results": [],
        }

    client._post = fake_post.__get__(client, type(client))
    return calls


def test_dense_year_recurses_to_monthly() -> None:
    """A year over the soft cap → 12 monthly sub-queries."""
    client = CompetitionCasesClient()
    try:
        calls = _stub_post(
            client,
            {(date(2020, 1, 1), date(2021, 1, 1)): 5000},
        )
        list(
            client.search(
                instrument=InstrumentType.STATE_AID,
                date_from=date(2020, 1, 1),
                date_to=date(2021, 1, 1),
            )
        )
        # Year-level probe + 12 monthly sub-windows
        assert calls[0] == (date(2020, 1, 1), date(2021, 1, 1))
        assert len(calls[1:]) == 12
        assert calls[1] == (date(2020, 1, 1), date(2020, 2, 1))
        assert calls[-1] == (date(2020, 12, 1), date(2021, 1, 1))
    finally:
        client.close()


def test_short_dense_window_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A month over the soft cap can't recurse → loud warning so loss isn't silent."""
    client = CompetitionCasesClient()
    try:
        _stub_post(
            client,
            {(date(2020, 3, 1), date(2020, 4, 1)): 4000},
        )
        with caplog.at_level(logging.WARNING, logger="dgcomp.sources.client"):
            list(
                client.search(
                    instrument=InstrumentType.STATE_AID,
                    date_from=date(2020, 3, 1),
                    date_to=date(2020, 4, 1),
                )
            )
        assert any(
            "soft cap" in m and "truncated" in m for m in caplog.messages
        )
    finally:
        client.close()


def test_post_retries_request_errors(mocker) -> None:
    client = CompetitionCasesClient()
    response = httpx.Response(
        200,
        json={"totalResults": 0, "results": []},
        request=httpx.Request("POST", "https://example.test"),
    )
    try:
        post = mocker.patch.object(
            client.http,
            "post",
            side_effect=[httpx.ReadTimeout("timed out"), response],
        )
        data = client._post({"bool": {"must": []}}, page=1)
        assert data == {"totalResults": 0, "results": []}
        assert post.call_count == 2
    finally:
        client.close()
