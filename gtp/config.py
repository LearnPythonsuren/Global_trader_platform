"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

from .net import DEFAULT_DOC_HOSTS

# Fifty liquid NSE large caps. Replace with your own list through GTP_UNIVERSE_CSV.
DEFAULT_UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "SUNPHARMA", "TITAN", "BAJFINANCE", "WIPRO", "ULTRACEMCO", "TATAMOTORS",
    "NTPC", "POWERGRID", "ONGC", "COALINDIA", "BPCL", "BAJAJFINSV", "HCLTECH", "TECHM", "LTIM", "NESTLEIND",
    "BRITANNIA", "TATACONSUM", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP", "TATASTEEL", "JSWSTEEL", "HINDALCO",
    "ADANIENT", "ADANIPORTS", "GRASIM", "HEROMOTOCO", "EICHERMOT", "BAJAJ-AUTO", "INDUSINDBK", "SBILIFE", "HDFCLIFE",
    "TRENT", "BEL",
]
DEFAULT_INDICES = ["NIFTY 50", "NIFTY BANK"]
DEMO_INDICES = ["NIFTY 50", "NIFTY BANK", "NIFTY IT", "NIFTY MIDCAP 100", "INDIA VIX"]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so the project has no extra dependency for it."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _universe_from_csv(path: str) -> list[str]:
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        col = next((c for c in reader.fieldnames or [] if c.strip().lower() in ("identifier", "symbol")), None)
        if col is None:
            raise ValueError(f"{path}: expected an 'Identifier' or 'Symbol' column")
        return [row[col].strip() for row in reader if row.get(col, "").strip()]


@dataclass
class Settings:
    mode: str = "demo"

    price_base_url: str = ""
    price_access_key: str = ""
    fundamental_base_url: str = "https://test.lisuns.com:4532"
    fundamental_access_key: str = ""
    mf_base_url: str = ""
    mf_access_key: str = ""
    news_base_url: str = ""
    news_api_key: str = ""

    webhook_secret: str = ""
    admin_token: str = ""
    db_path: str = "gtp.db"
    universe: list[str] = field(default_factory=lambda: list(DEFAULT_UNIVERSE))
    #: Index symbols shown in the market tape. None means "pick the default for the mode".
    indices: list[str] | None = None
    index_exchange: str = "NSE_IDX"
    price_exchange: str = "NSE"
    fundamental_exchange: str = "BSE"

    http_timeout: float = 15.0
    diagnostic_retries: int = 5

    # Earnings-call document reader: allowlisted hosts and optional transcription service.
    doc_allowed_hosts: list[str] = field(default_factory=lambda: list(DEFAULT_DOC_HOSTS))
    doc_max_bytes: int = 30_000_000
    transcribe_url: str = ""
    transcribe_key: str = ""
    transcribe_model: str = "whisper-1"

    def __post_init__(self) -> None:
        if self.indices is None:
            self.indices = list(DEMO_INDICES if self.demo else DEFAULT_INDICES)

    @property
    def demo(self) -> bool:
        return self.mode.lower() != "live"

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Settings":
        _load_dotenv(Path(env_file))
        e = os.environ.get
        universe_csv = e("GTP_UNIVERSE_CSV", "")
        return cls(
            mode=e("GTP_MODE", "demo"),
            price_base_url=e("GDF_PRICE_BASE_URL", ""),
            price_access_key=e("GDF_PRICE_ACCESS_KEY", ""),
            fundamental_base_url=e("GDF_FUNDAMENTAL_BASE_URL", "https://test.lisuns.com:4532"),
            fundamental_access_key=e("GDF_FUNDAMENTAL_ACCESS_KEY", ""),
            mf_base_url=e("GDF_MF_BASE_URL", ""),
            mf_access_key=e("GDF_MF_ACCESS_KEY", ""),
            news_base_url=e("GDF_NEWS_BASE_URL", ""),
            news_api_key=e("GDF_NEWS_API_KEY", ""),
            webhook_secret=e("GTP_WEBHOOK_SECRET", ""),
            admin_token=e("GTP_ADMIN_TOKEN", ""),
            # Vercel's filesystem is read-only except /tmp (and /tmp is per-instance, not durable).
            db_path=e("GTP_DB_PATH", "/tmp/gtp.db" if e("VERCEL") else "gtp.db"),
            universe=_universe_from_csv(universe_csv) if universe_csv else list(DEFAULT_UNIVERSE),
            indices=[i.strip() for i in e("GTP_INDICES", "").split(",") if i.strip()] or None,
            index_exchange=e("GTP_INDEX_EXCHANGE", "NSE_IDX"),
            price_exchange=e("GTP_PRICE_EXCHANGE", "NSE"),
            fundamental_exchange=e("GTP_FUNDAMENTAL_EXCHANGE", "BSE"),
            doc_allowed_hosts=([h.strip() for h in e("GTP_DOC_ALLOWED_HOSTS", "").split(",") if h.strip()]
                               or list(DEFAULT_DOC_HOSTS)),
            transcribe_url=e("GTP_TRANSCRIBE_URL", ""),
            transcribe_key=e("GTP_TRANSCRIBE_KEY", ""),
            transcribe_model=e("GTP_TRANSCRIBE_MODEL", "whisper-1"),
        )
