"""Join detector inventory to actual billed amounts via Cost Management.

The trick is to do **one** subscription-scoped `/query` per cycle —
grouped by `ResourceId` — rather than one query per finding. Cost
Management is heavily throttled (~5 req/min/subscription), so per-ID
queries would either rate-limit or take minutes for a tenant of any size.

Flow per page load:

    detectors      cost_actuals.price_resources(items)
       │                       │
       │   list[(rid, fallback_estimate)]
       └──────────────►        │
                               │   await _all_actuals()  ← cached ~10 min
                               │       │
                               │       └─►  one CM /query, group by ResourceId
                               │
                               │   per item:  actual if present, else fallback
                               ▼
                       (total, cost_source)

`cost_source` is one of:

* **actual**   — every priced resource had a Cost Management billing row.
* **estimate** — none had a billing row; pricing.py fallbacks throughout.
* **mixed**    — some had billing rows, some didn't.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from .az_clients import cost_management
from .cache import cache
from .config import settings


log = logging.getLogger("cost_actuals")


CostSource = Literal["actual", "estimate", "mixed"]


async def _all_actuals() -> dict[str, float]:
    """One CM /query per subscription, returning {lower(resourceId): monthly_actual}.

    Window is the trailing 30 days. Result is cached for the configured TTL
    (default 10 min). On any failure we return ``{}`` — callers gracefully
    fall back to estimates.
    """
    sub = settings().target_subscription_id
    if not sub:
        return {}

    async def _fetch() -> dict[str, float]:
        def _do() -> dict[str, float]:
            client = cost_management()
            body = {
                "type": "ActualCost",
                "timeframe": "Custom",
                "timePeriod": {
                    "from": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
                    "to":   datetime.now(timezone.utc).isoformat(),
                },
                "dataset": {
                    "granularity": "None",
                    "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                    "grouping": [{"type": "Dimension", "name": "ResourceId"}],
                },
            }
            try:
                result = client.query.usage(scope=f"/subscriptions/{sub}", parameters=body)
            except Exception as e:  # noqa: BLE001
                log.warning("Cost Management /query failed: %s", e)
                return {}

            cols = [c.name for c in (result.columns or [])]
            if "Cost" not in cols or "ResourceId" not in cols:
                return {}
            cost_idx = cols.index("Cost")
            rid_idx = cols.index("ResourceId")

            out: dict[str, float] = {}
            for row in (result.rows or []):
                if rid_idx >= len(row) or cost_idx >= len(row):
                    continue
                rid = str(row[rid_idx] or "").lower().strip()
                if not rid:
                    continue
                try:
                    out[rid] = float(row[cost_idx])
                except (TypeError, ValueError):
                    continue
            return out

        return await asyncio.to_thread(_do)

    return await cache.get_or_fetch("cost_actuals:all", _fetch)


async def price_resources(
    items: list[tuple[str, float]],
) -> tuple[float, CostSource]:
    """Sum monthly cost across items, preferring Cost Management actuals.

    ``items`` is a list of ``(resource_id, fallback_estimate)`` tuples.
    The fallback is used per-resource when no billing row exists for that
    ID (e.g., never-attached ASR replicas; freshly-created resources).

    Returns (total_monthly, cost_source).
    """
    if not items:
        return 0.0, "estimate"

    actuals = await _all_actuals()
    total = 0.0
    actual_n = 0
    estimate_n = 0
    for rid, fallback in items:
        a = actuals.get(rid.lower())
        if a is not None:
            total += a
            actual_n += 1
        else:
            total += max(0.0, fallback)
            estimate_n += 1

    if estimate_n == 0:
        src: CostSource = "actual"
    elif actual_n == 0:
        src = "estimate"
    else:
        src = "mixed"
    return round(total, 2), src
