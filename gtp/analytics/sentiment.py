"""Aggregate GDF news sentiment into scores traders can act on."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

WEIGHT = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}


def score(articles: Iterable[dict]) -> dict:
    """Net sentiment from -1 (all negative) to +1 (all positive), with counts."""
    arts = list(articles)
    counts = Counter((a.get("sentiment") or "neutral").lower() for a in arts)
    n = sum(counts.values())
    net = sum(WEIGHT.get(k, 0.0) * v for k, v in counts.items()) / n if n else 0.0
    if n == 0:
        label = "no coverage"
    elif net >= 0.25:
        label = "bullish"
    elif net <= -0.25:
        label = "bearish"
    else:
        label = "mixed"
    by_type: dict[str, Counter] = defaultdict(Counter)
    for a in arts:
        by_type[a.get("article_type") or "Other"][(a.get("sentiment") or "neutral").lower()] += 1
    return {
        "articles": n,
        "positive": counts.get("positive", 0),
        "negative": counts.get("negative", 0),
        "neutral": counts.get("neutral", 0),
        "net_score": round(net, 3),
        "label": label,
        "by_article_type": {k: dict(v) for k, v in by_type.items()},
    }


def by_symbol(articles: Iterable[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for a in articles:
        if a.get("symbol"):
            groups[a["symbol"]].append(a)
    rows = [{"symbol": s, **score(arts)} for s, arts in groups.items()]
    return sorted(rows, key=lambda r: -r["net_score"])
