from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from wordi.config import Settings
from wordi.db import make_engine
from wordi.main import create_app
from wordi.models import Base
from wordi.vectors import VectorModel

SECRETS = ["כלב", "חתול", "שולחן", "ים"]


def make_model(n_filler: int = 1500, dim: int = 16, seed: int = 0) -> VectorModel:
    """Secrets + 'filler' words + a few hand-placed words with known geometry around כלב."""
    rng = np.random.default_rng(seed)
    words = [*SECRETS, "גור", "הגור", "ביתי"]
    vecs = [rng.normal(size=dim) for _ in SECRETS]
    dog = vecs[0]
    vecs += [
        dog + rng.normal(scale=0.05, size=dim),
        dog + rng.normal(scale=0.3, size=dim),
        dog + rng.normal(scale=0.8, size=dim),
    ]
    letters = "אבגדזחטיכלמנסעפצקרשת"
    for i in range(n_filler):
        words.append("".join(letters[(i // 20**j) % 20] for j in range(3)) + "ן")
        vecs.append(rng.normal(size=dim))
    return VectorModel(words, np.vstack(vecs))


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def model() -> VectorModel:
    return make_model()


@pytest.fixture
def clock() -> FakeClock:
    # 2026-03-10 12:00 Israel time
    return FakeClock(datetime(2026, 3, 10, 10, 0, tzinfo=UTC))


# Set WORDI_TEST_DB_URL (e.g. postgresql://user@host/db) to run the suite against Postgres.
# The database's tables are dropped before and after every test.
TEST_DB_URL = os.environ.get("WORDI_TEST_DB_URL")


@pytest.fixture
def db_url(tmp_path) -> Iterator[str]:
    if not TEST_DB_URL:
        yield f"sqlite:///{tmp_path / 'test.db'}"
        return
    engine = make_engine(TEST_DB_URL)
    Base.metadata.drop_all(engine)
    yield TEST_DB_URL
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def app_factory(model: VectorModel, clock: FakeClock, tmp_path, db_url: str) -> Callable[..., TestClient]:
    def build(rate_limit: bool = False) -> TestClient:
        settings = Settings(
            db_url=db_url,
            web_dir=tmp_path / "no-web",
            epoch=date(2026, 1, 1),
            rate_limit_enabled=rate_limit,
        )
        return TestClient(create_app(settings, model=model, secret_words=list(SECRETS), clock=clock))

    return build


@pytest.fixture
def client(app_factory) -> TestClient:
    return app_factory()


def player_headers(pid: str = "11111111-1111-4111-8111-111111111111") -> dict[str, str]:
    return {"X-Player-Id": pid}
