"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "SUNPHARMA", "TITAN", "BAJFINANCE", "WIPRO", "ULTRACEMCO", "TATAMOTORS",
]


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

    http_timeout: float = 15.0
    diagnostic_retries: int = 5

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
            db_path=e("GTP_DB_PATH", "gtp.db"),
            universe=_universe_from_csv(universe_csv) if universe_csv else list(DEFAULT_UNIVERSE),
        )
