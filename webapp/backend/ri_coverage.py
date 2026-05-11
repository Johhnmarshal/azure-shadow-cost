"""RI / Savings-Plan coverage with cancellation-exposure buffer.

Aggregates the last N months of PAYG VM consumption from Cost Management by
``(MeterSubCategory, ResourceLocation)`` — the natural commitment unit.
Computes month-over-month coefficient of variation per group, picks an RI/SP
product per group based on stability, models cancellation exposure at 12% of
annual commit, and greedy-packs the highest-savings LOW+MEDIUM risk picks
into the operator-specified refund buffer.

Buffer is **explicit only**: passed via ``?buffer=`` on /api/ri-coverage, or
seeded from ``AZSHC_REFUND_BUFFER`` env var. No default. If unset, the
endpoint returns ``buffer_required: true`` and the SPA prompts.
"""
from __future__ import annotations

import asyncio
import logging
import os
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from .az_clients import cost_management
from .cache import cache
from .config import settings
from .models import Finding


log = logging.getLogger("ri_coverage")


Stability = Literal["STABLE", "VARIABLE", "UNSTABLE"]
RiskBand  = Literal["LOW", "MEDIUM", "HIGH"]


STABLE_CV_MAX:    float = 0.15
VARIABLE_CV_MAX:  float = 0.30
RI_1Y_SAVINGS:    float = 0.30
SP_1Y_SAVINGS:    float = 0.17
CANCEL_FEE_PCT:   float = 0.12

_COMMIT_PCT: dict[Stability, float] = {
    "STABLE":   0.80,
    "VARIABLE": 0.65,
    "UNSTABLE": 0.30,
}


@dataclass(frozen=True)
class GroupAnalysis:
    family: str
    region: str
    monthly_costs: tuple[float, ...]
    monthly_mean: float
    monthly_stddev: float
    cv: float
    stability: Stability
    risk: RiskBand
    product: str
    commit_pct: float
    savings_rate: float
    annual_payg: float
    annual_commit: float
    annual_savings: float
    cancellation_exposure: float


def cv(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return (0.0, 0.0, 0.0)
    mean = statistics.mean(values)
    if mean <= 0:
        return (mean, 0.0, 0.0)
    stddev = statistics.pstdev(values) if len(values) > 1 else 0.0
    return (mean, stddev, stddev / mean)


def classify(cv_value: float) -> tuple[Stability, RiskBand, str, float]:
    if cv_value < STABLE_CV_MAX:
        return ("STABLE",   "LOW",    "VM RI 1Y", RI_1Y_SAVINGS)
    if cv_value < VARIABLE_CV_MAX:
        return ("VARIABLE", "MEDIUM", "Compute SP 1Y", SP_1Y_SAVINGS)
    return     ("UNSTABLE", "HIGH",   "Compute SP 1Y (deferred)", SP_1Y_SAVINGS)


def analyse_group(family: str, region: str, monthly_costs: list[float]) -> GroupAnalysis:
    mean, stddev, cv_v = cv(monthly_costs)
    stability, risk, product, savings_rate = classify(cv_v)
    commit_pct = _COMMIT_PCT[stability]
    annual_payg = mean * 12
    annual_commit = annual_payg * commit_pct
    annual_savings = annual_commit * savings_rate
    cancellation_exposure = annual_commit * CANCEL_FEE_PCT
    return GroupAnalysis(
        family=family, region=region,
        monthly_costs=tuple(monthly_costs),
        monthly_mean=round(mean, 2),
        monthly_stddev=round(stddev, 2),
        cv=round(cv_v, 4),
        stability=stability, risk=risk,
        product=product, commit_pct=commit_pct,
        savings_rate=savings_rate,
        annual_payg=round(annual_payg, 2),
        annual_commit=round(annual_commit, 2),
        annual_savings=round(annual_savings, 2),
        cancellation_exposure=round(cancellation_exposure, 2),
    )


def build_shortlist(groups: list[GroupAnalysis], buffer: float) -> dict:
    eligible = sorted(
        [g for g in groups if g.risk in ("LOW", "MEDIUM")],
        key=lambda g: -g.annual_savings,
    )
    high_risk = [g for g in groups if g.risk == "HIGH"]

    shortlist: list[GroupAnalysis] = []
    over_buffer: list[GroupAnalysis] = []
    running = 0.0
    for g in eligible:
        if running + g.cancellation_exposure <= buffer:
            shortlist.append(g)
            running += g.cancellation_exposure
        else:
            over_buffer.append(g)

    return {
        "buffer": buffer,
        "running_exposure": round(running, 2),
        "shortlist": shortlist,
        "rejected_over_buffer": over_buffer,
        "rejected_high_risk": high_risk,
        "total_annual_savings": round(sum(g.annual_savings for g in shortlist), 2),
    }


def env_buffer() -> float | None:
    raw = os.environ.get("AZSHC_REFUND_BUFFER", "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
        return v if v >= 0 else None
    except ValueError:
        return None


async def _payg_consumption(months: int = 3) -> list[GroupAnalysis]:
    sub = settings().target_subscription_id
    if not sub:
        return []

    async def _fetch() -> list[GroupAnalysis]:
        def _do() -> list[GroupAnalysis]:
            client = cost_management()
            end = datetime.now(timezone.utc).replace(microsecond=0)
            start = end - timedelta(days=months * 31)
            body = {
                "type": "ActualCost",
                "timeframe": "Custom",
                "timePeriod": {"from": start.isoformat(), "to": end.isoformat()},
                "dataset": {
                    "granularity": "Monthly",
                    "filter": {
                        "and": [
                            {"dimensions": {"name": "ServiceName",
                                            "operator": "In",
                                            "values": ["Virtual Machines"]}},
                            {"dimensions": {"name": "PricingModel",
                                            "operator": "In",
                                            "values": ["OnDemand"]}},
                        ]
                    },
                    "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                    "grouping": [
                        {"type": "Dimension", "name": "MeterSubCategory"},
                        {"type": "Dimension", "name": "ResourceLocation"},
                    ],
                },
            }
            try:
                result = client.query.usage(scope=f"/subscriptions/{sub}", parameters=body)
            except Exception as e:  # noqa: BLE001
                log.warning("CM /query for RI coverage failed: %s", e)
                return []

            cols = [c.name for c in (result.columns or [])]
            try:
                ic = cols.index("Cost")
                im = cols.index("MeterSubCategory")
                il = cols.index("ResourceLocation")
                id_ = cols.index("UsageDate")
            except ValueError:
                log.warning("Unexpected CM columns for RI coverage: %s", cols)
                return []

            buckets: dict[tuple[str, str], dict[str, float]] = {}
            for row in (result.rows or []):
                family = str(row[im] or "Unknown")
                region = str(row[il] or "Unknown")
                date = str(row[id_])
                try:
                    cost = float(row[ic] or 0)
                except (TypeError, ValueError):
                    continue
                key = (family, region)
                buckets.setdefault(key, {})[date] = buckets[key].get(date, 0) + cost

            groups: list[GroupAnalysis] = []
            for (family, region), monthly in buckets.items():
                groups.append(analyse_group(family, region, list(monthly.values())))
            return groups

        return await asyncio.to_thread(_do)

    return await cache.get_or_fetch("ri_coverage:groups", _fetch, ttl_override=3600)


def to_dict(g: GroupAnalysis) -> dict:
    return {
        "family": g.family, "region": g.region,
        "monthly_costs": list(g.monthly_costs),
        "monthly_mean": g.monthly_mean,
        "monthly_stddev": g.monthly_stddev,
        "cv": g.cv,
        "stability": g.stability, "risk": g.risk,
        "product": g.product,
        "commit_pct": g.commit_pct,
        "savings_rate": g.savings_rate,
        "annual_payg": g.annual_payg,
        "annual_commit": g.annual_commit,
        "annual_savings": g.annual_savings,
        "cancellation_exposure": g.cancellation_exposure,
    }


async def ri_coverage_details(buffer: float | None) -> dict:
    if settings().use_mock_data:
        from . import mock_data
        groups = list(mock_data.MOCK_RI_GROUPS)
    else:
        groups = await _payg_consumption()

    out: dict = {
        "groups": [to_dict(g) for g in groups],
        "buffer": buffer,
        "buffer_required": buffer is None or buffer <= 0,
        "shortlist": [],
        "rejected_over_buffer": [],
        "rejected_high_risk": [to_dict(g) for g in groups if g.risk == "HIGH"],
        "running_exposure": 0.0,
        "total_annual_savings": 0.0,
    }

    if buffer is not None and buffer > 0:
        result = build_shortlist(groups, buffer)
        out["shortlist"] = [to_dict(g) for g in result["shortlist"]]
        out["rejected_over_buffer"] = [to_dict(g) for g in result["rejected_over_buffer"]]
        out["running_exposure"] = result["running_exposure"]
        out["total_annual_savings"] = result["total_annual_savings"]
        out["buffer_required"] = False

    return out


async def detect_ri_coverage() -> list[Finding]:
    if settings().use_mock_data:
        from . import mock_data
        return list(mock_data.MOCK_RI_ROLLUPS)

    buffer = env_buffer()
    if buffer is None or buffer <= 0:
        return []

    details = await ri_coverage_details(buffer)
    if not details["shortlist"]:
        return []

    monthly_savings = details["total_annual_savings"] / 12
    rids = [f"{g['family']}|{g['region']}" for g in details["shortlist"]]
    return [Finding(
        id=_stable_id("ri_coverage", *rids[:25]),
        detector="ri_coverage",
        category="Commitment",
        resource=f"{len(details['shortlist'])} RI/SP picks fit within {buffer:,.0f} buffer",
        resource_ids=rids,
        owner="finops", env="prod",
        savings_monthly_usd=round(monthly_savings, 2),
        cost_source="actual",
        effort_hours=4,
        risk="Medium", tier="Walk", confidence="HIGH",
        business_value=(
            "Commit only what fits inside your cancellation-exposure buffer. "
            "The binding constraint is procurement policy, not the data."
        ),
    )]


def _stable_id(detector: str, *parts: str) -> str:
    return f"{detector}:{uuid.uuid5(uuid.NAMESPACE_URL, ':'.join(parts) or detector)}"
