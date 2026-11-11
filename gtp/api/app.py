"""FastAPI application: the API your customers call, plus the web dashboard."""

from __future__ import annotations

import asyncio
import hmac
import json
import mimetypes
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__, services
from ..analytics import backtest as bt
from ..analytics import funds, screener, sentiment
from ..analytics import indicators as ta
from ..config import Settings
from ..gdf import DataHub, GDFAuthError, GDFError, GDFNotConfigured
from ..gdf import fundamentals as fmod
from ..gdf import mutualfunds as mfmod
from ..gdf.news import normalize_article
from ..platform import plans as P
from ..documents import build_documents
from ..net import FetchError, FetchNotAllowed
from ..platform.store import Customer, Store
from .deps import current_customer, require, require_admin

# Response headers applied to every response (SSE-safe pure-ASGI middleware below).
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
}


class SecurityHeaders:
    """Pure-ASGI middleware that adds security headers without buffering the body (keeps SSE working)."""

    def __init__(self, app, headers: dict[str, str]):
        self.app = app
        self.headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                present = {k for k, _ in message["headers"]}
                message["headers"].extend((k, v) for k, v in self.headers if k not in present)
            await send(message)

        await self.app(scope, receive, send_wrapper)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DAY = 86400
DEMO_KEYS = {"free": "demo-free-key", "pro": "demo-pro-key", "algo": "demo-algo-key"}

# Windows takes MIME types from the registry, where .js is sometimes text/plain. Browsers refuse to
# run JavaScript modules served that way, so the types the dashboard needs are set explicitly.
for _type, _ext in (("text/javascript", ".js"), ("text/css", ".css"), ("image/svg+xml", ".svg"),
                    ("font/woff2", ".woff2"), ("application/json", ".json")):
    mimetypes.add_type(_type, _ext)

# The dashboard runs only its own scripts and talks only to this server.
PAGE_HEADERS = {
    "Cache-Control": "no-cache",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

PRICE_FUNCTIONS = frozenset({
    "GetLastQuote", "GetLastQuoteShort", "GetLastQuoteShortWithClose", "GetLastQuoteArray",
    "GetLastQuoteArrayShort", "GetLastQuoteArrayShortWithClose", "GetSnapshot", "GetHistory",
    "GetHistoryAfterMarket", "GetExchangeSnapshot", "GetLastQuoteOptionChain", "GetHistoryGreeks",
    "GetSnapshotGreeks", "GetLastQuoteOptionGreek", "GetLastQuoteArrayOptionGreeks",
    "GetLastQuoteOptionGreeksChain", "GetTopGainersLosers", "GetVolumeShockers", "GetExchanges",
    "GetInstruments", "GetInstrumentsOnSearch", "GetInstrumentTypes", "GetProducts", "GetExpiryDates",
    "GetOptionTypes", "GetStrikePrices", "GetHolidays", "GetServerInfo", "GetLimitation",
    "GetMarketMessages", "GetExchangeMessages",
})
RAW_APIS = {
    "price": ("price", PRICE_FUNCTIONS),
    "fundamentals": ("fundamentals", fmod.FUNCTIONS),
    "mf": ("mutual_funds", mfmod.FUNCTIONS),
    "news": ("news", frozenset({"api/news", "api/news/multi", "api/general/news"})),
}


class Assets(StaticFiles):
    """Dashboard files. Browsers revalidate on every load, so a new deploy shows at once."""

    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            if path.endswith(".woff2"):
                # Fonts never change at a given URL, so they can be cached hard.
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                # JS/CSS must always reflect the current deploy: revalidate at the browser and at the
                # edge (no long Vercel-CDN cache), so a push is visible immediately and never mixes
                # an old bundle with a new API.
                response.headers["Cache-Control"] = "no-cache"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response


class NewsBroker:
    """Fans out articles received on the webhook to connected stream clients."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, article: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(article)
            except asyncio.QueueFull:
                pass

    @property
    def subscribers(self) -> int:
        return len(self._subs)


def _csv(value: str | None) -> list[str]:
    return [v.strip().upper() for v in (value or "").split(",") if v.strip()]


def _limit_symbols(customer: Customer, symbols: list[str]) -> list[str]:
    cap = customer.plan.max_symbols_per_request
    if len(symbols) > cap:
        raise HTTPException(400, f"Your plan allows {cap} symbols per request (got {len(symbols)})")
    if not symbols:
        raise HTTPException(400, "Provide at least one symbol")
    return symbols


def _periods_per_year(periodicity: str, period: int) -> int:
    return {"MINUTE": 252 * 375 // period, "HOUR": 252 * 6 // period, "DAY": 252 // period,
            "WEEK": 52 // period, "MONTH": 12 // period}[periodicity] or 1


# -- request bodies -----------------------------------------------------------
class Filter(BaseModel):
    field: str
    op: str = "=="
    value: Any = None


class ScreenRequest(BaseModel):
    preset: Optional[str] = Field(None, description=f"One of: {', '.join(screener.PRESETS)}")
    filters: list[Filter] = []
    sort: Optional[str] = Field(None, description="Field name; prefix with '-' for descending")
    universe: Optional[list[str]] = Field(None, description="Symbols to scan; defaults to the configured universe")
    limit: int = Field(50, ge=1, le=500)
    price_exchange: str = "NSE"
    fundamental_exchange: str = "BSE"


class BacktestBase(BaseModel):
    exchange: str = "NSE"
    symbol: str
    periodicity: Literal["MINUTE", "HOUR", "DAY", "WEEK", "MONTH"] = "DAY"
    period: int = Field(1, ge=1)
    bars: int = Field(1000, ge=30)
    cost_bps: float = Field(10.0, ge=0, le=500)
    initial_capital: float = Field(100_000.0, gt=0)


class BacktestRequest(BacktestBase):
    strategy: str = "sma_cross"
    params: dict[str, Any] = {}
    include_equity: bool = True


class DocRead(BaseModel):
    url: str
    kind: Optional[Literal["pdf", "audio"]] = None


class NewCustomer(BaseModel):
    name: str
    email: str
    plan: str = "free"


class CustomerUpdate(BaseModel):
    plan: Optional[str] = None
    active: Optional[bool] = None


# -- app factory -------------------------------------------------------------------
def create_app(settings: Settings | None = None, hub: DataHub | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.store.close()

    app = FastAPI(
        title="Global Trader Platform API",
        version=__version__,
        description=(
            "Market intelligence for traders and algo developers: live and historical prices, fundamentals, "
            "mutual funds and sentiment-tagged news from Global Datafeeds, plus Company 360, a market map, "
            "a screener, option-chain analytics and backtesting. Authenticate with the `X-API-Key` header."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.hub = hub or DataHub.from_settings(settings)
    app.state.store = store or Store(settings.db_path)
    app.state.broker = NewsBroker()
    app.state.documents = build_documents(settings)
    app.add_middleware(SecurityHeaders, headers=SECURITY_HEADERS)

    if settings.demo and not app.state.store.list_customers():
        for plan_id, key in DEMO_KEYS.items():
            app.state.store.create_customer(f"Demo {plan_id}", "demo@example.com", plan_id, api_key=key)
    if settings.bootstrap_key and app.state.store.customer_by_key(settings.bootstrap_key) is None:
        # A durable owner key, so live mode has a working key despite the ephemeral serverless DB.
        app.state.store.create_customer("Owner", "owner@globaltrader.local", settings.bootstrap_plan,
                                        api_key=settings.bootstrap_key)

    _register_errors(app)
    _routes(app)
    if WEB_DIR.is_dir():
        app.mount("/static", Assets(directory=WEB_DIR), name="static")
    return app


def _register_errors(app: FastAPI) -> None:
    @app.exception_handler(GDFNotConfigured)
    async def _nc(_: Request, e: GDFNotConfigured):
        return JSONResponse({"detail": str(e)}, status_code=503)

    @app.exception_handler(GDFAuthError)
    async def _auth(_: Request, e: GDFAuthError):
        return JSONResponse({"detail": f"Upstream data provider rejected the request: {e}"}, status_code=502)

    @app.exception_handler(GDFError)
    async def _gdf(_: Request, e: GDFError):
        return JSONResponse({"detail": str(e), "function": e.function}, status_code=502)

    @app.exception_handler(ValueError)
    async def _val(_: Request, e: ValueError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    @app.exception_handler(LookupError)
    async def _lookup(_: Request, e: LookupError):
        return JSONResponse({"detail": str(e).strip("'\"")}, status_code=404)

    @app.exception_handler(FetchNotAllowed)
    async def _blocked(_: Request, e: FetchNotAllowed):
        return JSONResponse({"detail": f"Blocked by document policy: {e}"}, status_code=403)

    @app.exception_handler(FetchError)
    async def _fetch(_: Request, e: FetchError):
        return JSONResponse({"detail": str(e)}, status_code=502)


def _routes(app: FastAPI) -> None:  # noqa: C901 - a flat list of routes reads best here
    hub = lambda: app.state.hub  # noqa: E731
    settings: Settings = app.state.settings

    # -- public --------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html", headers=PAGE_HEADERS)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(WEB_DIR / "favicon.svg", media_type="image/svg+xml",
                            headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/health", tags=["platform"])
    def health():
        return {"status": "ok", "version": __version__, "mode": "demo" if settings.demo else "live",
                "stream_subscribers": app.state.broker.subscribers}

    @app.get("/v1/meta", tags=["platform"])
    def meta():
        """What a client needs to set itself up: mode, default symbols and the exchange session."""
        return {
            "name": "Global Trader Platform", "version": __version__, "mode": "demo" if settings.demo else "live",
            "demo_key": DEMO_KEYS["algo"] if settings.demo else None,
            "indices": settings.indices, "index_exchange": settings.index_exchange,
            "price_exchange": settings.price_exchange, "fundamental_exchange": settings.fundamental_exchange,
            "universe": settings.universe,
            "session": {"timezone": "Asia/Kolkata", "utc_offset_minutes": 330, "open": "09:15", "close": "15:30",
                        "weekdays": [1, 2, 3, 4, 5]},
            "server_time": int(time.time()),
        }

    @app.get("/v1/plans", tags=["platform"])
    def plans():
        return P.public_catalog()

    @app.get("/v1/me", tags=["platform"])
    def me(customer: Customer = Depends(current_customer)):
        return {"customer": customer.to_dict(), "plan": next(p for p in P.public_catalog() if p["id"] == customer.plan.id),
                "quota": app.state.store.quota(customer), "usage_30d": app.state.store.usage(customer.id),
                "demo_data": hub().demo}

    # -- prices ----------------------------------------------------------------
    @app.get("/v1/quote", tags=["prices"])
    def quote(symbol: str, exchange: str = "NSE", _: Customer = Depends(require(P.QUOTES))):
        return hub().price.last_quote(exchange, symbol.upper())

    @app.get("/v1/quotes", tags=["prices"])
    def quotes(symbols: str = Query(..., description="Comma-separated"), exchange: str = "NSE",
               customer: Customer = Depends(require(P.QUOTES))):
        return hub().price.last_quotes(exchange, _limit_symbols(customer, _csv(symbols)))

    @app.get("/v1/search", tags=["prices"])
    def search(q: str, exchange: str = "NSE", _: Customer = Depends(require(P.QUOTES))):
        return hub().price.search_instruments(exchange, q)[:50]

    @app.get("/v1/history", tags=["prices"])
    def history(symbol: str, exchange: str = "NSE",
                periodicity: Literal["TICK", "MINUTE", "HOUR", "DAY", "WEEK", "MONTH"] = "DAY",
                period: int = Query(1, ge=1), bars: int = Query(300, ge=1),
                from_ts: Optional[int] = Query(None, alias="from"), to_ts: Optional[int] = Query(None, alias="to"),
                indicators: Optional[str] = Query(None, description="e.g. sma:20,ema:50,rsi:14,macd,bollinger:20"),
                customer: Customer = Depends(require(P.HISTORY))):
        bars = min(bars, customer.plan.history_max_bars)
        candles = hub().price.history(exchange, symbol.upper(), periodicity, period, from_ts, to_ts, bars)
        out: dict[str, Any] = {"symbol": symbol.upper(), "exchange": exchange, "periodicity": periodicity,
                               "period": period, "candles": candles}
        if indicators:
            out["indicators"] = ta.compute(candles, _split_specs(indicators))
        return out

    @app.get("/v1/sparklines", tags=["prices"])
    def sparklines(symbols: str = Query(..., description="Comma-separated"), exchange: str = "NSE",
                   bars: int = Query(30, ge=5, le=120), customer: Customer = Depends(require(P.HISTORY))):
        """Recent daily closes for several symbols in one call, for small trend charts."""
        return services.sparklines(hub(), _limit_symbols(customer, _csv(symbols)), exchange=exchange, bars=bars)

    @app.get("/v1/technicals", tags=["prices"])
    def technicals(symbol: str, exchange: str = "NSE", _: Customer = Depends(require(P.HISTORY))):
        return {"symbol": symbol.upper(), **ta.snapshot(hub().price.history(exchange, symbol.upper(), "DAY", max_bars=300))}

    @app.get("/v1/market/pulse", tags=["market"])
    def pulse(watchlist: Optional[str] = None, news: bool = Query(True, description="Include news sections"),
              customer: Customer = Depends(require(P.QUOTES))):
        """Index quotes, your watchlist and (optionally) market news in one call."""
        wl = _limit_symbols(customer, _csv(watchlist)) if watchlist else None
        return services.market_pulse(hub(), index_exchange=settings.index_exchange, indices=settings.indices,
                                     equity_exchange=settings.price_exchange, watchlist=wl, include_news=news)

    @app.get("/v1/market/heatmap", tags=["market"])
    def heatmap(_: Customer = Depends(require(P.QUOTES))):
        """Day change, sector and market value of every stock in the universe, with sector and breadth totals."""
        return services.market_heatmap(hub(), settings.universe, price_exchange=settings.price_exchange,
                                       fundamental_exchange=settings.fundamental_exchange)

    # -- derivatives -------------------------------------------------------------
    @app.get("/v1/options/chain", tags=["derivatives"])
    def option_chain(product: str, exchange: str = "NFO", expiry: Optional[str] = None,
                     _: Customer = Depends(require(P.OPTIONS))):
        rows = hub().price.option_chain(exchange, product.upper(), expiry)
        expiries = sorted({r["expiry"] for r in rows if r.get("expiry")})
        return {"product": product.upper(), "expiry": expiry or (expiries[0] if len(expiries) == 1 else None),
                "expiries": expiries, "summary": services.option_chain_summary(rows), "rows": rows}

    @app.get("/v1/derivatives/participants", tags=["derivatives"])
    def participants(exchange: str = "NSE", _: Customer = Depends(require(P.OPTIONS))):
        """Open interest in index and stock derivatives by participant type (FII, DII, Pro, Client)."""
        return hub().fundamentals.participants(exchange)

    # -- fundamentals ---------------------------------------------------------------
    @app.get("/v1/fundamentals/{symbol}", tags=["fundamentals"])
    def fundamentals(symbol: str, exchange: str = "BSE", nature: Literal["Standalone", "Consolidated"] = "Standalone",
                     _: Customer = Depends(require(P.FUNDAMENTALS))):
        s = symbol.upper()
        return {"symbol": s, "ratios": hub().fundamentals.ratios(exchange, s, nature=nature),
                "sector": hub().fundamentals.sector(exchange, s), "profile": hub().fundamentals.company(exchange, s)}

    @app.get("/v1/fundamentals/{symbol}/results", tags=["fundamentals"])
    def results(symbol: str, year: Optional[int] = Query(None, description="Fiscal year: 2026 means FY 2026-27"),
                exchange: str = "BSE",
                statement: Literal["ProfitLoss", "BalanceSheet", "CashFlow"] = "ProfitLoss",
                period: Optional[Literal["QJ", "QS", "QD", "QM", "M6", "M9", "M12"]] = None,
                nature: Literal["Standalone", "Consolidated"] = "Standalone",
                _: Customer = Depends(require(P.FUNDAMENTALS))):
        """Reported line items of one statement. Defaults to the latest completed quarter."""
        latest_year, latest_period = services.recent_quarters(time.time(), 1)[0]
        year, period = year or latest_year, period or latest_period
        return {"symbol": symbol.upper(), "fiscal_year": year, "period": period, "statement": statement, "nature": nature,
                "items": hub().fundamentals.financial_results(exchange, symbol.upper(), year, statement=statement,
                                                              period=period, nature=nature)}

    @app.get("/v1/fundamentals/{symbol}/trend", tags=["fundamentals"])
    def trend(symbol: str, quarters: int = Query(6, ge=2, le=12), exchange: str = "BSE",
              nature: Literal["Standalone", "Consolidated"] = "Standalone",
              _: Customer = Depends(require(P.FUNDAMENTALS))):
        """Revenue, net profit and EPS for the last few reported quarters."""
        return services.financial_trend(hub(), symbol, exchange=exchange, quarters=quarters, nature=nature)

    @app.get("/v1/fundamentals/{symbol}/shareholding", tags=["fundamentals"])
    def shareholding(symbol: str, exchange: str = "BSE", kind: str = "SummaryAll",
                     _: Customer = Depends(require(P.FUNDAMENTALS))):
        return hub().fundamentals.shareholding(exchange, symbol.upper(), kind=kind)

    @app.get("/v1/corporate/announcements", tags=["fundamentals"])
    def announcements(symbol: Optional[str] = None, days: int = Query(7, ge=1, le=30), exchange: str = "BSE",
                      _: Customer = Depends(require(P.FUNDAMENTALS))):
        now = int(time.time())
        return hub().fundamentals.announcements(exchange, symbol.upper() if symbol else None, now - days * DAY, now)

    @app.get("/v1/corporate/actions", tags=["fundamentals"])
    def actions(symbol: Optional[str] = None, days: int = Query(30, ge=1, le=365), exchange: str = "BSE",
                _: Customer = Depends(require(P.FUNDAMENTALS))):
        now = int(time.time())
        return hub().fundamentals.corporate_actions(exchange, symbol.upper() if symbol else None, now - days * DAY, now)

    @app.get("/v1/corporate/results-calendar", tags=["fundamentals"])
    def results_calendar(exchange: str = "BSE", range: str = "Next7days", symbols: Optional[str] = None,  # noqa: A002
                         _: Customer = Depends(require(P.FUNDAMENTALS))):
        return hub().fundamentals.results_calendar(exchange, range, _csv(symbols) or None)

    @app.get("/v1/corporate/deals", tags=["fundamentals"])
    def deals(kind: Literal["bulk", "block"] = "bulk", exchange: str = "BSE", range: str = "Previous7days",  # noqa: A002
              symbol: Optional[str] = None, _: Customer = Depends(require(P.FUNDAMENTALS))):
        fetch = hub().fundamentals.bulk_deals if kind == "bulk" else hub().fundamentals.block_deals
        return fetch(exchange, range, symbol.upper() if symbol else None)

    @app.get("/v1/company/{symbol}", tags=["intelligence"])
    def company(symbol: str, price_exchange: str = "NSE", fundamental_exchange: str = "BSE",
                _: Customer = Depends(require(P.COMPANY_360))):
        return services.company_360(hub(), symbol, price_exchange=price_exchange,
                                    fundamental_exchange=fundamental_exchange)

    # -- earnings calls & documents -------------------------------------------
    @app.get("/v1/earnings/calendar", tags=["earnings"])
    def earnings_calendar(range: str = Query("Next7days", description="Next7days, Next30days, Previous7days, …"),  # noqa: A002
                          exchange: str = "BSE", _: Customer = Depends(require(P.EARNINGS))):
        """Upcoming and recent company results dates — the earnings calendar."""
        return services.earnings_calendar(hub(), exchange=exchange, range_=range)

    @app.get("/v1/earnings/{symbol}", tags=["earnings"])
    def earnings_company(symbol: str, exchange: str = "BSE", _: Customer = Depends(require(P.EARNINGS))):
        """One company's next results date and its recent earnings-call documents (transcript, audio, deck)."""
        return services.earnings_overview(hub(), symbol, exchange=exchange)

    @app.get("/v1/documents/providers", tags=["earnings"])
    def document_providers(_: Customer = Depends(require(P.EARNINGS))):
        """What the document reader can do here: which hosts are allowed and whether transcription is configured."""
        return app.state.documents.providers()

    @app.post("/v1/documents/read", tags=["earnings"])
    def documents_read(req: DocRead, customer: Customer = Depends(require(P.EARNINGS))):
        """Read an earnings-call document: extract text from a filing PDF, or transcribe a call recording.

        Only allowlisted exchange/vendor hosts can be fetched. Audio transcription needs the Algo plan.
        """
        from ..documents import classify
        if classify(req.url, req.kind) == "audio" and P.TRANSCRIPTS not in customer.plan.features:
            upgrade = next((p.name for p in P.PLANS.values() if P.TRANSCRIPTS in p.features), "a higher plan")
            raise HTTPException(403, f"Audio transcription is not in the {customer.plan.name} plan; upgrade to {upgrade}")
        return app.state.documents.read(req.url, req.kind)

    # -- screener & backtest ------------------------------------------------------------
    @app.get("/v1/screener/presets", tags=["intelligence"])
    def screener_presets():
        return {"presets": screener.PRESETS, "fields": screener.FIELDS, "operators": list(screener.OPS),
                "universe_size": len(settings.universe)}

    @app.post("/v1/screener", tags=["intelligence"])
    def run_screen(req: ScreenRequest, customer: Customer = Depends(require(P.SCREENER))):
        filters = [f.model_dump() for f in req.filters]
        sort = req.sort
        if req.preset:
            if req.preset not in screener.PRESETS:
                raise HTTPException(400, f"Unknown preset {req.preset!r}")
            preset = screener.PRESETS[req.preset]
            filters = list(preset["filters"]) + filters
            sort = sort or preset.get("sort")
        universe = req.universe or settings.universe
        cap = max(customer.plan.max_symbols_per_request, len(settings.universe))
        if len(universe) > cap:
            raise HTTPException(400, f"Universe too large for your plan (max {cap} symbols)")
        return screener.screen(hub(), universe, filters, sort=sort, limit=req.limit,
                               price_exchange=req.price_exchange, fundamental_exchange=req.fundamental_exchange)

    @app.get("/v1/backtest/strategies", tags=["intelligence"])
    def strategies():
        return {name: {"defaults": d} for name, (_, d) in bt.STRATEGIES.items()}

    def _backtest_candles(req: BacktestBase, customer: Customer) -> list[dict]:
        bars = min(req.bars, customer.plan.history_max_bars)
        return hub().price.history(req.exchange, req.symbol.upper(), req.periodicity, req.period, max_bars=bars)

    @app.post("/v1/backtest", tags=["intelligence"])
    def backtest(req: BacktestRequest, customer: Customer = Depends(require(P.BACKTEST))):
        candles = _backtest_candles(req, customer)
        result = bt.run(candles, req.strategy, req.params, initial_capital=req.initial_capital,
                        cost_bps=req.cost_bps, periods_per_year=_periods_per_year(req.periodicity, req.period))
        return {"symbol": req.symbol.upper(), "exchange": req.exchange, "bars": len(candles),
                **result.to_dict(include_equity=req.include_equity)}

    @app.post("/v1/backtest/compare", tags=["intelligence"])
    def backtest_compare(req: BacktestBase, customer: Customer = Depends(require(P.BACKTEST))):
        """Run every built-in strategy on the same bars and rank them against buy and hold."""
        candles = _backtest_candles(req, customer)
        return {"symbol": req.symbol.upper(), "exchange": req.exchange, "bars": len(candles),
                **bt.compare(candles, initial_capital=req.initial_capital, cost_bps=req.cost_bps,
                             periods_per_year=_periods_per_year(req.periodicity, req.period))}

    # -- news ---------------------------------------------------------------------------
    @app.get("/v1/news", tags=["news"])
    def news(symbol: str, sentiment_: Optional[Literal["positive", "negative", "neutral"]] = Query(None, alias="sentiment"),
             limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
             _: Customer = Depends(require(P.NEWS))):
        arts = hub().news.company_news(symbol.upper(), sentiment=sentiment_, limit=limit, offset=offset)
        return {"symbol": symbol.upper(), "sentiment": sentiment.score(arts), "articles": arts}

    @app.get("/v1/news/multi", tags=["news"])
    def news_multi(symbols: str, limit: int = Query(50, ge=1, le=200), customer: Customer = Depends(require(P.NEWS))):
        arts = hub().news.multi_company_news(_limit_symbols(customer, _csv(symbols)), limit=limit)
        return {"by_symbol": sentiment.by_symbol(arts), "articles": arts}

    @app.get("/v1/news/general", tags=["news"])
    def news_general(type: Optional[str] = None, limit: int = Query(20, ge=1, le=100),  # noqa: A002
                     _: Customer = Depends(require(P.NEWS))):
        arts = hub().news.general_news(type, limit=limit)
        return {"sentiment": sentiment.score(arts), "articles": arts}

    @app.get("/v1/news/stream", tags=["news"])
    async def news_stream(request: Request, symbols: Optional[str] = None,
                          _: Customer = Depends(require(P.STREAM))):
        """Server-sent events: articles pushed by the GDF webhook, filtered to ``symbols``."""
        wanted = set(_csv(symbols))
        broker: NewsBroker = app.state.broker
        q = broker.subscribe()
        fresh = getattr(hub().news, "fresh", None)        # demo mode writes its own articles

        async def gen():
            try:
                yield "retry: 3000\n\n"
                for a in reversed(app.state.store.recent_articles(sorted(wanted) or None, limit=10)):
                    yield f"event: article\ndata: {json.dumps(a)}\n\n"
                last_id = None
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        a = await asyncio.wait_for(q.get(), timeout=10)
                    except asyncio.TimeoutError:
                        a = fresh(sorted(wanted)) if fresh else None
                        if a is None or a["article_id"] == last_id:
                            yield ": keep-alive\n\n"
                            continue
                        last_id = a["article_id"]
                    if not wanted or (a.get("symbol") or "").upper() in wanted:
                        yield f"event: article\ndata: {json.dumps(a)}\n\n"
            finally:
                broker.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/webhooks/gdf/news", tags=["webhooks"])
    async def gdf_news_webhook(token: str = Query(...), payload: Any = Body(...)):
        """Receiver for GDF's news webhook. Register this URL with GDF as https://<host>/webhooks/gdf/news?token=..."""
        if not settings.webhook_secret or not hmac.compare_digest(token, settings.webhook_secret):
            raise HTTPException(401, "Invalid webhook token")
        items = payload if isinstance(payload, list) else (payload.get("data") if isinstance(payload, dict)
                                                           and isinstance(payload.get("data"), list) else [payload])
        stored = 0
        for raw in items:
            if not isinstance(raw, dict):
                continue
            a = normalize_article(raw)
            if app.state.store.save_article(a):
                stored += 1
                app.state.broker.publish(a)
        return {"received": len(items), "stored": stored}

    # -- mutual funds -----------------------------------------------------------------
    @app.get("/v1/mf/schemes", tags=["mutual funds"])
    def mf_schemes(name: Optional[str] = None, category: Optional[str] = None,
                   _: Customer = Depends(require(P.MUTUAL_FUNDS))):
        if not name and not category:
            raise HTTPException(400, "Pass a scheme name fragment or a category")
        return hub().mutual_funds.schemes(name=name, category=category)[:200]

    @app.get("/v1/mf/nav/browse", tags=["mutual funds"])
    def mf_nav_browse(limit: int = 60, _: Customer = Depends(require(P.MUTUAL_FUNDS))):
        """Live NAV board across the scheme universe (the NAV feed, no name directory needed)."""
        return hub().mutual_funds.nav(max_rows=max(1, min(limit, 300)))

    @app.get("/v1/mf/nav", tags=["mutual funds"])
    def mf_nav(code: Optional[str] = None, name: Optional[str] = None, isin: Optional[str] = None,
               _: Customer = Depends(require(P.MUTUAL_FUNDS))):
        if not (code or name or isin):
            raise HTTPException(400, "Pass code, name or isin")
        return hub().mutual_funds.nav(code=code, name=name, isin=isin)

    @app.get("/v1/mf/compare", tags=["mutual funds"])
    def mf_compare(codes: str, customer: Customer = Depends(require(P.MUTUAL_FUNDS))):
        return funds.compare(hub(), _limit_symbols(customer, _csv(codes)))

    @app.get("/v1/mf/overlap", tags=["mutual funds"])
    def mf_overlap(a: str, b: str, _: Customer = Depends(require(P.MUTUAL_FUNDS))):
        return funds.overlap(hub(), a, b)

    @app.get("/v1/mf/{code}/returns", tags=["mutual funds"])
    def mf_returns(code: str, _: Customer = Depends(require(P.MUTUAL_FUNDS))):
        return funds.returns(hub(), code)

    @app.get("/v1/mf/{code}/holdings", tags=["mutual funds"])
    def mf_holdings(code: str, _: Customer = Depends(require(P.MUTUAL_FUNDS))):
        h = hub().mutual_funds.holdings(code=code)
        return {"code": code, "exposure": funds.exposure(h), "holdings": h}

    # -- raw pass-through ---------------------------------------------------------
    @app.get("/v1/raw/{api}/{function:path}", tags=["raw"])
    def raw(api: str, function: str, request: Request, _: Customer = Depends(require(P.RAW))):
        """Call any documented GDF function directly, with the same query parameters as GDF's docs."""
        if api not in RAW_APIS:
            raise HTTPException(404, f"Unknown API {api!r}; use one of {', '.join(RAW_APIS)}")
        attr, allowed = RAW_APIS[api]
        if function not in allowed:
            raise HTTPException(404, f"{function!r} is not a documented {api} function")
        client = getattr(hub(), attr)
        client = getattr(client, "inner", client)
        if not hasattr(client, "call"):
            raise HTTPException(400, "Raw pass-through needs live mode (GTP_MODE=live)")
        blocked = {"accesskey", "api_key", "x_api_key"}
        params = {k: v for k, v in request.query_params.items() if k.lower() not in blocked}
        return client.call(function, **params)

    # -- admin ----------------------------------------------------------------------
    @app.get("/admin/customers", tags=["admin"], dependencies=[Depends(require_admin)])
    def admin_list():
        return [c.to_dict() for c in app.state.store.list_customers()]

    @app.post("/admin/customers", tags=["admin"], dependencies=[Depends(require_admin)])
    def admin_create(body: NewCustomer):
        c, key = app.state.store.create_customer(body.name, body.email, body.plan)
        return {"customer": c.to_dict(), "api_key": key, "note": "Store this key now; it is not shown again."}

    @app.patch("/admin/customers/{cid}", tags=["admin"], dependencies=[Depends(require_admin)])
    def admin_update(cid: int, body: CustomerUpdate):
        c = app.state.store.update_customer(cid, plan=body.plan, active=body.active)
        if c is None:
            raise HTTPException(404, "No such customer")
        return c.to_dict()

    @app.post("/admin/customers/{cid}/rotate-key", tags=["admin"], dependencies=[Depends(require_admin)])
    def admin_rotate(cid: int):
        if app.state.store.get_customer(cid) is None:
            raise HTTPException(404, "No such customer")
        return {"api_key": app.state.store.rotate_key(cid)}

    @app.get("/admin/customers/{cid}/usage", tags=["admin"], dependencies=[Depends(require_admin)])
    def admin_usage(cid: int, days: int = 30):
        return app.state.store.usage(cid, days)


def _split_specs(text: str) -> list[str]:
    """Split "sma:20,ema:50,macd:12,26,9,rsi:14" into specs. Commas after a number continue its args."""
    specs: list[str] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if specs and part.replace(".", "", 1).isdigit():
            specs[-1] += "," + part
        else:
            specs.append(part)
    return specs
