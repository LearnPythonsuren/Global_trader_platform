"""Global Datafeeds News API (AI-summarised, sentiment-tagged market news).

Docs: https://newsdocs.globaldatafeeds.in/
  GET /api/news           news for one company (symbol, isin or scrip code)
  GET /api/news/multi     news for many companies
  GET /api/general/news   market and economy news (IPO, commodities, ...)
Auth is the ``api_key`` query parameter. GDF can also push new articles to
a webhook, which the platform receives at POST /webhooks/gdf/news.
"""

from __future__ import annotations

from typing import Any, Iterable

from .base import BaseGDFClient, first_list

ARTICLE_FIELDS = (
    "article_id", "title", "specific_title", "summary", "long_summary", "link", "date", "company",
    "article_type", "sentiment", "source", "sector", "symbol", "ISIN", "scrip_code", "created_at",
)


def normalize_article(row: dict) -> dict:
    out = {k: row.get(k) for k in ARTICLE_FIELDS}
    out["isin"] = out.pop("ISIN")
    if out.get("sentiment"):
        out["sentiment"] = str(out["sentiment"]).strip().lower()
    return out


def _articles(data: Any) -> list[dict]:
    rows = data if isinstance(data, list) else first_list(data)
    if not rows and isinstance(data, dict) and "title" in data:
        rows = [data]
    return [normalize_article(r) for r in rows if isinstance(r, dict)]


class NewsClient(BaseGDFClient):
    api_name = "News"
    key_param = "api_key"

    def company_news(self, symbol: str | None = None, *, isin: str | None = None, scrip_code: str | None = None,
                     sentiment: str | None = None, article_type: str | None = None,
                     from_date: str | None = None, to_date: str | None = None,
                     limit: int = 20, offset: int = 0) -> list[dict]:
        return _articles(self.call(
            "api/news", symbol=symbol, isin=isin, scrip_code=scrip_code, sentiment=sentiment,
            articaltype=article_type, **{"from": from_date, "to": to_date}, limit=limit, offset=offset,
        ))

    def multi_company_news(self, symbols: Iterable[str], *, sentiment: str | None = None,
                           sector: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
        return _articles(self.call(
            "api/news/multi", symbols=",".join(symbols), sentiment=sentiment, sector=sector,
            limit=limit, offset=offset,
        ))

    def general_news(self, type_: str | None = None, *, sentiment: str | None = None,
                     limit: int = 20, offset: int = 0) -> list[dict]:
        return _articles(self.call("api/general/news", Type=type_, sentiment=sentiment, limit=limit, offset=offset))
