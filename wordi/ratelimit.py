"""In-memory sliding-window rate limiting (per client IP and route bucket)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

# (path prefix, method or None for any, bucket, max requests per window); first match wins.
RULES: list[tuple[str, str | None, str, int]] = [
    ("/api/guess", "POST", "guess", 90),
    ("/api/hint", None, "hint", 20),
    ("/api/free/new", "POST", "new", 20),
    ("/api/leaderboard", "POST", "submit", 6),
    ("/api/", None, "api", 240),
]
WINDOW_SECONDS = 60.0


class SlidingWindowLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._clock = clock

    def allow(self, key: str, bucket: str, limit: int, window: float = WINDOW_SECONDS) -> bool:
        now = self._clock()
        hits = self._hits[(key, bucket)]
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        if len(self._hits) > 50_000:  # crude memory bound
            self._hits = defaultdict(deque, {k: v for k, v in self._hits.items() if v})
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, trust_proxy: bool = False) -> None:
        super().__init__(app)
        self.limiter = SlidingWindowLimiter()
        self.trust_proxy = trust_proxy

    def _client_ip(self, request: Request) -> str:
        if self.trust_proxy:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        for prefix, method, bucket, limit in RULES:
            if path.startswith(prefix) and (method is None or method == request.method):
                if not self.limiter.allow(self._client_ip(request), bucket, limit):
                    return JSONResponse(
                        {"error": "rate_limited", "message": "יותר מדי בקשות. חכו רגע ונסו שוב."},
                        status_code=429,
                        headers={"Retry-After": str(int(WINDOW_SECONDS))},
                    )
                break
        return await call_next(request)
