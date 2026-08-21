"""Search-provider adapters.

Finding candidate pages is done through a search API rather than by crawling a site's own
search form: it is faster, it is what the APIs exist for, and it keeps us off pages that
site owners would rather we left alone.

With `SEARCH_PROVIDER=none` (the default) discovery is disabled and the pricing services
report their data as unavailable. That is the correct behaviour for an unconfigured system —
the alternative would be inventing results.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str = ""

    @property
    def host(self) -> str:
        return urlparse(self.url).netloc.lower().removeprefix("www.")


class SearchProvider(ABC):
    name = "none"

    @abstractmethod
    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...

    def is_configured(self) -> bool:
        return False


class NullSearchProvider(SearchProvider):
    """No discovery configured. Returns nothing rather than pretending."""

    name = "none"

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        log.info("search.disabled", query=query[:120])
        return []


class SerperProvider(SearchProvider):
    name = "serper"

    def is_configured(self) -> bool:
        return bool(settings.serper_api_key)

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        if not self.is_configured():
            return []
        try:
            with httpx.Client(timeout=settings.scraper_timeout_seconds) as client:
                response = client.post(
                    "https://google.serper.dev/search",
                    headers={
                        "X-API-KEY": settings.serper_api_key,
                        "Content-Type": "application/json",
                    },
                    json={"q": query, "num": limit, "gl": settings.market_country.lower()},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("search.serper_failed", error=str(exc))
            return []

        payload = response.json()
        return [
            SearchHit(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            )
            for item in payload.get("organic", [])[:limit]
            if item.get("link")
        ]


class TavilyProvider(SearchProvider):
    name = "tavily"

    def is_configured(self) -> bool:
        return bool(settings.tavily_api_key)

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        if not self.is_configured():
            return []
        try:
            with httpx.Client(timeout=settings.scraper_timeout_seconds) as client:
                response = client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": settings.tavily_api_key,
                        "query": query,
                        "max_results": limit,
                        "search_depth": "basic",
                    },
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("search.tavily_failed", error=str(exc))
            return []

        payload = response.json()
        return [
            SearchHit(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", "")[:400],
            )
            for item in payload.get("results", [])[:limit]
            if item.get("url")
        ]


class BraveProvider(SearchProvider):
    name = "brave"

    def is_configured(self) -> bool:
        return bool(settings.brave_api_key)

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        if not self.is_configured():
            return []
        try:
            with httpx.Client(timeout=settings.scraper_timeout_seconds) as client:
                response = client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={
                        "X-Subscription-Token": settings.brave_api_key,
                        "Accept": "application/json",
                    },
                    params={"q": query, "count": limit, "country": settings.market_country},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("search.brave_failed", error=str(exc))
            return []

        payload = response.json()
        return [
            SearchHit(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
            )
            for item in payload.get("web", {}).get("results", [])[:limit]
            if item.get("url")
        ]


_PROVIDERS: dict[str, type[SearchProvider]] = {
    "serper": SerperProvider,
    "tavily": TavilyProvider,
    "brave": BraveProvider,
    "none": NullSearchProvider,
}


def get_search_provider() -> SearchProvider:
    provider = _PROVIDERS.get(settings.search_provider, NullSearchProvider)()
    if not provider.is_configured() and provider.name != "none":
        log.warning("search.provider_unconfigured", provider=provider.name)
        return NullSearchProvider()
    return provider
