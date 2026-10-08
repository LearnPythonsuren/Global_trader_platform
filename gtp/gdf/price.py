"""Global Datafeeds real-time and historical price data (REST API).

Docs: https://globaldatafeeds.in/global-datafeeds-apis/global-datafeeds-apis/
URL syntax: http://endpoint:port/<Function>/?accessKey=<key>&...
JSON is the default response format.
"""

from __future__ import annotations

from typing import Any, Iterable

from .base import BaseGDFClient, ci_get, first_list, to_epoch_seconds

MAX_INSTRUMENTS_PER_CALL = 25
PERIODICITIES = ("TICK", "MINUTE", "HOUR", "DAY", "WEEK", "MONTH")


def normalize_quote(row: dict, exchange: str | None = None) -> dict:
    ltp = _f(ci_get(row, "LastTradePrice", "LTP"))
    prev_close = _f(ci_get(row, "Close"))
    change = ci_get(row, "PriceChange")
    change_pct = ci_get(row, "PriceChangePercentage")
    if change is None and ltp is not None and prev_close:
        change = ltp - prev_close
        change_pct = change / prev_close * 100
    return {
        "exchange": ci_get(row, "Exchange", default=exchange),
        "symbol": ci_get(row, "InstrumentIdentifier", "Identifier"),
        "ltp": ltp,
        "open": _f(ci_get(row, "Open")),
        "high": _f(ci_get(row, "High")),
        "low": _f(ci_get(row, "Low")),
        "prev_close": prev_close,
        "change": _round(change),
        "change_pct": _round(change_pct),
        "volume": _f(ci_get(row, "TotalQtyTraded", "TradedQty")),
        "value": _f(ci_get(row, "Value")),
        "atp": _f(ci_get(row, "AverageTradedPrice")),
        "bid": _f(ci_get(row, "BuyPrice")),
        "ask": _f(ci_get(row, "SellPrice")),
        "bid_qty": _f(ci_get(row, "BuyQty")),
        "ask_qty": _f(ci_get(row, "SellQty")),
        "open_interest": _f(ci_get(row, "OpenInterest")),
        "lot_size": _f(ci_get(row, "QuotationLot")),
        "last_trade_time": to_epoch_seconds(ci_get(row, "LastTradeTime")),
        "server_time": to_epoch_seconds(ci_get(row, "ServerTime")),
    }


def parse_option_identifier(identifier: str) -> dict:
    """OPTIDX_NIFTY_15JUL2021_CE_14650 -> expiry, option_type, strike."""
    parts = identifier.split("_")
    if len(parts) >= 5 and parts[3] in ("CE", "PE"):
        return {"expiry": parts[2], "option_type": parts[3], "strike": _f(parts[4])}
    return {}


def normalize_candle(row: dict) -> dict:
    return {
        "t": to_epoch_seconds(ci_get(row, "LastTradeTime")),
        "o": _f(ci_get(row, "Open")),
        "h": _f(ci_get(row, "High")),
        "l": _f(ci_get(row, "Low")),
        "c": _f(ci_get(row, "Close")),
        "v": _f(ci_get(row, "TradedQty", "TotalQtyTraded")),
        "oi": _f(ci_get(row, "OpenInterest")),
    }


class PriceClient(BaseGDFClient):
    api_name = "Price"
    key_param = "accessKey"

    def _url(self, function: str) -> str:
        # GDF's price REST docs use a trailing slash: /GetLastQuote/?accessKey=...
        return f"{self.base_url}/{function.strip('/')}/"

    # -- quotes ------------------------------------------------------------
    def last_quote(self, exchange: str, symbol: str) -> dict:
        data = self.call("GetLastQuote", exchange=exchange, instrumentIdentifier=symbol)
        row = data[0] if isinstance(data, list) and data else data
        return normalize_quote(row, exchange)

    def last_quotes(self, exchange: str, symbols: Iterable[str]) -> list[dict]:
        """Quotes for many symbols; batches into calls of 25 as GDF requires."""
        symbols = list(symbols)
        out: list[dict] = []
        for i in range(0, len(symbols), MAX_INSTRUMENTS_PER_CALL):
            chunk = symbols[i : i + MAX_INSTRUMENTS_PER_CALL]
            data = self.call("GetLastQuoteArray", exchange=exchange, instrumentIdentifiers=chunk)
            out.extend(normalize_quote(r, exchange) for r in first_list(data))
        return out

    # -- history -----------------------------------------------------------
    def history(
        self,
        exchange: str,
        symbol: str,
        periodicity: str = "DAY",
        period: int = 1,
        from_ts: int | None = None,
        to_ts: int | None = None,
        max_bars: int = 0,
        adjust_splits: bool = True,
    ) -> list[dict]:
        periodicity = periodicity.upper()
        if periodicity not in PERIODICITIES:
            raise ValueError(f"periodicity must be one of {PERIODICITIES}")
        data = self.call(
            "GetHistory",
            exchange=exchange,
            instrumentIdentifier=symbol,
            periodicity=periodicity,
            period=period,
            **{"from": from_ts, "to": to_ts},
            max=max_bars,
            adjustSplits=adjust_splits,
        )
        candles = [normalize_candle(r) for r in first_list(data)]
        candles = [c for c in candles if c["t"] is not None and c["c"] is not None]
        candles.sort(key=lambda c: c["t"])
        return candles

    # -- reference data ----------------------------------------------------
    def exchanges(self) -> Any:
        return self.call("GetExchanges")

    def search_instruments(self, exchange: str, search: str, **filters: Any) -> list[dict]:
        data = self.call("GetInstrumentsOnSearch", exchange=exchange, search=search.upper(), **filters)
        return first_list(data)

    def option_chain(
        self, exchange: str, product: str, expiry: str | None = None, option_type: str | None = None,
        strike_price: float | None = None,
    ) -> list[dict]:
        data = self.call(
            "GetLastQuoteOptionChain", exchange=exchange, product=product, expiry=expiry,
            optionType=option_type, strikePrice=strike_price,
        )
        rows = []
        for r in first_list(data):
            q = normalize_quote(r, exchange)
            q["oi_change"] = _f(ci_get(r, "OpenInterestChange"))
            q["total_buy_qty"] = _f(ci_get(r, "TotalBuyQty"))
            q["total_sell_qty"] = _f(ci_get(r, "TotalSellQty"))
            q.update(parse_option_identifier(q["symbol"] or ""))
            rows.append(q)
        return rows

    def top_gainers_losers(self, exchange: str, **params: Any) -> Any:
        return self.call("GetTopGainersLosers", exchange=exchange, **params)

    def holidays(self, exchange: str) -> Any:
        return self.call("GetHolidays", exchange=exchange)


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _round(v: Any, nd: int = 4) -> float | None:
    v = _f(v)
    return None if v is None else round(v, nd)
