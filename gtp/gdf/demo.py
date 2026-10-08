"""Offline demo providers with the same methods as the live GDF clients.

They return deterministic synthetic data (same symbol gives the same series)
shaped like the normalised live responses. This lets you demo the product,
develop, and run tests without Global Datafeeds keys. Nothing here is real
market data, and every payload served in demo mode says so.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from typing import Any, Iterable

COMPANIES: dict[str, dict[str, Any]] = {
    "RELIANCE": ("Reliance Industries Ltd.", "INE002A01018", 500325, "Energy", "Oil Gas & Consumable Fuels", 2900),
    "TCS": ("Tata Consultancy Services Ltd.", "INE467B01029", 532540, "Information Technology", "IT - Software", 3600),
    "HDFCBANK": ("HDFC Bank Ltd.", "INE040A01034", 500180, "Financial Services", "Banks", 1650),
    "INFY": ("Infosys Ltd.", "INE009A01021", 500209, "Information Technology", "IT - Software", 1550),
    "ICICIBANK": ("ICICI Bank Ltd.", "INE090A01021", 532174, "Financial Services", "Banks", 1200),
    "HINDUNILVR": ("Hindustan Unilever Ltd.", "INE030A01027", 500696, "FMCG", "Personal Care", 2450),
    "ITC": ("ITC Ltd.", "INE154A01025", 500875, "FMCG", "Cigarettes & Tobacco", 430),
    "SBIN": ("State Bank of India", "INE062A01020", 500112, "Financial Services", "Banks", 780),
    "BHARTIARTL": ("Bharti Airtel Ltd.", "INE397D01024", 532454, "Telecommunication", "Telecom Services", 1600),
    "KOTAKBANK": ("Kotak Mahindra Bank Ltd.", "INE237A01028", 500247, "Financial Services", "Banks", 1800),
    "LT": ("Larsen & Toubro Ltd.", "INE018A01030", 500510, "Capital Goods", "Construction", 3500),
    "AXISBANK": ("Axis Bank Ltd.", "INE238A01034", 532215, "Financial Services", "Banks", 1100),
    "ASIANPAINT": ("Asian Paints Ltd.", "INE021A01026", 500820, "Consumer Durables", "Paints", 2850),
    "MARUTI": ("Maruti Suzuki India Ltd.", "INE585B01010", 532500, "Automobile", "Passenger Cars", 12000),
    "SUNPHARMA": ("Sun Pharmaceutical Industries Ltd.", "INE044A01036", 524715, "Healthcare", "Pharmaceuticals", 1700),
    "TITAN": ("Titan Company Ltd.", "INE280A01028", 500114, "Consumer Durables", "Jewellery", 3400),
    "BAJFINANCE": ("Bajaj Finance Ltd.", "INE296A01032", 500034, "Financial Services", "NBFC", 7000),
    "WIPRO": ("Wipro Ltd.", "INE075A01022", 507685, "Information Technology", "IT - Software", 520),
    "ULTRACEMCO": ("UltraTech Cement Ltd.", "INE481G01011", 532538, "Construction Materials", "Cement", 11000),
    "TATAMOTORS": ("Tata Motors Ltd.", "INE155A01022", 500570, "Automobile", "Passenger Cars", 950),
}
INDICES = {"NIFTY 50": 24500, "NIFTY BANK": 52000, "SENSEX": 80500}

DAY = 86400


def _seed(*parts: Any) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _base_price(symbol: str) -> float:
    if symbol in COMPANIES:
        return float(COMPANIES[symbol][5])
    if symbol in INDICES:
        return float(INDICES[symbol])
    return 100 + _seed(symbol) % 2000


def _daily_series(symbol: str, days: int = 1500) -> list[dict]:
    """Deterministic daily OHLCV path ending today (weekdays only)."""
    rng = random.Random(_seed("daily", symbol))
    drift = rng.uniform(-0.0002, 0.0008)
    vol = rng.uniform(0.011, 0.022)
    today = int(time.time()) // DAY * DAY
    dates = []
    d = today
    while len(dates) < days:
        if time.gmtime(d).tm_wday < 5:
            dates.append(d)
        d -= DAY
    dates.reverse()
    # walk backwards from the anchor price so "today" stays near the base price
    price = _base_price(symbol)
    closes = [price]
    for _ in range(days - 1):
        price = price / math.exp(drift + vol * rng.gauss(0, 1))
        closes.append(price)
    closes.reverse()
    out = []
    prev = closes[0]
    for t, c in zip(dates, closes):
        o = prev * (1 + rng.gauss(0, vol / 3))
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        v = int(rng.uniform(0.5, 1.5) * 2_000_000 * 1000 / max(c, 1))
        out.append({"t": t + 10 * 3600, "o": round(o, 2), "h": round(h, 2), "l": round(lo, 2),
                    "c": round(c, 2), "v": v, "oi": None})
        prev = c
    return out


def _resample(candles: list[dict], bucket: int) -> list[dict]:
    out: list[dict] = []
    for c in candles:
        key = c["t"] // bucket
        if out and out[-1]["_k"] == key:
            b = out[-1]
            b["h"], b["l"], b["c"] = max(b["h"], c["h"]), min(b["l"], c["l"]), c["c"]
            b["v"] += c["v"]
        else:
            out.append({**c, "_k": key})
    for b in out:
        b.pop("_k")
    return out


class DemoPrice:
    demo = True

    def last_quote(self, exchange: str, symbol: str) -> dict:
        bars = _daily_series(symbol)
        last, prev = bars[-1], bars[-2]
        rng = random.Random(_seed("q", symbol, int(time.time()) // 5))
        ltp = round(last["c"] * (1 + rng.gauss(0, 0.001)), 2)
        return {
            "exchange": exchange, "symbol": symbol, "ltp": ltp, "open": last["o"],
            "high": max(last["h"], ltp), "low": min(last["l"], ltp), "prev_close": prev["c"],
            "change": round(ltp - prev["c"], 2), "change_pct": round((ltp / prev["c"] - 1) * 100, 2),
            "volume": last["v"], "value": round(last["v"] * ltp, 2), "atp": round((last["h"] + last["l"]) / 2, 2),
            "bid": round(ltp - 0.05, 2), "ask": round(ltp + 0.05, 2), "bid_qty": 100, "ask_qty": 120,
            "open_interest": None, "lot_size": 1, "last_trade_time": int(time.time()), "server_time": int(time.time()),
        }

    def last_quotes(self, exchange: str, symbols: Iterable[str]) -> list[dict]:
        return [self.last_quote(exchange, s) for s in symbols]

    def history(self, exchange: str, symbol: str, periodicity: str = "DAY", period: int = 1,
                from_ts: int | None = None, to_ts: int | None = None, max_bars: int = 0,
                adjust_splits: bool = True) -> list[dict]:
        periodicity = periodicity.upper()
        if periodicity in ("MINUTE", "HOUR", "TICK"):
            bars = self._intraday(symbol, 60 if periodicity != "HOUR" else 3600, period)
        else:
            bars = _daily_series(symbol)
            if periodicity == "DAY" and period > 1:
                bars = bars[::period]
            elif periodicity == "WEEK":
                bars = _resample(bars, 7 * DAY * period)
            elif periodicity == "MONTH":
                bars = _resample(bars, 30 * DAY * period)
        if from_ts:
            bars = [b for b in bars if b["t"] >= from_ts]
        if to_ts:
            bars = [b for b in bars if b["t"] <= to_ts]
        if max_bars:
            bars = bars[-max_bars:]
        return bars

    def _intraday(self, symbol: str, step: int, period: int) -> list[dict]:
        rng = random.Random(_seed("intra", symbol, int(time.time()) // DAY))
        price = _daily_series(symbol)[-2]["c"]
        start = int(time.time()) // DAY * DAY + 3 * 3600 + 45 * 60  # 09:15 IST
        out = []
        n = (375 * 60) // (step * period)
        for i in range(n):
            o = price
            price = price * math.exp(rng.gauss(0, 0.0012 * math.sqrt(step * period / 60)))
            out.append({"t": start + i * step * period, "o": round(o, 2), "h": round(max(o, price) * 1.0005, 2),
                        "l": round(min(o, price) * 0.9995, 2), "c": round(price, 2),
                        "v": int(rng.uniform(1000, 20000)), "oi": None})
        return out

    def search_instruments(self, exchange: str, search: str, **filters: Any) -> list[dict]:
        q = search.upper()
        rows = [{"Identifier": s, "Name": v[0], "Exchange": exchange, "QuotationLot": 1}
                for s, v in COMPANIES.items() if q in s or q in v[0].upper()]
        rows += [{"Identifier": s, "Name": s, "Exchange": "NSE_IDX", "QuotationLot": 1} for s in INDICES if q in s]
        return rows

    def option_chain(self, exchange: str, product: str, expiry: str | None = None, option_type: str | None = None,
                     strike_price: float | None = None) -> list[dict]:
        spot = self.last_quote("NSE_IDX" if product.upper() in ("NIFTY", "BANKNIFTY") else "NSE",
                               {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK"}.get(product.upper(), product))["ltp"]
        step = 50 if spot < 30000 else 100
        atm = round(spot / step) * step
        expiry = expiry or time.strftime("%d%b%Y", time.gmtime(time.time() + 7 * DAY)).upper()
        rows = []
        rng = random.Random(_seed("oc", product, expiry))
        for k in range(-10, 11):
            strike = atm + k * step
            for ot in ("CE", "PE"):
                if option_type and ot != option_type:
                    continue
                if strike_price and strike != strike_price:
                    continue
                intrinsic = max(0.0, spot - strike) if ot == "CE" else max(0.0, strike - spot)
                tv = spot * 0.01 * math.exp(-abs(strike - spot) / (spot * 0.03))
                ltp = round(intrinsic + tv, 2)
                oi = int(rng.uniform(5e4, 5e6) * math.exp(-abs(k) / 6))
                rows.append({
                    "exchange": exchange, "symbol": f"OPTIDX_{product.upper()}_{expiry}_{ot}_{strike}",
                    "strike": strike, "option_type": ot, "expiry": expiry, "ltp": ltp,
                    "open_interest": oi, "oi_change": int(oi * rng.uniform(-0.2, 0.3)),
                    "volume": int(oi * rng.uniform(0.5, 3)), "change_pct": round(rng.uniform(-30, 30), 2),
                })
        return rows

    def top_gainers_losers(self, exchange: str, **params: Any) -> dict:
        quotes = sorted(self.last_quotes(exchange, COMPANIES), key=lambda q: q["change_pct"])
        return {"gainers": quotes[::-1][:5], "losers": quotes[:5]}

    def exchanges(self) -> list[str]:
        return ["NSE", "NSE_IDX", "NFO", "BSE", "BSE_IDX", "BFO", "MCX", "CDS"]


class DemoFundamentals:
    demo = True

    def _info(self, symbol: str) -> tuple:
        if symbol not in COMPANIES:
            raise KeyError(f"Unknown demo symbol {symbol!r}. Demo symbols: {', '.join(COMPANIES)}")
        return COMPANIES[symbol]

    def company(self, exchange: str, symbol: str) -> dict:
        name, isin, code, *_ = self._info(symbol)
        return {"Symbol": symbol, "ScripCode": code, "CompanyName": name, "ISIN": isin}

    def ratios(self, exchange: str, symbol: str, **_: Any) -> dict:
        self._info(symbol)
        rng = random.Random(_seed("ratios", symbol))
        bars = _daily_series(symbol)[-252:]
        close = bars[-1]["c"]
        pe = rng.uniform(9, 55)
        eps = close / pe
        shares = rng.uniform(1e12, 2e13) / close  # market cap of ₹1-20 lakh crore
        bv = close / rng.uniform(0.8, 6.0)
        debt = 0 if rng.random() < 0.3 else rng.uniform(1e10, 3e12)
        return {
            "close": close, "year": time.gmtime().tm_year, "last_quarter": "QJ",
            "market_cap": round(close * shares / 1e7, 2), "week52_high": max(b["h"] for b in bars),
            "week52_low": min(b["l"] for b in bars), "eps": round(eps, 2), "pe": round(pe, 2),
            "book_value": round(bv, 2), "dividend_yield": round(rng.uniform(0, 3.5), 2),
            "ebit": round(eps * shares * 1.4), "interest_coverage": round(rng.uniform(2, 90), 2),
            "face_value": rng.choice([1, 2, 5, 10]), "price_sales": round(rng.uniform(0.8, 12), 2),
            "profit_after_tax": round(eps * shares), "enterprise_value": round(close * shares + debt),
            "debt": round(debt), "pb": round(close / bv, 2),
            "pct_from_52w_high": round((close / max(b["h"] for b in bars) - 1) * 100, 2),
        }

    def sector(self, exchange: str, symbol: str) -> dict:
        name, _, _, sector, industry, _ = self._info(symbol)
        return {"Symbol": symbol, "Sector": sector, "Industry": industry, "BasicIndustry": industry}

    def shareholding(self, exchange: str, symbol: str, **_: Any) -> list[dict]:
        self._info(symbol)
        rng = random.Random(_seed("shp", symbol))
        promoter = rng.uniform(0, 72)
        fii = rng.uniform(10, 45)
        dii = rng.uniform(8, 30)
        total = promoter + fii + dii
        if total > 95:
            f = 95 / total
            promoter, fii, dii = promoter * f, fii * f, dii * f
        public = 100 - promoter - fii - dii
        return [{"Category": k, "Percentage": round(v, 2)} for k, v in
                (("Promoter", promoter), ("FII", fii), ("DII", dii), ("Public", public))]

    def financial_results(self, exchange: str, symbol: str, year: int, **_: Any) -> list[dict]:
        rng = random.Random(_seed("fin", symbol, year))
        rev = rng.uniform(5e10, 2.5e12)
        rows = []
        for q in ("QJ", "QS", "QD", "QM"):
            rev *= rng.uniform(0.97, 1.08)
            rows.append({"Period": q, "Year": year, "Revenue": round(rev), "NetProfit": round(rev * rng.uniform(0.08, 0.22))})
        return rows

    def announcements(self, exchange: str, symbol: str | None, from_ts: int, to_ts: int, **_: Any) -> list[dict]:
        sym = symbol or "RELIANCE"
        name = COMPANIES.get(sym, (sym,))[0]
        rng = random.Random(_seed("ann", sym))
        heads = ["Board Meeting Intimation for Financial Results", "Press Release / Media Release",
                 "Analyst / Investor Meet - Intimation", "Outcome of Board Meeting", "Change in Directorate"]
        return [{"ScripId": sym, "ScripName": name.upper(), "HeadLine": f"{name}: {h}", "Descriptor": h,
                 "FillingDate": time.strftime("%m-%d-%Y", time.gmtime(to_ts - i * 3 * DAY)), "AttachmentUrl": None}
                for i, h in enumerate(rng.sample(heads, 3))]

    def corporate_actions(self, exchange: str, symbol: str | None, from_ts: int, to_ts: int) -> list[dict]:
        return [{"ScripId": symbol or "RELIANCE", "Purpose": "Dividend - Rs 10 Per Share",
                 "ExDate": time.strftime("%m-%d-%Y", time.gmtime(to_ts - 20 * DAY))}]

    def results_calendar(self, exchange: str, range_: str = "Next7Days", symbols: list[str] | None = None) -> list:
        now = int(time.time())
        return [{"ScripId": s, "MeetingDate": time.strftime("%m-%d-%Y", time.gmtime(now + (i + 1) * DAY)),
                 "Purpose": "Quarterly Results"} for i, s in enumerate((symbols or list(COMPANIES))[:5])]

    def bulk_deals(self, *a: Any, **k: Any) -> list:
        return []

    block_deals = bulk_deals

    def fii_dii(self, *a: Any, **k: Any) -> list:
        return []


SCHEMES = {
    "149264": ("NJ Balanced Advantage Fund - Direct Plan - Growth Option", "Hybrid", "Balanced Advantage", 13.2, 0.007),
    "118989": ("HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth", "Equity", "Mid Cap Fund", 190.0, 0.011),
    "120503": ("Axis ELSS Tax Saver Fund - Direct Plan - Growth", "Equity", "ELSS", 98.0, 0.010),
    "122639": ("Parag Parikh Flexi Cap Fund - Direct Plan - Growth", "Equity", "Flexi Cap Fund", 88.0, 0.008),
    "120716": ("UTI Nifty 50 Index Fund - Direct Plan - Growth", "Equity", "Index Fund", 165.0, 0.009),
    "119062": ("HDFC Corporate Bond Fund - Direct Plan - Growth", "Debt", "Corporate Bond Fund", 31.0, 0.0012),
}


def _nav_series(code: str) -> dict[int, float]:
    name, _, _, base, vol = SCHEMES[code]
    rng = random.Random(_seed("nav", code))
    drift = rng.uniform(0.0002, 0.0007) if vol > 0.002 else 0.00028
    today = int(time.time()) // DAY * DAY
    nav = base
    series = {}
    for i in range(0, 5 * 365 + 1):
        series[today - i * DAY] = round(nav, 4)
        nav = nav / math.exp(drift + vol * rng.gauss(0, 1))
    return series


class DemoMutualFunds:
    demo = True

    def amcs(self) -> list:
        return [{"Name": n} for n in ("NJ Mutual Fund", "HDFC Mutual Fund", "Axis Mutual Fund",
                                      "PPFAS Mutual Fund", "UTI Mutual Fund")]

    def schemes(self, name: str | None = None, category: str | None = None, type_: str | None = None) -> list:
        out = []
        for code, (n, cat, sub, *_r) in SCHEMES.items():
            if name and name.lower() not in n.lower():
                continue
            if category and category.lower() != cat.lower():
                continue
            out.append({"Code": code, "Name": n, "Category": cat, "SubCategory": sub, "Type": "Open Ended",
                        "ISINGrowth": f"INFDEMO{code}", "IsActive": "True"})
        return out

    def categories(self) -> list:
        return [{"Category": c} for c in sorted({v[1] for v in SCHEMES.values()})]

    def nav(self, *, code: str | None = None, isin: str | None = None, name: str | None = None,
            category: str | None = None, max_rows: int = 100) -> list[dict]:
        rows = []
        for s in self.schemes(name=name, category=category):
            if code and s["Code"] != code:
                continue
            series = _nav_series(s["Code"])
            t = max(series)
            rows.append({"code": s["Code"], "name": s["Name"], "nav": series[t],
                         "date": time.strftime("%m-%d-%Y 00:00:00", time.gmtime(t)),
                         "isin_growth": s["ISINGrowth"], "isin_div_payout": None, "isin_div_reinvest": None})
        return rows[:max_rows]

    def nav_on(self, date_ts: int, *, code: str | None = None, isin: str | None = None) -> list[dict]:
        if code not in SCHEMES:
            return []
        series = _nav_series(code)
        day = date_ts // DAY * DAY
        while day not in series and day > min(series):
            day -= DAY
        if day not in series:
            return []
        return [{"code": code, "name": SCHEMES[code][0], "nav": series[day],
                 "date": time.strftime("%m-%d-%Y 00:00:00", time.gmtime(day))}]

    def aum(self, **_: Any) -> list:
        return []

    def holdings(self, *, code: str | None = None, isin: str | None = None, name: str | None = None,
                 filter_: str = "All") -> list[dict]:
        if code not in SCHEMES:
            return []
        rng = random.Random(_seed("hold", code))
        if SCHEMES[code][1] == "Debt":
            return [{"instrument": "7.18% GOI 2033", "isin": "IN0020230085", "industry": "SOV", "weight": 22.5,
                     "asset_type": "Debt", "size": None, "sector": "Government", "quantity": None,
                     "market_value": None, "date": None}]
        picks = rng.sample(list(COMPANIES), 12)
        weights = [rng.uniform(1, 10) for _ in picks]
        scale = rng.uniform(70, 95) / sum(weights)
        return sorted(({
            "instrument": COMPANIES[s][0], "isin": COMPANIES[s][1], "industry": COMPANIES[s][4],
            "quantity": None, "market_value": None, "weight": round(w * scale, 2), "asset_type": "Equity",
            "size": "Large Cap", "sector": COMPANIES[s][3], "date": None,
        } for s, w in zip(picks, weights)), key=lambda h: -h["weight"])

    def holdings_what_changed(self, name: str) -> list:
        return []

    def new_fund_offers(self, range_: str = "Past365Days") -> list:
        return []


_HEADLINES = {
    "positive": ["{n} beats street estimates as quarterly profit jumps {x}%",
                 "{n} bags large order, shares rally {x}%",
                 "Brokerages raise target price on {n} after strong guidance"],
    "negative": ["{n} shares slip {x}% after margin pressure in latest quarter",
                 "Regulator issues notice to {n}; stock under pressure",
                 "{n} cuts FY guidance citing weak demand"],
    "neutral": ["{n} schedules board meeting to consider fund raising",
                "{n} announces record date for dividend",
                "{n} appoints new independent director"],
}
_TYPES = ["Earnings", "Corporate Actions", "Orders & Contracts", "Regulatory", "Management", "Index & Reshuffles"]


class DemoNews:
    demo = True

    def _make(self, symbol: str, count: int) -> list[dict]:
        name, isin, code, sector, *_ = COMPANIES.get(symbol, (symbol, None, None, None))
        rng = random.Random(_seed("news", symbol, int(time.time()) // (6 * 3600)))
        now = int(time.time())
        out = []
        for i in range(count):
            s = rng.choices(["positive", "negative", "neutral"], weights=[4, 3, 3])[0]
            head = rng.choice(_HEADLINES[s]).format(n=name, x=rng.randint(2, 9))
            out.append({
                "article_id": _seed(symbol, i, now // 3600) % 10_000_000, "title": head, "specific_title": head,
                "summary": f"[DEMO] {head}.", "long_summary": f"[DEMO] Synthetic article about {name}.",
                "link": None, "date": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now - i * 5 * 3600)),
                "company": name, "article_type": rng.choice(_TYPES), "sentiment": s, "source": "Demo Wire",
                "sector": sector, "symbol": symbol, "isin": isin, "scrip_code": code, "created_at": None,
            })
        return out

    def company_news(self, symbol: str | None = None, *, sentiment: str | None = None, limit: int = 20,
                     offset: int = 0, **_: Any) -> list[dict]:
        rows = self._make(symbol or "RELIANCE", 30)
        if sentiment:
            rows = [r for r in rows if r["sentiment"] == sentiment.lower()]
        return rows[offset: offset + limit]

    def multi_company_news(self, symbols: Iterable[str], *, sentiment: str | None = None, limit: int = 50,
                           offset: int = 0, **_: Any) -> list[dict]:
        rows = [a for s in symbols for a in self._make(s, 6)]
        if sentiment:
            rows = [r for r in rows if r["sentiment"] == sentiment.lower()]
        rows.sort(key=lambda r: r["date"], reverse=True)
        return rows[offset: offset + limit]

    def general_news(self, type_: str | None = None, *, sentiment: str | None = None, limit: int = 20,
                     offset: int = 0) -> list[dict]:
        rows = self._make("MARKET", 20)
        for r in rows:
            r["company"], r["symbol"], r["article_type"] = "N/A", None, type_ or "Economy"
            r["title"] = r["specific_title"] = r["title"].replace("MARKET", "Indian equities")
        if sentiment:
            rows = [r for r in rows if r["sentiment"] == sentiment.lower()]
        return rows[offset: offset + limit]
