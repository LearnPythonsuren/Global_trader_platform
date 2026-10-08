"""Mutual fund analytics built on GDF NAV and portfolio holdings data."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

DAY = 86400
HORIZONS = {"1m": 30, "3m": 91, "6m": 182, "1y": 365, "3y": 3 * 365, "5y": 5 * 365}


def _parse_date(s: str | None) -> float | None:
    if not s:
        return None
    for fmt in ("%m-%d-%Y %H:%M:%S", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    return None


def returns(hub: Any, code: str, *, now: int | None = None) -> dict:
    """Point-to-point and annualised (CAGR, for horizons over 1 year) returns."""
    now = now or int(time.time())
    latest = hub.mutual_funds.nav(code=code, max_rows=1)
    if not latest:
        raise LookupError(f"No NAV found for scheme code {code}")
    cur = latest[0]
    cur_nav = float(cur["nav"])
    out: dict[str, Any] = {"code": code, "name": cur["name"], "nav": cur_nav, "date": cur["date"], "returns": {}}
    for label, days in HORIZONS.items():
        past = hub.mutual_funds.nav_on(now - days * DAY, code=code)
        if not past or not past[0].get("nav"):
            out["returns"][label] = None
            continue
        past_nav = float(past[0]["nav"])
        abs_ret = cur_nav / past_nav - 1
        entry: dict[str, Any] = {"nav": past_nav, "date": past[0].get("date"), "absolute_pct": round(abs_ret * 100, 2)}
        if days > 365:
            entry["cagr_pct"] = round(((cur_nav / past_nav) ** (365 / days) - 1) * 100, 2)
        out["returns"][label] = entry
    return out


def compare(hub: Any, codes: list[str]) -> list[dict]:
    rows = []
    for code in codes:
        try:
            rows.append(returns(hub, code))
        except Exception as e:  # noqa: BLE001
            rows.append({"code": code, "error": str(e)})
    return rows


def overlap(hub: Any, code_a: str, code_b: str) -> dict:
    """Portfolio overlap: common stocks, and the sum over them of min(weight_a, weight_b)."""
    a = {h["isin"] or h["instrument"]: h for h in hub.mutual_funds.holdings(code=code_a)}
    b = {h["isin"] or h["instrument"]: h for h in hub.mutual_funds.holdings(code=code_b)}
    common = sorted(set(a) & set(b), key=lambda k: -min(a[k]["weight"] or 0, b[k]["weight"] or 0))
    rows = [{
        "instrument": a[k]["instrument"], "isin": a[k]["isin"],
        "weight_a": a[k]["weight"], "weight_b": b[k]["weight"],
        "overlap_weight": round(min(a[k]["weight"] or 0, b[k]["weight"] or 0), 2),
    } for k in common]
    return {
        "scheme_a": code_a, "scheme_b": code_b,
        "holdings_a": len(a), "holdings_b": len(b), "common_holdings": len(common),
        "overlap_pct": round(sum(r["overlap_weight"] for r in rows), 2),
        "common": rows,
    }


def exposure(holdings: list[dict]) -> dict:
    """Sector, market-cap bucket and asset-type breakdown of a fund portfolio."""
    def group(key: str) -> list[dict]:
        acc: dict[str, float] = {}
        for h in holdings:
            acc[h.get(key) or "Other"] = acc.get(h.get(key) or "Other", 0.0) + float(h.get("weight") or 0)
        return [{"name": k, "weight": round(v, 2)} for k, v in sorted(acc.items(), key=lambda kv: -kv[1])]

    return {"by_sector": group("sector"), "by_size": group("size"), "by_asset_type": group("asset_type"),
            "top10_weight": round(sum(sorted((float(h.get("weight") or 0) for h in holdings), reverse=True)[:10]), 2)}


def stock_in_funds(hub: Any, isin: str, codes: list[str]) -> list[dict]:
    """Which of the given schemes hold a stock (by ISIN), and at what weight."""
    out = []
    for code in codes:
        for h in hub.mutual_funds.holdings(code=code):
            if h.get("isin") == isin:
                out.append({"code": code, "weight": h["weight"], "instrument": h["instrument"]})
    return sorted(out, key=lambda r: -(r["weight"] or 0))
