"""SQLAlchemy ORM models. All datetimes are naive UTC."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class GameSession(Base):
    __tablename__ = "game_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    player_id: Mapped[str] = mapped_column(String(36), index=True)
    mode: Mapped[str] = mapped_column(String(8))  # "daily" | "free"
    puzzle_number: Mapped[int | None] = mapped_column(Integer)
    secret_word: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    first_guess_at: Mapped[datetime | None] = mapped_column(DateTime)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime)
    gave_up_at: Mapped[datetime | None] = mapped_column(DateTime)
    used_hint: Mapped[bool] = mapped_column(Boolean, default=False)
    guess_count: Mapped[int] = mapped_column(Integer, default=0)

    guesses: Mapped[list[Guess]] = relationship(
        back_populates="session", order_by="Guess.seq", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_daily_player_puzzle",
            "player_id",
            "puzzle_number",
            unique=True,
            sqlite_where=text("mode = 'daily'"),
            postgresql_where=text("mode = 'daily'"),
        ),
    )

    @property
    def finished(self) -> bool:
        return self.solved_at is not None or self.gave_up_at is not None

    @property
    def duration_ms(self) -> int | None:
        if self.solved_at is None or self.first_guess_at is None:
            return None
        return int((self.solved_at - self.first_guess_at).total_seconds() * 1000)


class Guess(Base):
    __tablename__ = "guesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("game_sessions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    word: Mapped[str] = mapped_column(String(64))
    similarity: Mapped[float] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    is_hint: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    session: Mapped[GameSession] = relationship(back_populates="guesses")

    __table_args__ = (UniqueConstraint("session_id", "word", name="uq_guess_session_word"),)


class LeaderboardEntry(Base):
    __tablename__ = "leaderboard_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("game_sessions.id"), unique=True)
    player_id: Mapped[str] = mapped_column(String(36), index=True)
    puzzle_number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(20))
    guess_count: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    submitted_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("player_id", "puzzle_number", name="uq_lb_player_puzzle"),
        Index("ix_lb_ranking", "puzzle_number", "guess_count", "duration_ms", "submitted_at"),
    )
