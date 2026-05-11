"""Decision text + metadata → vocab DB inserts.

Tokenise the document, drop tokens that fail the cheap shape filter or are
already in vocab, then ask the LLM (in batches) which of the survivors are
real words. Insert the kept ones.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from dgcomp.vocab.filter import passes_shape
from dgcomp.vocab.segment import segment
from dgcomp.vocab.store import VocabEntry, VocabStore
from dgcomp.vocab.tokenize import tokenise
from dgcomp.vocab.validate import Validator

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    case_id: str
    case_type: str  # M | AT | SA | DMA | FS
    case_title: str
    decision_date: str  # ISO date (YYYY-MM-DD)
    doc_url: str


def process_document(
    *,
    text: str,
    meta: DocumentMeta,
    store: VocabStore,
    validator: Validator,
    chunk_size: int = 25,
) -> list[VocabEntry]:
    """Pipeline one document through tokenise → filter → LLM → insert."""
    candidates = list(_candidates(text, store))
    if not candidates:
        return []

    pairs = [(tok, sent) for tok, _, sent in candidates]
    verdicts = validator.validate(pairs, chunk_size=chunk_size)

    inserted: list[VocabEntry] = []
    for (token, word_lower, sentence), keep in zip(candidates, verdicts, strict=True):
        if not keep:
            continue
        entry = VocabEntry(
            word_lower=word_lower,
            display_form=token,
            first_seen_at=meta.decision_date,
            case_id=meta.case_id,
            case_type=meta.case_type,
            case_title=meta.case_title,
            doc_url=meta.doc_url,
            sentence=sentence,
        )
        if store.add_word(entry):
            inserted.append(entry)
    if inserted:
        logger.info(
            "%s: %d new words from %d candidates",
            meta.case_id, len(inserted), len(candidates),
        )
    return inserted


def _candidates(
    text: str, store: VocabStore
) -> Iterator[tuple[str, str, str]]:
    """Yield (display_form, word_lower, sentence) for first-occurrence
    candidates that survive the shape filter and aren't yet in vocab.
    """
    seen: set[str] = set()
    for sentence in segment(text):
        for token in tokenise(sentence):
            wl = token.lower()
            if wl in seen or store.has_word(wl) or not passes_shape(token):
                seen.add(wl)
                continue
            seen.add(wl)
            yield token, wl, sentence
