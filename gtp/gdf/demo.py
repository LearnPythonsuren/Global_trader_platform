"""Offline demo providers with the same methods as the live GDF clients.

Everything here is synthetic. It exists so the product can be demonstrated,
developed and tested without Global Datafeeds keys, and every payload served
in demo mode says so.

The simulated market is built to behave like the real one:

* Prices are a deterministic function of the calendar, so yesterday's candle
  is the same tomorrow. Each symbol follows a market factor, a sector factor
  and its own noise, so sectors move together and indices track their stocks.
* The NSE session is modelled in IST (Mon-Fri 09:15-15:30). During the
  session, today's candle forms minute by minute and quotes tick. Outside it
  the completed day is shown and the last price only jitters slightly.
* Quotes, daily bars and intraday bars always agree: the last bar closes at
  the last traded price, and today's daily bar is the sum of its minute bars.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import math
import random
import threading
import time
from functools import lru_cache
from typing import Any, Callable, Iterable

DAY = 86400
IST_OFFSET = 19800                      # UTC+05:30
SESSION_OPEN = 9 * 3600 + 15 * 60       # 09:15 IST, seconds after midnight
SESSION_MINUTES = 375                   # 09:15 to 15:30
EPOCH_DN = 16440                        # Monday 2015-01-05 as days since 1970-01-01: first simulated trading day
ANCHOR_K = 2868                         # trading-day index of early January 2026, where prices equal their base
ANNUAL_DRIFT = 0.10
REVERSION = 0.995
RISK_FREE = 0.065

# symbol: (name, ISIN, BSE scrip code, sector, industry, base price)
COMPANIES: dict[str, tuple] = {
    "RELIANCE": ("Reliance Industries Ltd.", "INE002A01018", 500325, "Oil Gas & Consumable Fuels", "Petroleum Products", 1450),
    "TCS": ("Tata Consultancy Services Ltd.", "INE467B01029", 532540, "Information Technology", "IT - Software", 3300),
    "HDFCBANK": ("HDFC Bank Ltd.", "INE040A01034", 500180, "Financial Services", "Banks", 980),
    "INFY": ("Infosys Ltd.", "INE009A01021", 500209, "Information Technology", "IT - Software", 1550),
    "ICICIBANK": ("ICICI Bank Ltd.", "INE090A01021", 532174, "Financial Services", "Banks", 1400),
    "HINDUNILVR": ("Hindustan Unilever Ltd.", "INE030A01027", 500696, "Fast Moving Consumer Goods", "Diversified FMCG", 2450),
    "ITC": ("ITC Ltd.", "INE154A01025", 500875, "Fast Moving Consumer Goods", "Diversified FMCG", 420),
    "SBIN": ("State Bank of India", "INE062A01020", 500112, "Financial Services", "Banks", 850),
    "BHARTIARTL": ("Bharti Airtel Ltd.", "INE397D01024", 532454, "Telecommunication", "Telecom - Services", 1950),
    "KOTAKBANK": ("Kotak Mahindra Bank Ltd.", "INE237A01028", 500247, "Financial Services", "Banks", 2100),
    "LT": ("Larsen & Toubro Ltd.", "INE018A01030", 500510, "Construction", "Construction", 3700),
    "AXISBANK": ("Axis Bank Ltd.", "INE238A01034", 532215, "Financial Services", "Banks", 1180),
    "ASIANPAINT": ("Asian Paints Ltd.", "INE021A01026", 500820, "Consumer Durables", "Paints", 2450),
    "MARUTI": ("Maruti Suzuki India Ltd.", "INE585B01010", 532500, "Automobile and Auto Components", "Automobiles", 14000),
    "SUNPHARMA": ("Sun Pharmaceutical Industries Ltd.", "INE044A01036", 524715, "Healthcare", "Pharmaceuticals", 1700),
    "TITAN": ("Titan Company Ltd.", "INE280A01028", 500114, "Consumer Durables", "Gems & Jewellery", 3500),
    "BAJFINANCE": ("Bajaj Finance Ltd.", "INE296A01032", 500034, "Financial Services", "Finance", 950),
    "WIPRO": ("Wipro Ltd.", "INE075A01022", 507685, "Information Technology", "IT - Software", 250),
    "ULTRACEMCO": ("UltraTech Cement Ltd.", "INE481G01011", 532538, "Construction Materials", "Cement & Cement Products", 12000),
    "TATAMOTORS": ("Tata Motors Ltd.", "INE155A01022", 500570, "Automobile and Auto Components", "Automobiles", 700),
    "NTPC": ("NTPC Ltd.", "INE733E01010", 532555, "Power", "Power", 340),
    "POWERGRID": ("Power Grid Corporation of India Ltd.", "INE752E01010", 532898, "Power", "Power", 290),
    "ONGC": ("Oil & Natural Gas Corporation Ltd.", "INE213A01029", 500312, "Oil Gas & Consumable Fuels", "Oil", 245),
    "COALINDIA": ("Coal India Ltd.", "INE522F01014", 533278, "Oil Gas & Consumable Fuels", "Consumable Fuels", 390),
    "BPCL": ("Bharat Petroleum Corporation Ltd.", "INE029A01011", 500547, "Oil Gas & Consumable Fuels", "Petroleum Products", 320),
    "BAJAJFINSV": ("Bajaj Finserv Ltd.", "INE918I01026", 532978, "Financial Services", "Finance", 2000),
    "HCLTECH": ("HCL Technologies Ltd.", "INE860A01027", 532281, "Information Technology", "IT - Software", 1550),
    "TECHM": ("Tech Mahindra Ltd.", "INE669C01036", 532755, "Information Technology", "IT - Software", 1500),
    "LTIM": ("LTIMindtree Ltd.", "INE214T01019", 540005, "Information Technology", "IT - Software", 5300),
    "NESTLEIND": ("Nestle India Ltd.", "INE239A01024", 500790, "Fast Moving Consumer Goods", "Food Products", 1200),
    "BRITANNIA": ("Britannia Industries Ltd.", "INE216A01030", 500825, "Fast Moving Consumer Goods", "Food Products", 5800),
    "TATACONSUM": ("Tata Consumer Products Ltd.", "INE192A01025", 500800, "Fast Moving Consumer Goods", "Agricultural Food", 1100),
    "DRREDDY": ("Dr. Reddy's Laboratories Ltd.", "INE089A01031", 500124, "Healthcare", "Pharmaceuticals", 1250),
    "CIPLA": ("Cipla Ltd.", "INE059A01026", 500087, "Healthcare", "Pharmaceuticals", 1500),
    "DIVISLAB": ("Divi's Laboratories Ltd.", "INE361B01024", 532488, "Healthcare", "Pharmaceuticals", 6200),
    "APOLLOHOSP": ("Apollo Hospitals Enterprise Ltd.", "INE437A01024", 508869, "Healthcare", "Healthcare Services", 7400),
    "TATASTEEL": ("Tata Steel Ltd.", "INE081A01020", 500470, "Metals & Mining", "Ferrous Metals", 160),
    "JSWSTEEL": ("JSW Steel Ltd.", "INE019A01038", 500228, "Metals & Mining", "Ferrous Metals", 1050),
    "HINDALCO": ("Hindalco Industries Ltd.", "INE038A01020", 500440, "Metals & Mining", "Non-Ferrous Metals", 700),
    "ADANIENT": ("Adani Enterprises Ltd.", "INE423A01024", 512599, "Metals & Mining", "Metals & Minerals Trading", 2400),
    "ADANIPORTS": ("Adani Ports and Special Economic Zone Ltd.", "INE742F01042", 532921, "Services", "Transport Infrastructure", 1400),
    "GRASIM": ("Grasim Industries Ltd.", "INE047A01021", 500300, "Construction Materials", "Cement & Cement Products", 2750),
    "HEROMOTOCO": ("Hero MotoCorp Ltd.", "INE158A01026", 500182, "Automobile and Auto Components", "Automobiles", 5000),
    "EICHERMOT": ("Eicher Motors Ltd.", "INE066A01021", 505200, "Automobile and Auto Components", "Automobiles", 5600),
    "BAJAJ-AUTO": ("Bajaj Auto Ltd.", "INE917I01010", 532977, "Automobile and Auto Components", "Automobiles", 8500),
    "INDUSINDBK": ("IndusInd Bank Ltd.", "INE095A01012", 532187, "Financial Services", "Banks", 800),
    "SBILIFE": ("SBI Life Insurance Company Ltd.", "INE123W01016", 540719, "Financial Services", "Insurance", 1800),
    "HDFCLIFE": ("HDFC Life Insurance Company Ltd.", "INE795G01014", 540777, "Financial Services", "Insurance", 760),
    "TRENT": ("Trent Ltd.", "INE849A01020", 500251, "Consumer Services", "Retailing", 5200),
    "BEL": ("Bharat Electronics Ltd.", "INE263A01024", 500049, "Capital Goods", "Aerospace & Defense", 400),
}

# index: (base level, sector factor, daily volatility, market weight, sector weight, own weight, drift, reversion)
INDICES: dict[str, tuple] = {
    "NIFTY 50": (25800, None, 0.0085, 1.0, 0.0, 0.06, ANNUAL_DRIFT, REVERSION),
    "NIFTY BANK": (57800, "Financial Services", 0.0105, 0.8, 0.58, 0.12, ANNUAL_DRIFT, REVERSION),
    "NIFTY IT": (36500, "Information Technology", 0.0120, 0.7, 0.68, 0.15, ANNUAL_DRIFT, REVERSION),
    "NIFTY MIDCAP 100": (59800, None, 0.0110, 0.9, 0.0, 0.43, ANNUAL_DRIFT, REVERSION),
    "SENSEX": (84500, None, 0.0084, 1.0, 0.0, 0.08, ANNUAL_DRIFT, REVERSION),
    "INDIA VIX": (12.8, None, 0.0400, -0.75, 0.0, 0.66, 0.0, 0.96),
}
OPTION_UNDERLYINGS = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "NIFTYIT": "NIFTY IT", "MIDCPNIFTY": "NIFTY MIDCAP 100"}


def _seed(*parts: Any) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16], 16)


class UnknownDemoSymbol(LookupError):
    def __init__(self, symbol: str):
        super().__init__(f"Unknown demo symbol {symbol!r}. Demo mode covers {len(COMPANIES)} large caps "
                         f"(e.g. RELIANCE, TCS, INFY) and these indices: {', '.join(INDICES)}")


# -- calendar ---------------------------------------------------------------
def _dn_of_k(k: int) -> int:
    """Day number (days since 1970-01-01, IST) of trading-day index k."""
    return EPOCH_DN + (k // 5) * 7 + k % 5


def _k_of_dn(dn: int) -> int:
    d = dn - EPOCH_DN
    return (d // 7) * 5 + min(d % 7, 4)


def _open_ts(k: int) -> int:
    return _dn_of_k(k) * DAY + SESSION_OPEN - IST_OFFSET


def _close_ts(k: int) -> int:
    return _open_ts(k) + SESSION_MINUTES * 60


def _date_of_k(k: int) -> _dt.date:
    return _dt.date.fromordinal(719163 + _dn_of_k(k))


def session_state(ts: float) -> tuple[int, int | None, float]:
    """(trading-day index of the current session, completed minutes if it is open else None, seconds into the minute)."""
    local = ts + IST_OFFSET
    dn = int(local // DAY)
    sec = local - dn * DAY
    if (dn + 3) % 7 < 5 and sec >= SESSION_OPEN:
        into = sec - SESSION_OPEN
        if into < SESSION_MINUTES * 60:
            return _k_of_dn(dn), int(into // 60), into % 60
        return _k_of_dn(dn), None, 0.0
    dn -= 1
    while (dn + 3) % 7 >= 5:
        dn -= 1
    return _k_of_dn(dn), None, 0.0


def _iso(ts: float, with_time: bool = True) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S" if with_time else "%Y-%m-%d", time.gmtime(ts + IST_OFFSET))


# -- price model ----------------------------------------------------------------
_LOCK = threading.RLock()
_STREAMS: dict[str, tuple[random.Random, list[float]]] = {}
_SERIES: dict[str, "_Series"] = {}


def _factor(name: str, k: int) -> list[float]:
    """Standard normal draws for a market or sector factor, one per trading day, extended on demand."""
    rng, vals = _STREAMS.setdefault(name, (random.Random(_seed("factor", name)), []))
    while len(vals) <= k:
        vals.append(rng.gauss(0, 1))
    return vals


def _profile(symbol: str) -> dict:
    rng = random.Random(_seed("profile", symbol))
    if symbol in INDICES:
        base, sector, sigma, wm, ws, wi, drift, phi = INDICES[symbol]
        volume = 0.0
    elif symbol in COMPANIES:
        base, sector = COMPANIES[symbol][5], COMPANIES[symbol][3]
        sigma, wm, ws, wi, drift, phi = rng.uniform(0.011, 0.021), 0.6, 0.42, 0.68, ANNUAL_DRIFT, REVERSION
        volume = rng.uniform(1.5e9, 2.2e10) / base      # shares/day for a turnover of Rs 150-2,200 crore
    else:
        raise UnknownDemoSymbol(symbol)
    norm = math.sqrt(wm * wm + ws * ws + wi * wi)
    return {"base": float(base), "sector": sector, "sigma": sigma, "wm": wm / norm, "ws": ws / norm, "wi": wi / norm,
            "drift": drift, "phi": phi, "volume": volume, "index": symbol in INDICES}


class _Series:
    """Daily bars (open, high, low, close, volume) of one symbol by trading-day index."""

    def __init__(self, symbol: str):
        self.p = _profile(symbol)
        self.rng = random.Random(_seed("series", symbol))
        self.x = 0.0
        self.bars: list[tuple[float, float, float, float, float]] = []

    def extend(self, k: int) -> None:
        p, g = self.p, self.rng.gauss
        market = _factor("market", k)
        sector = _factor("sector:" + p["sector"], k) if p["ws"] else None
        while len(self.bars) <= k:
            i = len(self.bars)
            z = p["wm"] * market[i] + (p["ws"] * sector[i] if sector else 0.0) + p["wi"] * g(0, 1)
            prev = self.bars[-1][3] if self.bars else p["base"] * math.exp(p["drift"] * (i - 1 - ANCHOR_K) / 252)
            self.x = p["phi"] * self.x + p["sigma"] * z
            close = round(p["base"] * math.exp(p["drift"] * (i - ANCHOR_K) / 252 + self.x), 2)
            open_ = round(prev * math.exp(p["sigma"] * 0.35 * g(0, 1)), 2)
            high = max(open_, close, round(max(open_, close) * math.exp(abs(p["sigma"] * 0.55 * g(0, 1))), 2))
            low = min(open_, close, round(min(open_, close) * math.exp(-abs(p["sigma"] * 0.55 * g(0, 1))), 2))
            volume = round(p["volume"] * math.exp(0.35 * g(0, 1)) * (0.75 + 0.5 * abs(z)))
            self.bars.append((open_, high, low, close, float(volume)))


def _bars(symbol: str, k: int) -> list[tuple[float, float, float, float, float]]:
    with _LOCK:
        series = _SERIES.get(symbol)
        if series is None:
            series = _SERIES[symbol] = _Series(symbol)
        if len(series.bars) <= k:
            series.extend(k)
        return series.bars


@lru_cache(maxsize=600)
def _minute_path(symbol: str, k: int) -> tuple[list[float], list[float], list[float], list[float]]:
    """Minute-by-minute path of trading day k that reproduces its daily bar exactly.

    Returns (price, high, low, volume). price[i] is the price after i minutes,
    so minute i (1-based) opens at price[i-1] and closes at price[i].
    """
    o, h, lo, c, v = _bars(symbol, k)[k]
    n = SESSION_MINUTES
    rng = random.Random(_seed("intraday", symbol, k))
    walk = [0.0]
    for _ in range(n):
        walk.append(walk[-1] + rng.gauss(0, 1))
    line = [math.log(o) + (math.log(c) - math.log(o)) * i / n for i in range(n + 1)]
    dev = [walk[i] - walk[n] * i / n for i in range(n + 1)]          # Brownian bridge: zero at both ends
    # Scale the excursions above and below the open-to-close line so the path touches the day's high and low.
    up = min(((math.log(h) - line[i]) / dev[i] for i in range(1, n) if dev[i] > 1e-9), default=0.0)
    down = min(((line[i] - math.log(lo)) / -dev[i] for i in range(1, n) if dev[i] < -1e-9), default=0.0)
    price = [math.exp(line[i] + dev[i] * (up if dev[i] > 0 else down)) for i in range(n + 1)]
    price[0], price[n] = o, c
    high, low, weights = [o], [o], [0.0]
    for i in range(1, n + 1):
        a, b = price[i - 1], price[i]
        wick = abs(rng.gauss(0, 1)) * 0.00025
        high.append(min(h, max(a, b) * (1 + wick)))
        low.append(max(lo, min(a, b) * (1 - wick)))
        weights.append((1 + 1.8 * math.exp(-i / 25) + 1.2 * math.exp(-(n - i) / 20)) * math.exp(0.45 * rng.gauss(0, 1)))
    total = sum(weights)
    return price, high, low, [v * w / total for w in weights]


def _live(symbol: str, ts: float) -> dict:
    """The current session of one symbol at time ts: today's bar so far and the last traded price."""
    k, minutes, sec = session_state(ts)
    bars = _bars(symbol, k)
    o, h, lo, c, v = bars[k]
    prev = bars[k - 1][3]
    noise = random.Random(_seed("tick", symbol, int(ts // 3))).gauss(0, 1)
    if minutes is None:                                             # session over: only a small jitter
        ltp = round(min(h, max(lo, c * (1 + 0.00035 * noise))), 2)
        return {"k": k, "minutes": SESSION_MINUTES, "forming": None, "o": o, "h": h, "l": lo, "ltp": ltp,
                "v": v, "prev": prev, "open": False}
    price, high, low, vol = _minute_path(symbol, k)
    frac = sec / 60.0
    a, b = price[minutes], price[minutes + 1]
    ltp = a + (b - a) * frac + abs(b - a) * 0.4 * noise * (1 - frac)
    ltp = round(min(h, max(lo, ltp)), 2)
    forming = {"o": round(a, 2), "h": round(max(a, ltp), 2), "l": round(min(a, ltp), 2), "c": ltp,
               "v": vol[minutes + 1] * frac}
    return {"k": k, "minutes": minutes, "forming": forming, "o": o,
            "h": round(max([o, ltp] + high[1:minutes + 1]), 2), "l": round(min([o, ltp] + low[1:minutes + 1]), 2),
            "ltp": ltp, "v": sum(vol[1:minutes + 1]) + forming["v"], "prev": prev, "open": True}


def _bar(t: int, o: float, h: float, lo: float, c: float, v: float) -> dict:
    return {"t": int(t), "o": round(o, 2), "h": round(h, 2), "l": round(lo, 2), "c": round(c, 2), "v": int(round(v)),
            "oi": None}


def _daily(symbol: str, ts: float, count: int = 0) -> list[dict]:
    live = _live(symbol, ts)
    k = live["k"]
    bars = _bars(symbol, k)
    first = max(0, k - count + 1) if count else 0
    out = [_bar(_close_ts(i), *bars[i]) for i in range(first, k)]
    out.append(_bar(_close_ts(k), live["o"], live["h"], live["l"], live["ltp"], live["v"]))
    return out


def _intraday(symbol: str, ts: float, step: int, days: int) -> list[dict]:
    """Bars of `step` minutes for the last `days` sessions, ending with the bar that is still forming."""
    live = _live(symbol, ts)
    k = live["k"]
    out: list[dict] = []
    for i in range(max(1, k - days + 1), k + 1):
        price, high, low, vol = _minute_path(symbol, i)
        done = live["minutes"] if i == k else SESSION_MINUTES
        start = _open_ts(i)
        for g0 in range(0, done, step):
            g1 = min(g0 + step, done)
            out.append(_bar(start + g0 * 60, price[g0], max(high[g0 + 1:g1 + 1]), min(low[g0 + 1:g1 + 1]),
                            price[g1], sum(vol[g0 + 1:g1 + 1])))
        if i < k:
            continue
        forming = live["forming"]
        if forming is None:                                         # closed: the last bar ends at the jittered price
            last = out[-1]
            last["c"], last["h"], last["l"] = live["ltp"], max(last["h"], live["ltp"]), min(last["l"], live["ltp"])
        elif done % step:                                           # the forming minute belongs to the last bar
            last = out[-1]
            last["c"], last["h"], last["l"] = forming["c"], max(last["h"], forming["h"]), min(last["l"], forming["l"])
            last["v"] += int(round(forming["v"]))
        else:
            out.append(_bar(start + done * 60, forming["o"], forming["h"], forming["l"], forming["c"], forming["v"]))
    return out


def _group(bars: list[dict], key: Callable[[dict], Any]) -> list[dict]:
    out: list[dict] = []
    last_key = object()
    for b in bars:
        kk = key(b)
        if kk == last_key:
            g = out[-1]
            g["t"], g["h"], g["l"], g["c"], g["v"] = b["t"], max(g["h"], b["h"]), min(g["l"], b["l"]), b["c"], g["v"] + b["v"]
        else:
            out.append(dict(b))
            last_key = kk
    return out


def _quote(exchange: str, symbol: str, ts: float) -> dict:
    live = _live(symbol, ts)
    index = _bars(symbol, live["k"]) is not None and _SERIES[symbol].p["index"]
    ltp, prev = live["ltp"], live["prev"]
    atp = round((live["h"] + live["l"] + ltp) / 3, 2)
    return {
        "exchange": exchange, "symbol": symbol, "ltp": ltp, "open": live["o"], "high": live["h"], "low": live["l"],
        "prev_close": prev, "change": round(ltp - prev, 2), "change_pct": round((ltp / prev - 1) * 100, 2),
        "volume": None if index else int(round(live["v"])), "value": None if index else round(live["v"] * atp, 2),
        "atp": None if index else atp, "bid": None if index else round(ltp - 0.05, 2),
        "ask": None if index else round(ltp + 0.05, 2), "bid_qty": None if index else 100 + _seed(symbol, int(ts // 3)) % 900,
        "ask_qty": None if index else 100 + _seed(symbol, "a", int(ts // 3)) % 900, "open_interest": None,
        "lot_size": 1, "last_trade_time": int(ts) if live["open"] else _close_ts(live["k"]), "server_time": int(ts),
    }


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _black_scholes(spot: float, strike: float, years: float, vol: float, kind: str) -> float:
    d1 = (math.log(spot / strike) + (RISK_FREE + vol * vol / 2) * years) / (vol * math.sqrt(years))
    d2 = d1 - vol * math.sqrt(years)
    call = spot * _norm_cdf(d1) - strike * math.exp(-RISK_FREE * years) * _norm_cdf(d2)
    return call if kind == "CE" else call - spot + strike * math.exp(-RISK_FREE * years)


class DemoPrice:
    demo = True

    def __init__(self, clock: Callable[[], float] = time.time):
        self._now = clock

    def last_quote(self, exchange: str, symbol: str) -> dict:
        return _quote(exchange, symbol, self._now())

    def last_quotes(self, exchange: str, symbols: Iterable[str]) -> list[dict]:
        """Quotes for the symbols the demo knows; unknown ones are left out, as a feed would do."""
        now = self._now()
        return [_quote(exchange, s, now) for s in symbols if s in COMPANIES or s in INDICES]

    def history(self, exchange: str, symbol: str, periodicity: str = "DAY", period: int = 1,
                from_ts: int | None = None, to_ts: int | None = None, max_bars: int = 0,
                adjust_splits: bool = True) -> list[dict]:
        now = self._now()
        periodicity, period = periodicity.upper(), max(1, int(period))
        if periodicity in ("TICK", "MINUTE", "HOUR"):
            step = period * (60 if periodicity == "HOUR" else 1)
            per_day = math.ceil(SESSION_MINUTES / step)
            days = math.ceil(max_bars / per_day) + 1 if max_bars else (60 if periodicity == "HOUR" else 5)
            if from_ts:
                days = max(days, int((now - from_ts) // DAY * 5 / 7) + 2)
            bars = _intraday(symbol, now, step, min(days, 250 if step >= 60 else 60))
        else:
            span = {"DAY": 1, "WEEK": 5, "MONTH": 23}[periodicity] * period
            bars = _daily(symbol, now, (max_bars + 1) * span if max_bars and not from_ts else 0)
            if periodicity == "WEEK":
                bars = _group(bars, lambda b: ((b["t"] + IST_OFFSET) // DAY - EPOCH_DN) // (7 * period))
            elif periodicity == "MONTH":
                def month(b: dict) -> int:
                    d = _dt.date.fromordinal(719163 + (b["t"] + IST_OFFSET) // DAY)
                    return (d.year * 12 + d.month - 1) // period
                bars = _group(bars, month)
            elif period > 1:
                bars = _group(bars, lambda b: _k_of_dn((b["t"] + IST_OFFSET) // DAY) // period)
        if from_ts:
            bars = [b for b in bars if b["t"] >= from_ts]
        if to_ts:
            bars = [b for b in bars if b["t"] <= to_ts]
        return bars[-max_bars:] if max_bars else bars

    def search_instruments(self, exchange: str, search: str, **filters: Any) -> list[dict]:
        q = search.upper().strip()
        rows = [{"Identifier": s, "Name": v[0], "Exchange": exchange, "QuotationLot": 1, "Sector": v[3]}
                for s, v in COMPANIES.items() if q in s or q in v[0].upper()]
        rows += [{"Identifier": s, "Name": s, "Exchange": "NSE_IDX", "QuotationLot": 1, "Sector": "Index"}
                 for s in INDICES if q in s]
        rows.sort(key=lambda r: (not r["Identifier"].startswith(q), r["Identifier"]))
        return rows

    def option_chain(self, exchange: str, product: str, expiry: str | None = None, option_type: str | None = None,
                     strike_price: float | None = None) -> list[dict]:
        now = self._now()
        product = product.upper()
        underlying = OPTION_UNDERLYINGS.get(product, product)
        live = _live(underlying, now)
        spot, prev_spot, k = live["ltp"], live["prev"], live["k"]
        date = _date_of_k(k)
        if expiry:
            try:
                expiry_date = _dt.datetime.strptime(expiry.title(), "%d%b%Y").date()
            except ValueError:
                raise ValueError(f"expiry must look like 25NOV2026, got {expiry!r}") from None
        else:                                                   # NSE index weekly expiry: Tuesday
            expiry_date = date + _dt.timedelta(days=(1 - date.weekday()) % 7)
        expiry = expiry_date.strftime("%d%b%Y").upper()
        expiry_ts = (expiry_date.toordinal() - 719163) * DAY + SESSION_OPEN + SESSION_MINUTES * 60 - IST_OFFSET
        years = max((expiry_ts - now) / DAY, 0.25) / 365
        step = 100 if spot > 40000 else 50 if spot > 9000 else 20 if spot > 3000 else 10 if spot > 1000 else 5 if spot > 400 else 1
        atm = round(spot / step) * step
        base_vol = 0.115 + (_seed("iv", product, k) % 40) / 1000
        kind_prefix = "OPTIDX" if underlying in INDICES else "OPTSTK"
        lot = {"NIFTY": 75, "BANKNIFTY": 35}.get(product, 1)
        rows = []
        for n in range(-12, 13):
            strike = atm + n * step
            if strike <= 0 or (strike_price and strike != strike_price):
                continue
            moneyness = math.log(strike / spot)
            vol = base_vol + 0.9 * moneyness * moneyness - 0.12 * moneyness          # smile with a put skew
            for kind in ("CE", "PE"):
                if option_type and kind != option_type.upper():
                    continue
                rng = random.Random(_seed("chain", product, expiry, strike, kind, k))
                ltp = max(0.05, round(_black_scholes(spot, strike, years, vol, kind), 2))
                prev = max(0.05, _black_scholes(prev_spot, strike, years + 1 / 365, vol, kind))
                otm = strike >= atm if kind == "CE" else strike <= atm
                oi = rng.uniform(4e5, 3.5e6) * math.exp(-abs(n) / 7) * (1.0 if otm else 0.45)
                oi *= 1.7 if strike % (step * 10) == 0 else 1.25 if strike % (step * 2) == 0 else 1.0
                oi = int(oi // lot * lot)
                rows.append({
                    "exchange": exchange, "symbol": f"{kind_prefix}_{product}_{expiry}_{kind}_{strike:g}",
                    "strike": float(strike), "option_type": kind, "expiry": expiry, "ltp": ltp,
                    "change_pct": round((ltp / prev - 1) * 100, 2), "open_interest": oi,
                    "oi_change": int(oi * rng.uniform(-0.18, 0.3)), "volume": int(oi * rng.uniform(0.6, 3.5)),
                    "iv": round(vol * 100, 2), "bid": round(ltp * 0.997, 2), "ask": round(ltp * 1.003 + 0.05, 2),
                    "lot_size": lot,
                })
        return rows

    def top_gainers_losers(self, exchange: str, **params: Any) -> dict:
        quotes = sorted(self.last_quotes(exchange, COMPANIES), key=lambda q: q["change_pct"])
        return {"gainers": quotes[::-1][:5], "losers": quotes[:5]}

    def exchanges(self) -> list[str]:
        return ["NSE", "NSE_IDX", "NFO", "BSE", "BSE_IDX", "BFO", "MCX", "CDS"]


# -- fundamentals -------------------------------------------------------------------
_QUARTERS = {"QJ": 0, "QS": 1, "QD": 2, "QM": 3}
_SPANS = {"M6": ("QJ", "QS"), "M9": ("QJ", "QS", "QD"), "M12": ("QJ", "QS", "QD", "QM")}
_ANNOUNCEMENTS = [
    ("Board Meeting", "Board meeting intimation for consideration of quarterly financial results"),
    ("Press Release", "Press release on new order wins and capacity expansion"),
    ("Investor Meet", "Schedule of analyst and institutional investor meetings"),
    ("Outcome of Board Meeting", "Outcome of board meeting: financial results approved"),
    ("Change in Management", "Appointment of an independent director"),
    ("Credit Rating", "Credit rating reaffirmed by the rating agency"),
    ("Newspaper Publication", "Newspaper publication of financial results"),
]


def _company(symbol: str) -> tuple:
    if symbol not in COMPANIES:
        raise UnknownDemoSymbol(symbol)
    return COMPANIES[symbol]


def _fundamentals(symbol: str) -> dict:
    """Per-share figures that stay fixed while the price moves, so P/E and P/B move with the price."""
    base = _company(symbol)[5]
    rng = random.Random(_seed("fundamentals", symbol))
    eps = base / rng.uniform(11, 58)
    return {"eps": eps, "book_value": base / rng.uniform(0.9, 7.5), "shares": rng.uniform(8e11, 1.8e13) / base,
            "dividend": eps * rng.uniform(0.0, 0.55), "debt": 0.0 if rng.random() < 0.25 else rng.uniform(2e10, 2.5e12),
            "interest_coverage": rng.uniform(2.5, 85), "sales_per_share": eps * rng.uniform(4, 14),
            "face_value": rng.choice([1, 2, 5, 10])}


class DemoFundamentals:
    demo = True

    def __init__(self, clock: Callable[[], float] = time.time):
        self._now = clock

    def company(self, exchange: str, symbol: str) -> dict:
        name, isin, code, *_ = _company(symbol)
        return {"symbol": symbol, "name": name, "isin": isin, "scrip_code": code}

    def sector(self, exchange: str, symbol: str) -> dict:
        name, isin, _, sector, industry, _ = _company(symbol)
        return {"symbol": symbol, "name": name, "isin": isin, "macro": sector, "sector": sector, "industry": industry,
                "basic_industry": industry}

    def ratios(self, exchange: str, symbol: str, **_: Any) -> dict:
        f = _fundamentals(symbol)
        now = self._now()
        bars = _daily(symbol, now, 252)
        close = bars[-1]["c"]
        high52, low52 = max(b["h"] for b in bars), min(b["l"] for b in bars)
        market_cap = close * f["shares"]
        profit = f["eps"] * f["shares"]
        return {
            "close": close, "year": time.gmtime(now).tm_year, "last_quarter": "QS",
            "market_cap": round(market_cap / 1e7, 2),                          # Rs crore, as GDF reports it
            "week52_high": high52, "week52_low": low52, "eps": round(f["eps"], 2), "pe": round(close / f["eps"], 2),
            "book_value": round(f["book_value"], 2), "dividend_yield": round(f["dividend"] / close * 100, 2),
            "ebit": round(profit * 1.45), "interest_coverage": round(f["interest_coverage"], 2),
            "face_value": f["face_value"], "price_sales": round(close / f["sales_per_share"], 2),
            "profit_after_tax": round(profit), "enterprise_value": round(market_cap + f["debt"]),
            "debt": round(f["debt"]), "pb": round(close / f["book_value"], 2),
            "pct_from_52w_high": round((close / high52 - 1) * 100, 2),
        }

    def shareholding(self, exchange: str, symbol: str, **_: Any) -> list[dict]:
        _company(symbol)
        rng = random.Random(_seed("shareholding", symbol))
        promoter, fii, dii = rng.uniform(0, 72), rng.uniform(10, 42), rng.uniform(8, 28)
        total = promoter + fii + dii
        if total > 94:
            promoter, fii, dii = (x * 94 / total for x in (promoter, fii, dii))
        now = time.gmtime(self._now() + IST_OFFSET - 45 * DAY)
        quarter_end = ("March", "June", "September", "December")[(now.tm_mon - 1) // 3]
        period = f"{quarter_end} {now.tm_year}"
        rows = (("Promoter", promoter), ("FII", fii), ("DII", dii), ("Public", 100 - promoter - fii - dii))
        return [{"entity": e, "value": round(v, 2), "period": period} for e, v in rows]

    def financial_results(self, exchange: str, symbol: str, year: int, *, statement: str = "ProfitLoss",
                          period: str = "QD", nature: str = "Standalone", **_: Any) -> list[dict]:
        f = _fundamentals(symbol)
        quarters = _SPANS.get(period, (period,))
        if any(q not in _QUARTERS for q in quarters):
            raise ValueError(f"period must be one of {', '.join(list(_QUARTERS) + list(_SPANS))}")
        scale = 1.12 if nature == "Consolidated" else 1.0
        revenue = profit = 0.0
        for q in quarters:
            index = (int(year) - 2026) * 4 + _QUARTERS[q]              # quarters relative to FY2026-27
            rng = random.Random(_seed("results", symbol, year, q))
            growth = math.exp(0.028 * index) * rng.uniform(0.94, 1.07)
            revenue += f["sales_per_share"] * f["shares"] / 4 * growth * scale
            profit += f["eps"] * f["shares"] / 4 * growth * rng.uniform(0.9, 1.1) * scale
        rng = random.Random(_seed("results", symbol, year, period, statement))
        if statement == "BalanceSheet":
            equity = f["book_value"] * f["shares"] * scale
            items = [("Equity share capital", "EquityShareCapital", f["face_value"] * f["shares"]),
                     ("Other equity", "OtherEquity", equity - f["face_value"] * f["shares"]),
                     ("Total borrowings", "Borrowings", f["debt"] * scale),
                     ("Total equity and liabilities", "EquityAndLiabilities", (equity + f["debt"]) * rng.uniform(1.25, 1.6)),
                     ("Cash and cash equivalents", "CashAndCashEquivalents", equity * rng.uniform(0.03, 0.2))]
        elif statement == "CashFlow":
            items = [("Net cash from operating activities", "CashFlowsFromOperatingActivities", profit * rng.uniform(0.9, 1.5)),
                     ("Net cash used in investing activities", "CashFlowsFromInvestingActivities", -profit * rng.uniform(0.3, 1.1)),
                     ("Net cash used in financing activities", "CashFlowsFromFinancingActivities", -profit * rng.uniform(0.1, 0.6))]
        else:
            other = revenue * rng.uniform(0.01, 0.04)
            tax = profit * rng.uniform(0.31, 0.36)
            items = [("Revenue from operations", "RevenueFromOperations", revenue), ("Other income", "OtherIncome", other),
                     ("Total income", "Income", revenue + other), ("Total expenses", "Expenses", revenue + other - profit - tax),
                     ("Profit before tax", "ProfitBeforeTax", profit + tax), ("Tax expense", "TaxExpense", tax),
                     ("Net profit for the period", "ProfitLossForPeriod", profit),
                     ("Basic earnings per share", "BasicEarningsLossPerShare", profit / f["shares"])]
        return [{"label": label, "key": key, "value": round(value, 2), "raw_value": str(round(value, 2)),
                 "unit": "INR", "decimals": "2" if key.startswith("Basic") else "-5", "description": None}
                for label, key, value in items]

    def announcements(self, exchange: str, symbol: str | None, from_ts: int, to_ts: int, **_: Any) -> list[dict]:
        symbols = [symbol] if symbol else list(COMPANIES)[:12]
        out = []
        for sym in symbols:
            name, _, code, *_rest = _company(sym)
            if symbol:                       # earnings-call documents for the latest reported quarter
                out.extend(_earnings_announcements(sym, name, code, to_ts, from_ts))
            rng = random.Random(_seed("announcements", sym, to_ts // (7 * DAY)))
            for i, (category, text) in enumerate(rng.sample(_ANNOUNCEMENTS, 3 if symbol else 1)):
                when = to_ts - rng.randint(1, 9) * 3600 - i * rng.randint(2, 5) * DAY
                if when < from_ts:
                    continue
                out.append({"symbol": sym, "name": name, "scrip_code": code, "date": _iso(when),
                            "headline": text, "body": f"[DEMO] {name} has informed the exchange: {text.lower()}.",
                            "category": category, "critical": category == "Outcome of Board Meeting",
                            "meeting_date": None, "url": None})
        return sorted(out, key=lambda a: a["date"], reverse=True)

    def corporate_actions(self, exchange: str, symbol: str | None, from_ts: int, to_ts: int) -> list[dict]:
        out = []
        for sym in ([symbol] if symbol else list(COMPANIES)[:8]):
            name, _, code, *_rest = _company(sym)
            f = _fundamentals(sym)
            rng = random.Random(_seed("actions", sym))
            ex = to_ts - rng.randint(10, 300) * DAY
            if ex < from_ts or f["dividend"] <= 0:
                continue
            out.append({"symbol": sym, "name": name, "scrip_code": code, "type": "Dividend", "purpose_code": "DP",
                        "announced": _iso(ex - 21 * DAY), "ex_date": _iso(ex, False), "record_kind": "RD",
                        "record_from": _iso(ex, False), "record_to": _iso(ex, False), "payment_date": _iso(ex + 20 * DAY, False),
                        "ratio": f"Rs {f['dividend']:.2f} per share", "url": None})
        return sorted(out, key=lambda a: a["ex_date"], reverse=True)

    def results_calendar(self, exchange: str, range_: str = "Next7days", symbols: list[str] | None = None) -> list[dict]:
        now = self._now()
        week = int((now + IST_OFFSET) // (7 * DAY))
        picks = symbols or random.Random(_seed("calendar", week)).sample(list(COMPANIES), 8)
        out = []
        for i, sym in enumerate(picks):
            name, isin, *_rest = _company(sym)
            q = _quote("NSE", sym, now)
            out.append({"symbol": sym, "name": name, "isin": isin, "date": _iso(now + (i // 2 + 1) * DAY, False),
                        "ltp": q["ltp"], "change_pct": q["change_pct"]})
        return out

    def _deals(self, kind: str) -> list[dict]:
        now = self._now()
        rng = random.Random(_seed(kind, int((now + IST_OFFSET) // DAY)))
        clients = ["Plutus Wealth Management LLP", "Societe Generale", "Graviton Research Capital LLP",
                   "Tower Research Capital Markets India", "HRTI Private Limited", "BofA Securities Europe SA"]
        out = []
        for sym in rng.sample(list(COMPANIES), 6):
            q = _quote("NSE", sym, now)
            qty = rng.randint(2, 60) * 50_000
            out.append({"date": _iso(now - rng.randint(0, 5) * DAY, False), "symbol": sym, "scrip_code": _company(sym)[2],
                        "client": rng.choice(clients), "side": rng.choice(["buy", "sell"]), "qty": float(qty),
                        "qty_pct": round(qty / _fundamentals(sym)["shares"] * 100, 4), "price": q["ltp"]})
        return sorted(out, key=lambda d: d["date"], reverse=True)

    def bulk_deals(self, *a: Any, **k: Any) -> list[dict]:
        return self._deals("bulk")

    def block_deals(self, *a: Any, **k: Any) -> list[dict]:
        return self._deals("block")

    def participants(self, exchange: str = "NSE", client_type: str | None = None, *a: Any, **k: Any) -> list[dict]:
        now = self._now()
        day, _, _ = session_state(now)
        rows = []
        for client in ("Client", "DII", "FII", "Pro"):
            rng = random.Random(_seed("participants", client, day))
            size = {"Client": 3.0, "DII": 0.4, "FII": 1.6, "Pro": 1.0}[client]
            fil, fis = (int(rng.uniform(4e4, 2.6e5) * size) for _ in range(2))
            fsl, fss = (int(rng.uniform(4e5, 3.2e6) * size) for _ in range(2))
            ocl, opl, ocs, ops = (int(rng.uniform(4e5, 3e6) * size) for _ in range(4))
            option_net = (ocl - ocs) - (opl - ops)
            rows.append({
                "client": client, "date": _iso(_close_ts(day)),
                "future_index_long": fil, "future_index_short": fis, "future_index_net_position": fil - fis,
                "future_index_signal": "Bullish" if fil >= fis else "Bearish",
                "future_stock_long": fsl, "future_stock_short": fss, "future_stock_net_position": fsl - fss,
                "future_stock_signal": "Bullish" if fsl >= fss else "Bearish",
                "option_index_call_long": ocl, "option_index_put_long": opl, "option_index_call_short": ocs,
                "option_index_put_short": ops, "option_index_net_oi": option_net,
                "option_index_signal": "Bullish" if option_net >= 0 else "Bearish",
                "total_long_contracts": fil + fsl + ocl + opl, "total_short_contracts": fis + fss + ocs + ops,
            })
        if client_type:
            rows = [r for r in rows if r["client"].lower() == client_type.lower()]
        return rows


# -- mutual funds ---------------------------------------------------------------
# AMFI code: (scheme name, category, sub-category, base NAV, daily volatility, annual drift, AMC)
def _fiscal_quarter(now: float) -> tuple[int, str, str]:
    """(fiscal year, quarter code, label) of the most recently completed quarter."""
    t = time.gmtime(now + IST_OFFSET)
    fy = t.tm_year if t.tm_mon >= 4 else t.tm_year - 1
    i = ((t.tm_mon - 4) % 12) // 3 - 1
    if i < 0:
        i, fy = 3, fy - 1
    code = ("QJ", "QS", "QD", "QM")[i]
    end_month = ("Jun", "Sep", "Dec", "Mar")[i]
    year = fy + 1 if code == "QM" else fy
    return fy, f"Q{i + 1}FY{str(fy + 1)[2:]}", f"{end_month} {year}"


def _earnings_announcements(symbol: str, name: str, code: int, to_ts: float, from_ts: float) -> list[dict]:
    """Transcript PDF, investor presentation, audio recording and results outcome for recent quarters."""
    out = []
    for q in range(2):
        fy, tag, label = _fiscal_quarter(to_ts - q * 91 * DAY)
        base = to_ts - q * 91 * DAY - 5 * DAY
        url = lambda f: f"https://demo.gtp.local/ec/{symbol}/{tag}/{f}"  # noqa: E731
        items = [
            ("Outcome of Board Meeting", f"Outcome of Board Meeting - Audited Financial Results for {label}", url("results.pdf"), 0),
            ("Investor Presentation", f"Investor Presentation - {label} Earnings", url("presentation.pdf"), 4 * 3600),
            ("Transcript", f"Transcript of {label} Earnings Conference Call", url("transcript.pdf"), 3 * DAY),
            ("Audio Recording", f"Audio Recording of {label} Earnings Conference Call", url("audio.mp3"), 2 * DAY),
        ]
        for category, headline, link, delay in items:
            when = base - delay
            if when < from_ts:
                continue
            out.append({"symbol": symbol, "name": name, "scrip_code": code, "date": _iso(when),
                        "headline": headline, "body": f"[DEMO] {name}: {headline}.", "category": category,
                        "critical": category == "Outcome of Board Meeting", "meeting_date": None, "url": link})
    return out


def _transcript_text(symbol: str, tag: str) -> str:
    name = COMPANIES.get(symbol, (symbol,))[0]
    rng = random.Random(_seed("transcript", symbol, tag))
    rev = rng.uniform(5_000, 65_000)
    growth = rng.uniform(6, 18)
    margin = rng.uniform(14, 28)
    eps = rng.uniform(8, 120)
    guide = rng.choice(["double-digit", "steady", "mid-teens", "high single-digit"])
    paras = [
        "[DEMO TRANSCRIPT — synthetic, not a real filing]",
        f"{name} — {tag} Earnings Conference Call",
        "Moderator: Ladies and gentlemen, good day and welcome to the earnings conference call of "
        f"{name}. We have with us the senior management team. As a reminder, all participant lines are in "
        "listen-only mode. Please note that this conference is being recorded.",
        "Management: Thank you, and good evening everyone. I am pleased to report another resilient quarter. "
        f"Revenue for the quarter came in at approximately Rs {rev:,.0f} crore, a growth of about {growth:.1f}% "
        f"year on year, led by broad-based demand across our key segments. Operating margin for the quarter was "
        f"around {margin:.1f}%, reflecting disciplined cost management and operating leverage. Profit after tax "
        f"translated to earnings per share of roughly Rs {eps:,.1f} for the quarter.",
        "Management: On the demand environment, we continue to see healthy traction in domestic markets, while "
        "the export book remains selective. Our order pipeline is robust and we remain focused on execution, "
        f"working capital discipline and return ratios. For the full year we expect {guide} revenue growth, with "
        "margins broadly in the range we have guided to earlier.",
        "Moderator: Thank you. We will now begin the question-and-answer session.",
        "Analyst: Congratulations on the quarter. My first question is on margins — how should we think about the "
        "trajectory over the next few quarters given input-cost movements?",
        "Management: Good question. We expect margins to remain range-bound with a modest upward bias as pricing "
        "actions and efficiency programmes play through. We are not assuming any material change in commodity "
        "costs in our guidance.",
        "Analyst: And on capital allocation — any update on capex plans and the dividend policy?",
        "Management: We continue to invest behind capacity and technology, and our board remains committed to a "
        "consistent dividend payout. We will balance growth investments with returns to shareholders.",
        "Moderator: Thank you. That concludes today's conference call. You may now disconnect your lines.",
    ]
    return "\n\n".join(paras)


def demo_document(url: str, kind: str) -> dict:
    """Return synthetic earnings-call content for a demo.gtp.local document URL."""
    parts = url.split("/")
    try:
        symbol, tag = parts[-3], parts[-2]
    except IndexError:
        symbol, tag = "RELIANCE", "Q2FY27"
    name = COMPANIES.get(symbol, (symbol,))[0]
    filename = parts[-1].lower()
    if kind == "audio" or filename.endswith((".mp3", ".wav", ".m4a")):
        text = _transcript_text(symbol, tag)
        return {"kind": "audio", "source": url, "available": True, "transcript": text,
                "provider": "demo", "model": "demo-whisper", "demo": True, "duration_min": 42}
    if "presentation" in filename:
        body = (f"[DEMO] {name} — {tag} Investor Presentation.\n\nSlide 1: Financial highlights.\n"
                "Slide 2: Segment performance.\nSlide 3: Outlook and guidance.\nThis is synthetic demo content.")
    elif "results" in filename:
        body = (f"[DEMO] {name} — Outcome of Board Meeting, {tag}.\n\nThe Board approved the audited financial "
                "results for the quarter. Revenue, profit and EPS are reported in the accompanying statement. "
                "Synthetic demo content.")
    else:
        body = _transcript_text(symbol, tag)
    pages = max(1, body.count("\n\n") + 1)
    return {"kind": "pdf", "source": url, "content_type": "application/pdf", "pages": pages,
            "pages_read": pages, "chars": len(body), "truncated": False, "text": body, "demo": True}


SCHEMES: dict[str, tuple] = {
    "122639": ("Parag Parikh Flexi Cap Fund - Direct Plan - Growth", "Equity", "Flexi Cap Fund", 90.0, 0.0075, 0.17, "PPFAS Mutual Fund"),
    "120716": ("UTI Nifty 50 Index Fund - Direct Plan - Growth", "Equity", "Index Fund", 170.0, 0.0085, 0.12, "UTI Mutual Fund"),
    "118989": ("HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth", "Equity", "Mid Cap Fund", 200.0, 0.0105, 0.19, "HDFC Mutual Fund"),
    "125497": ("SBI Small Cap Fund - Direct Plan - Growth", "Equity", "Small Cap Fund", 200.0, 0.0115, 0.18, "SBI Mutual Fund"),
    "118778": ("Nippon India Small Cap Fund - Direct Plan - Growth", "Equity", "Small Cap Fund", 190.0, 0.0125, 0.21, "Nippon India Mutual Fund"),
    "120465": ("Axis Bluechip Fund - Direct Plan - Growth", "Equity", "Large Cap Fund", 68.0, 0.0085, 0.11, "Axis Mutual Fund"),
    "118825": ("Mirae Asset Large Cap Fund - Direct Plan - Growth", "Equity", "Large Cap Fund", 125.0, 0.0085, 0.12, "Mirae Asset Mutual Fund"),
    "120586": ("ICICI Prudential Bluechip Fund - Direct Plan - Growth", "Equity", "Large Cap Fund", 120.0, 0.0085, 0.14, "ICICI Prudential Mutual Fund"),
    "120503": ("Axis ELSS Tax Saver Fund - Direct Plan - Growth", "Equity", "ELSS", 105.0, 0.0095, 0.11, "Axis Mutual Fund"),
    "149264": ("NJ Balanced Advantage Fund - Direct Plan - Growth Option", "Hybrid", "Balanced Advantage", 14.0, 0.0050, 0.09, "NJ Mutual Fund"),
    "119062": ("HDFC Corporate Bond Fund - Direct Plan - Growth", "Debt", "Corporate Bond Fund", 33.0, 0.0008, 0.075, "HDFC Mutual Fund"),
}
# Mid and small caps that only appear in fund portfolios: (name, sector, size)
OTHER_HOLDINGS = [
    ("Persistent Systems Ltd.", "Information Technology", "Mid Cap"), ("Coforge Ltd.", "Information Technology", "Mid Cap"),
    ("Dixon Technologies (India) Ltd.", "Consumer Durables", "Mid Cap"), ("Max Healthcare Institute Ltd.", "Healthcare", "Mid Cap"),
    ("The Indian Hotels Company Ltd.", "Consumer Services", "Mid Cap"), ("Cummins India Ltd.", "Capital Goods", "Mid Cap"),
    ("PB Fintech Ltd.", "Financial Services", "Mid Cap"), ("The Federal Bank Ltd.", "Financial Services", "Mid Cap"),
    ("Lupin Ltd.", "Healthcare", "Mid Cap"), ("Balkrishna Industries Ltd.", "Automobile and Auto Components", "Mid Cap"),
    ("Polycab India Ltd.", "Capital Goods", "Mid Cap"), ("Voltas Ltd.", "Consumer Durables", "Mid Cap"),
    ("Fortis Healthcare Ltd.", "Healthcare", "Mid Cap"), ("Mphasis Ltd.", "Information Technology", "Mid Cap"),
    ("Ashok Leyland Ltd.", "Capital Goods", "Mid Cap"), ("Tube Investments of India Ltd.", "Automobile and Auto Components", "Mid Cap"),
    ("Multi Commodity Exchange of India Ltd.", "Financial Services", "Small Cap"), ("Blue Star Ltd.", "Consumer Durables", "Small Cap"),
    ("Kaynes Technology India Ltd.", "Capital Goods", "Small Cap"), ("Radico Khaitan Ltd.", "Fast Moving Consumer Goods", "Small Cap"),
    ("Central Depository Services (India) Ltd.", "Financial Services", "Small Cap"), ("Karur Vysya Bank Ltd.", "Financial Services", "Small Cap"),
    ("Brigade Enterprises Ltd.", "Realty", "Small Cap"), ("Finolex Industries Ltd.", "Capital Goods", "Small Cap"),
    ("Kirloskar Oil Engines Ltd.", "Capital Goods", "Small Cap"), ("Aster DM Healthcare Ltd.", "Healthcare", "Small Cap"),
    ("KPIT Technologies Ltd.", "Information Technology", "Small Cap"), ("Navin Fluorine International Ltd.", "Chemicals", "Small Cap"),
    ("Crompton Greaves Consumer Electricals Ltd.", "Consumer Durables", "Small Cap"),
    ("Cholamandalam Financial Holdings Ltd.", "Financial Services", "Small Cap"),
]
_NAV_EPOCH_DN = 16436                    # 2015-01-01
_NAV_ANCHOR_DN = 20454                   # 2026-01-01, where each NAV equals its base
_NAVS: dict[str, tuple[random.Random, list[float], list[float]]] = {}


def _nav(code: str, dn: int) -> float | None:
    """NAV of a scheme on IST day number dn."""
    if dn < _NAV_EPOCH_DN:
        return None
    _, _, _, base, vol, drift, _ = SCHEMES[code]
    with _LOCK:
        rng, xs, navs = _NAVS.setdefault(code, (random.Random(_seed("nav", code)), [0.0], []))
        i = dn - _NAV_EPOCH_DN
        while len(navs) <= i:
            d = len(navs)
            weekday = (d + _NAV_EPOCH_DN + 3) % 7
            xs[0] = xs[0] * 0.9992 + (vol * rng.gauss(0, 1) if weekday < 5 else 0.0)
            navs.append(round(base * math.exp(drift * (d + _NAV_EPOCH_DN - _NAV_ANCHOR_DN) / 365 + xs[0]), 4))
        return navs[i]


def _nav_row(code: str, dn: int) -> dict:
    name = SCHEMES[code][0]
    return {"code": code, "name": name, "nav": _nav(code, dn),
            "date": _dt.date.fromordinal(719163 + dn).strftime("%m-%d-%Y 00:00:00"),
            "isin_growth": f"INFDEMO{code}", "isin_div_payout": None, "isin_div_reinvest": None}


class DemoMutualFunds:
    demo = True

    def __init__(self, clock: Callable[[], float] = time.time):
        self._now = clock

    def _latest_dn(self) -> int:
        """NAVs are published in the evening for the last business day."""
        dn = int((self._now() + IST_OFFSET) // DAY) - 1
        while (dn + 3) % 7 >= 5:
            dn -= 1
        return dn

    def amcs(self) -> list:
        return [{"Name": n} for n in sorted({v[6] for v in SCHEMES.values()})]

    def schemes(self, name: str | None = None, category: str | None = None, type_: str | None = None) -> list:
        out = []
        for code, (scheme, cat, sub, _base, _vol, _drift, amc) in SCHEMES.items():
            if name and name.lower() not in scheme.lower() and name.lower() not in sub.lower():
                continue
            if category and category.lower() != cat.lower():
                continue
            out.append({"Code": code, "Name": scheme, "Category": cat, "SubCategory": sub, "Type": "Open Ended",
                        "ISINGrowth": f"INFDEMO{code}", "IsActive": "True", "AMC": amc})
        return out

    def categories(self) -> list:
        return [{"Category": c} for c in sorted({v[1] for v in SCHEMES.values()})]

    def nav(self, *, code: str | None = None, isin: str | None = None, name: str | None = None,
            category: str | None = None, max_rows: int = 100) -> list[dict]:
        dn = self._latest_dn()
        rows = [_nav_row(s["Code"], dn) for s in self.schemes(name=name, category=category)
                if not code or s["Code"] == code]
        return rows[:max_rows]

    def nav_on(self, date_ts: int, *, code: str | None = None, isin: str | None = None) -> list[dict]:
        if code not in SCHEMES:
            return []
        dn = int((date_ts + IST_OFFSET) // DAY)
        while (dn + 3) % 7 >= 5:
            dn -= 1
        return [_nav_row(code, dn)] if _nav(code, dn) is not None else []

    def aum(self, **_: Any) -> list:
        return []

    def holdings(self, *, code: str | None = None, isin: str | None = None, name: str | None = None,
                 filter_: str = "All") -> list[dict]:
        if code not in SCHEMES:
            return []
        _, category, sub, *_rest = SCHEMES[code]
        rng = random.Random(_seed("holdings", code))
        month = _dt.date.fromordinal(719163 + self._latest_dn()).replace(day=1) - _dt.timedelta(days=1)
        as_of = month.isoformat()
        if category == "Debt":
            papers = [("7.18% Government of India 2033", "SOV"), ("7.10% Government of India 2034", "SOV"),
                      ("National Bank for Agriculture and Rural Development", "AAA"), ("REC Ltd.", "AAA"),
                      ("Power Finance Corporation Ltd.", "AAA"), ("HDFC Bank Ltd. (Tier II)", "AAA"),
                      ("Small Industries Development Bank of India", "AAA"), ("LIC Housing Finance Ltd.", "AAA")]
            weights = sorted((rng.uniform(4, 14) for _ in papers), reverse=True)
            return [{"instrument": n, "isin": None, "industry": rating, "quantity": None, "market_value": None,
                     "weight": round(w, 2), "asset_type": "Debt", "size": None,
                     "sector": "Government" if rating == "SOV" else "Financial Services", "date": as_of}
                    for (n, rating), w in zip(papers, weights)]
        large = [(v[0], v[1], v[4], v[3], "Large Cap", _fundamentals(s)["shares"] * v[5]) for s, v in COMPANIES.items()]
        others = [(n, None, sector, sector, size, 0.0) for n, sector, size in OTHER_HOLDINGS]
        if sub == "Index Fund":                                    # the 30 largest, weighted by market value
            picks = sorted(large, key=lambda r: -r[5])[:30]
            weights = [r[5] for r in picks]
            equity = 99.6
        else:
            mid = [o for o in others if o[4] == "Mid Cap"]
            small = [o for o in others if o[4] == "Small Cap"]
            mix = {"Mid Cap Fund": (4, 14, 4), "Small Cap Fund": (2, 6, 14), "Large Cap Fund": (22, 3, 0),
                   "Flexi Cap Fund": (15, 6, 3), "ELSS": (16, 6, 2), "Balanced Advantage": (16, 3, 0)}.get(sub, (16, 5, 2))
            picks = rng.sample(large, mix[0]) + rng.sample(mid, mix[1]) + rng.sample(small, mix[2])
            weights = [rng.uniform(1.0, 9.0) ** 1.4 for _ in picks]
            equity = rng.uniform(62, 70) if category == "Hybrid" else rng.uniform(91, 97)
        scale = equity / sum(weights)
        rows = [{"instrument": r[0], "isin": r[1], "industry": r[2], "quantity": None, "market_value": None,
                 "weight": round(w * scale, 2), "asset_type": "Equity", "size": r[4], "sector": r[3], "date": as_of}
                for r, w in zip(picks, weights)]
        return sorted(rows, key=lambda h: -h["weight"])

    def holdings_what_changed(self, name: str) -> list:
        return []

    def new_fund_offers(self, range_: str = "Past365Days") -> list:
        return []


# -- news ------------------------------------------------------------------------------
_HEADLINES = {
    "positive": [
        ("Earnings", "{n} beats street estimates as quarterly profit rises {x}%"),
        ("Orders & Contracts", "{n} wins a multi-year order worth Rs {y} crore"),
        ("Broker Views", "Brokerages raise their target price on {n} after strong guidance"),
        ("Corporate Actions", "{n} board approves an interim dividend and a share buyback"),
        ("Expansion", "{n} to invest Rs {y} crore in new capacity over three years"),
        ("Index & Reshuffles", "{n} leads sector gainers as volumes surge"),
    ],
    "negative": [
        ("Earnings", "{n} misses estimates as margins narrow by {x}0 basis points"),
        ("Regulatory", "Regulator seeks clarification from {n} on disclosure lapses"),
        ("Broker Views", "Brokerages cut estimates for {n} on weak demand outlook"),
        ("Management", "{n} chief financial officer resigns; shares slip {x}%"),
        ("Earnings", "{n} lowers full-year guidance citing higher input costs"),
        ("Index & Reshuffles", "{n} drags its sector index lower on heavy selling"),
    ],
    "neutral": [
        ("Corporate Actions", "{n} fixes the record date for its dividend"),
        ("Management", "{n} appoints a new independent director to its board"),
        ("Board Meeting", "{n} to consider fund raising at its board meeting next week"),
        ("Investor Meet", "{n} to hold its analyst day; no change to guidance expected"),
    ],
}
_MACRO = [
    ("Economy", "positive", "GST collections rise {x}% year on year, signalling steady consumption"),
    ("Economy", "neutral", "RBI keeps the repo rate unchanged and retains its neutral stance"),
    ("Flows", "negative", "Foreign portfolio investors sell Rs {y} crore of Indian equities this week"),
    ("Flows", "positive", "Domestic institutions absorb foreign selling with Rs {y} crore of inflows"),
    ("Commodities", "negative", "Brent crude climbs {x}% as supply concerns return"),
    ("Commodities", "positive", "Gold eases from its record high as the dollar firms"),
    ("Currency", "neutral", "Rupee trades in a narrow range ahead of US inflation data"),
    ("IPO", "positive", "Primary market stays busy as {x} companies line up IPOs this month"),
    ("Economy", "positive", "Manufacturing PMI stays in expansion for another month"),
    ("Global Markets", "negative", "Asian markets slip as US bond yields move higher"),
    ("Derivatives", "neutral", "Nifty options data points to a narrow range before weekly expiry"),
    ("Economy", "negative", "Retail inflation edges up on food prices"),
]
_SOURCES = ["Demo Wire", "Demo Business Daily", "Demo Markets Desk"]


class DemoNews:
    demo = True

    def __init__(self, clock: Callable[[], float] = time.time):
        self._now = clock

    def _company_articles(self, symbol: str, count: int) -> list[dict]:
        name, isin, code, sector, *_ = COMPANIES.get(symbol, (symbol, None, None, None))
        now = self._now()
        move = _quote("NSE", symbol, now)["change_pct"] if symbol in COMPANIES else 0.0
        weights = [6, 2, 3] if move > 0.8 else [2, 6, 3] if move < -0.8 else [4, 3, 4]
        slot = int(now // (4 * 3600))
        out = []
        for i in range(count):
            rng = random.Random(_seed("news", symbol, slot - i))
            tone = rng.choices(["positive", "negative", "neutral"], weights=weights)[0]
            kind, template = rng.choice(_HEADLINES[tone])
            title = template.format(n=name, x=rng.randint(2, 9), y=rng.randint(4, 90) * 100)
            when = (slot - i) * 4 * 3600 + rng.randint(0, 4 * 3600 - 1)
            when = min(when, now - 60)
            out.append({
                "article_id": _seed("article", symbol, slot - i) % 10_000_000, "title": title, "specific_title": title,
                "summary": f"[DEMO] {title}. This is a synthetic article generated for the demo.",
                "long_summary": f"[DEMO] {title}. Synthetic article about {name} generated for the demo.",
                "link": None, "date": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(when)), "company": name,
                "article_type": kind, "sentiment": tone, "source": rng.choice(_SOURCES), "sector": sector,
                "symbol": symbol, "isin": isin, "scrip_code": code, "created_at": None,
            })
        return out

    def fresh(self, symbols: Iterable[str] | None = None) -> dict:
        """A brand-new article, stamped now, for the live stream. A different one every 20 seconds."""
        now = self._now()
        tick = int(now // 20)
        pool = [s for s in (symbols or []) if s in COMPANIES] or list(COMPANIES)
        rng = random.Random(_seed("fresh", tick))
        symbol = rng.choice(pool)
        name, isin, code, sector, *_ = COMPANIES[symbol]
        tone = rng.choices(["positive", "negative", "neutral"], weights=[4, 3, 3])[0]
        kind, template = rng.choice(_HEADLINES[tone])
        title = template.format(n=name, x=rng.randint(2, 9), y=rng.randint(4, 90) * 100)
        return {
            "article_id": 10_000_000 + tick % 80_000_000, "title": title, "specific_title": title,
            "summary": f"[DEMO] {title}. This is a synthetic article generated for the demo.",
            "long_summary": f"[DEMO] {title}.", "link": None,
            "date": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now)), "company": name,
            "article_type": kind, "sentiment": tone, "source": rng.choice(_SOURCES), "sector": sector,
            "symbol": symbol, "isin": isin, "scrip_code": code, "created_at": None,
        }

    def company_news(self, symbol: str | None = None, *, sentiment: str | None = None, limit: int = 20,
                     offset: int = 0, **_: Any) -> list[dict]:
        rows = self._company_articles(symbol or "RELIANCE", 30)
        if sentiment:
            rows = [r for r in rows if r["sentiment"] == sentiment.lower()]
        return rows[offset: offset + limit]

    def multi_company_news(self, symbols: Iterable[str], *, sentiment: str | None = None, limit: int = 50,
                           offset: int = 0, **_: Any) -> list[dict]:
        rows = [a for s in symbols for a in self._company_articles(s, 6)]
        if sentiment:
            rows = [r for r in rows if r["sentiment"] == sentiment.lower()]
        rows.sort(key=lambda r: r["date"], reverse=True)
        return rows[offset: offset + limit]

    def general_news(self, type_: str | None = None, *, sentiment: str | None = None, limit: int = 20,
                     offset: int = 0) -> list[dict]:
        now = self._now()
        slot = int(now // (2 * 3600))
        rows = []
        for i in range(24):
            rng = random.Random(_seed("macro", slot - i))
            kind, tone, template = rng.choice(_MACRO)
            title = template.format(x=rng.randint(2, 9), y=rng.randint(8, 95) * 100)
            when = min((slot - i) * 2 * 3600 + rng.randint(0, 7199), now - 60)
            rows.append({
                "article_id": _seed("macro-article", slot - i) % 10_000_000, "title": title, "specific_title": title,
                "summary": f"[DEMO] {title}. This is a synthetic article generated for the demo.",
                "long_summary": f"[DEMO] {title}.", "link": None,
                "date": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(when)), "company": "N/A",
                "article_type": kind, "sentiment": tone, "source": rng.choice(_SOURCES), "sector": None,
                "symbol": None, "isin": None, "scrip_code": None, "created_at": None,
            })
        if type_:
            rows = [r for r in rows if r["article_type"].lower() == type_.lower()] or rows
        if sentiment:
            rows = [r for r in rows if r["sentiment"] == sentiment.lower()]
        return rows[offset: offset + limit]
