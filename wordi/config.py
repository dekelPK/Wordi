"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    db_url: str = field(default_factory=lambda: _env("WORDI_DB_URL", f"sqlite:///{DATA_DIR / 'wordi.db'}"))
    vectors_path: Path = field(
        default_factory=lambda: Path(_env("WORDI_VECTORS", str(DATA_DIR / "vectors" / "he.npz")))
    )
    neighbors_path: Path = field(
        default_factory=lambda: Path(_env("WORDI_NEIGHBORS", str(DATA_DIR / "vectors" / "neighbors.npz")))
    )
    secret_words_path: Path = field(
        default_factory=lambda: Path(_env("WORDI_SECRET_WORDS", str(DATA_DIR / "secret_words.json")))
    )
    web_dir: Path = field(default_factory=lambda: Path(_env("WORDI_WEB_DIR", str(ROOT_DIR / "web"))))
    timezone: str = field(default_factory=lambda: _env("WORDI_TZ", "Asia/Jerusalem"))
    # Puzzle #1 is played on this (Israel) date.
    epoch: date = field(default_factory=lambda: date.fromisoformat(_env("WORDI_EPOCH", "2026-01-01")))
    # Changing the salt reshuffles the daily order.
    daily_salt: str = field(default_factory=lambda: _env("WORDI_DAILY_SALT", "wordi-v1"))
    neighbors_k: int = 1000
    # Honour X-Forwarded-For for rate limiting (only behind a trusted reverse proxy).
    trust_proxy: bool = field(default_factory=lambda: _env("WORDI_TRUST_PROXY", "0") == "1")
    rate_limit_enabled: bool = field(default_factory=lambda: _env("WORDI_RATE_LIMIT", "1") == "1")
