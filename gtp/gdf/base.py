"""Shared HTTP plumbing for all Global Datafeeds (GDF) REST APIs.

Every GDF API is HTTP GET with query parameters. Instead of data, the server
sometimes answers with a plain-text "diagnostic response". The docs say a
client must handle these:

* "Authentication request received. Try request data in next moment." means
  the data isn't ready yet. Send the same request again until it is.
* "Access Denied. ..." means the key is bad, blocked or expired.
* Anything else in plain text (date out of range, instrument not allowed for
  a demo key, ...) is an error for the caller.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

RETRY_MARKERS = ("try request data in next moment",)
AUTH_MARKERS = ("access denied",)


class GDFError(RuntimeError):
    """GDF returned a diagnostic message instead of data."""

    def __init__(self, message: str, *, function: str = "", status: int | None = None):
        super().__init__(message)
        self.function = function
        self.status = status


class GDFAuthError(GDFError):
    """The access key was rejected (not found, blocked, expired)."""


class GDFNotConfigured(GDFError):
    """The base URL or key for this API is not set."""


class BaseGDFClient:
    """Builds requests, decodes JSON, and handles GDF diagnostic responses."""

    #: Name of the query parameter that carries the key ("accessKey" or "api_key").
    key_param = "accessKey"
    #: Extra parameters sent with every request (e.g. format=Json).
    default_params: dict[str, Any] = {}
    #: Name of the product, used in error messages.
    api_name = "GDF"

    def __init__(
        self,
        base_url: str,
        access_key: str,
        *,
        timeout: float = 15.0,
        retries: int = 5,
        retry_delay: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.access_key = access_key or ""
        self.retries = retries
        self.retry_delay = retry_delay
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    # -- request helpers ---------------------------------------------------
    def _url(self, function: str) -> str:
        return f"{self.base_url}/{function.lstrip('/')}"

    def call(self, function: str, **params: Any) -> Any:
        """Call any GDF function by name and return the decoded JSON.

        Parameters set to ``None`` are dropped. Lists are joined with ``+``,
        which GDF uses to separate multiple identifiers.
        """
        if not self.base_url or not self.access_key:
            raise GDFNotConfigured(
                f"{self.api_name} API is not configured (set its base URL and key)", function=function
            )
        query: dict[str, Any] = {**self.default_params, self.key_param: self.access_key}
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, (list, tuple)):
                v = "+".join(str(x) for x in v)
            elif isinstance(v, bool):
                v = "true" if v else "false"
            query[k] = v

        delay = self.retry_delay
        for attempt in range(self.retries + 1):
            resp = self._http.get(self._url(function), params=query)
            body = resp.text
            data = _try_json(body)
            if data is not _NOT_JSON:
                if resp.status_code >= 400:
                    raise GDFError(_short(body), function=function, status=resp.status_code)
                return data

            message = body.strip().strip('"')
            low = message.lower()
            if any(m in low for m in RETRY_MARKERS) and attempt < self.retries:
                time.sleep(delay)
                delay = min(delay * 2, 4.0)
                continue
            if any(m in low for m in AUTH_MARKERS) or resp.status_code in (401, 403):
                raise GDFAuthError(_short(message), function=function, status=resp.status_code)
            raise GDFError(_short(message) or f"HTTP {resp.status_code}", function=function, status=resp.status_code)
        raise GDFError("Data not ready after retries", function=function)  # pragma: no cover


_NOT_JSON = object()


def _try_json(body: str) -> Any:
    body = body.strip()
    if not body or body[0] not in "[{":
        return _NOT_JSON
    try:
        return json.loads(body)
    except ValueError:
        return _NOT_JSON


def _short(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


# -- response normalisation helpers ----------------------------------------
def unwrap(data: Any) -> Any:
    """GDF fundamental/MF responses wrap rows in {"Value": [...]}."""
    if isinstance(data, dict):
        for key in ("Value", "value", "data", "Data", "result", "Result"):
            if key in data:
                return data[key]
    return data


def first_list(data: Any) -> list:
    """Return the first list found in a response (top level or one level down)."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def ci_get(row: dict, *names: str, default: Any = None) -> Any:
    """Case-insensitive dict lookup. GDF mixes LASTTRADEPRICE and LastTradePrice."""
    if not isinstance(row, dict):
        return default
    lowered = {k.lower(): v for k, v in row.items()}
    for n in names:
        v = lowered.get(n.lower())
        if v is not None:
            return v
    return default


def to_epoch_seconds(value: Any) -> int | None:
    """GDF timestamps come in seconds or milliseconds; normalise to seconds."""
    if value is None or value == "":
        return None
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return None
    return v // 1000 if v > 10_000_000_000 else v
