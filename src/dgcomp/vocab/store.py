"""SQLite vocabulary store. ``word_lower`` is the dedup key; ``display_form``
preserves the original case for display in posts.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS vocab (
  word_lower    TEXT PRIMARY KEY,
  display_form  TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  case_id       TEXT NOT NULL,
  case_type     TEXT NOT NULL,
  case_title    TEXT NOT NULL DEFAULT '',
  doc_url       TEXT NOT NULL,
  sentence      TEXT NOT NULL,
  posted_at     TEXT,
  posted_to     TEXT
);

CREATE TABLE IF NOT EXISTS source_documents (
  doc_id        TEXT PRIMARY KEY,
  case_id       TEXT NOT NULL,
  url           TEXT NOT NULL,
  fetched_at    TEXT NOT NULL,
  sha256        TEXT NOT NULL,
  decision_date TEXT,
  pages         INTEGER
);

CREATE TABLE IF NOT EXISTS llm_cache (
  cache_key    TEXT PRIMARY KEY,
  keep         INTEGER NOT NULL,
  validated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vocab_unposted
  ON vocab(posted_at) WHERE posted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_vocab_first_seen
  ON vocab(first_seen_at);
"""


@dataclass(frozen=True, slots=True)
class VocabEntry:
    word_lower: str
    display_form: str
    first_seen_at: str
    case_id: str
    case_type: str
    case_title: str
    doc_url: str
    sentence: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> VocabEntry:
        return cls(
            word_lower=row["word_lower"],
            display_form=row["display_form"],
            first_seen_at=row["first_seen_at"],
            case_id=row["case_id"],
            case_type=row["case_type"],
            case_title=row["case_title"] or "",
            doc_url=row["doc_url"],
            sentence=row["sentence"],
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _cache_key(word_lower: str, sentence: str) -> str:
    return sha256(f"{word_lower}\n{sentence}".encode()).hexdigest()


class VocabStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def __enter__(self) -> VocabStore:
        return self

    def __exit__(self, *_: object) -> None:
        self._conn.close()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # --- vocab ---

    def has_word(self, word_lower: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM vocab WHERE word_lower = ?", (word_lower,)
        ).fetchone() is not None

    def add_word(self, entry: VocabEntry) -> bool:
        """Insert if absent. True if inserted, False if it was already there."""
        with self._tx() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO vocab
                   (word_lower, display_form, first_seen_at, case_id, case_type,
                    case_title, doc_url, sentence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.word_lower, entry.display_form, entry.first_seen_at,
                    entry.case_id, entry.case_type, entry.case_title,
                    entry.doc_url, entry.sentence,
                ),
            )
        return cur.rowcount > 0

    def pop_oldest_unposted(self, since: str | None = None) -> VocabEntry | None:
        """Return the oldest unposted word; optional ``since`` is a posting cutoff."""
        sql = "SELECT * FROM vocab WHERE posted_at IS NULL"
        args: tuple = ()
        if since:
            sql += " AND first_seen_at >= ?"
            args = (since,)
        sql += " ORDER BY first_seen_at ASC, word_lower ASC LIMIT 1"
        row = self._conn.execute(sql, args).fetchone()
        return VocabEntry.from_row(row) if row else None

    def mark_posted(self, word_lower: str, channels: list[str]) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE vocab SET posted_at = ?, posted_to = ? WHERE word_lower = ?",
                (_now(), json.dumps(channels), word_lower),
            )

    def recent_words(self, limit: int = 5000) -> list[VocabEntry]:
        rows = self._conn.execute(
            "SELECT * FROM vocab ORDER BY first_seen_at DESC, word_lower ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [VocabEntry.from_row(r) for r in rows]

    # --- source_documents ---

    def has_doc(self, doc_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM source_documents WHERE doc_id = ?", (doc_id,)
        ).fetchone() is not None

    def record_doc(
        self, *, doc_id: str, case_id: str, url: str, sha256_hex: str,
        decision_date: str | None, pages: int | None,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO source_documents
                   (doc_id, case_id, url, fetched_at, sha256, decision_date, pages)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (doc_id, case_id, url, _now(), sha256_hex, decision_date, pages),
            )

    # --- llm_cache ---

    def cache_lookup(self, word_lower: str, sentence: str) -> bool | None:
        row = self._conn.execute(
            "SELECT keep FROM llm_cache WHERE cache_key = ?",
            (_cache_key(word_lower, sentence),),
        ).fetchone()
        return None if row is None else bool(row["keep"])

    def cache_store(self, word_lower: str, sentence: str, keep: bool) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (cache_key, keep, validated_at) "
                "VALUES (?, ?, ?)",
                (_cache_key(word_lower, sentence), int(keep), _now()),
            )
