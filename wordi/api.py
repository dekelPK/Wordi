"""HTTP routes."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from . import leaderboard as lb
from .game import Clock, GameError, GameService
from .models import GameSession
from .schemas import (
    DailyInfo,
    GiveUpResponse,
    GuessIn,
    GuessOut,
    GuessResponse,
    LeaderboardIn,
    LeaderboardOut,
    LeaderboardRow,
    PuzzleStats,
    SessionIn,
    SessionState,
    YesterdayInfo,
)

router = APIRouter(prefix="/api")


# --- dependencies ------------------------------------------------------------


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as db:
        yield db


def get_game(request: Request) -> GameService:
    return request.app.state.game


def get_now(request: Request) -> datetime:
    clock: Clock = request.app.state.clock
    return clock()


def _parse_player_id(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def optional_player(
    x_player_id: Annotated[str | None, Header()] = None,
    wordi_pid: Annotated[str | None, Cookie()] = None,
) -> str | None:
    return _parse_player_id(x_player_id) or _parse_player_id(wordi_pid)


def require_player(player_id: Annotated[str | None, Depends(optional_player)]) -> str:
    if player_id is None:
        raise HTTPException(400, {"error": "no_player", "message": "מזהה שחקן חסר. רעננו את הדף."})
    return player_id


DB = Annotated[Session, Depends(get_db)]
Game = Annotated[GameService, Depends(get_game)]
Now = Annotated[datetime, Depends(get_now)]
Player = Annotated[str, Depends(require_player)]
MaybePlayer = Annotated[str | None, Depends(optional_player)]


# --- helpers -----------------------------------------------------------------


def _stats(game: GameService, secret: str) -> PuzzleStats:
    nb = game.neighbors(secret)
    return PuzzleStats(top1=nb.similarity_at(1), top10=nb.similarity_at(10), top1000=nb.similarity_at(1000))


def _state(db: Session, game: GameService, sess: GameSession) -> SessionState:
    submitted = sess.mode == "daily" and lb.has_submitted(db, sess)
    return SessionState(
        session_id=sess.id,
        mode=sess.mode,  # type: ignore[arg-type]
        puzzle_number=sess.puzzle_number,
        stats=_stats(game, sess.secret_word),
        guesses=[
            GuessOut(seq=g.seq, word=g.word, similarity=g.similarity, rank=g.rank, is_hint=g.is_hint)
            for g in sess.guesses
        ],
        guess_count=sess.guess_count,
        solved=sess.solved_at is not None,
        gave_up=sess.gave_up_at is not None,
        used_hint=sess.used_hint,
        duration_ms=sess.duration_ms,
        secret=sess.secret_word if sess.finished else None,
        leaderboard_eligible=sess.mode == "daily"
        and sess.solved_at is not None
        and not sess.used_hint
        and not submitted,
        submitted=submitted,
    )


def _session_for(
    db: Session, game: GameService, player: str, now: datetime, mode: str, session_id: str | None
) -> GameSession:
    if mode == "daily":
        sess = game.daily_session(db, player, now) if session_id is None else game.get_session(db, session_id, player)
        if sess.mode != "daily":
            raise GameError("bad_mode", "המשחק לא תואם למצב שנבחר.")
        return sess
    if session_id is None:
        raise GameError("no_session", "חסר מזהה משחק.")
    return game.get_session(db, session_id, player)


# --- routes ------------------------------------------------------------------


@router.get("/health")
def health(game: Game) -> dict[str, int | str]:
    return {"status": "ok", "vocabulary": len(game.model), "secret_words": len(game.calendar.words)}


@router.get("/daily-info", response_model=DailyInfo)
def daily_info(game: Game, now: Now) -> DailyInfo:
    cal = game.calendar
    puzzle = cal.today(now)
    reset = cal.next_reset(now)
    return DailyInfo(
        puzzle_number=puzzle,
        date=cal.date_of(puzzle).isoformat(),
        stats=_stats(game, cal.word_for_puzzle(puzzle)),
        next_reset=reset.isoformat(),
        seconds_to_reset=max(0, int((reset - now).total_seconds())),
    )


@router.get("/yesterday", response_model=YesterdayInfo)
def yesterday(game: Game, now: Now) -> YesterdayInfo:
    cal = game.calendar
    puzzle = cal.today(now) - 1
    word = cal.word_for_puzzle(puzzle)
    nb = game.neighbors(word)
    nearest = [
        GuessOut(seq=i + 1, word=w, similarity=nb.similarities[i], rank=nb.rank(w), is_hint=False)
        for i, w in enumerate(nb.words[:10])
    ]
    return YesterdayInfo(puzzle_number=puzzle, date=cal.date_of(puzzle).isoformat(), word=word, nearest=nearest)


@router.post("/daily/session", response_model=SessionState)
def daily_session(db: DB, game: Game, player: Player, now: Now) -> SessionState:
    return _state(db, game, game.daily_session(db, player, now))


@router.get("/session/{session_id}", response_model=SessionState)
def session_state(session_id: str, db: DB, game: Game, player: Player) -> SessionState:
    return _state(db, game, game.get_session(db, session_id, player))


@router.post("/free/new", response_model=SessionState)
def free_new(db: DB, game: Game, player: Player, now: Now) -> SessionState:
    return _state(db, game, game.free_session(db, player, now))


@router.post("/guess", response_model=GuessResponse)
def guess(body: GuessIn, db: DB, game: Game, player: Player, now: Now) -> GuessResponse:
    sess = _session_for(db, game, player, now, body.mode, body.session_id)
    result = game.guess(db, sess, body.word, now)
    return GuessResponse(
        **asdict(result),
        session_id=sess.id,
        guess_count=sess.guess_count,
        duration_ms=sess.duration_ms,
        secret=sess.secret_word if result.solved else None,
    )


@router.get("/hint", response_model=GuessResponse)
def hint(
    session_id: Annotated[str, Query(max_length=64)], db: DB, game: Game, player: Player, now: Now
) -> GuessResponse:
    sess = game.get_session(db, session_id, player)
    result = game.hint(db, sess, now)
    return GuessResponse(**asdict(result), session_id=sess.id, guess_count=sess.guess_count)


@router.post("/giveup", response_model=GiveUpResponse)
def give_up(body: SessionIn, db: DB, game: Game, player: Player, now: Now) -> GiveUpResponse:
    sess = game.get_session(db, body.session_id, player)
    return GiveUpResponse(secret=game.give_up(db, sess, now))


@router.post("/leaderboard", response_model=LeaderboardRow)
def submit_leaderboard(body: LeaderboardIn, db: DB, game: Game, player: Player, now: Now) -> LeaderboardRow:
    sess = game.get_session(db, body.session_id, player)
    lb.submit(db, sess, body.name, now)
    _, me, _ = lb.daily_board(db, sess.puzzle_number or 0, player)
    assert me is not None
    return LeaderboardRow(**asdict(me))


@router.get("/leaderboard", response_model=LeaderboardOut)
def get_leaderboard(
    db: DB,
    game: Game,
    player: MaybePlayer,
    now: Now,
    scope: Literal["today", "yesterday", "alltime"] = "today",
    sort: Literal["wins", "fastest"] = "wins",
) -> LeaderboardOut:
    if scope == "alltime":
        rows = lb.alltime_wins(db, player) if sort == "wins" else lb.alltime_fastest(db, player)
        me = next((r for r in rows if r.is_me), None)
        return LeaderboardOut(
            scope=scope,
            sort=sort,
            puzzle_number=None,
            total=len(rows),
            rows=[LeaderboardRow(**asdict(r)) for r in rows],
            me=LeaderboardRow(**asdict(me)) if me else None,
        )
    puzzle = game.calendar.today(now) - (1 if scope == "yesterday" else 0)
    rows, me, total = lb.daily_board(db, puzzle, player)
    return LeaderboardOut(
        scope=scope,
        sort="daily",
        puzzle_number=puzzle,
        total=total,
        rows=[LeaderboardRow(**asdict(r)) for r in rows],
        me=LeaderboardRow(**asdict(me)) if me else None,
    )
