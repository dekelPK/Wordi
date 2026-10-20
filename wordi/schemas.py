"""Request / response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["daily", "free"]


class GuessIn(BaseModel):
    mode: Mode
    session_id: str | None = Field(default=None, max_length=64)
    word: str = Field(max_length=40)


class SessionIn(BaseModel):
    session_id: str = Field(max_length=64)


class LeaderboardIn(BaseModel):
    session_id: str = Field(max_length=64)
    name: str = Field(max_length=60)


class PuzzleStats(BaseModel):
    """Similarity of the 1st / 10th / 1000th nearest word to the secret."""

    top1: float
    top10: float
    top1000: float


class GuessOut(BaseModel):
    seq: int
    word: str
    similarity: float
    rank: int | None
    is_hint: bool


class SessionState(BaseModel):
    session_id: str
    mode: Mode
    puzzle_number: int | None
    stats: PuzzleStats
    guesses: list[GuessOut]
    guess_count: int
    solved: bool
    gave_up: bool
    used_hint: bool
    duration_ms: int | None
    secret: str | None  # only once solved or given up
    leaderboard_eligible: bool
    submitted: bool


class GuessResponse(BaseModel):
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
    session_id: str
    guess_count: int
    duration_ms: int | None = None
    secret: str | None = None


class GiveUpResponse(BaseModel):
    secret: str


class DailyInfo(BaseModel):
    puzzle_number: int
    date: str
    stats: PuzzleStats
    next_reset: str
    seconds_to_reset: int


class YesterdayInfo(BaseModel):
    puzzle_number: int
    date: str
    word: str
    nearest: list[GuessOut]


class LeaderboardRow(BaseModel):
    rank: int
    name: str
    guesses: int
    duration_ms: int
    is_me: bool
    puzzle_number: int | None = None
    wins: int | None = None
    avg_guesses: float | None = None


class LeaderboardOut(BaseModel):
    scope: Literal["today", "yesterday", "alltime"]
    sort: Literal["daily", "wins", "fastest"]
    puzzle_number: int | None
    total: int
    rows: list[LeaderboardRow]
    me: LeaderboardRow | None
