"""Composite views that combine all four Global Datafeeds APIs into one answer.

These are the product's main features. One call returns what a trader would
otherwise piece together from several screens. Each section is fetched on
its own, so a section the customer's GDF subscription doesn't cover comes
back with an ``error`` and the rest of the view still works.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .analytics import indicators as ta
from .analytics import sentiment

DAY = 86400


def _section(fn: Callable[[], Any]) -> dict:
    try:
        return {"data": fn()}
    except Exception as e:  # noqa: BLE001 - surface per-section failures to the caller
        return {"error": f"{type(e).__name__}: {e}"}


def company_360(hub: Any, symbol: str, *, price_exchange: str = "NSE", fundamental_exchange: str = "BSE",
                news_limit: int = 15) -> dict:
    symbol = symbol.strip().upper()
    now = int(time.time())
    tasks: dict[str, Callable[[], Any]] = {
        "quote": lambda: hub.price.last_quote(price_exchange, symbol),
        "technicals": lambda: ta.snapshot(hub.price.history(price_exchange, symbol, "DAY", max_bars=300)),
        "profile": lambda: hub.fundamentals.company(fundamental_exchange, symbol),
        "sector": lambda: hub.fundamentals.sector(fundamental_exchange, symbol),
        "ratios": lambda: hub.fundamentals.ratios(fundamental_exchange, symbol),
        "shareholding": lambda: hub.fundamentals.shareholding(fundamental_exchange, symbol),
        "announcements": lambda: hub.fundamentals.announcements(fundamental_exchange, symbol, now - 30 * DAY, now)[:10],
        "corporate_actions": lambda: hub.fundamentals.corporate_actions(fundamental_exchange, symbol, now - 365 * DAY, now),
        "news": lambda: hub.news.company_news(symbol, limit=news_limit),
    }
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {k: pool.submit(_section, fn) for k, fn in tasks.items()}
        out = {k: f.result() for k, f in futures.items()}

    news = out["news"].get("data") or []
    out["news_sentiment"] = {"data": sentiment.score(news)} if "data" in out["news"] else out["news"]
    out["signals"] = {"data": _signals(out)}
    return {"symbol": symbol, "generated_at": now, "demo": hub.demo, "sections": out}


def _signals(sections: dict) -> list[dict]:
    """Plain-English flags drawn from the other sections."""
    flags: list[dict] = []
    tech = sections["technicals"].get("data") or {}
    ratios = sections["ratios"].get("data") or {}
    senti = (sections.get("news_sentiment") or {}).get("data") or {}
    if tech.get("rsi14") is not None:
        if tech["rsi14"] < 30:
            flags.append({"type": "technical", "tone": "bullish", "text": f"RSI(14) {tech['rsi14']} is oversold"})
        elif tech["rsi14"] > 70:
            flags.append({"type": "technical", "tone": "bearish", "text": f"RSI(14) {tech['rsi14']} is overbought"})
    if tech.get("trend") in ("uptrend", "downtrend"):
        flags.append({"type": "technical", "tone": "bullish" if tech["trend"] == "uptrend" else "bearish",
                      "text": f"Price is in a {tech['trend']} (close vs 50/200-day SMA)"})
    if tech.get("pct_from_52w_high") is not None and tech["pct_from_52w_high"] > -3:
        flags.append({"type": "technical", "tone": "bullish", "text": "Trading within 3% of its 52-week high"})
    pe = ratios.get("pe")
    if pe is not None:
        if pe < 15:
            flags.append({"type": "fundamental", "tone": "bullish", "text": f"Low P/E of {pe:.1f}"})
        elif pe > 60:
            flags.append({"type": "fundamental", "tone": "bearish", "text": f"Rich P/E of {pe:.1f}"})
    if ratios.get("debt") == 0:
        flags.append({"type": "fundamental", "tone": "bullish", "text": "Debt-free on the latest filing"})
    if senti.get("articles"):
        tone = {"bullish": "bullish", "bearish": "bearish"}.get(senti["label"], "neutral")
        flags.append({"type": "news", "tone": tone,
                      "text": f"News flow is {senti['label']} ({senti['positive']} positive / "
                              f"{senti['negative']} negative of {senti['articles']})"})
    return flags


def market_pulse(hub: Any, *, index_exchange: str = "NSE_IDX", indices: tuple[str, ...] = ("NIFTY 50", "NIFTY BANK"),
                 equity_exchange: str = "NSE", watchlist: list[str] | None = None) -> dict:
    tasks: dict[str, Callable[[], Any]] = {
        "indices": lambda: hub.price.last_quotes(index_exchange, list(indices)),
        "general_news": lambda: hub.news.general_news(limit=10),
    }
    if watchlist:
        tasks["watchlist"] = lambda: hub.price.last_quotes(equity_exchange, watchlist)
        tasks["watchlist_news"] = lambda: sentiment.by_symbol(hub.news.multi_company_news(watchlist, limit=100))
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {k: pool.submit(_section, fn) for k, fn in tasks.items()}
        out = {k: f.result() for k, f in futures.items()}
    if "data" in out.get("watchlist", {}):
        qs = sorted((q for q in out["watchlist"]["data"] if q.get("change_pct") is not None),
                    key=lambda q: q["change_pct"])
        out["movers"] = {"data": {"gainers": qs[::-1][:5], "losers": qs[:5]}}
    if "data" in out["general_news"]:
        out["market_sentiment"] = {"data": sentiment.score(out["general_news"]["data"])}
    return {"generated_at": int(time.time()), "demo": hub.demo, "sections": out}


def option_chain_summary(rows: list[dict]) -> dict:
    """Put-call ratio, max-pain strike and the strikes with the highest OI."""
    calls = [r for r in rows if r.get("option_type") == "CE" and r.get("strike") is not None]
    puts = [r for r in rows if r.get("option_type") == "PE" and r.get("strike") is not None]
    call_oi = sum(r.get("open_interest") or 0 for r in calls)
    put_oi = sum(r.get("open_interest") or 0 for r in puts)
    strikes = sorted({r["strike"] for r in calls + puts})
    max_pain, best = None, None
    for k in strikes:
        pain = sum(max(0.0, k - c["strike"]) * (c.get("open_interest") or 0) for c in calls) + \
               sum(max(0.0, p["strike"] - k) * (p.get("open_interest") or 0) for p in puts)
        if best is None or pain < best:
            max_pain, best = k, pain
    top = lambda xs: sorted(xs, key=lambda r: -(r.get("open_interest") or 0))[:3]  # noqa: E731
    return {
        "pcr_oi": round(put_oi / call_oi, 3) if call_oi else None,
        "total_call_oi": call_oi, "total_put_oi": put_oi, "max_pain": max_pain,
        "resistance": [r["strike"] for r in top(calls)],
        "support": [r["strike"] for r in top(puts)],
    }
