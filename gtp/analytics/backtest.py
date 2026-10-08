"""Simple, dependency-free backtester for single-instrument strategies.

A strategy decides a target position (1 = long, 0 = flat, -1 = short) at the
close of each bar. That position earns the *next* bar's return, so there is
no look-ahead. Each change in position pays transaction costs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from . import indicators as ta

StrategyFn = Callable[[list[dict], dict], list[float]]


def _sma_cross(candles: list[dict], p: dict) -> list[float]:
    c = [b["c"] for b in candles]
    fast, slow = ta.sma(c, int(p.get("fast", 20))), ta.sma(c, int(p.get("slow", 50)))
    short = bool(p.get("allow_short", False))
    return [0.0 if f is None or s is None else (1.0 if f > s else (-1.0 if short else 0.0)) for f, s in zip(fast, slow)]


def _ema_cross(candles: list[dict], p: dict) -> list[float]:
    c = [b["c"] for b in candles]
    fast, slow = ta.ema(c, int(p.get("fast", 12))), ta.ema(c, int(p.get("slow", 26)))
    short = bool(p.get("allow_short", False))
    return [0.0 if f is None or s is None else (1.0 if f > s else (-1.0 if short else 0.0)) for f, s in zip(fast, slow)]


def _rsi_reversion(candles: list[dict], p: dict) -> list[float]:
    """Buy when RSI drops below `lower`, exit when it rises above `upper`."""
    c = [b["c"] for b in candles]
    r = ta.rsi(c, int(p.get("period", 14)))
    lower, upper = float(p.get("lower", 30)), float(p.get("upper", 55))
    pos, out = 0.0, []
    for v in r:
        if v is not None:
            if pos == 0 and v < lower:
                pos = 1.0
            elif pos == 1 and v > upper:
                pos = 0.0
        out.append(pos)
    return out


def _breakout(candles: list[dict], p: dict) -> list[float]:
    """Donchian channel breakout: long on a new N-bar high, exit on an M-bar low."""
    n_entry, n_exit = int(p.get("entry", 20)), int(p.get("exit", 10))
    h = [b["h"] or b["c"] for b in candles]
    lo = [b["l"] or b["c"] for b in candles]
    c = [b["c"] for b in candles]
    pos, out = 0.0, []
    for i in range(len(c)):
        if i >= n_entry and pos == 0 and c[i] > max(h[i - n_entry : i]):
            pos = 1.0
        elif i >= n_exit and pos == 1 and c[i] < min(lo[i - n_exit : i]):
            pos = 0.0
        out.append(pos)
    return out


def _macd_trend(candles: list[dict], p: dict) -> list[float]:
    m = ta.macd([b["c"] for b in candles], int(p.get("fast", 12)), int(p.get("slow", 26)), int(p.get("signal", 9)))
    return [0.0 if h is None else (1.0 if h > 0 else 0.0) for h in m["histogram"]]


def _buy_hold(candles: list[dict], p: dict) -> list[float]:
    return [1.0] * len(candles)


STRATEGIES: dict[str, tuple[StrategyFn, dict]] = {
    "sma_cross": (_sma_cross, {"fast": 20, "slow": 50, "allow_short": False}),
    "ema_cross": (_ema_cross, {"fast": 12, "slow": 26, "allow_short": False}),
    "rsi_reversion": (_rsi_reversion, {"period": 14, "lower": 30, "upper": 55}),
    "breakout": (_breakout, {"entry": 20, "exit": 10}),
    "macd_trend": (_macd_trend, {"fast": 12, "slow": 26, "signal": 9}),
    "buy_hold": (_buy_hold, {}),
}


@dataclass
class Trade:
    entry_time: int
    exit_time: Optional[int]
    side: str
    entry_price: float
    exit_price: Optional[float]
    return_pct: Optional[float]


@dataclass
class BacktestResult:
    strategy: str
    params: dict
    metrics: dict
    benchmark: dict
    equity: list[dict]
    trades: list[Trade] = field(default_factory=list)

    def to_dict(self, include_equity: bool = True) -> dict:
        d = {
            "strategy": self.strategy, "params": self.params, "metrics": self.metrics, "benchmark": self.benchmark,
            "trades": [t.__dict__ for t in self.trades],
        }
        if include_equity:
            d["equity"] = self.equity
        return d


def run(
    candles: Sequence[dict],
    strategy: str = "sma_cross",
    params: dict | None = None,
    *,
    initial_capital: float = 100_000.0,
    cost_bps: float = 10.0,
    periods_per_year: int = 252,
) -> BacktestResult:
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}; choose from {', '.join(STRATEGIES)}")
    candles = [b for b in candles if b.get("c")]
    if len(candles) < 3:
        raise ValueError("Need at least 3 bars to backtest")
    fn, defaults = STRATEGIES[strategy]
    p = {**defaults, **(params or {})}
    target = fn(list(candles), p)

    closes = [b["c"] for b in candles]
    cost = cost_bps / 10_000
    equity = [initial_capital]
    bench = [initial_capital]
    pos = 0.0
    trades: list[Trade] = []
    open_trade: Optional[Trade] = None
    bar_rets: list[float] = []
    for i in range(1, len(candles)):
        # position decided at close i-1 earns the return of bar i
        new_pos = target[i - 1]
        if new_pos != pos:
            if open_trade is not None:
                _close(open_trade, candles[i - 1], closes[i - 1])
                open_trade = None
            if new_pos != 0:
                open_trade = Trade(candles[i - 1]["t"], None, "long" if new_pos > 0 else "short",
                                   closes[i - 1], None, None)
                trades.append(open_trade)
        turnover = abs(new_pos - pos)
        pos = new_pos
        r = closes[i] / closes[i - 1] - 1
        strat_r = pos * r - turnover * cost
        bar_rets.append(strat_r)
        equity.append(equity[-1] * (1 + strat_r))
        bench.append(bench[-1] * (1 + r))
    if open_trade is not None:
        open_trade.exit_price = closes[-1]
        open_trade.return_pct = _trade_ret(open_trade, closes[-1])

    years = max((candles[-1]["t"] - candles[0]["t"]) / (365.25 * 86400), 1e-9)
    metrics = _metrics(equity, bar_rets, years, periods_per_year)
    closed = [t for t in trades if t.return_pct is not None]
    wins = [t for t in closed if t.return_pct > 0]
    metrics.update({
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 2) if closed else None,
        "avg_trade_pct": round(sum(t.return_pct for t in closed) / len(closed), 3) if closed else None,
        "exposure_pct": round(sum(1 for x in target[:-1] if x != 0) / (len(target) - 1) * 100, 2),
        "final_equity": round(equity[-1], 2),
    })
    bench_rets = [bench[i] / bench[i - 1] - 1 for i in range(1, len(bench))]
    benchmark = _metrics(bench, bench_rets, years, periods_per_year)
    curve = [{"t": b["t"], "equity": round(e, 2), "benchmark": round(be, 2)}
             for b, e, be in zip(candles, equity, bench)]
    return BacktestResult(strategy, p, metrics, benchmark, curve, trades)


def _close(t: Trade, bar: dict, price: float) -> None:
    t.exit_time, t.exit_price = bar["t"], price
    t.return_pct = _trade_ret(t, price)


def _trade_ret(t: Trade, price: float) -> float:
    r = price / t.entry_price - 1
    return round((r if t.side == "long" else -r) * 100, 3)


def _metrics(equity: list[float], rets: list[float], years: float, ppy: int) -> dict:
    total = equity[-1] / equity[0] - 1
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1 if equity[-1] > 0 else -1.0
    mean = sum(rets) / len(rets) if rets else 0.0
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.0
    downside = [min(r, 0) for r in rets]
    dsd = math.sqrt(sum(d * d for d in downside) / len(downside)) if downside else 0.0
    peak, mdd = equity[0], 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    return {
        "total_return_pct": round(total * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "volatility_pct": round(sd * math.sqrt(ppy) * 100, 2),
        "sharpe": round(mean / sd * math.sqrt(ppy), 3) if sd else None,
        "sortino": round(mean / dsd * math.sqrt(ppy), 3) if dsd else None,
        "max_drawdown_pct": round(mdd * 100, 2),
        "calmar": round(cagr / abs(mdd), 3) if mdd else None,
    }
