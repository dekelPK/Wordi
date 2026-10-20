from fastapi.testclient import TestClient

from wordi.models import GameSession

from .conftest import FakeClock, player_headers

P1 = player_headers()
P2 = player_headers("22222222-2222-4222-8222-222222222222")


def today_secret(client: TestClient, clock: FakeClock) -> str:
    cal = client.app.state.game.calendar
    return cal.word_for_puzzle(cal.today(clock()))


def guess(client: TestClient, word: str, mode: str = "daily", session_id: str | None = None, headers=P1) -> dict:
    r = client.post("/api/guess", json={"mode": mode, "session_id": session_id, "word": word}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def a_non_secret(client: TestClient, secret: str) -> str:
    return next(w for w in ["כלב", "חתול", "שולחן", "ים"] if w != secret)


def test_daily_info(client: TestClient) -> None:
    info = client.get("/api/daily-info").json()
    assert info["puzzle_number"] == 69  # 2026-03-10
    assert info["date"] == "2026-03-10"
    s = info["stats"]
    assert s["top1"] >= s["top10"] >= s["top1000"]
    assert info["seconds_to_reset"] == 12 * 3600
    assert "secret" not in info and "word" not in info


def test_player_id_required(client: TestClient) -> None:
    r = client.post("/api/guess", json={"mode": "daily", "word": "כלב"})
    assert r.status_code == 400


def test_guess_validation_messages(client: TestClient, clock: FakeClock) -> None:
    secret = today_secret(client, clock)
    word = a_non_secret(client, secret)
    r = guess(client, "dog")
    assert r["valid"] is False and r["error"] == "not_hebrew"
    r = guess(client, "בלבלבלב")
    assert r["valid"] is False and r["error"] == "unknown_word" and "לא מכיר" in r["message"]
    first = guess(client, word)
    assert first["valid"] and first["seq"] == 1 and first["solved"] is False and first["secret"] is None
    dup = guess(client, word)
    assert dup["valid"] is False and dup["error"] == "duplicate" and dup["word"] == word
    assert guess(client, "בלבלבלב")["guess_count"] == 1  # invalid guesses don't count


def test_rank_reported_for_near_words(client: TestClient, clock: FakeClock) -> None:
    sess = client.post("/api/free/new", headers=P1).json()
    game = client.app.state.game
    # force a known secret for this free session
    with client.app.state.session_factory() as db:
        db.get(GameSession, sess["session_id"]).secret_word = "כלב"
        db.commit()
    nb = game.neighbors("כלב")
    r = guess(client, "גור", "free", sess["session_id"])
    assert r["rank"] == 1000 and r["similarity"] == nb.similarities[0]
    r = guess(client, "לגור", "free", sess["session_id"])  # prefix stripped -> duplicate of גור
    assert r["error"] == "duplicate"
    r = guess(client, "ביתי", "free", sess["session_id"])
    assert r["rank"] == 998


def test_win_flow_and_timing(client: TestClient, clock: FakeClock) -> None:
    secret = today_secret(client, clock)
    guess(client, a_non_secret(client, secret))
    clock.advance(seconds=95)
    r = guess(client, secret)
    assert r["solved"] and r["similarity"] == 100 and r["secret"] == secret
    assert r["guess_count"] == 2 and r["duration_ms"] == 95_000
    # game is over: further guesses are rejected
    r2 = client.post("/api/guess", json={"mode": "daily", "word": "ים"}, headers=P1)
    assert r2.status_code == 400 and r2.json()["error"] == "finished"
    state = client.post("/api/daily/session", headers=P1).json()
    assert state["solved"] and state["secret"] == secret and state["leaderboard_eligible"]


def test_secret_hidden_until_finished(client: TestClient, clock: FakeClock) -> None:
    state = client.post("/api/daily/session", headers=P1).json()
    assert state["secret"] is None
    free = client.post("/api/free/new", headers=P1).json()
    assert free["secret"] is None
    assert client.get(f"/api/session/{free['session_id']}", headers=P1).json()["secret"] is None
    r = client.post("/api/giveup", json={"session_id": free["session_id"]}, headers=P1)
    assert r.status_code == 200 and r.json()["secret"]
    assert client.get(f"/api/session/{free['session_id']}", headers=P1).json()["gave_up"]


def test_one_daily_session_per_player(client: TestClient, clock: FakeClock) -> None:
    s1 = client.post("/api/daily/session", headers=P1).json()["session_id"]
    s2 = client.post("/api/daily/session", headers=P1).json()["session_id"]
    s3 = client.post("/api/daily/session", headers=P2).json()["session_id"]
    assert s1 == s2 != s3
    # after giving up the daily, the player can't start over
    client.post("/api/giveup", json={"session_id": s1}, headers=P1)
    assert client.post("/api/daily/session", headers=P1).json()["gave_up"]
    # ...until Israel midnight
    clock.advance(hours=12)
    fresh = client.post("/api/daily/session", headers=P1).json()
    assert fresh["session_id"] != s1 and fresh["puzzle_number"] == 70 and not fresh["gave_up"]


def test_sessions_are_private(client: TestClient) -> None:
    free = client.post("/api/free/new", headers=P1).json()
    assert client.get(f"/api/session/{free['session_id']}", headers=P2).status_code == 404
    r = client.post("/api/guess", json={"mode": "free", "session_id": free["session_id"], "word": "ים"}, headers=P2)
    assert r.status_code == 404


def test_free_play_excludes_todays_word(client: TestClient, clock: FakeClock) -> None:
    secret = today_secret(client, clock)
    game = client.app.state.game
    with client.app.state.session_factory() as db:
        for _ in range(30):
            assert game.free_session(db, "p", clock()).secret_word != secret


def test_hint_moves_toward_secret(client: TestClient, clock: FakeClock) -> None:
    free = client.post("/api/free/new", headers=P1).json()
    sid = free["session_id"]
    with client.app.state.session_factory() as db:
        secret = client.app.state.game.get_session(db, sid, P1["X-Player-Id"]).secret_word
    nb = client.app.state.game.neighbors(secret)
    h1 = client.get(f"/api/hint?session_id={sid}", headers=P1).json()
    assert h1["is_hint"] and h1["rank"] == 500 and h1["word"] == nb.word_at_rank(500)
    guess(client, nb.word_at_rank(900), "free", sid)
    h2 = client.get(f"/api/hint?session_id={sid}", headers=P1).json()
    assert h2["rank"] == 950
    guess(client, nb.word_at_rank(1000), "free", sid)
    r = client.get(f"/api/hint?session_id={sid}", headers=P1)
    assert r.status_code == 400 and r.json()["error"] == "no_more_hints"
    state = client.get(f"/api/session/{sid}", headers=P1).json()
    assert state["used_hint"] and state["guess_count"] == 2 and len(state["guesses"]) == 4


def test_yesterday(client: TestClient, clock: FakeClock) -> None:
    y = client.get("/api/yesterday").json()
    cal = client.app.state.game.calendar
    assert y["puzzle_number"] == 68 and y["word"] == cal.word_for_puzzle(68)
    assert len(y["nearest"]) == 10 and y["nearest"][0]["rank"] == 1000
