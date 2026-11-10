import pytest
from fastapi.testclient import TestClient

from gtp.api.app import create_app
from gtp.config import Settings
from gtp.platform.store import Store


@pytest.fixture()
def client(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), webhook_secret="hook", admin_token="admin")
    with TestClient(create_app(s)) as c:
        yield c


ALGO = {"X-API-Key": "demo-algo-key"}
FREE = {"X-API-Key": "demo-free-key"}


def test_auth_required(client):
    assert client.get("/v1/quote?symbol=TCS").status_code == 401
    assert client.get("/v1/quote?symbol=TCS", headers={"X-API-Key": "bad"}).status_code == 401
    r = client.get("/v1/quote?symbol=TCS", headers=FREE)
    assert r.status_code == 200 and r.json()["symbol"] == "TCS"
    assert "X-RateLimit-Remaining-Minute" in r.headers


def test_plan_gating(client):
    r = client.get("/v1/company/TCS", headers=FREE)
    assert r.status_code == 403 and "upgrade" in r.json()["detail"]
    assert client.get("/v1/company/TCS", headers={"X-API-Key": "demo-pro-key"}).status_code == 200
    assert client.post("/v1/backtest", json={"symbol": "TCS"}, headers={"X-API-Key": "demo-pro-key"}).status_code == 403


def test_symbol_cap(client):
    r = client.get("/v1/quotes?symbols=A,B,C,D,E,F", headers=FREE)
    assert r.status_code == 400


def test_core_endpoints(client):
    for path in ["/v1/history?symbol=TCS&bars=60&indicators=sma:20,macd:12,26,9", "/v1/technicals?symbol=TCS",
                 "/v1/fundamentals/TCS", "/v1/options/chain?product=NIFTY", "/v1/market/pulse?watchlist=TCS,INFY",
                 "/v1/news?symbol=TCS", "/v1/news/general", "/v1/mf/122639/returns", "/v1/mf/overlap?a=122639&b=120716",
                 "/v1/corporate/announcements?symbol=TCS", "/v1/me"]:
        r = client.get(path, headers=ALGO)
        assert r.status_code == 200, (path, r.text)
    h = client.get("/v1/history?symbol=TCS&bars=60&indicators=sma:20,macd:12,26,9", headers=ALGO).json()
    assert len(h["candles"]) == 60 and set(h["indicators"]) == {"sma:20", "macd:12,26,9"}


def test_new_endpoints(client):
    meta = client.get("/v1/meta").json()
    assert meta["mode"] == "demo" and meta["demo_key"] == "demo-algo-key" and "NIFTY 50" in meta["indices"]
    assert len(meta["universe"]) == 50 and meta["session"]["open"] == "09:15"
    h = client.get("/v1/market/heatmap", headers=FREE).json()
    assert len(h["stocks"]) == 50 and len(h["sectors"]) >= 10 and len(h["gainers"]) == 5
    assert all(s["market_cap"] and s["sector"] != "Other" for s in h["stocks"])
    sp = client.get("/v1/sparklines?symbols=TCS,INFY&bars=20", headers=FREE).json()
    assert set(sp) == {"TCS", "INFY"} and len(sp["TCS"]) == 20
    p = client.get("/v1/market/pulse?watchlist=TCS,INFY&news=false", headers=FREE).json()["sections"]
    assert set(p) == {"indices", "watchlist", "movers"} and len(p["indices"]["data"]) == 5
    assert "general_news" in client.get("/v1/market/pulse", headers=FREE).json()["sections"]
    cmp_ = client.post("/v1/backtest/compare", json={"symbol": "TCS", "bars": 400}, headers=ALGO).json()
    assert len(cmp_["results"]) == 5 and cmp_["bars"] == 400 and "sharpe" in cmp_["benchmark"]
    assert client.post("/v1/backtest/compare", json={"symbol": "TCS"}, headers=FREE).status_code == 403
    t = client.get("/v1/fundamentals/TCS/trend?quarters=5", headers=ALGO).json()
    assert len(t) == 5 and t[-1]["label"]
    res = client.get("/v1/fundamentals/TCS/results", headers=ALGO).json()
    assert res["period"] in ("QJ", "QS", "QD", "QM") and res["items"][0]["key"] == "RevenueFromOperations"
    bs = client.get("/v1/fundamentals/TCS/results?statement=BalanceSheet&period=M12&year=2025", headers=ALGO).json()
    assert bs["fiscal_year"] == 2025 and any(i["key"] == "Borrowings" for i in bs["items"])
    part = client.get("/v1/derivatives/participants", headers=ALGO).json()
    assert {r["client"] for r in part} == {"Client", "DII", "FII", "Pro"}
    assert client.get("/v1/corporate/deals?kind=block", headers=ALGO).json()[0]["side"] in ("buy", "sell")
    me = client.get("/v1/me", headers=ALGO).json()
    assert me["quota"]["day_limit"] == 250_000 and me["quota"]["day_used"] >= 5
    chain = client.get("/v1/options/chain?product=NIFTY", headers=ALGO).json()
    assert chain["expiry"] and chain["summary"]["atm_strike"] and len(chain["rows"]) == 50
    sh = client.get("/v1/fundamentals/TCS/shareholding", headers=ALGO).json()
    assert abs(sum(r["value"] for r in sh) - 100) < 0.05 and sh[0]["entity"] == "Promoter"


def test_dashboard_is_served_with_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_history_capped_by_plan(client):
    r = client.get("/v1/history?symbol=TCS&bars=5000", headers=FREE).json()
    assert len(r["candles"]) == 500


def test_screener_and_backtest(client):
    r = client.post("/v1/screener", json={"preset": "momentum"}, headers=ALGO)
    assert r.status_code == 200 and r.json()["universe_size"] == 50
    assert client.post("/v1/screener", json={"preset": "nope"}, headers=ALGO).status_code == 400
    r = client.post("/v1/backtest", json={"symbol": "INFY", "strategy": "breakout", "include_equity": False}, headers=ALGO)
    assert r.status_code == 200 and "equity" not in r.json()
    assert client.post("/v1/backtest", json={"symbol": "INFY", "strategy": "zzz"}, headers=ALGO).status_code == 400


def test_unknown_symbol_is_404(client):
    assert client.get("/v1/fundamentals/NOPE", headers=ALGO).status_code == 404


def test_raw_passthrough_needs_live(client):
    assert client.get("/v1/raw/price/GetExchanges", headers=ALGO).status_code == 400
    assert client.get("/v1/raw/price/DropTables", headers=ALGO).status_code == 404
    assert client.get("/v1/raw/price/GetExchanges", headers=FREE).status_code == 403


def test_webhook(client):
    assert client.post("/webhooks/gdf/news?token=wrong", json={}).status_code == 401
    art = {"article_id": 7, "title": "TCS wins deal", "symbol": "TCS", "sentiment": "Positive"}
    assert client.post("/webhooks/gdf/news?token=hook", json=art).json() == {"received": 1, "stored": 1}
    assert client.post("/webhooks/gdf/news?token=hook", json=[art]).json() == {"received": 1, "stored": 0}  # deduped
    stored = client.app.state.store.recent_articles(["TCS"])
    assert stored[0]["sentiment"] == "positive"


def test_admin(client):
    assert client.get("/admin/customers").status_code == 401
    H = {"X-Admin-Token": "admin"}
    r = client.post("/admin/customers", json={"name": "Asha", "email": "a@x.in", "plan": "pro"}, headers=H).json()
    key, cid = r["api_key"], r["customer"]["id"]
    assert client.get("/v1/company/TCS", headers={"X-API-Key": key}).status_code == 200
    client.patch(f"/admin/customers/{cid}", json={"active": False}, headers=H)
    assert client.get("/v1/quote?symbol=TCS", headers={"X-API-Key": key}).status_code == 403
    new = client.post(f"/admin/customers/{cid}/rotate-key", headers=H).json()["api_key"]
    client.patch(f"/admin/customers/{cid}", json={"active": True}, headers=H)
    assert client.get("/v1/quote?symbol=TCS", headers={"X-API-Key": key}).status_code == 401
    assert client.get("/v1/quote?symbol=TCS", headers={"X-API-Key": new}).status_code == 200
    assert client.get(f"/admin/customers/{cid}/usage", headers=H).json()


def test_rate_limits(tmp_path):
    store = Store(str(tmp_path / "r.db"))
    c, _ = store.create_customer("x", "x@x", "free")
    from gtp.platform.store import RateLimitExceeded
    for i in range(c.plan.requests_per_minute):
        store.check_and_record(c, "/v1/quote", now=1000.0 + i * 0.1)
    with pytest.raises(RateLimitExceeded):
        store.check_and_record(c, "/v1/quote", now=1010.0)
    store.check_and_record(c, "/v1/quote", now=1061.0)  # window slid
    assert store.usage(c.id, days=100000)[0]["count"] == c.plan.requests_per_minute + 1


def test_store_falls_back_when_path_is_not_writable(tmp_path):
    # A path inside a missing directory cannot be opened; the store must fall back to the temp dir.
    store = Store(str(tmp_path / "missing-dir" / "x.db"))
    try:
        assert store.path != str(tmp_path / "missing-dir" / "x.db")
        c, key = store.create_customer("x", "x@x", "free")
        assert store.customer_by_key(key).id == c.id
    finally:
        store.close()
        import os
        os.remove(store.path)


def test_earnings_and_documents(client):
    cal = client.get('/v1/earnings/calendar?range=Next7days', headers=ALGO).json()
    assert cal['range'] == 'Next7days' and (cal['upcoming'] or cal['recent'])
    ov = client.get('/v1/earnings/TCS', headers={'X-API-Key': 'demo-pro-key'}).json()
    kinds = {d['kind'] for d in ov['documents']}
    assert {'transcript', 'audio', 'presentation', 'results'} <= kinds
    # free plan cannot see earnings
    assert client.get('/v1/earnings/TCS', headers=FREE).status_code == 403
    # read a transcript PDF (pro plan)
    doc = next(d for d in ov['documents'] if d['kind'] == 'transcript')
    pdf = client.post('/v1/documents/read', json={'url': doc['url']}, headers={'X-API-Key': 'demo-pro-key'}).json()
    assert pdf['kind'] == 'pdf' and pdf['chars'] > 100 and 'Conference Call' in pdf['text']
    # audio transcription: algo yes, pro no
    audio = next(d for d in ov['documents'] if d['is_audio'])
    algo = client.post('/v1/documents/read', json={'url': audio['url']}, headers=ALGO).json()
    assert algo['available'] and algo['transcript']
    assert client.post('/v1/documents/read', json={'url': audio['url']}, headers={'X-API-Key': 'demo-pro-key'}).status_code == 403


def test_document_reader_blocks_ssrf(client):
    for bad in ['http://169.254.169.254/latest/meta-data', 'https://localhost/x.pdf',
                'https://evil.com/x.pdf', 'https://bseindia.com.evil.com/x.pdf',
                'https://demo.gtp.local.evil.com/ec/TCS/Q2FY27/audio.mp3']:
        r = client.post('/v1/documents/read', json={'url': bad}, headers=ALGO)
        assert r.status_code == 403, bad


def test_security_headers_on_every_response(client):
    h = client.get('/health').headers
    assert h['x-content-type-options'] == 'nosniff' and h['x-frame-options'] == 'DENY'
    assert 'strict-transport-security' in h and h['referrer-policy'] == 'no-referrer'
    # present on the dashboard page too, alongside its CSP
    page = client.get('/').headers
    assert page['x-frame-options'] == 'DENY' and 'content-security-policy' in page
