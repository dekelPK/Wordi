"""Daily leaderboard: name validation, submission and ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from .game import GameError, to_db
from .models import GameSession, LeaderboardEntry
from .profanity import is_profane

NAME_MIN, NAME_MAX = 2, 20
_NAME_RE = re.compile(r"^[א-תA-Za-z0-9 ]+$")
BOARD_LIMIT = 100

# Daily ranking: fewest guesses, then fastest, then earliest submission.
DAILY_ORDER = (LeaderboardEntry.guess_count, LeaderboardEntry.duration_ms, LeaderboardEntry.submitted_at)


def validate_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not NAME_MIN <= len(name) <= NAME_MAX:
        raise GameError("bad_name", f"השם צריך להכיל {NAME_MIN}–{NAME_MAX} תווים.")
    if not _NAME_RE.match(name):
        raise GameError("bad_name", "השם יכול להכיל רק אותיות בעברית או באנגלית, ספרות ורווחים.")
    if is_profane(name):
        raise GameError("bad_name", "השם הזה לא מתאים לטבלה. נסו שם אחר.")
    return name


def submit(db: Session, sess: GameSession, name: str, now: datetime) -> LeaderboardEntry:
    if sess.mode != "daily" or sess.puzzle_number is None:
        raise GameError("not_daily", "רק האתגר היומי נכנס לטבלת המובילים.")
    if sess.solved_at is None or sess.first_guess_at is None:
        raise GameError("not_solved", "אפשר להירשם לטבלה רק אחרי שפותרים את החידה.")
    if sess.used_hint:
        raise GameError("used_hint", "פתרון בעזרת רמז לא נכנס לטבלת המובילים.")
    clean = validate_name(name)
    entry = LeaderboardEntry(
        session_id=sess.id,
        player_id=sess.player_id,
        puzzle_number=sess.puzzle_number,
        name=clean,
        guess_count=sess.guess_count,
        duration_ms=sess.duration_ms or 0,
        submitted_at=to_db(now),
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise GameError("already_submitted", "כבר נרשמת לטבלה של היום.", 409) from None
    return entry


@dataclass(frozen=True)
class Row:
    rank: int
    name: str
    guesses: int
    duration_ms: int
    is_me: bool
    puzzle_number: int | None = None
    wins: int | None = None
    avg_guesses: float | None = None


def _daily_row(rank: int, e: LeaderboardEntry, player_id: str | None) -> Row:
    return Row(rank, e.name, e.guess_count, e.duration_ms, e.player_id == player_id)


def daily_board(db: Session, puzzle: int, player_id: str | None) -> tuple[list[Row], Row | None, int]:
    """Top entries for a puzzle, the requesting player's own row (even outside the top) and the total."""
    stmt = select(LeaderboardEntry).where(LeaderboardEntry.puzzle_number == puzzle).order_by(*DAILY_ORDER)
    entries = db.scalars(stmt.limit(BOARD_LIMIT)).all()
    rows = [_daily_row(i + 1, e, player_id) for i, e in enumerate(entries)]
    total = db.scalar(select(func.count()).where(LeaderboardEntry.puzzle_number == puzzle)) or 0
    me = next((r for r in rows if r.is_me), None)
    if me is None and player_id:
        mine = db.scalars(
            select(LeaderboardEntry).where(
                LeaderboardEntry.puzzle_number == puzzle, LeaderboardEntry.player_id == player_id
            )
        ).first()
        if mine is not None:
            E = LeaderboardEntry
            better = db.scalar(
                select(func.count()).where(
                    E.puzzle_number == puzzle,
                    or_(
                        E.guess_count < mine.guess_count,
                        and_(E.guess_count == mine.guess_count, E.duration_ms < mine.duration_ms),
                        and_(
                            E.guess_count == mine.guess_count,
                            E.duration_ms == mine.duration_ms,
                            E.submitted_at < mine.submitted_at,
                        ),
                    ),
                )
            )
            me = _daily_row((better or 0) + 1, mine, player_id)
    return rows, me, total


def alltime_wins(db: Session, player_id: str | None) -> list[Row]:
    """Players ordered by number of leaderboard wins, then average guesses, then best time."""
    E = LeaderboardEntry
    latest = aliased(LeaderboardEntry)
    latest_name = (
        select(latest.name)
        .where(latest.player_id == E.player_id)
        .order_by(latest.submitted_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    wins = func.count(E.id).label("wins")
    avg = func.avg(E.guess_count).label("avg")
    best_ms = func.min(E.duration_ms).label("best_ms")
    best_guesses = func.min(E.guess_count).label("best_guesses")
    stmt = (
        select(E.player_id, latest_name.label("name"), wins, avg, best_ms, best_guesses)
        .group_by(E.player_id)
        .order_by(wins.desc(), avg.asc(), best_ms.asc())
        .limit(BOARD_LIMIT)
    )
    return [
        Row(
            rank=i + 1,
            name=r.name,
            guesses=r.best_guesses,
            duration_ms=r.best_ms,
            is_me=r.player_id == player_id,
            wins=r.wins,
            avg_guesses=round(float(r.avg), 1),
        )
        for i, r in enumerate(db.execute(stmt))
    ]


def alltime_fastest(db: Session, player_id: str | None) -> list[Row]:
    """Fastest individual solves across all puzzles."""
    E = LeaderboardEntry
    stmt = select(E).order_by(E.duration_ms, E.guess_count, E.submitted_at).limit(BOARD_LIMIT)
    return [
        Row(i + 1, e.name, e.guess_count, e.duration_ms, e.player_id == player_id, puzzle_number=e.puzzle_number)
        for i, e in enumerate(db.scalars(stmt))
    ]


def has_submitted(db: Session, sess: GameSession) -> bool:
    return db.scalar(select(func.count()).where(LeaderboardEntry.session_id == sess.id)) == 1
