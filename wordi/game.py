"""Game rules: sessions, guesses, hints and give-up. The server is the source of truth."""

from __future__ import annotations

import math
import random
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .hebrew import is_hebrew_word, normalize
from .models import GameSession, Guess
from .vectors import Neighbors, VectorModel
from .words import DailyCalendar

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_db(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


class GameError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class GuessResult:
    valid: bool
    input: str
    word: str | None = None
    similarity: float | None = None
    rank: int | None = None
    solved: bool = False
    seq: int | None = None
    is_hint: bool = False
    error: str | None = None
    message: str | None = None


def _invalid(raw: str, code: str, message: str, existing: Guess | None = None) -> GuessResult:
    if existing is None:
        return GuessResult(valid=False, input=raw, error=code, message=message)
    return GuessResult(
        valid=False,
        input=raw,
        word=existing.word,
        similarity=existing.similarity,
        rank=existing.rank,
        seq=existing.seq,
        is_hint=existing.is_hint,
        error=code,
        message=message,
    )


class GameService:
    def __init__(
        self,
        model: VectorModel,
        calendar: DailyCalendar,
        free_words: list[str],
        *,
        k: int = 1000,
        rng: random.Random | None = None,
    ) -> None:
        self.model = model
        self.calendar = calendar
        self.free_words = free_words
        self.k = k
        self.rng = rng or random.SystemRandom()

    # --- sessions ------------------------------------------------------------

    def neighbors(self, secret: str) -> Neighbors:
        return self.model.neighbors(secret, self.k)

    def get_session(self, db: Session, session_id: str, player_id: str) -> GameSession:
        sess = db.get(GameSession, session_id)
        if sess is None or sess.player_id != player_id:
            raise GameError("session_not_found", "המשחק לא נמצא.", 404)
        return sess

    def daily_session(self, db: Session, player_id: str, now: datetime) -> GameSession:
        """The player's single official attempt at today's puzzle (created on first use)."""
        puzzle = self.calendar.today(now)
        stmt = select(GameSession).where(
            GameSession.player_id == player_id,
            GameSession.mode == "daily",
            GameSession.puzzle_number == puzzle,
        )
        sess = db.scalars(stmt).first()
        if sess is not None:
            return sess
        sess = GameSession(
            id=secrets.token_hex(16),
            player_id=player_id,
            mode="daily",
            puzzle_number=puzzle,
            secret_word=self.calendar.word_for_puzzle(puzzle),
            created_at=to_db(now),
            used_hint=False,
            guess_count=0,
        )
        db.add(sess)
        try:
            db.commit()
        except IntegrityError:  # concurrent request created it first
            db.rollback()
            return db.scalars(stmt).one()
        return sess

    def free_session(self, db: Session, player_id: str, now: datetime) -> GameSession:
        todays = self.calendar.word_for_puzzle(self.calendar.today(now))
        pool = [w for w in self.free_words if w != todays] or self.free_words
        sess = GameSession(
            id=secrets.token_hex(16),
            player_id=player_id,
            mode="free",
            puzzle_number=None,
            secret_word=self.rng.choice(pool),
            created_at=to_db(now),
            used_hint=False,
            guess_count=0,
        )
        db.add(sess)
        db.commit()
        return sess

    # --- actions -------------------------------------------------------------

    def guess(self, db: Session, sess: GameSession, raw: str, now: datetime) -> GuessResult:
        if sess.finished:
            raise GameError("finished", "המשחק הזה כבר הסתיים.")
        word = normalize(raw)
        if not word or not is_hebrew_word(word):
            return _invalid(raw, "not_hebrew", "יש להקליד מילה אחת בעברית.")
        resolved = self.model.resolve(word)
        if resolved is None:
            return _invalid(raw, "unknown_word", f"אני לא מכיר את המילה „{word}”.")
        existing = next((g for g in sess.guesses if g.word == resolved), None)
        if existing is not None:
            return _invalid(raw, "duplicate", f"כבר ניחשת את „{resolved}”.", existing)

        solved = resolved == sess.secret_word
        similarity = 100.0 if solved else self.model.similarity(resolved, sess.secret_word)
        rank = None if solved else self.neighbors(sess.secret_word).rank(resolved)
        if sess.first_guess_at is None:
            sess.first_guess_at = to_db(now)
        sess.guess_count += 1
        if solved:
            sess.solved_at = to_db(now)
        g = self._add_guess(sess, resolved, similarity, rank, is_hint=False, now=now)
        try:
            db.commit()
        except IntegrityError:  # same word submitted twice concurrently
            db.rollback()
            return _invalid(raw, "duplicate", f"כבר ניחשת את „{resolved}”.")
        return GuessResult(
            valid=True, input=raw, word=resolved, similarity=similarity, rank=rank, solved=solved, seq=g.seq
        )

    def hint(self, db: Session, sess: GameSession, now: datetime) -> GuessResult:
        """Reveal an unguessed word ranked between the best guess so far and the secret."""
        if sess.finished:
            raise GameError("finished", "המשחק הזה כבר הסתיים.")
        nb = self.neighbors(sess.secret_word)
        guessed = {g.word for g in sess.guesses}
        best = max((g.rank or 0 for g in sess.guesses), default=0)
        target = best + math.ceil((nb.k - best) / 2)
        order = [*range(target, nb.k + 1), *range(target - 1, best, -1)]
        word = next((nb.word_at_rank(r) for r in order if nb.word_at_rank(r) not in guessed), None)
        if word is None:
            raise GameError("no_more_hints", "אין רמזים נוספים — כבר ניחשת את המילה הקרובה ביותר.")
        rank = nb.rank(word)
        similarity = self.model.similarity(word, sess.secret_word)
        sess.used_hint = True
        if sess.first_guess_at is None:
            sess.first_guess_at = to_db(now)
        g = self._add_guess(sess, word, similarity, rank, is_hint=True, now=now)
        db.commit()
        return GuessResult(valid=True, input=word, word=word, similarity=similarity, rank=rank, seq=g.seq, is_hint=True)

    def give_up(self, db: Session, sess: GameSession, now: datetime) -> str:
        if sess.solved_at is None and sess.gave_up_at is None:
            sess.gave_up_at = to_db(now)
            db.commit()
        return sess.secret_word

    @staticmethod
    def _add_guess(
        sess: GameSession, word: str, similarity: float, rank: int | None, *, is_hint: bool, now: datetime
    ) -> Guess:
        g = Guess(
            seq=len(sess.guesses) + 1,
            word=word,
            similarity=similarity,
            rank=rank,
            is_hint=is_hint,
            created_at=to_db(now),
        )
        sess.guesses.append(g)
        return g
