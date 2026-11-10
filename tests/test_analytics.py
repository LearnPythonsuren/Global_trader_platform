import pytest

from gtp import services
from gtp.analytics import backtest, funds, screener, sentiment
from gtp.analytics import indicators as ta
from gtp.config import Settings
from gtp.gdf import DataHub


@pytest.fixture(scope="module")
def hub():
    return DataHub.from_settings(Settings())


def bars(closes):
    return [{"t": 86400 * i, "o": c, "h": c, "l": c, "c": c, "v": 1, "oi": None} for i, c in enumerate(closes)]


def test_sma_ema_rsi_basics():
    assert ta.sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    e = ta.ema([1, 2, 3, 4, 5], 3)
    assert e[:2] == [None, None] and e[2] == 2 and e[3] == pytest.approx(3.0)
    assert ta.rsi(list(range(1, 30)), 14)[-1] == 100.0
    assert ta.rsi(list(range(30, 1, -1)), 14)[-1] == pytest.approx(0.0)


def test_compute_specs():
    out = ta.compute(bars([float(x) for x in range(1, 60)]), ["sma:5", "macd", "bollinger:20,2", "rsi"])
    assert set(out) == {"sma:5", "macd", "bollinger:20,2", "rsi"}
    assert set(out["macd"]) == {"macd", "signal", "histogram"}
    with pytest.raises(ValueError):
        ta.compute(bars([1.0, 2.0]), ["nope"])


def test_backtest_has_no_lookahead():
    # Price doubles on the bar after the signal flips; a look-ahead bug would capture the jump on the same bar.
    closes = [10.0] * 30 + [20.0] * 5
    res = backtest.run(bars(closes), "buy_hold", cost_bps=0)
    assert res.metrics["total_return_pct"] == pytest.approx(100.0)
    flat = backtest.run(bars([10.0] * 40), "sma_cross", {"fast": 2, "slow": 5}, cost_bps=0)
    assert flat.metrics["total_return_pct"] == 0


def test_backtest_costs_and_all_strategies(hub):
    candles = hub.price.history("NSE", "TCS", max_bars=600)
    for name in backtest.STRATEGIES:
        r = backtest.run(candles, name)
        assert len(r.equity) == len(candles)
        assert r.metrics["max_drawdown_pct"] <= 0
    cheap = backtest.run(candles, "sma_cross", cost_bps=0).metrics["final_equity"]
    dear = backtest.run(candles, "sma_cross", cost_bps=50).metrics["final_equity"]
    assert dear < cheap
    with pytest.raises(ValueError):
        backtest.run(candles, "unknown")


def test_screener(hub):
    res = screener.screen(hub, ["TCS", "INFY", "BOGUS"], [{"field": "pe", "op": ">", "value": 0}], sort="-pe")
    syms = [r["symbol"] for r in res["results"]]
    assert set(syms) == {"TCS", "INFY"}
    assert res["results"][0]["pe"] >= res["results"][1]["pe"]
    assert res["failed"][0]["symbol"] == "BOGUS"
    with pytest.raises(ValueError):
        screener.screen(hub, ["TCS"], [{"field": "nope", "op": "<", "value": 1}])


def test_matches_ops():
    row = {"pe": 10, "sector": "Banks", "above_sma200": True}
    assert screener.matches(row, [{"field": "pe", "op": "between", "value": [5, 15]}])
    assert screener.matches(row, [{"field": "sector", "op": "==", "value": "banks"}])
    assert not screener.matches(row, [{"field": "rsi14", "op": "<", "value": 30}])  # missing field never matches


def test_sentiment_score():
    s = sentiment.score([{"sentiment": "positive"}] * 3 + [{"sentiment": "negative"}])
    assert s["net_score"] == 0.5 and s["label"] == "bullish"
    assert sentiment.score([])["label"] == "no coverage"


def test_funds(hub):
    r = funds.returns(hub, "122639")
    assert r["returns"]["1y"]["absolute_pct"] is not None and "cagr_pct" in r["returns"]["3y"]
    ov = funds.overlap(hub, "122639", "122639")
    assert ov["overlap_pct"] == pytest.approx(sum(h["weight"] for h in hub.mutual_funds.holdings(code="122639")), 0.1)
    assert funds.exposure(hub.mutual_funds.holdings(code="122639"))["by_sector"]


def test_company_360_isolates_failures(hub):
    r = services.company_360(hub, "TCS")
    assert all("data" in v for v in r["sections"].values())
    balance = r["sections"]["signal_balance"]["data"]
    assert -1 <= balance["score"] <= 1 and balance["bullish"] + balance["bearish"] + balance["neutral"] == \
        len(r["sections"]["signals"]["data"])

    class NoFundamentals:
        def __getattr__(self, name):
            def fail(*a, **k):
                raise RuntimeError("fundamental data is not part of this subscription")
            return fail

    partial = DataHub(price=hub.price, fundamentals=NoFundamentals(), mutual_funds=hub.mutual_funds,
                      news=hub.news, demo=True)
    bad = services.company_360(partial, "TCS")["sections"]
    assert "error" in bad["ratios"] and "error" in bad["shareholding"]
    assert "data" in bad["quote"] and "data" in bad["news"] and "data" in bad["signals"]


def test_signal_balance():
    b = services.signal_balance([{"tone": "bullish"}, {"tone": "bullish"}, {"tone": "bearish"}, {"tone": "neutral"}])
    assert b == {"bullish": 2, "bearish": 1, "neutral": 1, "score": 0.333, "label": "mixed"}
    assert services.signal_balance([])["label"] == "no clear signals"


def test_heatmap_sparklines_and_trend(hub):
    h = services.market_heatmap(hub, ["TCS", "INFY", "HDFCBANK", "BOGUS"])
    assert {s["symbol"] for s in h["stocks"]} == {"TCS", "INFY", "HDFCBANK"} and h["missing"] == ["BOGUS"]
    it = next(s for s in h["sectors"] if s["sector"] == "Information Technology")
    assert it["stocks"] == 2 and it["advancers"] + it["decliners"] <= 2
    assert sum(h["breadth"].values()) == 3
    sp = services.sparklines(hub, ["TCS", "BOGUS"], bars=30)
    assert list(sp) == ["TCS"] and len(sp["TCS"]) == 30
    trend = services.financial_trend(hub, "TCS", quarters=4)
    assert len(trend) == 4 and all(t["revenue"] > t["net_profit"] > 0 for t in trend)
    assert [t["period"] for t in trend] == [q for _, q in services.recent_quarters(__import__("time").time(), 4)][::-1]


def test_recent_quarters():
    import calendar
    nov = calendar.timegm((2026, 11, 10, 6, 0, 0))
    assert services.recent_quarters(nov, 3) == [(2026, "QS"), (2026, "QJ"), (2025, "QM")]
    feb = calendar.timegm((2026, 2, 10, 6, 0, 0))
    assert services.recent_quarters(feb, 2) == [(2025, "QD"), (2025, "QS")]
    apr = calendar.timegm((2026, 4, 2, 6, 0, 0))
    assert services.recent_quarters(apr, 1) == [(2025, "QM")]


def test_backtest_compare(hub):
    out = backtest.compare(hub.price.history("NSE", "INFY", max_bars=500))
    names = [r["strategy"] for r in out["results"]]
    assert set(names) == set(backtest.STRATEGIES) - {"buy_hold"} and out["benchmark"]["total_return_pct"] is not None
    returns = [r["metrics"]["total_return_pct"] for r in out["results"]]
    assert returns == sorted(returns, reverse=True)


def test_option_chain_summary():
    rows = [{"strike": 100, "option_type": "CE", "open_interest": 10}, {"strike": 100, "option_type": "PE", "open_interest": 30},
            {"strike": 110, "option_type": "CE", "open_interest": 40}, {"strike": 90, "option_type": "PE", "open_interest": 20}]
    s = services.option_chain_summary(rows)
    assert s["pcr_oi"] == 1.0 and s["max_pain"] == 100 and s["resistance"][0] == 110
    priced = [{"strike": k, "option_type": t, "open_interest": 1, "ltp": p} for k, t, p in
              ((90, "CE", 12), (90, "PE", 1), (100, "CE", 4), (100, "PE", 3.5), (110, "CE", 1), (110, "PE", 11))]
    assert services.option_chain_summary(priced)["atm_strike"] == 100
