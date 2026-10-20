from datetime import UTC, date, datetime

from wordi.words import DailyCalendar

WORDS = [f"מילה{c}" for c in "אבגדהוזחטיכלמנסעפצקרשת"]


def cal(words: list[str] = WORDS) -> DailyCalendar:
    return DailyCalendar.create(words, date(2026, 1, 1), "salt", "Asia/Jerusalem")


def test_puzzle_numbering() -> None:
    c = cal()
    assert c.puzzle_number(date(2026, 1, 1)) == 1
    assert c.puzzle_number(date(2026, 10, 20)) == 293
    assert c.date_of(293) == date(2026, 10, 20)


def test_selection_is_deterministic_and_order_independent() -> None:
    a, b = cal(), cal(list(reversed(WORDS)))
    assert [a.word_for_puzzle(n) for n in range(1, 60)] == [b.word_for_puzzle(n) for n in range(1, 60)]
    other_salt = DailyCalendar.create(WORDS, date(2026, 1, 1), "other", "Asia/Jerusalem")
    assert [a.word_for_puzzle(n) for n in range(1, 23)] != [other_salt.word_for_puzzle(n) for n in range(1, 23)]


def test_every_word_used_once_per_cycle() -> None:
    c = cal()
    cycle = [c.word_for_puzzle(n) for n in range(1, len(WORDS) + 1)]
    assert sorted(cycle) == sorted(WORDS)
    assert c.word_for_puzzle(1) == c.word_for_puzzle(len(WORDS) + 1)


def test_day_changes_at_israel_midnight_winter() -> None:
    c = cal()  # January: Israel is UTC+2
    assert c.today(datetime(2026, 1, 10, 21, 59, tzinfo=UTC)) == 10
    assert c.today(datetime(2026, 1, 10, 22, 0, tzinfo=UTC)) == 11


def test_day_changes_at_israel_midnight_summer() -> None:
    c = cal()  # July: Israel is UTC+3
    before = datetime(2026, 7, 10, 20, 59, tzinfo=UTC)
    after = datetime(2026, 7, 10, 21, 0, tzinfo=UTC)
    assert c.today(after) == c.today(before) + 1
    assert c.next_reset(before) == after


def test_next_reset_is_local_midnight() -> None:
    c = cal()
    reset = c.next_reset(datetime(2026, 1, 10, 12, 0, tzinfo=UTC))
    assert reset.astimezone(UTC) == datetime(2026, 1, 10, 22, 0, tzinfo=UTC)
