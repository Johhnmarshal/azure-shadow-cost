"""Detector implementations.

Each detector is an async function that returns a list of :class:`Finding`.
They share helpers for running KQL via Azure Resource Graph and for
estimating monthly cost from the inventory shape.

These are intentionally conservative on cost estimates — better to under-
promise and over-deliver. If you have actual unit-cost telemetry from your
EA, replace the constants in :mod:`pricing`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

from . import pricing
from .az_clients import resource_graph
from .cache import cache
from .config import settings
from .models import Finding


log = logging.getLogger("detectors")
KQL_DIR = Path(__file__).parent / "kql"


# ----------------------------------------------------------------------------
# Resource Graph helper
# ----------------------------------------------------------------------------

def _load_kql(name: str, **substitutions: str) -> str:
    text = (KQL_DIR / f"{name}.kql").read_text()
    for key, value in substitutions.items():
        text = text.replace("{" + key + "}", value)
    return text


async def _run_arg(query: str, page_size: int = 1000) -> list[dict[str, Any]]:
    """Submit a KQL query against Resource Graph for the configured sub.

    Resource Graph is synchronous in the SDK; we run it in a thread to keep
    FastAPI's event loop free.
    """
    import asyncio

    sub = settings().target_subscription_id
    if not sub:
        raise RuntimeError("TARGET_SUBSCRIPTION_ID is not set.")

    def _do() -> list[dict[str, Any]]:
        client = resource_graph()
        rows: list[dict[str, Any]] = []
        skip_token: str | None = None
        while True:
            req = QueryRequest(
                subscriptions=[sub],
                query=query,
                options=QueryRequestOptions(
                    top=page_size,
                    skip_token=skip_token,
                    result_format="objectArray",
                ),
            )
            resp = client.resources(req)
            rows.extend(resp.data or [])
            skip_token = getattr(resp, "skip_token", None)
            if not skip_token:
                break
        return rows

    return await asyncio.to_thread(_do)


def _required_tags_kql_list() -> str:
    return ", ".join(f'"{t}"' for t in settings().required_tags)


def _make_id(detector: str, *parts: str) -> str:
    seed = ":".join((detector,) + parts)
    return f"{detector}:{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"


def _env_bucket(env_value: str) -> str:
    e = (env_value or "").lower()
    if e in {"prod", "production"}:
        return "prod"
    if e in {"dev", "development", "test", "qa", "staging", "sandbox", "nonprod", "non-prod"}:
        return "nonprod"
    return "unknown"


# ----------------------------------------------------------------------------
# Detectors — Orphaned & idle infra
# ----------------------------------------------------------------------------

async def detect_unattached_disks() -> list[Finding]:
    rows = await cache.get_or_fetch(
        "arg:unattached_disks",
        lambda: _run_arg(_load_kql("unattached_disks")),
    )
    if not rows:
        return []
    monthly = sum(pricing.disk_monthly_usd(r.get("sku", "Premium_LRS"), int(r.get("sizeGB", 0))) for r in rows)
    sample = ", ".join(r["name"] for r in rows[:3])
    return [Finding(
        id=_make_id("unattached_disks", *(r["id"] for r in rows[:25])),
        detector="unattached_disks",
        category="Orphaned storage",
        resource=f"{len(rows)} unattached managed disks ({sample}{'…' if len(rows) > 3 else ''})",
        resource_ids=[r["id"] for r in rows],
        owner="(untagged)" if all(r.get("owner") == "(untagged)" for r in rows) else "mixed",
        env=_env_bucket(rows[0].get("env", "")),
        savings_monthly_usd=round(monthly, 2),
        effort_hours=max(1, len(rows) // 50),
        risk="Low",
        tier="Crawl",
        business_value=f"Frees ~${monthly*12:,.0f}/yr. Pair with deny-mode Azure Policy on unattached disk creation.",
    )]


async def detect_unused_public_ips() -> list[Finding]:
    rows = await cache.get_or_fetch(
        "arg:unused_public_ips",
        lambda: _run_arg(_load_kql("unused_public_ips")),
    )
    chargeable = [r for r in rows if r.get("sku") == "Standard"]
    if not chargeable:
        return []
    monthly = pricing.PUBLIC_IP_STANDARD_MONTHLY_USD * len(chargeable)
    return [Finding(
        id=_make_id("unused_public_ips", *(r["id"] for r in chargeable[:25])),
        detector="unused_public_ips",
        category="Orphaned network",
        resource=f"{len(chargeable)} unattached Standard public IPs",
        resource_ids=[r["id"] for r in chargeable],
        owner="mixed" if any(r.get("owner") != "(untagged)" for r in chargeable) else "(untagged)",
        env="unknown",
        savings_monthly_usd=round(monthly, 2),
        effort_hours=max(1, len(chargeable) // 100),
        risk="Low",
        tier="Crawl",
        business_value="Pure waste. Add Azure Policy to deny-create unattached Standard PIPs.",
    )]


async def detect_empty_app_service_plans() -> list[Finding]:
    rows = await cache.get_or_fetch(
        "arg:empty_asp",
        lambda: _run_arg(_load_kql("empty_app_service_plans")),
    )
    if not rows:
        return []
    monthly = sum(pricing.app_service_plan_monthly_usd(r.get("skuName", "B1")) for r in rows)
    return [Finding(
        id=_make_id("empty_asp", *(r["id"] for r in rows[:25])),
        detector="empty_app_service_plans",
        category="Idle compute",
        resource=f"{len(rows)} App Service Plans with zero hosted apps",
        resource_ids=[r["id"] for r in rows],
        owner="mixed",
        env="unknown",
        savings_monthly_usd=round(monthly, 2),
        effort_hours=max(1, len(rows) // 20),
        risk="Low",
        tier="Crawl",
        business_value="Plans bill regardless of attached sites. Delete after confirming with each owner.",
    )]


# ----------------------------------------------------------------------------
# Detectors — Allocation / tagging gap
# ----------------------------------------------------------------------------

async def detect_tagging_gap() -> list[Finding]:
    rows = await cache.get_or_fetch(
        "arg:untagged",
        lambda: _run_arg(_load_kql("untagged_resources", required_tags=_required_tags_kql_list())),
    )
    if not rows:
        return []
    by_type: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    findings: list[Finding] = []
    for rtype, items in sorted(by_type.items(), key=lambda x: -len(x[1]))[:10]:
        # Cost estimate: assume ~$25/mo opportunity per untagged resource —
        # this is a coarse "unattributed spend" proxy until joined with CM.
        est = 25.0 * len(items)
        findings.append(Finding(
            id=_make_id("tagging_gap", rtype),
            detector="tagging_gap",
            category="Tagging",
            resource=f"{len(items)} {rtype} resources missing required tags",
            resource_ids=[r["id"] for r in items],
            owner="(untagged)",
            env="unknown",
            savings_monthly_usd=round(est, 2),
            effort_hours=max(2, len(items) // 30),
            risk="Low",
            tier="Crawl",
            business_value=(
                "Closes the Visibility Gap. Required before any rightsizing or commitment-coverage decision —"
                " you cannot allocate what you cannot attribute."
            ),
        ))
    return findings


# ----------------------------------------------------------------------------
# Detectors — Commitment drift (Reservations / Savings Plans)
# ----------------------------------------------------------------------------

async def detect_commitment_drift() -> list[Finding]:
    """Surface RIs / SPs whose 30-day utilization is below the break-even.

    Uses the Consumption API's `reservation_recommendation_details` and
    `reservations_summaries` endpoints. Requires Reservations Reader at
    the billing scope; if the call 403s, return a single advisory finding
    instead of crashing.
    """
    from .az_clients import consumption
    import asyncio

    async def _fetch() -> list[dict[str, Any]]:
        def _do() -> list[dict[str, Any]]:
            try:
                client = consumption()
                # 'monthly' grain, last 30 days
                summaries = client.reservations_summaries.list_by_reservation_order(
                    reservation_order_id="-",
                    grain="monthly",
                )
                out: list[dict[str, Any]] = []
                for s in summaries:
                    out.append({
                        "reservationOrderId": s.reservation_order_id,
                        "reservationId": s.reservation_id,
                        "skuName": s.sku_name,
                        "avgUtilizationPercentage": float(s.avg_utilization_percentage or 0),
                        "minUtilizationPercentage": float(s.min_utilization_percentage or 0),
                        "reservedHours": float(s.reserved_hours or 0),
                        "usedHours": float(s.used_hours or 0),
                    })
                return out
            except Exception as e:  # noqa: BLE001 — broad for graceful degradation
                log.warning("commitment_drift fetch failed: %s", e)
                return []

        return await asyncio.to_thread(_do)

    rows = await cache.get_or_fetch("commitment:summaries", _fetch)
    if not rows:
        return [Finding(
            id="commitment:advisory",
            detector="commitment_advisory",
            category="Commitment",
            resource="Reservations / Savings Plans summary unavailable",
            resource_ids=[],
            owner="finops",
            env="prod",
            savings_monthly_usd=0,
            effort_hours=1,
            risk="Low",
            tier="Walk",
            business_value=(
                "Grant Reservations Reader at the billing-account scope to enable commitment-drift detection."
            ),
        )]

    underused = [r for r in rows if r["avgUtilizationPercentage"] < 70]
    if not underused:
        return []
    # Conservative: 25% of the unused hours converts to recoverable spend if
    # exchanged or sized down. ~$0.10/hour blended per RI as an opener.
    recoverable = sum((r["reservedHours"] - r["usedHours"]) * 0.10 * 0.25 for r in underused)
    return [Finding(
        id=_make_id("commitment_drift", *(r["reservationId"] for r in underused[:25])),
        detector="commitment_drift",
        category="Commitment",
        resource=f"{len(underused)} reservations under 70% utilization (last 30d)",
        resource_ids=[r["reservationId"] for r in underused],
        owner="finops",
        env="prod",
        savings_monthly_usd=round(recoverable, 2),
        effort_hours=8,
        risk="Medium",
        tier="Walk",
        business_value=(
            "Exchange or right-size before renewal. Underused commitments lock today's inefficiency in for 1–3 years."
        ),
    )]


# ----------------------------------------------------------------------------
# Detectors — Data plane / PaaS waste
# ----------------------------------------------------------------------------

async def detect_overprovisioned_storage() -> list[Finding]:
    rows = await cache.get_or_fetch(
        "arg:storage_overprov",
        lambda: _run_arg(_load_kql("storage_overprovisioned_redundancy")),
    )
    if not rows:
        return []
    # Crude estimate: 50% saving relative to a baseline $20/mo per account.
    # Replace with actual CM-derived per-account spend in v1.1.
    monthly = 10 * len(rows)
    return [Finding(
        id=_make_id("storage_overprov", *(r["id"] for r in rows[:25])),
        detector="storage_overprovisioned_redundancy",
        category="Data plane",
        resource=f"{len(rows)} non-prod storage accounts on geo/zone redundancy",
        resource_ids=[r["id"] for r in rows],
        owner="mixed",
        env="nonprod",
        savings_monthly_usd=round(monthly, 2),
        effort_hours=max(2, len(rows) // 5),
        risk="Medium",
        tier="Walk",
        business_value="LRS is sufficient for ephemeral non-prod state. Confirm DR requirements per account before applying.",
    )]


async def detect_long_retention_log_analytics() -> list[Finding]:
    rows = await cache.get_or_fetch(
        "arg:la_retention",
        lambda: _run_arg(_load_kql("idle_log_analytics")),
    )
    if not rows:
        return []
    # Move retention beyond 90d to Archive tier (~$0.02/GB-mo vs Analytics $2.30/GB-mo).
    # Without ingestion volumes, estimate $80/mo per workspace.
    monthly = 80 * len(rows)
    return [Finding(
        id=_make_id("la_retention", *(r["id"] for r in rows[:25])),
        detector="long_retention_log_analytics",
        category="Log/obs",
        resource=f"{len(rows)} Log Analytics workspaces with retention > 90 days",
        resource_ids=[r["id"] for r in rows],
        owner="mixed",
        env="unknown",
        savings_monthly_usd=round(monthly, 2),
        effort_hours=max(2, len(rows)),
        risk="Medium",
        tier="Walk",
        business_value="Move >90d retention to the Archive tier; queries against archived logs incur per-GB cost only when needed.",
    )]


async def detect_overprovisioned_cosmos() -> list[Finding]:
    rows = await cache.get_or_fetch(
        "arg:cosmos_overprov",
        lambda: _run_arg(_load_kql("cosmos_overprovisioned_throughput")),
    )
    if not rows:
        return []
    monthly = 250 * len(rows)
    return [Finding(
        id=_make_id("cosmos_overprov", *(r["id"] for r in rows[:25])),
        detector="overprovisioned_cosmos",
        category="Data plane",
        resource=f"{len(rows)} non-prod Cosmos DB accounts with multi-region writes",
        resource_ids=[r["id"] for r in rows],
        owner="mixed",
        env="nonprod",
        savings_monthly_usd=round(monthly, 2),
        effort_hours=max(4, len(rows) * 2),
        risk="Medium",
        tier="Walk",
        business_value="Single-region single-write is sufficient for non-prod. Multi-region adds 2–3x RU cost.",
    )]


# ----------------------------------------------------------------------------
# Roll-up
# ----------------------------------------------------------------------------

ALL_DETECTORS = (
    # Orphaned & idle
    detect_unattached_disks,
    detect_unused_public_ips,
    detect_empty_app_service_plans,
    # Tagging
    detect_tagging_gap,
    # Commitment
    detect_commitment_drift,
    # Data plane
    detect_overprovisioned_storage,
    detect_long_retention_log_analytics,
    detect_overprovisioned_cosmos,
)


async def run_all() -> list[Finding]:
    import asyncio

    results = await asyncio.gather(*(d() for d in ALL_DETECTORS), return_exceptions=True)
    out: list[Finding] = []
    for d, r in zip(ALL_DETECTORS, results):
        if isinstance(r, Exception):
            log.exception("detector %s failed: %s", d.__name__, r)
            continue
        out.extend(r)
    return out


def visibility_gap_pct(findings: Iterable[Finding]) -> float:
    spend = [f.savings_monthly_usd for f in findings]
    untagged = [f.savings_monthly_usd for f in findings if f.owner in ("(untagged)", "mixed")]
    total = sum(spend)
    return round((sum(untagged) / total * 100) if total > 0 else 0, 1)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
