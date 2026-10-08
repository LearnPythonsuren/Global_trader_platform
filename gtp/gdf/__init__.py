"""Clients for the Global Datafeeds APIs, plus offline demo providers."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from .base import GDFAuthError, GDFError, GDFNotConfigured
from .fundamentals import FundamentalsClient
from .mutualfunds import MutualFundClient
from .news import NewsClient
from .price import PriceClient

__all__ = [
    "DataHub", "GDFError", "GDFAuthError", "GDFNotConfigured",
    "PriceClient", "FundamentalsClient", "MutualFundClient", "NewsClient",
]

# Seconds to cache each method's result. Caching cuts the calls you make to
# GDF, which matters when many of your customers ask for the same data.
TTL = {
    "last_quote": 2, "last_quotes": 2, "history": 60, "option_chain": 3, "top_gainers_losers": 15,
    "search_instruments": 3600, "exchanges": 86400,
    "company": 86400, "ratios": 6 * 3600, "sector": 86400, "shareholding": 86400,
    "financial_results": 6 * 3600, "announcements": 300, "corporate_actions": 3600,
    "results_calendar": 3600, "bulk_deals": 3600, "block_deals": 3600, "fii_dii": 3600,
    "amcs": 86400, "schemes": 86400, "categories": 86400, "nav": 3600, "nav_on": 86400,
    "aum": 3600, "holdings": 86400, "holdings_what_changed": 86400, "new_fund_offers": 3600,
    "company_news": 60, "multi_company_news": 60, "general_news": 60,
}


class Cached:
    """Wraps a provider and memoises its methods for the TTLs above."""

    def __init__(self, inner: Any, ttl: dict[str, float] | None = None, max_entries: int = 20_000):
        self._inner = inner
        self._ttl = TTL if ttl is None else ttl
        self._store: dict[tuple, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._max = max_entries

    @property
    def inner(self) -> Any:
        return self._inner

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        ttl = self._ttl.get(name)
        if not callable(attr) or not ttl:
            return attr

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = (name, _freeze(args), _freeze(kwargs))
            now = time.monotonic()
            with self._lock:
                hit = self._store.get(key)
                if hit and hit[0] > now:
                    return hit[1]
            value = attr(*args, **kwargs)
            with self._lock:
                if len(self._store) >= self._max:
                    self._store = {k: v for k, v in self._store.items() if v[0] > now}
                    if len(self._store) >= self._max:
                        self._store.clear()
                self._store[key] = (now + ttl, value)
            return value

        return wrapper

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


def _freeze(v: Any) -> Any:
    if isinstance(v, dict):
        return tuple(sorted((k, _freeze(x)) for k, x in v.items()))
    if isinstance(v, (list, tuple, set)):
        return tuple(_freeze(x) for x in v)
    return v


@dataclass
class DataHub:
    """One object holding the four data providers the platform uses."""

    price: Any
    fundamentals: Any
    mutual_funds: Any
    news: Any
    demo: bool

    @classmethod
    def from_settings(cls, s: Settings, *, cache: bool = True) -> "DataHub":
        if s.demo:
            from .demo import DemoFundamentals, DemoMutualFunds, DemoNews, DemoPrice
            providers = [DemoPrice(), DemoFundamentals(), DemoMutualFunds(), DemoNews()]
        else:
            kw = {"timeout": s.http_timeout, "retries": s.diagnostic_retries}
            providers = [
                PriceClient(s.price_base_url, s.price_access_key, **kw),
                FundamentalsClient(s.fundamental_base_url, s.fundamental_access_key, **kw),
                MutualFundClient(s.mf_base_url, s.mf_access_key, **kw),
                NewsClient(s.news_base_url, s.news_api_key, **kw),
            ]
        if cache:
            providers = [Cached(p) for p in providers]
        return cls(*providers, demo=s.demo)
