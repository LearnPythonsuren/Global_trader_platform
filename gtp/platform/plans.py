"""Subscription plans you sell to traders and algo developers.

Each plan sets rate limits and the features it unlocks. Prices are only
placeholders. Set them from your own Global Datafeeds costs and margins.
"""

from __future__ import annotations

from dataclasses import dataclass

# Feature flags checked by the API layer.
QUOTES = "quotes"              # last quote, multi-quote, search
HISTORY = "history"            # OHLC history + indicators
NEWS = "news"                  # company, multi and general news + sentiment
MUTUAL_FUNDS = "mutual_funds"  # NAV, returns, holdings, overlap
FUNDAMENTALS = "fundamentals"  # ratios, results, shareholding, corporate data
COMPANY_360 = "company_360"    # composite view across all four APIs
SCREENER = "screener"
OPTIONS = "options"            # option chain + PCR / max pain
BACKTEST = "backtest"
STREAM = "stream"              # real-time news stream (server-sent events)
RAW = "raw"                    # pass-through to any documented GDF function


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price_inr_month: int
    requests_per_minute: int
    requests_per_day: int
    features: frozenset[str]
    max_symbols_per_request: int
    history_max_bars: int
    description: str


PLANS: dict[str, Plan] = {
    p.id: p for p in (
        Plan("free", "Starter", 0, 30, 1_000,
             frozenset({QUOTES, HISTORY, NEWS, MUTUAL_FUNDS}), 5, 500,
             "Quotes, charts, news and mutual fund NAVs for personal use."),
        Plan("pro", "Trader Pro", 1_499, 120, 20_000,
             frozenset({QUOTES, HISTORY, NEWS, MUTUAL_FUNDS, FUNDAMENTALS, COMPANY_360, SCREENER, OPTIONS}), 25, 5_000,
             "Adds fundamentals, Company 360, the screener and option-chain analytics."),
        Plan("algo", "Algo Developer", 4_999, 600, 250_000,
             frozenset({QUOTES, HISTORY, NEWS, MUTUAL_FUNDS, FUNDAMENTALS, COMPANY_360, SCREENER, OPTIONS,
                        BACKTEST, STREAM, RAW}), 100, 50_000,
             "Everything, plus backtesting, the real-time news stream and raw GDF pass-through."),
    )
}


def get_plan(plan_id: str) -> Plan:
    try:
        return PLANS[plan_id]
    except KeyError:
        raise ValueError(f"Unknown plan {plan_id!r}; choose from {', '.join(PLANS)}") from None


def public_catalog() -> list[dict]:
    return [{
        "id": p.id, "name": p.name, "price_inr_month": p.price_inr_month, "description": p.description,
        "requests_per_minute": p.requests_per_minute, "requests_per_day": p.requests_per_day,
        "max_symbols_per_request": p.max_symbols_per_request, "history_max_bars": p.history_max_bars,
        "features": sorted(p.features),
    } for p in PLANS.values()]
