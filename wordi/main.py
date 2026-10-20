"""Application factory. Run with: uvicorn wordi.main:create_app --factory"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import Settings
from .db import make_engine, make_session_factory
from .game import Clock, GameError, GameService, utc_now
from .ratelimit import RateLimitMiddleware
from .vectors import VectorModel
from .words import DailyCalendar, load_secret_words

log = logging.getLogger("wordi")


def create_app(
    settings: Settings | None = None,
    *,
    model: VectorModel | None = None,
    secret_words: list[str] | None = None,
    clock: Clock = utc_now,
) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:  %(name)s - %(message)s")
    if model is None:
        if not settings.vectors_path.exists():
            raise SystemExit(
                f"Vector file not found: {settings.vectors_path}\n"
                "Run scripts/prepare_vectors.py (or scripts/make_demo_vectors.py for a quick demo)."
            )
        model = VectorModel.load(settings.vectors_path)
        loaded = model.load_neighbors(settings.neighbors_path)
        if loaded:
            log.info("Loaded precomputed neighbours for %d secret words", loaded)

    words = secret_words if secret_words is not None else load_secret_words(settings.secret_words_path)
    missing = [w for w in words if w not in model]
    if missing:
        log.warning("%d secret words are not in the vocabulary and were skipped: %s", len(missing), missing[:20])
    words = [w for w in words if w in model]

    calendar = DailyCalendar.create(words, settings.epoch, settings.daily_salt, settings.timezone)
    engine = make_engine(settings.db_url)

    app = FastAPI(title="Wordi", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)
    app.state.game = GameService(model, calendar, words, k=settings.neighbors_k)
    app.state.clock = clock

    @app.exception_handler(GameError)
    async def _game_error(_request: Request, exc: GameError) -> JSONResponse:
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)

    if settings.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware, trust_proxy=settings.trust_proxy)
    app.include_router(router)

    # Warm the neighbour cache for the puzzles people are about to play.
    today = calendar.today(clock())
    for n in (today - 1, today, today + 1):
        app.state.game.neighbors(calendar.word_for_puzzle(n))

    if settings.web_dir.exists():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
    return app
