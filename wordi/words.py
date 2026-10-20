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


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class DailyCalendar:
    """Maps dates to secret words.

    The order comes from the *full* curated list, so it is the same on every server whatever its
    vocabulary. A day whose word is missing from the vocabulary falls back to a substitute chosen
    deterministically from the available words, without shifting any other day.
    """

    words: tuple[str, ...]  # every curated word, in daily order
    available: frozenset[str]  # the ones present in the vocabulary
    epoch: date
    salt: str
    tz: ZoneInfo

    @classmethod
    def create(
        cls, words: list[str], epoch: date, salt: str, tz_name: str, available: set[str] | None = None
    ) -> DailyCalendar:
        usable = frozenset(words if available is None else (w for w in words if w in available))
        if not usable:
            raise ValueError("no secret word is in the vocabulary")
        # A stable pseudo-random order: independent of the order in the JSON file.
        ordered = sorted(words, key=lambda w: _hash(f"{salt}:{w}"))
        return cls(tuple(ordered), usable, epoch, salt, ZoneInfo(tz_name))

    def local_date(self, now: datetime) -> date:
        return now.astimezone(self.tz).date()

    def puzzle_number(self, day: date) -> int:
        return (day - self.epoch).days + 1

    def date_of(self, puzzle_number: int) -> date:
        return self.epoch + timedelta(days=puzzle_number - 1)

    def word_for_puzzle(self, puzzle_number: int) -> str:
        word = self.words[(puzzle_number - 1) % len(self.words)]
        if word in self.available:
            return word
        return min(self.available, key=lambda w: _hash(f"{self.salt}:{puzzle_number}:{w}"))

    def today(self, now: datetime) -> int:
        return self.puzzle_number(self.local_date(now))

    def next_reset(self, now: datetime) -> datetime:
        """The next local midnight, as an aware datetime."""
        tomorrow = self.local_date(now) + timedelta(days=1)
        return datetime.combine(tomorrow, time.min, tzinfo=self.tz)
