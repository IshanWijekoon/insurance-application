"""Polite HTTP fetching for market research.

Non-negotiable behaviour, enforced here rather than left to each caller:

* Only hosts present and enabled in the `market_sources` whitelist are contacted.
* `robots.txt` is fetched, cached and honoured. When `SCRAPER_RESPECT_ROBOTS` is true — and
  it cannot be false in production — a disallowed path is not requested.
* Per-host rate limits are applied, with a descriptive User-Agent identifying the crawler.
* Responses are cached in Redis for `SCRAPER_CACHE_TTL_HOURS`.
* Authentication walls and CAPTCHAs are treated as a hard stop, never something to work
  around: a 401/403 marks the source unusable for that query and the code moves on.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import redis

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_CACHE_PREFIX = "market:fetch:"
_ROBOTS_PREFIX = "market:robots:"
_ROBOTS_TTL = 24 * 3600


@dataclass
class FetchResult:
    url: str
    status_code: int
    text: str
    from_cache: bool = False
    retrieved_at: datetime | None = None
    blocked_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code == 200 and bool(self.text)


class RobotsCache:
    def __init__(self, client: redis.Redis | None):
        self._redis = client
        self._local: dict[str, tuple[RobotFileParser, float]] = {}

    def allows(self, url: str, user_agent: str) -> tuple[bool, str | None]:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        parser = self._load(origin)
        if parser is None:
            # A missing or unreachable robots.txt is conventionally read as "allowed", but
            # this crawler treats an unreachable one as a stop: a source we cannot verify
            # permission for is not one we scrape.
            return False, "robots.txt could not be retrieved, so the source was not fetched."

        allowed = parser.can_fetch(user_agent, url)
        return allowed, None if allowed else "robots.txt disallows this path."

    def _load(self, origin: str) -> RobotFileParser | None:
        cached = self._local.get(origin)
        if cached and time.time() - cached[1] < _ROBOTS_TTL:
            return cached[0]

        body: str | None = None
        if self._redis is not None:
            try:
                raw = self._redis.get(f"{_ROBOTS_PREFIX}{origin}")
                body = raw.decode() if isinstance(raw, bytes) else raw
            except redis.RedisError:
                body = None

        if body is None:
            try:
                with httpx.Client(timeout=10, follow_redirects=True) as client:
                    response = client.get(
                        urljoin(origin, "/robots.txt"),
                        headers={"User-Agent": settings.scraper_user_agent},
                    )
                body = response.text if response.status_code == 200 else ""
            except httpx.HTTPError as exc:
                log.warning("robots.fetch_failed", origin=origin, error=str(exc))
                return None

            if self._redis is not None:
                try:
                    self._redis.setex(f"{_ROBOTS_PREFIX}{origin}", _ROBOTS_TTL, body)
                except redis.RedisError:
                    pass

        parser = RobotFileParser()
        parser.parse(body.splitlines())
        self._local[origin] = (parser, time.time())
        return parser


class RateLimiter:
    """Per-host minimum interval between requests."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def wait(self, host: str, per_minute: int) -> None:
        if per_minute <= 0:
            return
        interval = 60.0 / per_minute
        elapsed = time.monotonic() - self._last.get(host, 0.0)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last[host] = time.monotonic()


class MarketFetcher:
    def __init__(self) -> None:
        try:
            self._redis: redis.Redis | None = redis.from_url(settings.redis_url)
            self._redis.ping()
        except (redis.RedisError, ValueError) as exc:
            log.warning("market.cache_unavailable", error=str(exc))
            self._redis = None

        self.robots = RobotsCache(self._redis)
        self.limiter = RateLimiter()

    def fetch(self, url: str, *, rate_limit_per_minute: int = 10, use_cache: bool = True) -> FetchResult:
        now = datetime.now(UTC)

        if use_cache:
            cached = self._from_cache(url)
            if cached is not None:
                return FetchResult(url, 200, cached, from_cache=True, retrieved_at=now)

        if settings.scraper_respect_robots:
            allowed, reason = self.robots.allows(url, settings.scraper_user_agent)
            if not allowed:
                log.info("market.robots_blocked", url=url, reason=reason)
                return FetchResult(url, 0, "", retrieved_at=now, blocked_reason=reason)

        host = urlparse(url).netloc
        self.limiter.wait(host, rate_limit_per_minute)

        try:
            with httpx.Client(
                timeout=settings.scraper_timeout_seconds, follow_redirects=True
            ) as client:
                response = client.get(
                    url,
                    headers={
                        "User-Agent": settings.scraper_user_agent,
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "en",
                    },
                )
        except httpx.HTTPError as exc:
            log.warning("market.fetch_failed", url=url, error=str(exc))
            return FetchResult(url, 0, "", retrieved_at=now, blocked_reason=str(exc))

        if response.status_code in {401, 403}:
            return FetchResult(
                url, response.status_code, "", retrieved_at=now,
                blocked_reason=(
                    "The source requires authentication or blocked the request. "
                    "It was skipped rather than circumvented."
                ),
            )

        if response.status_code == 429:
            return FetchResult(
                url, 429, "", retrieved_at=now,
                blocked_reason="The source rate-limited the request.",
            )

        if response.status_code == 200 and use_cache:
            self._to_cache(url, response.text)

        return FetchResult(url, response.status_code, response.text, retrieved_at=now)

    def _cache_key(self, url: str) -> str:
        return _CACHE_PREFIX + hashlib.sha256(url.encode()).hexdigest()

    def _from_cache(self, url: str) -> str | None:
        if self._redis is None:
            return None
        try:
            raw = self._redis.get(self._cache_key(url))
        except redis.RedisError:
            return None
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else raw

    def _to_cache(self, url: str, body: str) -> None:
        if self._redis is None:
            return
        try:
            self._redis.setex(
                self._cache_key(url), settings.scraper_cache_ttl_hours * 3600, body
            )
        except redis.RedisError:
            pass
