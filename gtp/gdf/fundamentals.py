"""Global Datafeeds fundamental and corporate data API.

Docs: https://docs.globaldatafeeds.in/
Every function is GET /<Function>?accessKey=...&exchange=...&format=Json.
Rows come back wrapped in {"Value": [...]}.
"""

from __future__ import annotations

from typing import Any

from .base import BaseGDFClient, unwrap

# Every REST function listed in the fundamental API docs, so call() can be
# used safely as a pass-through for anything without a typed wrapper below.
FUNCTIONS = frozenset({
    "GetCorporateAnnouncementsCategories", "GetCorporateAnnouncements",
    "GetCorporateActionsCategories", "GetCorporateActions",
    "GetResultsCalendar", "GetFinancialResultsItems", "GetFinancialResults", "GetFinancialRatios",
    "GetSectoralClassification", "GetSectors", "GetMei", "GetIndustries", "GetBasicIndustries",
    "GetShpItems", "GetSHP", "GetSHPAdvanced",
    "GetScripMCap", "GetExchangeMCap", "GetAnnualReports", "GetCompanyData",
    "GetBulkDeals", "GetBlockDeals", "GetDeliveryVolumes", "GetFIIDII",
    "GetBhavCopyCM", "GetBhavCopyFO", "GetFuturesAndOptions", "GetIndexDetail",
    "GetCircuitFilterDetails", "GetStatisticsGroupAbCompanies", "GetIndexHighlights",
    "GetTotalTradeHighlights", "GetScripGroupTradeHighlights", "GetTurnoverDetailsOfTop15ScripsofAgroup",
    "GetSeriesChange", "GetBannedSecurities", "GetDeliverable", "GetVolatality", "GetStatsMCap",
    "GetNewHL", "GetCircuitBreakers", "GetServerInfo", "GetLimitation", "GetInstruments",
})

RATIO_FIELDS = {
    "EODClosePrice": "close",
    "Year": "year",
    "LastQ": "last_quarter",
    "MarketCap": "market_cap",
    "Week52High": "week52_high",
    "Week52Low": "week52_low",
    "EPS": "eps",
    "PeRatio": "pe",
    "BookValuePerShare": "book_value",
    "DividendYield": "dividend_yield",
    "EBIT": "ebit",
    "InterestCoverageRatio": "interest_coverage",
    "FaceValue": "face_value",
    "PriceSalesRatio": "price_sales",
    "ProfitAfterTax": "profit_after_tax",
    "EnterpriseValue": "enterprise_value",
    "Debt": "debt",
}


def normalize_ratios(row: dict) -> dict:
    out = {snake: row.get(gdf) for gdf, snake in RATIO_FIELDS.items()}
    close, bv = out.get("close"), out.get("book_value")
    out["pb"] = round(close / bv, 4) if close and bv else None
    if close and out.get("week52_high"):
        out["pct_from_52w_high"] = round((close / out["week52_high"] - 1) * 100, 2)
    return out


class FundamentalsClient(BaseGDFClient):
    api_name = "Fundamental"
    key_param = "accessKey"
    default_params = {"format": "Json", "dTFormat": "String"}

    def call(self, function: str, **params: Any) -> Any:
        return unwrap(super().call(function, **params))

    def company(self, exchange: str, symbol: str) -> dict:
        rows = self.call("GetCompanyData", exchange=exchange, instrumentIdentifiers=symbol)
        return rows[0] if isinstance(rows, list) and rows else (rows or {})

    def ratios(self, exchange: str, symbol: str, *, kind: str = "EOD", nature: str = "Standalone",
               period: str | None = None, year: int | None = None) -> dict:
        data = self.call("GetFinancialRatios", exchange=exchange, instrumentIdentifier=symbol,
                         type=kind, natureOfReport=nature, period=period, year=year)
        row = data[0] if isinstance(data, list) and data else data
        return normalize_ratios(row or {})

    def financial_results(self, exchange: str, symbol: str, year: int, *, statement: str = "ProfitLoss",
                          period: str = "QD", nature: str = "Standalone") -> Any:
        return self.call("GetFinancialResults", exchange=exchange, instrumentIdentifier=symbol, year=year,
                         type=statement, period=period, natureOfReport=nature)

    def shareholding(self, exchange: str, symbol: str, *, kind: str = "SummaryAll", period: str | None = None) -> Any:
        return self.call("GetSHPAdvanced", exchange=exchange, instrumentIdentifier=symbol, type=kind, period=period)

    def sector(self, exchange: str, symbol: str) -> dict:
        rows = self.call("GetSectoralClassification", exchange=exchange, instrumentIdentifiers=symbol)
        return rows[0] if isinstance(rows, list) and rows else (rows or {})

    def announcements(self, exchange: str, symbol: str | None, from_ts: int, to_ts: int, **filters: Any) -> list:
        return self.call("GetCorporateAnnouncements", exchange=exchange, instrumentIdentifier=symbol,
                         **{"from": from_ts, "to": to_ts}, **filters) or []

    def corporate_actions(self, exchange: str, symbol: str | None, from_ts: int, to_ts: int) -> list:
        return self.call("GetCorporateActions", exchange=exchange, instrumentIdentifier=symbol,
                         **{"from": from_ts, "to": to_ts}) or []

    def results_calendar(self, exchange: str, range_: str = "Next7Days", symbols: list[str] | None = None) -> list:
        return self.call("GetResultsCalendar", exchange=exchange, range=range_, instrumentIdentifiers=symbols) or []

    def bulk_deals(self, exchange: str, range_: str = "Previous7days", symbol: str | None = None) -> list:
        return self.call("GetBulkDeals", exchange=exchange, range=range_, instrumentIdentifier=symbol) or []

    def block_deals(self, exchange: str, range_: str = "Previous7days", symbol: str | None = None) -> list:
        return self.call("GetBlockDeals", exchange=exchange, range=range_, instrumentIdentifier=symbol) or []

    def fii_dii(self, exchange: str, client_type: str, from_ts: int, to_ts: int) -> list:
        return self.call("GetFIIDII", exchange=exchange, clientType=client_type, **{"from": from_ts, "to": to_ts}) or []
