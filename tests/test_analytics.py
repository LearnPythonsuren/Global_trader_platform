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
    bad = services.company_360(hub, "UNKNOWN")
    assert "error" in bad["sections"]["ratios"] and "data" in bad["sections"]["quote"]


def test_option_chain_summary():
    rows = [{"strike": 100, "option_type": "CE", "open_interest": 10}, {"strike": 100, "option_type": "PE", "open_interest": 30},
            {"strike": 110, "option_type": "CE", "open_interest": 40}, {"strike": 90, "option_type": "PE", "open_interest": 20}]
    s = services.option_chain_summary(rows)
    assert s["pcr_oi"] == 1.0 and s["max_pain"] == 100 and s["resistance"][0] == 110
