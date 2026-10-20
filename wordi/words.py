"""Secret-word list and the deterministic daily calendar."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .hebrew import normalize

log = logging.getLogger(__name__)


def load_secret_words(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    words = data["words"] if isinstance(data, dict) else data
    return list(dict.fromkeys(normalize(w) for w in words if w.strip()))


@dataclass(frozen=True)
class DailyCalendar:
    words: tuple[str, ...]
    epoch: date
    salt: str
    tz: ZoneInfo

    @classmethod
    def create(cls, words: list[str], epoch: date, salt: str, tz_name: str) -> DailyCalendar:
        if not words:
            raise ValueError("secret word list is empty")
        # A stable pseudo-random order: independent of the order in the JSON file.
        ordered = sorted(words, key=lambda w: hashlib.sha256(f"{salt}:{w}".encode()).hexdigest())
        return cls(tuple(ordered), epoch, salt, ZoneInfo(tz_name))

    def local_date(self, now: datetime) -> date:
        return now.astimezone(self.tz).date()

    def puzzle_number(self, day: date) -> int:
        return (day - self.epoch).days + 1

    def date_of(self, puzzle_number: int) -> date:
        return self.epoch + timedelta(days=puzzle_number - 1)

    def word_for_puzzle(self, puzzle_number: int) -> str:
        return self.words[(puzzle_number - 1) % len(self.words)]

    def today(self, now: datetime) -> int:
        return self.puzzle_number(self.local_date(now))

    def next_reset(self, now: datetime) -> datetime:
        """The next local midnight, as an aware datetime."""
        tomorrow = self.local_date(now) + timedelta(days=1)
        return datetime.combine(tomorrow, time.min, tzinfo=self.tz)
