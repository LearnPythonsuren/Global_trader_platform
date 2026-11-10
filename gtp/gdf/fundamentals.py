"""Global Datafeeds fundamental and corporate data API.

Docs: https://docs.globaldatafeeds.in/
Every function is GET /<Function>?accessKey=...&exchange=...&format=Json.
Rows come back wrapped in {"Value": [...]}.

The typed methods below return one snake_case schema with ISO dates, so the
rest of the platform (and the demo provider) never deals with GDF's raw
field names. Use call() for the raw response of any function.
"""

from __future__ import annotations

import re
import time
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


_GDF_DATE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})(?:[ T](\d{2}):(\d{2}):(\d{2}))?$")
IST_OFFSET = 19800


def iso_date(value: Any) -> str | None:
    """Convert a GDF date to ISO text in IST: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS".

    GDF sends "MM-DD-YYYY[ HH:MM:SS]" strings (dTFormat=String), epoch seconds
    or epoch milliseconds, and uses year 0001 for "no date".
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        v = int(value)
        if v > 10_000_000_000:
            v //= 1000
        if v <= 0:
            return None
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(v + IST_OFFSET))
    m = _GDF_DATE.match(str(value).strip())
    if not m:
        return str(value)
    mm, dd, yyyy, hh, mi, ss = m.groups()
    if yyyy == "0001":
        return None
    out = f"{yyyy}-{mm}-{dd}"
    if hh and (hh, mi, ss) != ("00", "00", "00"):
        out += f" {hh}:{mi}:{ss}"
    return out


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _text(v: Any) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def snake_keys(row: dict) -> dict:
    """FutureIndexLong -> future_index_long, OptionIndexPutOI -> option_index_put_oi."""
    out = {}
    for k, v in row.items():
        k = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", k)
        k = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", k)
        out[k.lower()] = v
    return out


def normalize_company(r: dict) -> dict:
    return {"symbol": _text(r.get("Symbol")), "name": _text(r.get("CompanyName")), "isin": _text(r.get("ISIN")),
            "scrip_code": r.get("ScripCode")}


def normalize_sector(r: dict) -> dict:
    return {"symbol": _text(r.get("Symbol")), "name": _text(r.get("CompanyName")), "isin": _text(r.get("ISIN")),
            "macro": _text(r.get("MacroEconomicIndicator")), "sector": _text(r.get("Sector")),
            "industry": _text(r.get("Industry")), "basic_industry": _text(r.get("BasicIndustry"))}


def normalize_shareholding(r: dict) -> dict:
    return {"entity": _text(r.get("Entity")), "value": _num(r.get("Value")), "period": _text(r.get("Period"))}


def normalize_fact(r: dict) -> dict:
    return {"label": _text(r.get("Label")), "key": _text(r.get("Key")), "value": _num(r.get("Value")),
            "raw_value": r.get("Value"), "unit": _text(r.get("UnitId")), "decimals": r.get("Decimals"),
            "description": _text(r.get("Description"))}


def normalize_announcement(r: dict) -> dict:
    return {
        "symbol": _text(r.get("ScripId")), "name": _text(r.get("ScripName")), "scrip_code": r.get("ScripCode"),
        "date": iso_date(r.get("ReceivedAt")) or iso_date(r.get("FillingDate")),
        "headline": _text(r.get("HeadLine")) or _text(r.get("NewsSubject")), "body": _text(r.get("NewsBody")),
        "category": _text(r.get("Descriptor")) or _text(r.get("AnnounceType")),
        "critical": bool(r.get("CriticalNews")), "meeting_date": iso_date(r.get("MeetingDate")),
        "url": _text(r.get("AttachmentUrl")),
    }


def normalize_action(r: dict) -> dict:
    return {
        "symbol": _text(r.get("ScripId")), "name": _text(r.get("ScripName")), "scrip_code": r.get("ScripCode"),
        "type": _text(r.get("CorporateActionType")), "purpose_code": _text(r.get("PurposeCode")),
        "announced": iso_date(r.get("AnnouncementDate")), "ex_date": iso_date(r.get("ProvXdate")),
        "record_kind": _text(r.get("BcRdFlag")), "record_from": iso_date(r.get("BcRdFrom")),
        "record_to": iso_date(r.get("BcRdTo")), "payment_date": iso_date(r.get("PaymentDate")),
        "ratio": _text(r.get("RatioAmount")), "url": _text(r.get("AnnouncementUrl")),
    }


def normalize_result_date(r: dict) -> dict:
    return {"symbol": _text(r.get("ScripId")), "name": _text(r.get("ScripName")), "isin": _text(r.get("ISIN")),
            "date": iso_date(r.get("ResultsDate")), "ltp": _num(r.get("LTP")), "change_pct": _num(r.get("ChangePct"))}


def normalize_deal(r: dict) -> dict:
    side = (_text(r.get("DealType")) or "").upper()
    return {"date": iso_date(r.get("DealDate")), "symbol": _text(r.get("ScripId")) or _text(r.get("ScripName")),
            "scrip_code": r.get("ScripCode"), "client": _text(r.get("ClientName")),
            "side": "buy" if side.startswith("B") else "sell" if side.startswith("S") else None,
            "qty": _num(r.get("Qty")), "qty_pct": _num(r.get("QtyPct")), "price": _num(r.get("Price"))}


def normalize_participant(r: dict) -> dict:
    out = snake_keys(r)
    out["client"] = _text(out.pop("client_type", None))
    out["date"] = iso_date(out.get("date"))
    return out


def _rows(data: Any) -> list[dict]:
    if isinstance(data, dict):
        data = [data]
    return [r for r in (data or []) if isinstance(r, dict)]


class FundamentalsClient(BaseGDFClient):
    api_name = "Fundamental"
    key_param = "accessKey"
    default_params = {"format": "Json", "dTFormat": "String"}

    def call(self, function: str, **params: Any) -> Any:
        return unwrap(super().call(function, **params))

    def company(self, exchange: str, symbol: str) -> dict:
        rows = _rows(self.call("GetCompanyData", exchange=exchange, instrumentIdentifiers=symbol))
        return normalize_company(rows[0]) if rows else {}

    def ratios(self, exchange: str, symbol: str, *, kind: str = "EOD", nature: str = "Standalone",
               period: str | None = None, year: int | None = None) -> dict:
        rows = _rows(self.call("GetFinancialRatios", exchange=exchange, instrumentIdentifier=symbol,
                               type=kind, natureOfReport=nature, period=period, year=year))
        return normalize_ratios(rows[0] if rows else {})

    def financial_results(self, exchange: str, symbol: str, year: int, *, statement: str = "ProfitLoss",
                          period: str = "QD", nature: str = "Standalone") -> list[dict]:
        """Reported line items (XBRL facts) of one statement for one period."""
        rows = _rows(self.call("GetFinancialResults", exchange=exchange, instrumentIdentifier=symbol, year=year,
                               type=statement, period=period, natureOfReport=nature))
        return [normalize_fact(r) for r in rows]

    def shareholding(self, exchange: str, symbol: str, *, kind: str = "SummaryAll", period: str | None = None) -> list[dict]:
        rows = _rows(self.call("GetSHPAdvanced", exchange=exchange, instrumentIdentifier=symbol, type=kind, period=period))
        return [normalize_shareholding(r) for r in rows]

    def sector(self, exchange: str, symbol: str) -> dict:
        rows = _rows(self.call("GetSectoralClassification", exchange=exchange, instrumentIdentifiers=symbol))
        return normalize_sector(rows[0]) if rows else {}

    def announcements(self, exchange: str, symbol: str | None, from_ts: int, to_ts: int, **filters: Any) -> list[dict]:
        rows = _rows(self.call("GetCorporateAnnouncements", exchange=exchange, instrumentIdentifier=symbol,
                               **{"from": from_ts, "to": to_ts}, **filters))
        return [normalize_announcement(r) for r in rows]

    def corporate_actions(self, exchange: str, symbol: str | None, from_ts: int, to_ts: int) -> list[dict]:
        rows = _rows(self.call("GetCorporateActions", exchange=exchange, instrumentIdentifier=symbol,
                               **{"from": from_ts, "to": to_ts}))
        return [normalize_action(r) for r in rows]

    def results_calendar(self, exchange: str, range_: str = "Next7days", symbols: list[str] | None = None) -> list[dict]:
        rows = _rows(self.call("GetResultsCalendar", exchange=exchange, range=range_, instrumentIdentifiers=symbols))
        return [normalize_result_date(r) for r in rows]

    def bulk_deals(self, exchange: str, range_: str = "Previous7days", symbol: str | None = None) -> list[dict]:
        rows = _rows(self.call("GetBulkDeals", exchange=exchange, range=range_, instrumentIdentifier=symbol))
        return [normalize_deal(r) for r in rows]

    def block_deals(self, exchange: str, range_: str = "Previous7days", symbol: str | None = None) -> list[dict]:
        rows = _rows(self.call("GetBlockDeals", exchange=exchange, range=range_, instrumentIdentifier=symbol))
        return [normalize_deal(r) for r in rows]

    def annual_reports(self, exchange: str, symbol: str, from_year: int, to_year: int) -> list[dict]:
        rows = _rows(self.call("GetAnnualReports", exchange=exchange, instrumentIdentifiers=symbol,
                               **{"from": from_year, "to": to_year}))
        out = []
        for r in rows:
            out.append({"symbol": _text(r.get("ScripId")) or _text(r.get("Symbol")), "year": r.get("Year"),
                        "url": _text(r.get("AttachmentUrl")) or _text(r.get("Url")), "from_year": r.get("FromYear"),
                        "to_year": r.get("ToYear")})
        return out

    def participants(self, exchange: str = "NSE", client_type: str | None = None,
                     from_ts: int | None = None, to_ts: int | None = None) -> list[dict]:
        """Participant-wise F&O open interest (FII, DII, Pro, Client): GDF's GetFIIDII."""
        rows = _rows(self.call("GetFIIDII", exchange=exchange, clientType=client_type,
                               **{"from": from_ts, "to": to_ts}))
        return [normalize_participant(r) for r in rows]
