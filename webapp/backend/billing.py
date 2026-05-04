"""Detect the tenant's billing currency.

Strategy: instead of requiring Billing Account Reader (which is hard to
provision and tenant-specific), we issue a tiny Cost Management `/query`
against the configured subscription and read the `Currency` column from
the response. Cost Management Reader is a pre-existing requirement for
this app, so this needs no extra RBAC.

Override: ``REPORTING_CURRENCY`` env var. Set to a 3-letter ISO code
(e.g., ``GBP``) to bypass detection. Set to ``auto`` (the default) to
detect.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .az_clients import cost_management
from .cache import cache
from .config import settings


log = logging.getLogger("billing")


# Display glyphs for the most common Azure billing currencies. Falls back
# to the ISO code if a currency isn't here. Operators can extend this map.
CURRENCY_GLYPHS: dict[str, str] = {
    "USD": "$",  "GBP": "£",  "EUR": "€",  "JPY": "¥",  "AUD": "A$",
    "CAD": "C$", "CHF": "Fr.","INR": "₹", "SEK": "kr", "NOK": "kr",
    "DKK": "kr", "NZD": "NZ$","ZAR": "R",  "BRL": "R$","MXN": "Mex$",
    "SGD": "S$", "HKD": "HK$","KRW": "₩", "RUB": "₽",  "TWD": "NT$",
    "CNY": "¥",  "TRY": "₺",  "PLN": "zł","ILS": "₪",
}


@dataclass(frozen=True)
class BillingContext:
    currency_code: str
    glyph: str
    source: str  # "detected" | "override" | "fallback"

    def to_dict(self) -> dict[str, str]:
        return {"currency_code": self.currency_code, "glyph": self.glyph, "source": self.source}


def _glyph_for(code: str) -> str:
    return CURRENCY_GLYPHS.get(code.upper(), code.upper())


async def _probe_currency() -> str | None:
    """Run a 1-day Cost Management query and read the Currency column.

    Returns the ISO code or ``None`` if the call fails (typically because
    Cost Management Reader hasn't been granted yet).
    """
    sub = settings().target_subscription_id
    if not sub:
        return None

    def _do() -> str | None:
        client = cost_management()
        # Tiny 1-day window minimises cost and latency. We only need any row.
        body = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {
                "from": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                "to":   datetime.now(timezone.utc).isoformat(),
            },
            "dataset": {
                "granularity": "None",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            },
        }
        try:
            result = client.query.usage(scope=f"/subscriptions/{sub}", parameters=body)
        except Exception as e:  # noqa: BLE001 — graceful degradation
            log.warning("currency probe failed: %s", e)
            return None

        # Locate the Currency column index, then read the first row.
        cols = [c.name for c in (result.columns or [])]
        if "Currency" not in cols or not (result.rows or []):
            return None
        idx = cols.index("Currency")
        first = result.rows[0]
        return str(first[idx]).upper() if idx < len(first) else None

    return await asyncio.to_thread(_do)


async def context() -> BillingContext:
    """Resolve and cache the tenant billing context.

    Cached for the configured TTL (default 10 min). Call sites should
    treat this as a hot path — it's invoked once per page-load.
    """
    override = settings().reporting_currency
    if override and override.lower() != "auto":
        code = override.upper()
        return BillingContext(code, _glyph_for(code), "override")

    async def _fetch() -> BillingContext:
        detected = await _probe_currency()
        if detected:
            return BillingContext(detected, _glyph_for(detected), "detected")
        # Tenant query failed (no permission / no spend yet). Fall back
        # to USD; operators can override via REPORTING_CURRENCY.
        return BillingContext("USD", "$", "fallback")

    return await cache.get_or_fetch("billing:context", _fetch, ttl_override=3600)
