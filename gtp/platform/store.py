"""SQLite storage for customers, API keys, usage metering and webhook news."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from .plans import Plan, get_plan

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    plan TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    customer_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (customer_id, day, endpoint)
);
CREATE TABLE IF NOT EXISTS news_articles (
    article_key TEXT PRIMARY KEY,
    symbol TEXT,
    sentiment TEXT,
    received_at INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS news_symbol ON news_articles(symbol, received_at);
"""


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_api_key() -> str:
    return "gtp_" + secrets.token_urlsafe(30)


@dataclass
class Customer:
    id: int
    name: str
    email: str
    plan: Plan
    key_prefix: str
    active: bool
    created_at: int

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "email": self.email, "plan": self.plan.id,
                "key_prefix": self.key_prefix, "active": self.active, "created_at": self.created_at}


class RateLimitExceeded(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class Store:
    def __init__(self, path: str = "gtp.db"):
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        self._minute: dict[int, deque] = {}
        self._day_cache: dict[tuple[int, str], int] = {}

    def close(self) -> None:
        self._db.close()

    # -- customers -----------------------------------------------------------
    def create_customer(self, name: str, email: str, plan: str, api_key: str | None = None) -> tuple[Customer, str]:
        """Create a customer. Returns the customer and the plaintext key (shown once)."""
        get_plan(plan)
        key = api_key or new_api_key()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO customers (name, email, plan, key_hash, key_prefix, created_at) VALUES (?,?,?,?,?,?)",
                (name, email, plan, hash_key(key), key[:8], int(time.time())),
            )
            self._db.commit()
            cid = cur.lastrowid
        return self.get_customer(cid), key  # type: ignore[return-value]

    def _row_to_customer(self, row: sqlite3.Row | None) -> Customer | None:
        if row is None:
            return None
        return Customer(row["id"], row["name"], row["email"], get_plan(row["plan"]), row["key_prefix"],
                        bool(row["active"]), row["created_at"])

    def get_customer(self, customer_id: int) -> Customer | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        return self._row_to_customer(row)

    def customer_by_key(self, key: str) -> Customer | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM customers WHERE key_hash=?", (hash_key(key),)).fetchone()
        return self._row_to_customer(row)

    def list_customers(self) -> list[Customer]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM customers ORDER BY id").fetchall()
        return [c for c in (self._row_to_customer(r) for r in rows) if c]

    def update_customer(self, customer_id: int, *, plan: str | None = None, active: bool | None = None) -> Customer | None:
        if plan is not None:
            get_plan(plan)
        with self._lock:
            if plan is not None:
                self._db.execute("UPDATE customers SET plan=? WHERE id=?", (plan, customer_id))
            if active is not None:
                self._db.execute("UPDATE customers SET active=? WHERE id=?", (int(active), customer_id))
            self._db.commit()
        return self.get_customer(customer_id)

    def rotate_key(self, customer_id: int) -> str:
        key = new_api_key()
        with self._lock:
            self._db.execute("UPDATE customers SET key_hash=?, key_prefix=? WHERE id=?",
                             (hash_key(key), key[:8], customer_id))
            self._db.commit()
        return key

    # -- metering & limits ---------------------------------------------------
    def check_and_record(self, customer: Customer, endpoint: str, *, now: float | None = None) -> dict:
        """Apply per-minute and per-day limits, then record one request."""
        now = now or time.time()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        plan = customer.plan
        with self._lock:
            window = self._minute.setdefault(customer.id, deque())
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= plan.requests_per_minute:
                raise RateLimitExceeded(f"Rate limit of {plan.requests_per_minute}/min reached for plan {plan.id}",
                                        retry_after=max(1, int(window[0] + 60 - now) + 1))
            dkey = (customer.id, day)
            used_today = self._day_cache.get(dkey)
            if used_today is None:
                row = self._db.execute("SELECT COALESCE(SUM(count),0) FROM usage WHERE customer_id=? AND day=?",
                                       (customer.id, day)).fetchone()
                used_today = int(row[0])
            if used_today >= plan.requests_per_day:
                raise RateLimitExceeded(f"Daily quota of {plan.requests_per_day} reached for plan {plan.id}",
                                        retry_after=int(86400 - now % 86400))
            window.append(now)
            self._day_cache[dkey] = used_today + 1
            self._db.execute(
                "INSERT INTO usage (customer_id, day, endpoint, count) VALUES (?,?,?,1) "
                "ON CONFLICT(customer_id, day, endpoint) DO UPDATE SET count = count + 1",
                (customer.id, day, endpoint),
            )
            self._db.commit()
        return {"minute_remaining": plan.requests_per_minute - len(window),
                "day_remaining": plan.requests_per_day - used_today - 1}

    def usage(self, customer_id: int, days: int = 30) -> list[dict]:
        since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
        with self._lock:
            rows = self._db.execute(
                "SELECT day, endpoint, count FROM usage WHERE customer_id=? AND day>=? ORDER BY day DESC, count DESC",
                (customer_id, since),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- webhook news ------------------------------------------------------------
    def save_article(self, article: dict) -> bool:
        """Store a pushed article. Returns False if it was already stored."""
        key = str(article.get("article_id") or article.get("link") or hash_key(json.dumps(article, sort_keys=True)))
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO news_articles (article_key, symbol, sentiment, received_at, payload) "
                "VALUES (?,?,?,?,?)",
                (key, article.get("symbol"), article.get("sentiment"), int(time.time()), json.dumps(article)),
            )
            self._db.commit()
        return cur.rowcount > 0

    def recent_articles(self, symbols: list[str] | None = None, limit: int = 50) -> list[dict[str, Any]]:
        q = "SELECT payload FROM news_articles"
        args: list[Any] = []
        if symbols:
            q += f" WHERE symbol IN ({','.join('?' * len(symbols))})"
            args += symbols
        q += " ORDER BY received_at DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db.execute(q, args).fetchall()
        return [json.loads(r[0]) for r in rows]
