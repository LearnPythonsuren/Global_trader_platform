"""The simulated market must be internally consistent at every time of day."""

import datetime as dt

import pytest

from gtp.gdf import demo as D


def ist(y, m, d, hh, mm, ss=0):
    return (dt.date(y, m, d).toordinal() - 719163) * 86400 + hh * 3600 + mm * 60 + ss - D.IST_OFFSET


MOMENTS = {
    "first second of the session": ist(2026, 11, 10, 9, 15, 0),
    "inside the first minute": ist(2026, 11, 10, 9, 15, 20),
    "just before a 5-minute boundary": ist(2026, 11, 10, 9, 19, 59),
    "on a 5-minute boundary": ist(2026, 11, 10, 9, 20, 0),
    "mid-session": ist(2026, 11, 10, 11, 7, 30),
    "last second of the session": ist(2026, 11, 10, 15, 29, 59),
    "at the close": ist(2026, 11, 10, 15, 30, 0),
    "evening": ist(2026, 11, 10, 22, 0),
    "saturday": ist(2026, 11, 14, 12, 0),
    "monday before the open": ist(2026, 11, 16, 8, 0),
}


def test_session_calendar():
    k, minutes, _ = D.session_state(MOMENTS["mid-session"])
    assert D._date_of_k(k) == dt.date(2026, 11, 10) and minutes == 112
    assert D.session_state(MOMENTS["at the close"])[1] is None
    for name in ("saturday", "monday before the open"):          # both show Friday's completed session
        k, minutes, _ = D.session_state(MOMENTS[name])
        assert D._date_of_k(k) == dt.date(2026, 11, 13) and minutes is None
    for k in (0, 4, 5, 2868, 3100):
        assert D._k_of_dn(D._dn_of_k(k)) == k and (D._dn_of_k(k) + 3) % 7 < 5


@pytest.mark.parametrize("moment", MOMENTS)
@pytest.mark.parametrize("symbol", ["RELIANCE", "TATASTEEL", "NIFTY 50", "INDIA VIX"])
def test_quotes_daily_and_intraday_bars_agree(moment, symbol):
    now = MOMENTS[moment]
    price = D.DemoPrice(clock=lambda: now)
    quote = price.last_quote("NSE", symbol)
    daily = price.history("NSE", symbol, "DAY", max_bars=5)
    today_open = D._open_ts(D.session_state(now)[0])
    for periodicity, period in (("MINUTE", 1), ("MINUTE", 5), ("MINUTE", 15), ("HOUR", 1)):
        bars = [b for b in price.history("NSE", symbol, periodicity, period, max_bars=2000) if b["t"] >= today_open]
        assert bars[-1]["c"] == quote["ltp"] == daily[-1]["c"]
        assert bars[0]["o"] == daily[-1]["o"] == quote["open"]
        assert abs(max(b["h"] for b in bars) - daily[-1]["h"]) < 0.011
        assert abs(min(b["l"] for b in bars) - daily[-1]["l"]) < 0.011
        assert abs(sum(b["v"] for b in bars) - daily[-1]["v"]) <= max(400, daily[-1]["v"] * 0.002)
        assert all(b["l"] <= min(b["o"], b["c"]) and b["h"] >= max(b["o"], b["c"]) for b in bars)
        assert all(a["t"] < b["t"] for a, b in zip(bars, bars[1:]))
    assert quote["prev_close"] == daily[-2]["c"]
    assert quote["high"] == daily[-1]["h"] and quote["low"] == daily[-1]["l"]


def test_minute_bars_rebuild_past_daily_bars():
    now = MOMENTS["evening"]
    price = D.DemoPrice(clock=lambda: now)
    daily = price.history("NSE", "INFY", "DAY", max_bars=6)
    minutes = price.history("NSE", "INFY", "MINUTE", 1, max_bars=375 * 5)
    k = D.session_state(now)[0]
    for back in range(1, 5):
        day, start = daily[-1 - back], D._open_ts(k - back)
        bars = [b for b in minutes if start <= b["t"] < start + 375 * 60]
        assert len(bars) == 375 and bars[0]["o"] == day["o"] and bars[-1]["c"] == day["c"]
        assert abs(max(b["h"] for b in bars) - day["h"]) < 0.011 and abs(min(b["l"] for b in bars) - day["l"]) < 0.011


def test_history_is_stable_from_one_day_to_the_next():
    today = D.DemoPrice(clock=lambda: MOMENTS["evening"]).history("NSE", "INFY", "DAY", max_bars=6)
    tomorrow = D.DemoPrice(clock=lambda: MOMENTS["evening"] + 86400).history("NSE", "INFY", "DAY", max_bars=7)
    assert tomorrow[-3] == today[-2] and tomorrow[-4] == today[-3]


def test_week_and_month_bars_group_by_calendar():
    price = D.DemoPrice(clock=lambda: MOMENTS["evening"])
    weeks = price.history("NSE", "INFY", "WEEK", max_bars=8)
    months = price.history("NSE", "INFY", "MONTH", max_bars=6)
    assert len(weeks) == 8 and len(months) == 6
    ends = [dt.date.fromordinal(719163 + (b["t"] + D.IST_OFFSET) // 86400) for b in months]
    assert [d.month for d in ends] == [6, 7, 8, 9, 10, 11] and ends[-1] == dt.date(2026, 11, 10)
    assert all(dt.date.fromordinal(719163 + (b["t"] + D.IST_OFFSET) // 86400).weekday() == 4 for b in weeks[:-1])


def test_unknown_symbols():
    price = D.DemoPrice(clock=lambda: MOMENTS["evening"])
    with pytest.raises(LookupError):
        price.last_quote("NSE", "NOPE")
    assert [q["symbol"] for q in price.last_quotes("NSE", ["TCS", "NOPE"])] == ["TCS"]


def test_option_chain_respects_put_call_parity():
    now = MOMENTS["mid-session"]
    price = D.DemoPrice(clock=lambda: now)
    spot = price.last_quote("NSE_IDX", "NIFTY 50")["ltp"]
    rows = price.option_chain("NFO", "NIFTY")
    assert {r["expiry"] for r in rows} == {"10NOV2026"}             # a Tuesday: the weekly expiry day
    by_strike = {}
    for r in rows:
        by_strike.setdefault(r["strike"], {})[r["option_type"]] = r["ltp"]
    atm = min(by_strike, key=lambda k: abs(by_strike[k]["CE"] - by_strike[k]["PE"]))
    assert abs(atm - spot) <= 50
    assert price.option_chain("NFO", "NIFTY", "24NOV2026")[0]["expiry"] == "24NOV2026"
    with pytest.raises(ValueError):
        price.option_chain("NFO", "NIFTY", "next week")


def test_fund_navs_and_holdings():
    funds = D.DemoMutualFunds(clock=lambda: MOMENTS["evening"])
    nav = funds.nav(code="122639")[0]
    assert nav["date"].startswith("11-09-2026") and nav["nav"] > 0
    assert funds.nav_on(MOMENTS["evening"] - 400 * 86400, code="122639")[0]["nav"] != nav["nav"]
    assert funds.nav_on(0, code="122639") == []
    index = funds.holdings(code="120716")
    assert len(index) == 30 and abs(sum(h["weight"] for h in index) - 99.6) < 0.5
    small = funds.holdings(code="125497")
    assert sum(1 for h in small if h["size"] == "Small Cap") >= 10
    assert all(h["asset_type"] == "Debt" for h in funds.holdings(code="119062"))


def test_news_stream_article_changes_over_time():
    news = D.DemoNews(clock=lambda: MOMENTS["mid-session"])
    later = D.DemoNews(clock=lambda: MOMENTS["mid-session"] + 20)
    assert news.fresh(["TCS"])["symbol"] == "TCS"
    assert news.fresh()["article_id"] != later.fresh()["article_id"]
    assert len(news.company_news("INFY", limit=5)) == 5 and len(news.general_news(limit=8)) == 8
