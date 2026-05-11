"""Ingest one decision: scrape → extract → pipeline → record."""

from __future__ import annotations

import hashlib
import logging

from dgcomp.sources.client import DecisionDoc
from dgcomp.sources.extract import extract
from dgcomp.vocab.pipeline import DocumentMeta, process_document
from dgcomp.vocab.store import VocabEntry, VocabStore
from dgcomp.vocab.validate import Validator

log = logging.getLogger(__name__)


def ingest_one(
    *,
    doc: DecisionDoc,
    store: VocabStore,
    validator: Validator,
    chunk_size: int = 25,
) -> list[VocabEntry]:
    """Extract + pipeline one decision. Idempotent — already-ingested docs
    are skipped via ``source_documents.doc_id``.
    """
    if store.has_doc(doc.doc_id):
        log.debug("skip already-ingested %s", doc.doc_id)
        return []

    extracted = extract(doc.pdf_url)
    meta = DocumentMeta(
        case_id=doc.case_id,
        case_type=doc.case_type.value,
        case_title=doc.title,
        decision_date=doc.decision_date.isoformat(),
        doc_url=doc.pdf_url,
    )
    inserted = process_document(
        text=extracted.text,
        meta=meta,
        store=store,
        validator=validator,
        chunk_size=chunk_size,
    )
    store.record_doc(
        doc_id=doc.doc_id,
        case_id=doc.case_id,
        url=doc.pdf_url,
        sha256_hex=hashlib.sha256(extracted.text.encode()).hexdigest(),
        decision_date=doc.decision_date.isoformat(),
        pages=extracted.pages,
    )
    return inserted
