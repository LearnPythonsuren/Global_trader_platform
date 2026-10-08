"""Global Datafeeds mutual fund data API.

Docs: https://mfdocs.globaldatafeeds.in/
GET /<Function>?accessKey=...&format=Json. Rows come back as {"Value": [...]}.
Schemes can be looked up by AMFI scheme ``code``, ``isin`` or ``name``.
"""

from __future__ import annotations

from typing import Any

from .base import BaseGDFClient, unwrap

FUNCTIONS = frozenset({
    "GetAMCMaster", "GetSchemeMaster", "GetSchemeTypeMaster", "GetSchemeCategoryMaster",
    "GetNAV", "GetNAVHistory", "GetAUM", "GetAUMHistory", "GetAumSchemeComparison",
    "GetAumTopGainersLosers", "GetHoldings", "GetHoldingsByType", "GetHoldingsSearch",
    "GetHoldingsWhatChanged", "GetNewFundOffers", "GetLimitation", "GetServerInfo",
})


def normalize_nav(row: dict) -> dict:
    return {
        "code": str(row.get("Code", "")),
        "name": row.get("Name"),
        "nav": row.get("Value"),
        "date": row.get("Date"),
        "isin_growth": row.get("ISINGrowth") or None,
        "isin_div_payout": row.get("ISINDivPayout") or None,
        "isin_div_reinvest": row.get("ISINDivReinvest") or None,
    }


def normalize_holding(row: dict) -> dict:
    return {
        "instrument": row.get("Instrument"),
        "isin": row.get("Isin"),
        "industry": row.get("IndustryOrRating"),
        "quantity": row.get("Quantity"),
        "market_value": row.get("MarketValue"),
        "weight": row.get("Weight"),
        "asset_type": row.get("AssetType"),
        "size": row.get("Size"),
        "sector": row.get("Sector"),
        "date": row.get("Date"),
    }


class MutualFundClient(BaseGDFClient):
    api_name = "Mutual Fund"
    key_param = "accessKey"
    default_params = {"format": "Json", "dTFormat": "String"}

    def call(self, function: str, **params: Any) -> Any:
        return unwrap(super().call(function, **params))

    def amcs(self) -> list:
        return self.call("GetAMCMaster") or []

    def schemes(self, name: str | None = None, category: str | None = None, type_: str | None = None) -> list:
        return self.call("GetSchemeMaster", name=name, category=category, type=type_) or []

    def categories(self) -> list:
        return self.call("GetSchemeCategoryMaster") or []

    def nav(self, *, code: str | None = None, isin: str | None = None, name: str | None = None,
            category: str | None = None, max_rows: int = 100) -> list[dict]:
        rows = self.call("GetNAV", detailedInfo=True, code=code, isin=isin, name=name,
                         category=category, max=max_rows) or []
        return [normalize_nav(r) for r in rows]

    def nav_on(self, date_ts: int, *, code: str | None = None, isin: str | None = None) -> list[dict]:
        rows = self.call("GetNAVHistory", detailedInfo=False, code=code, isin=isin, date=date_ts) or []
        return [normalize_nav(r) for r in rows]

    def aum(self, *, isin: str | None = None, code: str | None = None) -> list:
        return self.call("GetAUM", isin=isin, code=code) or []

    def holdings(self, *, code: str | None = None, isin: str | None = None, name: str | None = None,
                 filter_: str = "All") -> list[dict]:
        rows = self.call("GetHoldings", code=code, isin=isin, name=name, filter=filter_) or []
        return [normalize_holding(r) for r in rows]

    def holdings_what_changed(self, name: str) -> list:
        return self.call("GetHoldingsWhatChanged", name=name) or []

    def new_fund_offers(self, range_: str = "Past365Days") -> list:
        return self.call("GetNewFundOffers", range=range_) or []
