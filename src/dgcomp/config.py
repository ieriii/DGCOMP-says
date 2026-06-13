"""Single source of truth for configuration.

Reads `.env` on disk plus environment variables.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # An empty ANTHROPIC_API_KEY="" exported in the shell would otherwise
        # silently override the .env file value.
        env_ignore_empty=True,
    )

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"

    buttondown_api_key: str = ""

    db_path: Path = Field(default=_REPO_ROOT / "data" / "vocab.sqlite")

    posting_cutoff_date: str = ""  # ISO date; only words ≥ this date are posted

    # Comma-separated instrument codes (AT|M|SA|DMA|FS) whose first-seen words
    # are ingested for dedup but never emailed. State aid is the highest-volume
    # instrument and least relevant to most competition readers, so it's
    # suppressed from the digest by default while still anchoring the
    # "first ever used by the Commission" guarantee.
    post_exclude_instruments: str = "SA"
