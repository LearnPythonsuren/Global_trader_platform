# Global Trader Platform

A product you can sell to traders and algo developers. It combines Global Datafeeds' four data APIs: **price**, **fundamentals**, **mutual funds** and **news**. On top of the data it adds analytics, paid plans, API keys and a web dashboard.

| Global Datafeeds API | Docs | What the platform uses it for |
|---|---|---|
| Price data (REST) | [globaldatafeeds.in/…/global-datafeeds-apis](https://globaldatafeeds.in/global-datafeeds-apis/global-datafeeds-apis/) | Quotes, OHLC history, instrument search, option chains |
| Fundamental / corporate data | [docs.globaldatafeeds.in](https://docs.globaldatafeeds.in/) | Ratios, results, shareholding, sector, announcements, corporate actions, deals |
| Mutual funds | [mfdocs.globaldatafeeds.in](https://mfdocs.globaldatafeeds.in/) | Scheme master, NAV, NAV history, holdings |
| News | [newsdocs.globaldatafeeds.in](https://newsdocs.globaldatafeeds.in/) | Company, multi-company and general news with sentiment, plus the push webhook |

## What customers get

| Feature | What it does | Plan |
|---|---|---|
| Quotes, charts, indicators | Live quotes and OHLC history (tick to monthly) with SMA, EMA, RSI, MACD, Bollinger and ATR | Starter |
| News and sentiment | AI-summarised news, scored per symbol (bullish, bearish or mixed) | Starter |
| Mutual fund analytics | NAV, 1M–5Y returns and CAGR, sector exposure, and portfolio overlap between two funds | Starter |
| **Company 360** | One call combines quote, technicals, ratios, sector, shareholding, filings, corporate actions and news, plus plain-English signals | Pro |
| **Screener** | Filter a universe on fundamentals and technicals together (e.g. P/E < 25 and above the 200-day SMA). Includes presets | Pro |
| **Option-chain analytics** | Full chain with PCR, max pain, and support/resistance from open interest | Pro |
| **Backtesting** | SMA/EMA cross, RSI mean reversion, Donchian breakout and MACD trend, with costs. Reports CAGR, Sharpe, Sortino, max drawdown, win rate and trades | Algo |
| **Real-time news stream** | Server-sent events fed by the GDF news webhook | Algo |
| **Raw pass-through** | Any documented GDF function, through your key, limits and cache | Algo |

Plans, prices and limits are in `gtp/platform/plans.py`. The prices there are placeholders: set them from your GDF costs.

## Quick start (demo mode, no keys needed)

```bash
pip install -r requirements.txt
python -m gtp serve            # http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 for the dashboard and http://127.0.0.1:8000/docs for the interactive API reference. Demo mode creates three keys: `demo-free-key`, `demo-pro-key` and `demo-algo-key`. **Demo mode only serves synthetic data.** The dashboard marks it with a DEMO DATA badge.

```bash
curl -H "X-API-Key: demo-pro-key" localhost:8000/v1/company/TCS
curl -H "X-API-Key: demo-algo-key" -X POST localhost:8000/v1/backtest \
     -H 'content-type: application/json' -d '{"symbol":"INFY","strategy":"sma_cross","params":{"fast":20,"slow":50}}'
```

## Going live with your Global Datafeeds keys

1. `cp .env.example .env`, set `GTP_MODE=live`, and fill in the base URL and key for each API you subscribe to. The price API host and port come from your GDF onboarding email. The MF and news base URLs aren't in the public docs, so ask GDF for them.
2. Run `python -m gtp check` to make one test call per API.
3. Create customers:
   ```bash
   python -m gtp customer create --name "Asha Traders" --email asha@example.com --plan pro
   python -m gtp customer list | set-plan <id> algo | disable <id> | rotate-key <id> | usage <id>
   ```
   Admins can also use the HTTP API: `/admin/customers` with the `X-Admin-Token` header.
4. Register the news webhook with GDF: `https://<your-host>/webhooks/gdf/news?token=<GTP_WEBHOOK_SECRET>`.
5. Optional: set `GTP_UNIVERSE_CSV` to the index-constituents CSV that GDF sends monthly. The screener will then scan it, e.g. the Nifty 100.

If a customer's plan includes a feature but your GDF subscription doesn't, that section of Company 360 returns an `error` and the rest still works.

## How it handles Global Datafeeds specifics

- **Diagnostic responses.** GDF sometimes returns plain text instead of data. When the text is "Try request data in next moment", the client retries with backoff. "Access Denied…" raises `GDFAuthError`. Other messages raise `GDFError`, which the API returns as HTTP 502 with GDF's message (`gtp/gdf/base.py`).
- **25-instrument limit.** Multi-symbol quote requests are split into batches of 25.
- **Field names.** The price API mixes `LASTTRADEPRICE` and `LastTradePrice`, and timestamps come in seconds or milliseconds. Everything is normalised to one snake_case schema.
- **Caching.** Every upstream call is cached per method: quotes for 2 s, history for 60 s, ratios for 6 h, holdings for 1 day (`gtp/gdf/__init__.py`). When many customers ask for the same symbol, you pay for one GDF call.

## Project layout

```
gtp/
  gdf/          Clients for the 4 GDF APIs, an offline demo provider, and the cache (DataHub)
  analytics/    indicators, backtest, screener, funds, sentiment
  services.py   Company 360, market pulse, option-chain summary
  platform/     plans, customers, API keys (stored hashed), metering, rate limits (SQLite)
  api/          FastAPI app, auth and plan gating
  web/          dashboard (plain JS and Chart.js)
  cli.py        serve / customer / check
tests/          pytest suite (python -m pytest)
```

## Before you sell this

- **Redistribution licence.** Reselling or exposing GDF data to your own customers usually needs a redistribution or vendor agreement with Global Datafeeds, and sometimes exchange (NSE/BSE/MCX) vendor approval for real-time data. Confirm this with GDF sales before launch.
- **Regulatory wording.** Signals, screens and backtests are analytics, not investment advice. Add disclaimers, and check whether any feature you market falls under SEBI research-analyst or investment-adviser rules.
- **Payments.** Plans are enforced, but billing isn't connected yet. Hook a payment provider (e.g. Razorpay) to `Store.update_customer` to change plans when a payment succeeds.
- **Production.** Run behind HTTPS with a process manager. SQLite and the in-memory rate limiter assume a single server; move to Postgres and Redis to run more than one.
