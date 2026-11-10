"""Live GDF clients against a mocked HTTP transport shaped like GDF's docs."""

import json

import httpx
import pytest

from gtp.gdf import FundamentalsClient, GDFAuthError, GDFError, GDFNotConfigured, MutualFundClient, NewsClient, PriceClient


def transport(handler):
    return httpx.MockTransport(handler)


def test_price_last_quote_array_batches_and_normalises():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        ids = req.url.params["instrumentIdentifiers"].split("+")
        rows = [{"EXCHANGE": "NSE", "INSTRUMENTIDENTIFIER": i, "LASTTRADEPRICE": 110.0, "CLOSE": 100.0,
                 "LASTTRADETIME": 1415114727418, "TOTALQTYTRADED": 10} for i in ids]
        return httpx.Response(200, json=rows)

    c = PriceClient("http://host:1234", "KEY", transport=transport(handler))
    quotes = c.last_quotes("NSE", [f"S{i}" for i in range(30)])
    assert len(quotes) == 30
    assert len(calls) == 2  # GDF allows 25 instruments per call
    assert calls[0].url.path == "/GetLastQuoteArray/"
    assert calls[0].url.params["accessKey"] == "KEY"
    q = quotes[0]
    assert q["ltp"] == 110.0 and q["prev_close"] == 100.0
    assert q["change"] == 10.0 and q["change_pct"] == 10.0
    assert q["last_trade_time"] == 1415114727  # milliseconds normalised to seconds


def test_price_history_parses_and_sorts():
    def handler(req):
        assert req.url.params["periodicity"] == "DAY"
        assert req.url.params["from"] == "100"
        return httpx.Response(200, json={"OHLC": [
            {"LASTTRADETIME": 200, "OPEN": 2, "HIGH": 3, "LOW": 1, "CLOSE": 2.5, "TRADEDQTY": 9, "OPENINTEREST": 0},
            {"LASTTRADETIME": 100, "OPEN": 1, "HIGH": 2, "LOW": 0.5, "CLOSE": 1.5, "TRADEDQTY": 5, "OPENINTEREST": 0},
        ]})

    c = PriceClient("http://h:1", "K", transport=transport(handler))
    bars = c.history("NSE", "TCS", from_ts=100)
    assert [b["t"] for b in bars] == [100, 200]
    assert bars[1]["c"] == 2.5 and bars[1]["v"] == 9


def test_option_chain_parses_identifier():
    def handler(req):
        return httpx.Response(200, json=[{"InstrumentIdentifier": "OPTIDX_NIFTY_15JUL2021_CE_14650",
                                          "LastTradePrice": 10, "OpenInterest": 500}])

    rows = PriceClient("http://h:1", "K", transport=transport(handler)).option_chain("NFO", "NIFTY")
    assert rows[0]["strike"] == 14650 and rows[0]["option_type"] == "CE" and rows[0]["expiry"] == "15JUL2021"


def test_diagnostic_retry_then_data():
    n = {"calls": 0}

    def handler(req):
        n["calls"] += 1
        if n["calls"] < 3:
            return httpx.Response(200, text="Authentication request received. Try request data in next moment.",
                                  headers={"content-type": "text/plain"})
        return httpx.Response(200, json={"Value": [{"Symbol": "TCS"}]})

    c = FundamentalsClient("https://h:4532", "K", retry_delay=0, transport=transport(handler))
    assert c.company("BSE", "TCS") == {"symbol": "TCS", "name": None, "isin": None, "scrip_code": None}
    assert n["calls"] == 3


def test_auth_and_other_diagnostics_raise():
    c = FundamentalsClient("https://h", "K", transport=transport(
        lambda r: httpx.Response(200, text="Access Denied. Key not found.")))
    with pytest.raises(GDFAuthError):
        c.call("GetSectors", exchange="BSE")
    c = FundamentalsClient("https://h", "K", transport=transport(
        lambda r: httpx.Response(200, text="Date is out of allowed range of 30 days.")))
    with pytest.raises(GDFError, match="out of allowed range"):
        c.call("GetCorporateAnnouncements", exchange="BSE")


def test_not_configured():
    with pytest.raises(GDFNotConfigured):
        MutualFundClient("", "").nav(code="1")


def test_fundamental_params_and_ratio_normalisation():
    def handler(req):
        p = req.url.params
        assert req.url.path == "/GetFinancialRatios"
        assert p["format"] == "Json" and p["type"] == "EOD" and p["natureOfReport"] == "Standalone"
        return httpx.Response(200, json={"EODClosePrice": 100.0, "PeRatio": 20.0, "BookValuePerShare": 50.0,
                                         "Week52High": 125.0, "MarketCap": 5})

    r = FundamentalsClient("https://h", "K", transport=transport(handler)).ratios("BSE", "TCS")
    assert r["pe"] == 20.0 and r["pb"] == 2.0 and r["pct_from_52w_high"] == -20.0


def test_mf_nav_and_holdings():
    def handler(req):
        if req.url.path == "/GetNAV":
            return httpx.Response(200, json={"Value": [{"Code": "149263", "Name": "NJ", "Value": 12.5,
                                                        "Date": "07-14-2026 00:00:00", "ISINGrowth": ""}]})
        return httpx.Response(200, json={"Value": [{"Instrument": "Reliance", "Isin": "INE002A01018", "Weight": 9.28}]})

    c = MutualFundClient("https://mf", "K", transport=transport(handler))
    assert c.nav(code="149263")[0] == {"code": "149263", "name": "NJ", "nav": 12.5, "date": "07-14-2026 00:00:00",
                                       "isin_growth": None, "isin_div_payout": None, "isin_div_reinvest": None}
    assert c.holdings(code="149263")[0]["weight"] == 9.28


def test_news_uses_api_key_param():
    def handler(req):
        assert req.url.params["api_key"] == "NK"
        assert req.url.path == "/api/news/multi"
        assert req.url.params["symbols"] == "TCS,INFY"
        return httpx.Response(200, text=json.dumps([{"title": "t", "sentiment": "Positive", "symbol": "TCS",
                                                     "ISIN": "INE467B01029", "article_id": 1}]))

    arts = NewsClient("https://news", "NK", transport=transport(handler)).multi_company_news(["TCS", "INFY"])
    assert arts[0]["sentiment"] == "positive" and arts[0]["isin"] == "INE467B01029"


def test_fundamental_rows_are_normalised():
    """Samples follow the field names in GDF's fundamental API docs."""
    samples = {
        "/GetSHPAdvanced": {"Value": [{"Entity": "Promoter", "Value": 58.22, "Period": "February 2025"},
                                      {"Entity": "Public", "Value": "41.78", "Period": "February 2025"}]},
        "/GetCorporateAnnouncements": {"Value": [{
            "ScripId": "KARURVYSYA", "FillingDate": "02-27-2025", "MeetingDate": "01-01-0001", "ScripCode": 590003,
            "ScripName": "KARUR VYSYA BANK LTD.", "HeadLine": "Karur Vysya Bank inaugurates 6 new branches today",
            "Descriptor": "General", "CriticalNews": 0, "AttachmentUrl": "https://example.com/a.pdf",
            "ReceivedAt": "02-27-2025 17:57:03"}]},
        "/GetCorporateActions": {"Value": [{
            "ScripId": "SHRINIWAS", "ScripName": "Shri Niwas Leasing and Finance Limited",
            "CorporateActionType": "Right Issue of Equity Shares", "PurposeCode": "ET ", "RatioAmount": "00100001 ",
            "AnnouncementDate": "02-20-2025 16:36:03", "BcRdFlag": "RD", "BcRdFrom": "02-27-2025 00:00:00",
            "BcRdTo": "02-27-2025 00:00:00", "ProvXdate": "02-27-2025 00:00:00", "PaymentDate": "01-01-0001 00:00:00"}]},
        "/GetResultsCalendar": {"Value": [{"ScripId": "ABB", "ScripCode": 500002, "ScripName": "ABB India",
                                           "ISIN": "INE117A01022", "ResultsDate": 1740594600000, "LTP": 5210.5,
                                           "ChangePct": -0.4}]},
        "/GetBulkDeals": {"Value": [{"ScripCode": 544072, "DealDate": "02-27-2025", "ScripId": "AIKPIPES",
                                     "ClientName": "SATYA PRAKASH MITTAL", "DealType": "S", "Qty": 44800,
                                     "QtyPct": 0.704, "Price": 81.4}]},
        "/GetSectoralClassification": {"Value": [{"Symbol": "TCS", "CompanyName": "Tata Consultancy Services Ltd.",
                                                  "Sector": "Information Technology", "Industry": "IT - Software",
                                                  "BasicIndustry": "Computers - Software & Consulting", "ISIN": "INE467B01029"}]},
        "/GetFinancialResults": {"Value": [{"Label": "Revenue from operations", "UnitId": "INR", "Decimals": "-5",
                                            "Value": "123456.7", "Description": "", "Key": "RevenueFromOperations"}]},
        "/GetFIIDII": {"Value": [{"Date": "05-22-2026 20:12:02", "ClientType": "FII", "FutureIndexLong": 254325,
                                  "FutureIndexShort": 92661, "OptionIndexNetOI": 563535, "FutureIndexSignal": "Bullish"}]},
    }
    c = FundamentalsClient("https://h", "K", transport=transport(lambda r: httpx.Response(200, json=samples[r.url.path])))
    assert c.shareholding("BSE", "ARL") == [{"entity": "Promoter", "value": 58.22, "period": "February 2025"},
                                              {"entity": "Public", "value": 41.78, "period": "February 2025"}]
    a = c.announcements("BSE", "KARURVYSYA", 1, 2)[0]
    assert a["date"] == "2025-02-27 17:57:03" and a["meeting_date"] is None and a["critical"] is False
    assert a["headline"].startswith("Karur Vysya") and a["url"] == "https://example.com/a.pdf"
    act = c.corporate_actions("BSE", None, 1, 2)[0]
    assert act["purpose_code"] == "ET" and act["ex_date"] == "2025-02-27" and act["payment_date"] is None
    assert act["announced"] == "2025-02-20 16:36:03" and act["ratio"] == "00100001"
    cal = c.results_calendar("BSE")[0]
    assert cal == {"symbol": "ABB", "name": "ABB India", "isin": "INE117A01022", "date": "2025-02-27 00:00:00",
                   "ltp": 5210.5, "change_pct": -0.4}
    deal = c.bulk_deals("BSE")[0]
    assert deal["side"] == "sell" and deal["date"] == "2025-02-27" and deal["qty"] == 44800 and deal["symbol"] == "AIKPIPES"
    assert c.sector("BSE", "TCS")["sector"] == "Information Technology"
    fact = c.financial_results("BSE", "TCS", 2025)[0]
    assert fact["key"] == "RevenueFromOperations" and fact["value"] == 123456.7 and fact["unit"] == "INR"
    row = c.participants("NSE")[0]
    assert row["client"] == "FII" and row["future_index_long"] == 254325 and row["option_index_net_oi"] == 563535
    assert row["date"] == "2026-05-22 20:12:02"
