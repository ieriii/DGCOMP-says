"""Command-line entry point.

  dgcomp run        — one tick of the live cron (ingest + post)
  dgcomp backfill   — historical ingest (no posting)
  dgcomp review     — print recent vocab additions for human triage
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import typer

from dgcomp.config import Settings
from dgcomp.ingest import ingest_one
from dgcomp.publish.buttondown import ButtondownPublisher
from dgcomp.sources.client import CompetitionCasesClient, InstrumentType
from dgcomp.vocab.store import VocabEntry, VocabStore
from dgcomp.vocab.validate import AnthropicAdapter, Validator

app = typer.Typer(no_args_is_help=True, add_completion=False)
log = logging.getLogger("dgcomp")

DEFAULT_INSTRUMENTS = [
    InstrumentType.MERGERS,
    InstrumentType.ANTITRUST,
    InstrumentType.STATE_AID,
    InstrumentType.DMA,
    InstrumentType.FOREIGN_SUBSIDIES,
]


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def review(
    limit: int = typer.Option(20, help="Number of most-recent additions to show"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Print the N most-recent vocabulary additions."""
    _setup_logging(verbose)
    settings = Settings()
    with VocabStore(settings.db_path) as store:
        for entry in store.recent_words(limit=limit):
            posted = "✓" if entry.posted_at else "·"
            typer.echo(
                f"{posted} {entry.first_seen_at}  {entry.display_form:<30}  "
                f"{entry.case_id:<14}  {entry.sentence[:80]}"
            )


@app.command()
def run(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    skip_post: bool = typer.Option(False, "--skip-post", help="Don't post (dry run)"),
) -> None:
    """One daily tick: ingest today's decisions and post new words."""
    _setup_logging(verbose)
    settings = Settings()

    today = date.today()

    with VocabStore(settings.db_path) as store:
        inserted = _ingest(
            settings,
            store,
            date_from=today,
            date_to=_exclusive_until(today),
            instruments=DEFAULT_INSTRUMENTS,
        )
        log.info("ingested %d new words", len(inserted))

        if not skip_post:
            _post_entries(settings, store, inserted)


@app.command()
def backfill(
    since: str = typer.Option("1990-01-01", help="ISO date — inclusive lower bound"),
    until: str = typer.Option("", help="ISO date — inclusive upper bound (default: today)"),
    instrument: str = typer.Option(
        "", help="Filter to one instrument (AT|M|SA|DMA|FS). Empty = all five."
    ),
    chunk_size: int = typer.Option(25, help="Words per Anthropic batch call."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Historical ingest. No posting."""
    _setup_logging(verbose)
    settings = Settings()

    date_from = date.fromisoformat(since)
    date_to = _exclusive_until(date.fromisoformat(until) if until else date.today())
    instruments = _instruments(instrument)

    typer.echo(
        f"backfill {date_from} → {date_to}  "
        f"instruments={[i.value for i in instruments]}  dry_run={dry_run}"
    )
    inserted = _ingest(
        settings, None, date_from=date_from, date_to=date_to,
        instruments=instruments, chunk_size=chunk_size, dry_run=dry_run,
    )
    typer.echo(f"done. {len(inserted)} new words.")


def _ingest(
    settings: Settings,
    store: VocabStore | None,
    *,
    date_from: date,
    date_to: date,
    instruments: list[InstrumentType] | None = None,
    chunk_size: int = 25,
    dry_run: bool = False,
) -> list[VocabEntry]:
    """Walk the API for ``date_from`` through exclusive ``date_to``.

    If ``store`` is None, opens one (used by ``backfill`` which manages its own).
    Returns the new vocab entries inserted (empty in dry-run).
    """
    instruments = instruments or DEFAULT_INSTRUMENTS
    own_store = store is None
    store = store or VocabStore(settings.db_path)
    client = CompetitionCasesClient()
    inserted_entries: list[VocabEntry] = []
    docs = 0
    try:
        validator = Validator(
            store=store,
            client=AnthropicAdapter(
                api_key=settings.anthropic_api_key, model=settings.anthropic_model
            ),
            model=settings.anthropic_model,
        )
        for inst in instruments:
            for doc in client.search(
                instrument=inst, date_from=date_from, date_to=date_to
            ):
                if dry_run:
                    typer.echo(
                        f"  would ingest {doc.case_id} {doc.decision_date} "
                        f"{doc.title[:60]}"
                    )
                    continue
                inserted = ingest_one(
                    doc=doc, store=store, validator=validator, chunk_size=chunk_size
                )
                inserted_entries.extend(inserted)
                docs += 1
                if docs % 10 == 0:
                    log.info("…%d docs · %d new words", docs, len(inserted_entries))
    finally:
        client.close()
        if own_store:
            store.close()
    return inserted_entries


def _exclusive_until(day: date) -> date:
    return day + timedelta(days=1)


def _instruments(instrument: str) -> list[InstrumentType]:
    return [InstrumentType(instrument)] if instrument else DEFAULT_INSTRUMENTS


def _post_entries(
    settings: Settings, store: VocabStore, entries: list[VocabEntry]
) -> None:
    if not entries:
        log.info("nothing new to post")
        return
    publisher = ButtondownPublisher(api_key=settings.buttondown_api_key)
    try:
        for entry in entries:
            if publisher.post(entry):
                store.mark_posted(entry.word_lower, ["buttondown"])
                log.info("posted: %s", entry.display_form)
    finally:
        publisher.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
