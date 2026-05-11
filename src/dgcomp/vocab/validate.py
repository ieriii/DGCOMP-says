"""Haiku-based validator: 'real word or OCR garbage?'.

One method, ``validate(items)``, judges any number of (word, sentence) pairs
in batched LLM calls and caches each verdict in SQLite. Used by both the
backfill (large N) and the live cron (small N) — the same code path either
way.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from dgcomp.vocab.store import VocabStore

logger = logging.getLogger(__name__)

PROMPT = """\
For each numbered word below, decide if it's a real word being used in the \
text or OCR garbage / a random letter sequence. Names, foreign words quoted \
inside the document, and abbreviations are fine — only reject genuine OCR \
artifacts (e.g. "competit", "ompetit") and random letter sequences.

{numbered_items}

Reply JSON only with one boolean per word in the same order:
{{"keep": [true, false, ...]}}
"""


class _AnthropicLike(Protocol):
    def messages_create(
        self, *, model: str, prompt: str, max_tokens: int
    ) -> str: ...


@dataclass(slots=True)
class AnthropicAdapter:
    """Thin wrapper around the official SDK; lazy-imported for test light weight."""

    api_key: str
    model: str

    def messages_create(self, *, model: str, prompt: str, max_tokens: int) -> str:
        from anthropic import Anthropic

        msg = Anthropic(api_key=self.api_key).messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")


@dataclass(slots=True)
class Validator:
    store: VocabStore
    client: _AnthropicLike
    model: str

    def validate(
        self, items: list[tuple[str, str]], *, chunk_size: int = 25
    ) -> list[bool]:
        """Validate ``(word, sentence)`` pairs. Cache-aware, batched."""
        if not items:
            return []

        results: list[bool | None] = [None] * len(items)
        pending: list[int] = []
        for i, (w, s) in enumerate(items):
            cached = self.store.cache_lookup(w.lower(), s)
            if cached is None:
                pending.append(i)
            else:
                results[i] = cached

        for off in range(0, len(pending), chunk_size):
            idx = pending[off : off + chunk_size]
            chunk = [items[i] for i in idx]
            try:
                verdicts = self._call(chunk)
            except Exception as exc:
                logger.warning(
                    "LLM batch failed (size=%d); retrying individually: %s",
                    len(chunk),
                    exc,
                )
                verdicts = self._retry_individually(chunk)
            for i, keep in zip(idx, verdicts, strict=True):
                results[i] = bool(keep)
                if keep is not None:
                    self.store.cache_store(items[i][0].lower(), items[i][1], keep)

        return [bool(r) for r in results]

    def _call(self, items: list[tuple[str, str]]) -> list[bool]:
        numbered = "\n".join(
            f'{i + 1}. "{w}" — context: "{_truncate(s, 200)}"'
            for i, (w, s) in enumerate(items)
        )
        # ~5 output tokens per verdict + ~30 for JSON wrapper / code fence.
        max_tokens = 30 + len(items) * 5
        raw = self.client.messages_create(
            model=self.model,
            prompt=PROMPT.format(numbered_items=numbered),
            max_tokens=max_tokens,
        )
        verdicts = _parse(raw)
        if len(verdicts) > len(items):
            logger.warning(
                "LLM returned %d verdicts for %d items; ignoring extras",
                len(verdicts),
                len(items),
            )
            verdicts = verdicts[: len(items)]
        if len(verdicts) != len(items):
            raise ValueError(
                f"size mismatch: got {len(verdicts)} for {len(items)}: {raw!r}"
            )
        return verdicts

    def _retry_individually(self, items: list[tuple[str, str]]) -> list[bool | None]:
        verdicts: list[bool | None] = []
        for item in items:
            for attempt in range(3):
                try:
                    verdicts.extend(self._call([item]))
                    break
                except Exception as exc:
                    if attempt < 2 and _is_retryable_llm_error(exc):
                        delay = 5 * (attempt + 1)
                        logger.warning(
                            "LLM single-item validation failed with retryable error; "
                            "retrying in %ss: %s",
                            delay,
                            exc,
                        )
                        time.sleep(delay)
                        continue
                    logger.exception("LLM single-item validation failed; dropping")
                    verdicts.append(None)
                    break
        return verdicts


def _truncate(s: str, n: int) -> str:
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _parse(raw: str) -> list[bool]:
    """Extract ``[true, false, ...]`` from the model reply."""
    raw = raw.strip()
    start = raw.find("{")
    if start < 0:
        raise ValueError(f"no JSON object: {raw!r}")
    depth = 0
    end = -1
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        raise ValueError(f"unterminated JSON: {raw!r}")
    obj = json.loads(raw[start : end + 1])
    keep = obj.get("keep")
    if keep is None and len(obj) == 1:
        keep = next(iter(obj.values()))
    if not isinstance(keep, list) or not all(isinstance(k, bool) for k in keep):
        raise ValueError(f"missing 'keep' bool list: {obj!r}")
    return keep


def _is_retryable_llm_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {429, 500, 502, 503, 504, 529}:
        return True
    name = type(exc).__name__.lower()
    return any(term in name for term in ("rate", "timeout", "overload", "serviceunavailable"))
