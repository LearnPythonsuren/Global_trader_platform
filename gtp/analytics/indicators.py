"""Technical indicators in plain Python, with no numpy dependency.

Every function takes a list of floats, oldest first, and returns a list of
the same length. Positions where the indicator isn't defined yet are None.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

Series = list[Optional[float]]


def sma(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    if len(values) < n:
        return out
    k = 2 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: Sequence[float], n: int = 14) -> Series:
    """Wilder's RSI."""
    out: Series = [None] * len(values)
    if len(values) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / n, losses / n
    out[n] = _rsi(avg_g, avg_l)
    for i in range(n + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_g = (avg_g * (n - 1) + max(d, 0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0)) / n
        out[i] = _rsi(avg_g, avg_l)
    return out


def _rsi(g: float, l: float) -> float:
    if l == 0:
        return 100.0 if g > 0 else 50.0
    return 100 - 100 / (1 + g / l)


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, Series]:
    ef, es = ema(values, fast), ema(values, slow)
    line: Series = [a - b if a is not None and b is not None else None for a, b in zip(ef, es)]
    start = next((i for i, v in enumerate(line) if v is not None), len(line))
    sig_part = ema([v for v in line[start:] if v is not None], signal)
    sig: Series = [None] * start + sig_part
    hist: Series = [a - b if a is not None and b is not None else None for a, b in zip(line, sig)]
    return {"macd": line, "signal": sig, "histogram": hist}


def bollinger(values: Sequence[float], n: int = 20, k: float = 2.0) -> dict[str, Series]:
    mid = sma(values, n)
    upper: Series = [None] * len(values)
    lower: Series = [None] * len(values)
    for i in range(n - 1, len(values)):
        window = values[i - n + 1 : i + 1]
        m = mid[i]
        sd = math.sqrt(sum((x - m) ** 2 for x in window) / n)
        upper[i], lower[i] = m + k * sd, m - k * sd
    return {"middle": mid, "upper": upper, "lower": lower}


def atr(high: Sequence[float], low: Sequence[float], close: Sequence[float], n: int = 14) -> Series:
    tr = [high[0] - low[0]] + [
        max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])) for i in range(1, len(close))
    ]
    out: Series = [None] * len(close)
    if len(tr) < n:
        return out
    prev = sum(tr[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(tr)):
        prev = (prev * (n - 1) + tr[i]) / n
        out[i] = prev
    return out


def donchian(high: Sequence[float], low: Sequence[float], n: int = 20) -> dict[str, Series]:
    up: Series = [None] * len(high)
    dn: Series = [None] * len(low)
    for i in range(n - 1, len(high)):
        up[i] = max(high[i - n + 1 : i + 1])
        dn[i] = min(low[i - n + 1 : i + 1])
    return {"upper": up, "lower": dn}


def pct_change(values: Sequence[float], periods: int) -> Optional[float]:
    if len(values) <= periods or not values[-periods - 1]:
        return None
    return (values[-1] / values[-periods - 1] - 1) * 100


def annualized_volatility(values: Sequence[float], periods_per_year: int = 252) -> Optional[float]:
    rets = [math.log(values[i] / values[i - 1]) for i in range(1, len(values)) if values[i - 1] > 0 and values[i] > 0]
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * periods_per_year) * 100


INDICATORS = ("sma", "ema", "rsi", "macd", "bollinger", "atr")


def compute(candles: list[dict], specs: Sequence[str]) -> dict[str, object]:
    """Compute indicators from specs like "sma:50", "rsi:14", "macd", "bollinger:20".

    Returns {spec: series or {component: series}}, aligned with ``candles``.
    """
    c = [b["c"] for b in candles]
    h = [b["h"] if b["h"] is not None else b["c"] for b in candles]
    lo = [b["l"] if b["l"] is not None else b["c"] for b in candles]
    out: dict[str, object] = {}
    for spec in specs:
        name, _, arg = spec.strip().lower().partition(":")
        args = [float(a) for a in arg.split(",") if a] if arg else []
        if name == "sma":
            out[spec] = _r(sma(c, int(args[0]) if args else 20))
        elif name == "ema":
            out[spec] = _r(ema(c, int(args[0]) if args else 20))
        elif name == "rsi":
            out[spec] = _r(rsi(c, int(args[0]) if args else 14))
        elif name == "macd":
            f, s, g = (int(a) for a in (args + [12, 26, 9][len(args):])[:3])
            out[spec] = {k: _r(v) for k, v in macd(c, f, s, g).items()}
        elif name == "bollinger":
            n = int(args[0]) if args else 20
            k = args[1] if len(args) > 1 else 2.0
            out[spec] = {k_: _r(v) for k_, v in bollinger(c, n, k).items()}
        elif name == "atr":
            out[spec] = _r(atr(h, lo, c, int(args[0]) if args else 14))
        else:
            raise ValueError(f"Unknown indicator {name!r}; choose from {', '.join(INDICATORS)}")
    return out


def _r(series: Series, nd: int = 4) -> Series:
    return [None if v is None else round(v, nd) for v in series]


def snapshot(candles: list[dict]) -> dict:
    """Headline technical numbers for the latest bar of a daily series."""
    if not candles:
        return {}
    c = [b["c"] for b in candles]
    last = c[-1]
    s50, s200 = sma(c, 50)[-1], sma(c, 200)[-1]
    window = candles[-252:]
    hi52 = max(b["h"] or b["c"] for b in window)
    lo52 = min(b["l"] or b["c"] for b in window)
    trend = None
    if s50 is not None and s200 is not None:
        trend = "uptrend" if last > s50 > s200 else "downtrend" if last < s50 < s200 else "sideways"
    return {
        "close": last,
        "rsi14": _round(rsi(c, 14)[-1]),
        "sma20": _round(sma(c, 20)[-1]),
        "sma50": _round(s50),
        "sma200": _round(s200),
        "above_sma200": None if s200 is None else last > s200,
        "trend": trend,
        "change_1w_pct": _round(pct_change(c, 5)),
        "change_1m_pct": _round(pct_change(c, 21)),
        "change_3m_pct": _round(pct_change(c, 63)),
        "change_1y_pct": _round(pct_change(c, 252)),
        "high_52w": hi52,
        "low_52w": lo52,
        "pct_from_52w_high": _round((last / hi52 - 1) * 100) if hi52 else None,
        "volatility_1y_pct": _round(annualized_volatility(c[-253:])),
        "atr14": _round(atr([b["h"] or b["c"] for b in candles], [b["l"] or b["c"] for b in candles], c)[-1]),
    }


def _round(v: Optional[float], nd: int = 2) -> Optional[float]:
    return None if v is None else round(v, nd)
