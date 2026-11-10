"""Composite views that combine all four Global Datafeeds APIs into one answer.

These are the product's main features. One call returns what a trader would
otherwise piece together from several screens. Each section is fetched on
its own, so a section the customer's GDF subscription doesn't cover comes
back with an ``error`` and the rest of the view still works.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable

from .analytics import indicators as ta
from .analytics import sentiment

DAY = 86400


def _section(fn: Callable[[], Any]) -> dict:
    try:
        return {"data": fn()}
    except Exception as e:  # noqa: BLE001 - surface per-section failures to the caller
        return {"error": f"{type(e).__name__}: {e}"}


def _gather(tasks: dict[str, Callable[[], Any]]) -> dict[str, dict]:
    with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
        futures = {k: pool.submit(_section, fn) for k, fn in tasks.items()}
        return {k: f.result() for k, f in futures.items()}


def company_360(hub: Any, symbol: str, *, price_exchange: str = "NSE", fundamental_exchange: str = "BSE",
                news_limit: int = 15) -> dict:
    symbol = symbol.strip().upper()
    now = int(time.time())
    out = _gather({
        "quote": lambda: hub.price.last_quote(price_exchange, symbol),
        "technicals": lambda: ta.snapshot(hub.price.history(price_exchange, symbol, "DAY", max_bars=300)),
        "profile": lambda: hub.fundamentals.company(fundamental_exchange, symbol),
        "sector": lambda: hub.fundamentals.sector(fundamental_exchange, symbol),
        "ratios": lambda: hub.fundamentals.ratios(fundamental_exchange, symbol),
        "shareholding": lambda: hub.fundamentals.shareholding(fundamental_exchange, symbol),
        "announcements": lambda: hub.fundamentals.announcements(fundamental_exchange, symbol, now - 30 * DAY, now)[:10],
        "corporate_actions": lambda: hub.fundamentals.corporate_actions(fundamental_exchange, symbol, now - 365 * DAY, now)[:10],
        "news": lambda: hub.news.company_news(symbol, limit=news_limit),
    })
    out["news_sentiment"] = {"data": sentiment.score(out["news"]["data"] or [])} if "data" in out["news"] else out["news"]
    signals = _signals(out)
    out["signals"] = {"data": signals}
    out["signal_balance"] = {"data": signal_balance(signals)}
    return {"symbol": symbol, "generated_at": now, "demo": hub.demo, "sections": out}


def _signals(sections: dict) -> list[dict]:
    """Plain-English observations drawn from the other sections. They describe, they do not advise."""
    flags: list[dict] = []

    def add(kind: str, tone: str, text: str) -> None:
        flags.append({"type": kind, "tone": tone, "text": text})

    tech = sections["technicals"].get("data") or {}
    ratios = sections["ratios"].get("data") or {}
    senti = (sections.get("news_sentiment") or {}).get("data") or {}

    rsi = tech.get("rsi14")
    if rsi is not None:
        if rsi < 30:
            add("technical", "bullish", f"RSI(14) at {rsi:.0f} is in oversold territory")
        elif rsi > 70:
            add("technical", "bearish", f"RSI(14) at {rsi:.0f} is in overbought territory")
    if tech.get("trend") == "uptrend":
        add("technical", "bullish", "Price is above its 50-day average, which is above the 200-day average")
    elif tech.get("trend") == "downtrend":
        add("technical", "bearish", "Price is below its 50-day average, which is below the 200-day average")
    if tech.get("macd_hist") is not None and tech.get("close"):
        if abs(tech["macd_hist"]) / tech["close"] > 0.002:
            add("technical", "bullish" if tech["macd_hist"] > 0 else "bearish",
                "MACD is above its signal line" if tech["macd_hist"] > 0 else "MACD is below its signal line")
    if tech.get("pct_from_52w_high") is not None and tech["pct_from_52w_high"] > -3:
        add("technical", "bullish", "Trading within 3% of its 52-week high")
    if tech.get("pct_from_52w_low") is not None and tech["pct_from_52w_low"] < 3:
        add("technical", "bearish", "Trading within 3% of its 52-week low")
    if tech.get("volume_ratio") is not None and tech["volume_ratio"] >= 1.8:
        add("technical", "neutral", f"Volume is {tech['volume_ratio']:.1f} times its 20-day average")

    pe = ratios.get("pe")
    if pe is not None and pe > 0:
        if pe < 15:
            add("fundamental", "bullish", f"Price-to-earnings of {pe:.1f} is low")
        elif pe > 60:
            add("fundamental", "bearish", f"Price-to-earnings of {pe:.1f} is high")
    if ratios.get("debt") == 0:
        add("fundamental", "bullish", "No debt on the latest filing")
    coverage = ratios.get("interest_coverage")
    if coverage is not None and 0 < coverage < 3 and ratios.get("debt"):
        add("fundamental", "bearish", f"Interest coverage of {coverage:.1f} is thin")
    if ratios.get("dividend_yield") is not None and ratios["dividend_yield"] >= 3:
        add("fundamental", "bullish", f"Dividend yield of {ratios['dividend_yield']:.1f}%")

    if senti.get("articles"):
        tone = {"bullish": "bullish", "bearish": "bearish"}.get(senti["label"], "neutral")
        add("news", tone, f"News flow is {senti['label']}: {senti['positive']} positive and "
                          f"{senti['negative']} negative of {senti['articles']} articles")
    return flags


def signal_balance(signals: Iterable[dict]) -> dict:
    """Count of bullish and bearish observations and a score from -1 (all bearish) to +1 (all bullish)."""
    signals = list(signals)
    bullish = sum(1 for s in signals if s["tone"] == "bullish")
    bearish = sum(1 for s in signals if s["tone"] == "bearish")
    decided = bullish + bearish
    score = round((bullish - bearish) / decided, 3) if decided else 0.0
    label = "no clear signals" if not decided else "mostly bullish" if score >= 0.34 else \
        "mostly bearish" if score <= -0.34 else "mixed"
    return {"bullish": bullish, "bearish": bearish, "neutral": len(signals) - decided, "score": score, "label": label}


def market_pulse(hub: Any, *, index_exchange: str = "NSE_IDX", indices: Iterable[str] = ("NIFTY 50", "NIFTY BANK"),
                 equity_exchange: str = "NSE", watchlist: list[str] | None = None, include_news: bool = True) -> dict:
    indices = list(indices)
    tasks: dict[str, Callable[[], Any]] = {"indices": lambda: hub.price.last_quotes(index_exchange, indices)}
    if include_news:
        tasks["general_news"] = lambda: hub.news.general_news(limit=10)
    if watchlist:
        tasks["watchlist"] = lambda: hub.price.last_quotes(equity_exchange, watchlist)
        if include_news:
            tasks["watchlist_news"] = lambda: sentiment.by_symbol(hub.news.multi_company_news(watchlist, limit=100))
    out = _gather(tasks)
    if "data" in out.get("watchlist", {}):
        quotes = sorted((q for q in out["watchlist"]["data"] if q.get("change_pct") is not None),
                        key=lambda q: q["change_pct"])
        out["movers"] = {"data": {"gainers": quotes[::-1][:5], "losers": quotes[:5]}}
    if "data" in out.get("general_news", {}):
        out["market_sentiment"] = {"data": sentiment.score(out["general_news"]["data"])}
    return {"generated_at": int(time.time()), "demo": hub.demo, "sections": out}


def market_heatmap(hub: Any, universe: Iterable[str], *, price_exchange: str = "NSE",
                   fundamental_exchange: str = "BSE", workers: int = 8) -> dict:
    """Every stock of the universe with its day change, sector and market value, plus sector and breadth totals."""
    universe = list(dict.fromkeys(s.strip().upper() for s in universe if s.strip()))
    quotes = {q["symbol"]: q for q in hub.price.last_quotes(price_exchange, universe) if q.get("symbol")}

    def describe(symbol: str) -> dict:
        info: dict[str, Any] = {"name": None, "sector": None, "industry": None, "market_cap": None}
        try:
            sector = hub.fundamentals.sector(fundamental_exchange, symbol)
            info.update(name=sector.get("name"), sector=sector.get("sector"), industry=sector.get("industry"))
        except Exception:  # noqa: BLE001 - fundamentals are optional for the map
            pass
        try:
            info["market_cap"] = hub.fundamentals.ratios(fundamental_exchange, symbol).get("market_cap")
        except Exception:  # noqa: BLE001
            pass
        return info

    with ThreadPoolExecutor(max_workers=workers) as pool:
        details = list(pool.map(describe, universe))

    stocks = []
    for symbol, info in zip(universe, details):
        q = quotes.get(symbol)
        if not q or q.get("ltp") is None:
            continue
        stocks.append({"symbol": symbol, **info, "sector": info["sector"] or "Other", "ltp": q["ltp"],
                       "change_pct": q.get("change_pct"), "volume": q.get("volume"), "value": q.get("value")})

    groups: dict[str, list[dict]] = {}
    for s in stocks:
        groups.setdefault(s["sector"], []).append(s)
    sectors = []
    for name, members in groups.items():
        priced = [m for m in members if m["change_pct"] is not None]
        weights = [m["market_cap"] or 0 for m in priced]
        if priced and sum(weights) > 0:
            change = sum(m["change_pct"] * w for m, w in zip(priced, weights)) / sum(weights)
        else:
            change = sum(m["change_pct"] for m in priced) / len(priced) if priced else None
        sectors.append({"sector": name, "stocks": len(members),
                        "market_cap": round(sum(m["market_cap"] or 0 for m in members), 2),
                        "change_pct": None if change is None else round(change, 2),
                        "advancers": sum(1 for m in priced if m["change_pct"] > 0),
                        "decliners": sum(1 for m in priced if m["change_pct"] < 0)})
    sectors.sort(key=lambda s: (s["change_pct"] is None, -(s["change_pct"] or 0)))
    changes = [s["change_pct"] for s in stocks if s["change_pct"] is not None]
    ranked = sorted((s for s in stocks if s["change_pct"] is not None), key=lambda s: s["change_pct"])
    return {
        "generated_at": int(time.time()), "demo": hub.demo, "stocks": stocks, "sectors": sectors,
        "breadth": {"advancers": sum(1 for c in changes if c > 0), "decliners": sum(1 for c in changes if c < 0),
                    "unchanged": sum(1 for c in changes if c == 0)},
        "gainers": ranked[::-1][:5], "losers": ranked[:5],
        "missing": [s for s in universe if s not in quotes],
    }


def sparklines(hub: Any, symbols: Iterable[str], *, exchange: str = "NSE", bars: int = 30, workers: int = 8) -> dict:
    """Recent daily closes per symbol, for small trend charts. Symbols without history are left out."""
    symbols = list(dict.fromkeys(symbols))

    def closes(symbol: str) -> list[float] | None:
        try:
            return [b["c"] for b in hub.price.history(exchange, symbol, "DAY", max_bars=bars)]
        except Exception:  # noqa: BLE001 - one bad symbol must not break the rest
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        series = list(pool.map(closes, symbols))
    return {s: c for s, c in zip(symbols, series) if c}


_QUARTERS = ["QJ", "QS", "QD", "QM"]                      # Indian fiscal year: April to March
_QUARTER_END = {"QJ": "Jun", "QS": "Sep", "QD": "Dec", "QM": "Mar"}
_REVENUE = (("RevenueFromOperations", "Revenue", "TotalIncome", "Income"),
            re.compile(r"revenue from operations|income from operations|total revenue|total income", re.I))
_PROFIT = (("ProfitLossForPeriod", "ProfitLossForThePeriod", "ProfitLoss", "NetProfit", "ProfitAfterTax"),
           re.compile(r"net profit|profit.*(for the period|after tax)", re.I))
_EPS = (("BasicEarningsLossPerShare", "BasicEarningsPerShare"), re.compile(r"basic.*earnings.*per share|basic eps", re.I))


def recent_quarters(now: float, count: int) -> list[tuple[int, str]]:
    """The last `count` completed quarters as (fiscal year, period code), newest first."""
    t = time.gmtime(now + 19800)
    fiscal_year = t.tm_year if t.tm_mon >= 4 else t.tm_year - 1
    i = ((t.tm_mon - 4) % 12) // 3
    out = []
    for _ in range(count):
        i -= 1
        if i < 0:
            i, fiscal_year = 3, fiscal_year - 1
        out.append((fiscal_year, _QUARTERS[i]))
    return out


def _pick(facts: list[dict], rule: tuple) -> float | None:
    keys, pattern = rule
    by_key = {f.get("key"): f.get("value") for f in facts if f.get("value") is not None}
    for key in keys:
        if key in by_key:
            return by_key[key]
    for f in facts:
        if f.get("value") is not None and f.get("label") and pattern.search(f["label"]):
            return f["value"]
    return None


def financial_trend(hub: Any, symbol: str, *, exchange: str = "BSE", quarters: int = 6,
                    nature: str = "Standalone") -> list[dict]:
    """Revenue, net profit and EPS for the last few reported quarters, oldest first."""
    symbol = symbol.strip().upper()

    def one(item: tuple[int, str]) -> dict | None:
        fiscal_year, period = item
        try:
            facts = hub.fundamentals.financial_results(exchange, symbol, fiscal_year, statement="ProfitLoss",
                                                       period=period, nature=nature)
        except LookupError:
            raise
        except Exception:  # noqa: BLE001 - a quarter that is not filed yet is simply skipped
            return None
        revenue, profit = _pick(facts, _REVENUE), _pick(facts, _PROFIT)
        if revenue is None and profit is None:
            return None
        year = fiscal_year + 1 if period == "QM" else fiscal_year
        return {"fiscal_year": fiscal_year, "period": period, "label": f"{_QUARTER_END[period]} {year}",
                "revenue": revenue, "net_profit": profit, "eps": _pick(facts, _EPS)}

    # One extra quarter is requested because the latest one may not be filed yet.
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = [r for r in pool.map(one, recent_quarters(time.time(), quarters + 1)) if r]
    return rows[:quarters][::-1]


EARNINGS_KINDS = {"transcript", "audio", "presentation", "results", "call"}

# Global Datafeeds has no dedicated earnings-call API: this material arrives through the
# fundamental API's GetCorporateAnnouncements. The platform auto-detects it from whatever
# that call returns by matching the exchange's own wording (headline, descriptor/category
# and the news body), newest signal first.
_EARNINGS_SIGNALS = (
    ("transcript", ("transcript", "con call transcript", "concall transcript", "earnings call transcript")),
    ("audio", ("audio recording", "audio of", "call recording", "recording of", "earnings call audio",
               "concall audio", "con. call audio", "audio file")),
    ("presentation", ("investor presentation", "analyst presentation", "earnings presentation",
                      "investor/analyst presentation", "presentation to investors", "investor deck")),
    ("results", ("financial results", "quarterly results", "audited results", "unaudited results",
                 "outcome of board meeting", "standalone and consolidated", "statement of results",
                 "board meeting outcome")),
    ("call", ("earnings call", "earnings conference call", "conference call", "con. call", "con call",
              "concall", "analyst meet", "investor meet", "institutional investor", "analysts/institutional",
              "earnings call intimation", "investor/analyst call", "investor call")),
)


def classify_earnings_doc(headline: str, category: str = "", body: str = "") -> str:
    """Decide what kind of earnings-call material an announcement is, from its own text.

    Works on whatever GetCorporateAnnouncements returns — the headline, the exchange
    descriptor/category, and the news body — so no special API option is needed.
    """
    low = f"{headline or ''} {category or ''} {body or ''}".lower()
    for kind, needles in _EARNINGS_SIGNALS:
        if any(n in low for n in needles):
            # "board meeting" that merely *schedules* results is still a results-related event.
            return kind
    if "board meeting" in low and ("result" in low or "financial" in low):
        return "results"
    return "other"


def earnings_calendar(hub: Any, *, exchange: str = "BSE", range_: str = "Next7days") -> dict:
    """Upcoming (or recent) earnings dates across the market, newest first."""
    rows = hub.fundamentals.results_calendar(exchange, range_) or []
    today = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 19800))
    for r in rows:
        d = (r.get("date") or "")[:10]
        r["upcoming"] = d >= today
    rows.sort(key=lambda r: (r.get("date") or ""))
    return {"range": range_, "exchange": exchange, "as_of": int(time.time()),
            "upcoming": [r for r in rows if r["upcoming"]], "recent": [r for r in rows if not r["upcoming"]]}


def earnings_overview(hub: Any, symbol: str, *, exchange: str = "BSE", days: int = 220) -> dict:
    """One company's next results date and its recent earnings-call documents."""
    symbol = symbol.strip().upper()
    now = int(time.time())
    out = _gather({
        "upcoming": lambda: hub.fundamentals.results_calendar(exchange, "Next30days", [symbol]),
        "announcements": lambda: hub.fundamentals.announcements(exchange, symbol, now - days * DAY, now),
    })
    docs, seen = [], set()
    for a in (out["announcements"].get("data") or []):
        kind = classify_earnings_doc(a.get("headline", ""), a.get("category", ""), a.get("body", ""))
        if kind == "other":
            continue
        key = (a.get("url"), a.get("headline"))
        if key in seen:
            continue
        seen.add(key)
        docs.append({
            "date": a.get("date"), "headline": a.get("headline"), "category": a.get("category"),
            "url": a.get("url"), "kind": kind, "is_audio": kind == "audio",
            "readable": bool(a.get("url")),           # any attached filing can be opened (PDF) or transcribed (audio)
        })
    docs.sort(key=lambda d: d.get("date") or "", reverse=True)
    return {"symbol": symbol, "generated_at": now, "demo": hub.demo,
            "upcoming": out["upcoming"].get("data") or [], "upcoming_error": out["upcoming"].get("error"),
            "documents": docs, "documents_error": out["announcements"].get("error")}


def option_chain_summary(rows: list[dict]) -> dict:
    """Put-call ratio, max-pain strike, at-the-money strike and the strikes with the highest open interest."""
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
    # Put-call parity: the call and put premiums are closest at the strike nearest the forward price.
    by_strike: dict[float, dict[str, float]] = {}
    for r in calls + puts:
        if r.get("ltp") is not None:
            by_strike.setdefault(r["strike"], {})[r["option_type"]] = r["ltp"]
    paired = [(abs(v["CE"] - v["PE"]), k) for k, v in by_strike.items() if "CE" in v and "PE" in v]
    atm = min(paired)[1] if paired else None

    def top(side: list[dict]) -> list[float]:
        return [r["strike"] for r in sorted(side, key=lambda r: -(r.get("open_interest") or 0))[:3]]

    return {
        "pcr_oi": round(put_oi / call_oi, 3) if call_oi else None,
        "total_call_oi": call_oi, "total_put_oi": put_oi, "max_pain": max_pain, "atm_strike": atm,
        "resistance": top(calls), "support": top(puts),
    }
