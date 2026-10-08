"""Authentication, plan gating and metering for the customer-facing API."""

from __future__ import annotations

import hmac
from typing import Callable

from fastapi import Depends, Header, HTTPException, Query, Request, Response

from ..platform.plans import PLANS
from ..platform.store import Customer, RateLimitExceeded


def _api_key(x_api_key: str | None = Header(None), api_key: str | None = Query(None, include_in_schema=False)) -> str:
    key = x_api_key or api_key
    if not key:
        raise HTTPException(401, "Missing API key. Send it in the X-API-Key header.")
    return key


def current_customer(request: Request, key: str = Depends(_api_key)) -> Customer:
    customer = request.app.state.store.customer_by_key(key)
    if customer is None:
        raise HTTPException(401, "Invalid API key")
    if not customer.active:
        raise HTTPException(403, "This API key is disabled. Contact support.")
    return customer


def require(feature: str | None = None) -> Callable[..., Customer]:
    """Dependency: valid key, plan includes ``feature``, and within rate limits."""

    def dep(request: Request, response: Response, customer: Customer = Depends(current_customer)) -> Customer:
        if feature and feature not in customer.plan.features:
            upgrade = next((p.name for p in PLANS.values() if feature in p.features), None)
            raise HTTPException(403, f"'{feature}' is not included in the {customer.plan.name} plan"
                                     + (f"; upgrade to {upgrade}" if upgrade else ""))
        route = request.scope.get("route")
        endpoint = getattr(route, "path", request.url.path)
        try:
            quota = request.app.state.store.check_and_record(customer, endpoint)
        except RateLimitExceeded as e:
            raise HTTPException(429, str(e), headers={"Retry-After": str(e.retry_after)}) from None
        response.headers["X-RateLimit-Remaining-Minute"] = str(quota["minute_remaining"])
        response.headers["X-RateLimit-Remaining-Day"] = str(quota["day_remaining"])
        return customer

    return dep


def require_admin(request: Request, x_admin_token: str | None = Header(None)) -> None:
    expected = request.app.state.settings.admin_token
    if not expected:
        raise HTTPException(503, "Admin API disabled: set GTP_ADMIN_TOKEN")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(401, "Invalid admin token")
