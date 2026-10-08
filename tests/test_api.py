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


def test_history_capped_by_plan(client):
    r = client.get("/v1/history?symbol=TCS&bars=5000", headers=FREE).json()
    assert len(r["candles"]) == 500


def test_screener_and_backtest(client):
    r = client.post("/v1/screener", json={"preset": "momentum"}, headers=ALGO)
    assert r.status_code == 200 and r.json()["universe_size"] == 20
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
