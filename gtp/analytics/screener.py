"""Stock screener that combines GDF fundamentals with technicals from price history.

A screen is a list of filters such as ``{"field": "pe", "op": "<", "value": 25}``
plus an optional sort. Fields come from the fundamental ratios (pe, pb, eps,
market_cap, ...) and from the technical snapshot (rsi14, trend, change_1m_pct, ...).
"""

from __future__ import annotations

import operator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable

from . import indicators as ta

OPS = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
    "==": operator.eq, "!=": operator.ne,
    "in": lambda a, b: a in b,
    "between": lambda a, b: b[0] <= a <= b[1],
}

FUNDAMENTAL_FIELDS = ("pe", "pb", "eps", "market_cap", "book_value", "dividend_yield", "debt",
                      "interest_coverage", "price_sales", "enterprise_value", "profit_after_tax")
TECHNICAL_FIELDS = ("close", "rsi14", "sma50", "sma200", "above_sma200", "trend", "change_1w_pct",
                    "change_1m_pct", "change_3m_pct", "change_1y_pct", "pct_from_52w_high",
                    "volatility_1y_pct", "atr14")
OTHER_FIELDS = ("symbol", "sector", "industry", "company")
FIELDS = FUNDAMENTAL_FIELDS + TECHNICAL_FIELDS + OTHER_FIELDS

PRESETS: dict[str, dict[str, Any]] = {
    "value": {
        "description": "Cheap on earnings and book, with low debt",
        "filters": [{"field": "pe", "op": "<", "value": 25}, {"field": "pb", "op": "<", "value": 5}],
        "sort": "pe",
    },
    "momentum": {
        "description": "In an uptrend and outperforming over 3 months",
        "filters": [{"field": "above_sma200", "op": "==", "value": True},
                    {"field": "change_3m_pct", "op": ">", "value": 0}],
        "sort": "-change_3m_pct",
    },
    "oversold_quality": {
        "description": "RSI below 40 with interest coverage above 5",
        "filters": [{"field": "rsi14", "op": "<", "value": 40},
                    {"field": "interest_coverage", "op": ">", "value": 5}],
        "sort": "rsi14",
    },
    "near_52w_high": {
        "description": "Within 5% of the 52-week high",
        "filters": [{"field": "pct_from_52w_high", "op": ">=", "value": -5}],
        "sort": "-pct_from_52w_high",
    },
}


def build_row(hub: Any, symbol: str, price_exchange: str = "NSE", fundamental_exchange: str = "BSE") -> dict:
    """Collect every screenable field for one symbol, tolerating missing data."""
    row: dict[str, Any] = {"symbol": symbol, "errors": []}
    try:
        candles = hub.price.history(price_exchange, symbol, "DAY", max_bars=300)
        row.update(ta.snapshot(candles))
    except Exception as e:  # noqa: BLE001 - one bad symbol must not break the screen
        row["errors"].append(f"price: {e}")
    try:
        ratios = hub.fundamentals.ratios(fundamental_exchange, symbol)
        row.update({k: ratios.get(k) for k in FUNDAMENTAL_FIELDS})
    except Exception as e:  # noqa: BLE001
        row["errors"].append(f"fundamentals: {e}")
    try:
        sec = hub.fundamentals.sector(fundamental_exchange, symbol)
        row["sector"] = sec.get("Sector")
        row["industry"] = sec.get("Industry")
    except Exception as e:  # noqa: BLE001
        row["errors"].append(f"sector: {e}")
    return row


def matches(row: dict, filters: Iterable[dict]) -> bool:
    for f in filters:
        field, op, value = f["field"], f.get("op", "=="), f.get("value")
        if field not in FIELDS:
            raise ValueError(f"Unknown field {field!r}")
        if op not in OPS:
            raise ValueError(f"Unknown operator {op!r}; use one of {', '.join(OPS)}")
        actual = row.get(field)
        if actual is None:
            return False
        if isinstance(actual, str) and isinstance(value, str):
            actual, value = actual.lower(), value.lower()
        try:
            if not OPS[op](actual, value):
                return False
        except TypeError:
            return False
    return True


def screen(
    hub: Any,
    universe: Iterable[str],
    filters: list[dict],
    *,
    sort: str | None = None,
    limit: int = 50,
    workers: int = 8,
    price_exchange: str = "NSE",
    fundamental_exchange: str = "BSE",
) -> dict:
    universe = list(dict.fromkeys(s.strip().upper() for s in universe if s.strip()))
    for f in filters:  # validate before doing any network work
        if f["field"] not in FIELDS:
            raise ValueError(f"Unknown field {f['field']!r}")
        if f.get("op", "==") not in OPS:
            raise ValueError(f"Unknown operator {f.get('op')!r}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(lambda s: build_row(hub, s, price_exchange, fundamental_exchange), universe))
    hits = [r for r in rows if matches(r, filters)]
    if sort:
        desc = sort.startswith("-")
        key = sort.lstrip("-+")
        if key not in FIELDS:
            raise ValueError(f"Unknown sort field {key!r}")
        present = [r for r in hits if r.get(key) is not None]
        missing = [r for r in hits if r.get(key) is None]
        hits = sorted(present, key=lambda r: r[key], reverse=desc) + missing
    return {
        "universe_size": len(universe),
        "matched": len(hits),
        "results": hits[:limit],
        "failed": [{"symbol": r["symbol"], "errors": r["errors"]} for r in rows if r["errors"]],
    }
