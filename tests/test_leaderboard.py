from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from wordi import leaderboard as lb
from wordi.game import GameError
from wordi.models import GameSession, LeaderboardEntry
from wordi.profanity import is_profane

from .conftest import FakeClock, player_headers
from .test_game_api import guess, today_secret

P1 = player_headers()


def pid(n: int) -> str:
    return f"{n:08d}-0000-4000-8000-000000000000"


# --- name validation -----------------------------------------------------------


@pytest.mark.parametrize("name", ["דקל", "Dekel K", "שחקן 7", "ab", "א" * 20])
def test_valid_names(name: str) -> None:
    assert lb.validate_name(name) == name


def test_name_whitespace_collapsed() -> None:
    assert lb.validate_name("  דקל   כהן ") == "דקל כהן"


@pytest.mark.parametrize("name", ["א", "א" * 21, "<script>", "a_b", "דקל!", "😀😀", ""])
def test_invalid_names(name: str) -> None:
    with pytest.raises(GameError):
        lb.validate_name(name)


@pytest.mark.parametrize("name", ["fuck you", "F U C K", "sh1t", "בן זונה", "שרמוטה", "כוס", "Hitler"])
def test_profanity_rejected(name: str) -> None:
    assert is_profane(name)
    with pytest.raises(GameError):
        lb.validate_name(name)


@pytest.mark.parametrize("name", ["כוסות", "Cassandra", "תחתית", "Grapes", "דקל"])
def test_profanity_avoids_obvious_false_positives(name: str) -> None:
    assert not is_profane(name)


# --- ordering ------------------------------------------------------------------


def _entry(db: Session, n: int, guesses: int, ms: int, submitted: datetime, puzzle: int = 5) -> None:
    sid = f"s{n:031d}"
    db.add(
        GameSession(
            id=sid,
            player_id=pid(n),
            mode="daily",
            puzzle_number=puzzle,
            secret_word="x",
            created_at=submitted,
            used_hint=False,
            guess_count=guesses,
        )
    )
    db.add(
        LeaderboardEntry(
            session_id=sid,
            player_id=pid(n),
            puzzle_number=puzzle,
            name=f"p{n}",
            guess_count=guesses,
            duration_ms=ms,
            submitted_at=submitted,
        )
    )


def test_daily_ordering(client: TestClient) -> None:
    t0 = datetime(2026, 3, 1, 12)
    with client.app.state.session_factory() as db:
        _entry(db, 1, 20, 60_000, t0)
        _entry(db, 2, 10, 90_000, t0 + timedelta(minutes=5))
        _entry(db, 3, 10, 30_000, t0 + timedelta(minutes=9))
        _entry(db, 4, 10, 30_000, t0 + timedelta(minutes=1))  # same score as 3, submitted earlier
        _entry(db, 5, 5, 999_000, t0, puzzle=6)  # other puzzle
        db.commit()
        rows, me, total = lb.daily_board(db, 5, pid(3))
    assert [r.name for r in rows] == ["p4", "p3", "p2", "p1"]
    assert [r.rank for r in rows] == [1, 2, 3, 4]
    assert total == 4 and me is not None and me.rank == 2 and me.is_me


def test_my_row_outside_top(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(lb, "BOARD_LIMIT", 2)
    t0 = datetime(2026, 3, 1, 12)
    with client.app.state.session_factory() as db:
        for n in range(1, 6):
            _entry(db, n, n, 1000, t0)
        db.commit()
        rows, me, total = lb.daily_board(db, 5, pid(4))
    assert len(rows) == 2 and total == 5
    assert me is not None and me.rank == 4 and me.name == "p4"


def test_alltime(client: TestClient) -> None:
    t0 = datetime(2026, 3, 1, 12)
    with client.app.state.session_factory() as db:
        _entry(db, 1, 30, 50_000, t0, puzzle=1)
        db.add(
            GameSession(
                id="x" * 32,
                player_id=pid(1),
                mode="daily",
                puzzle_number=2,
                secret_word="x",
                created_at=t0,
                used_hint=False,
                guess_count=10,
            )
        )
        db.add(
            LeaderboardEntry(
                session_id="x" * 32,
                player_id=pid(1),
                puzzle_number=2,
                name="renamed",
                guess_count=10,
                duration_ms=40_000,
                submitted_at=t0 + timedelta(days=1),
            )
        )
        _entry(db, 2, 5, 10_000, t0, puzzle=1)
        db.commit()
        wins = lb.alltime_wins(db, pid(2))
        fastest = lb.alltime_fastest(db, None)
    assert [(r.name, r.wins, r.avg_guesses) for r in wins] == [("renamed", 2, 20.0), ("p2", 1, 5.0)]
    assert wins[1].is_me
    assert [r.duration_ms for r in fastest] == [10_000, 40_000, 50_000]


# --- submission via the API ----------------------------------------------------


def solve_daily(client: TestClient, clock: FakeClock, headers=P1) -> str:
    secret = today_secret(client, clock)
    other = next(w for w in ["כלב", "חתול", "שולחן", "ים"] if w != secret)
    r = guess(client, other, headers=headers)
    clock.advance(seconds=42)
    r = guess(client, secret, headers=headers)
    assert r["solved"]
    return r["session_id"]


def test_submit_and_read(client: TestClient, clock: FakeClock) -> None:
    sid = solve_daily(client, clock)
    r = client.post("/api/leaderboard", json={"session_id": sid, "name": "דקל"}, headers=P1)
    assert r.status_code == 200 and r.json() == {
        "rank": 1,
        "name": "דקל",
        "guesses": 2,
        "duration_ms": 42_000,
        "is_me": True,
        "puzzle_number": None,
        "wins": None,
        "avg_guesses": None,
    }
    again = client.post("/api/leaderboard", json={"session_id": sid, "name": "דקל"}, headers=P1)
    assert again.status_code == 409
    board = client.get("/api/leaderboard?scope=today", headers=P1).json()
    assert board["total"] == 1 and board["me"]["name"] == "דקל"
    assert client.get("/api/leaderboard?scope=today").json()["rows"][0]["is_me"] is False
    assert client.get("/api/leaderboard?scope=yesterday").json()["total"] == 0
    state = client.post("/api/daily/session", headers=P1).json()
    assert state["submitted"] and not state["leaderboard_eligible"]
    # tomorrow it shows up under "yesterday"
    clock.advance(days=1)
    assert client.get("/api/leaderboard?scope=yesterday").json()["total"] == 1
    assert client.get("/api/leaderboard?scope=alltime&sort=fastest").json()["rows"][0]["duration_ms"] == 42_000


def test_submit_rejections(client: TestClient, clock: FakeClock) -> None:
    # unsolved
    sid = client.post("/api/daily/session", headers=P1).json()["session_id"]
    r = client.post("/api/leaderboard", json={"session_id": sid, "name": "דקל"}, headers=P1)
    assert r.json()["error"] == "not_solved"
    # someone else's session
    r = client.post("/api/leaderboard", json={"session_id": sid, "name": "דקל"}, headers=player_headers(pid(9)))
    assert r.status_code == 404
    # free play
    free = client.post("/api/free/new", headers=P1).json()["session_id"]
    r = client.post("/api/leaderboard", json={"session_id": free, "name": "דקל"}, headers=P1)
    assert r.json()["error"] == "not_daily"


def test_hint_disqualifies(client: TestClient, clock: FakeClock) -> None:
    sid = client.post("/api/daily/session", headers=P1).json()["session_id"]
    client.get(f"/api/hint?session_id={sid}", headers=P1)
    sid2 = solve_daily(client, clock)
    assert sid2 == sid
    state = client.post("/api/daily/session", headers=P1).json()
    assert state["used_hint"] and not state["leaderboard_eligible"]
    r = client.post("/api/leaderboard", json={"session_id": sid, "name": "דקל"}, headers=P1)
    assert r.status_code == 400 and r.json()["error"] == "used_hint"


def test_bad_name_rejected_via_api(client: TestClient, clock: FakeClock) -> None:
    sid = solve_daily(client, clock)
    r = client.post("/api/leaderboard", json={"session_id": sid, "name": "<b>x</b>"}, headers=P1)
    assert r.status_code == 400 and r.json()["error"] == "bad_name"


def test_rate_limit(app_factory) -> None:
    client = app_factory(rate_limit=True)
    codes = [client.post("/api/free/new", headers=P1).status_code for _ in range(25)]
    assert codes[:20] == [200] * 20 and codes[-1] == 429
