from __future__ import annotations

import httpx

from dgcomp.sources.extract import extract


def _response(
    status_code: int,
    text: str = "Number of Pages: 1\nMarkdown Content:\nHello",
) -> httpx.Response:
    return httpx.Response(
        status_code,
        text=text,
        request=httpx.Request("GET", "https://r.jina.ai/https://example.test/doc.pdf"),
    )


def test_extract_retries_jina_rate_limits(mocker) -> None:
    get = mocker.patch(
        "dgcomp.sources.extract.httpx.get",
        side_effect=[_response(429), _response(200)],
    )
    sleep = mocker.patch("dgcomp.sources.extract.time.sleep")

    doc = extract("https://example.test/doc.pdf")

    assert doc.text == "Hello"
    assert doc.pages == 1
    assert get.call_count == 2
    sleep.assert_called_once()
