"""Guardrails (PR6) — Policy Insights compliance + derived FinOps signals.

A "guardrail" is a single named control with a status and an enforcement
state. Two sources flow in:

* **Azure Policy Insights** (via Resource Graph): every cost-category
  policy assignment in the subscription, with its current compliance
  counts and effect (audit vs deny).
* **Derived from detectors**: the live state of the cost signals we
  already compute (Visibility Gap, RI coverage, advisor-unsafe peak
  rightsizing, untagged resources, unattached disks). These don't have
  an "enforced" state — they're advisory thresholds — but they do have
  status (healthy / warning / critical).

Both sources flow through the same ``Guardrail`` shape so the SPA can
render a unified list. The split between ``status`` and ``enforcement``
keeps the SPA pill logic simple — see the README of this PR for the rationale.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Literal

from .cache import cache
from .config import settings
from .models import Finding


log = logging.getLogger("guardrails")
KQL_DIR = Path(__file__).parent / "kql"


Status      = Literal["healthy", "warning", "critical"]
Enforcement = Literal["audit", "enforced", "disabled", "not-applicable"]
Severity    = Literal["low", "medium", "high"]
Category    = Literal["Commitments", "Governance", "Waste", "Optimization", "Policy"]


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Guardrail:
    id: str
    name: str
    category: Category
    description: str
    severity: Severity
    status: Status
    enforcement: Enforcement
    current_value: str | None      # human display (e.g. "82%", "12 disks")
    current_numeric: float | None  # for sorting / charts
    threshold: str | None
    threshold_numeric: float | None
    impact_monthly: float          # numeric, tenant currency
    source: str
    last_evaluated: str | None     # ISO 8601 or None


@dataclass(frozen=True)
class Violation:
    id: str
    guardrail_id: str
    title: str
    description: str
    severity: Severity
    cost_impact: float             # numeric, tenant currency
    owner: str
    recommendation: str
    date: str                      # ISO date


@dataclass(frozen=True)
class SummaryKPI:
    total_guardrails: int
    enforced: int
    healthy: int
    warning: int
    critical: int
    violations: int
    high_severity_violations: int
    overall_health: Status


# ---------------------------------------------------------------------------
# Derived guardrails — pure functions over Finding lists
# ---------------------------------------------------------------------------

def _stable_id(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))


def _visibility_gap_status(gap_pct: float) -> tuple[Status, Severity]:
    if gap_pct > 25.0: return ("critical", "high")
    if gap_pct > 10.0: return ("warning",  "medium")
    return ("healthy", "low")


def _ri_coverage_status(coverage_pct: float, threshold_pct: float = 75.0) -> tuple[Status, Severity]:
    """Coverage <60% critical, <threshold warning, else healthy."""
    if coverage_pct < 60.0:                return ("critical", "high")
    if coverage_pct < threshold_pct:       return ("warning",  "medium")
    return ("healthy", "low")


def _waste_status(monthly_impact: float) -> tuple[Status, Severity]:
    """Pragmatic thresholds — operators can override per-tenant later."""
    if monthly_impact > 5000:  return ("critical", "high")
    if monthly_impact > 500:   return ("warning",  "medium")
    if monthly_impact > 0:     return ("warning",  "low")
    return ("healthy", "low")


def derive_from_findings(
    findings: Iterable[Finding],
    visibility_gap_pct: float = 0.0,
    *,
    ri_coverage_target_pct: float = 75.0,
) -> list[Guardrail]:
    """Translate detector output into Guardrails.

    Pure: no Azure dependencies, fully unit-testable. The detector layer
    has already done the heavy lifting; this just rolls findings up into
    named controls with a status verdict.
    """
    items = list(findings)

    # --- Visibility Gap (Governance) -----------------------------------
    vg_status, vg_severity = _visibility_gap_status(visibility_gap_pct)
    vg = Guardrail(
        id="azshc:visibility-gap",
        name="Visibility Gap (untagged spend)",
        category="Governance",
        description=(
            "Percentage of recoverable spend attributable to resources missing one "
            "or more required tags. Crawl < 25%, Walk < 10%, Run < 2%."
        ),
        severity=vg_severity,
        status=vg_status,
        enforcement="not-applicable",
        current_value=f"{visibility_gap_pct:.1f}%",
        current_numeric=round(visibility_gap_pct, 2),
        threshold="< 10%",
        threshold_numeric=10.0,
        impact_monthly=round(sum(f.savings_monthly_usd for f in items
                                 if f.owner in ("(untagged)", "mixed")), 2),
        source="Tagging detector",
        last_evaluated=None,
    )

    # --- Unattached managed disks (Waste) ------------------------------
    disks = [f for f in items if f.detector == "unattached_disks"]
    disk_impact = sum(f.savings_monthly_usd for f in disks)
    disk_count  = sum(len(f.resource_ids) for f in disks)
    d_status, d_severity = _waste_status(disk_impact)
    disks_g = Guardrail(
        id="azshc:unattached-disks",
        name="Unattached managed disks",
        category="Waste",
        description="Managed disks left in 'Unattached' state — pure waste.",
        severity=d_severity,
        status=d_status,
        enforcement="not-applicable",
        current_value=f"{disk_count} disks" if disk_count else "clean",
        current_numeric=float(disk_count),
        threshold="0 disks",
        threshold_numeric=0.0,
        impact_monthly=round(disk_impact, 2),
        source="Orphaned-storage detector",
        last_evaluated=None,
    )

    # --- Peak-aware rightsizing (Optimization) -------------------------
    advisor_unsafe = next(
        (f for f in items if f.detector == "peak_advisor_unsafe"), None
    )
    if advisor_unsafe and advisor_unsafe.resource_ids:
        unsafe_n = len(advisor_unsafe.resource_ids)
        peak_status: Status = "critical" if unsafe_n > 0 else "healthy"
        peak_severity: Severity = "high" if unsafe_n > 0 else "low"
        peak_display = f"{unsafe_n} Advisor recs unsafe"
        peak_numeric = float(unsafe_n)
    else:
        peak_status, peak_severity = "healthy", "low"
        peak_display = "0 unsafe"
        peak_numeric = 0.0
    peak_g = Guardrail(
        id="azshc:peak-rightsizing",
        name="Peak-aware rightsizing — Advisor diff",
        category="Optimization",
        description=(
            "Advisor downsize recommendations that the P95 / P99 engine flags "
            "as unsafe. Each avoided incident dwarfs years of savings."
        ),
        severity=peak_severity,
        status=peak_status,
        enforcement="not-applicable",
        current_value=peak_display,
        current_numeric=peak_numeric,
        threshold="0 unsafe",
        threshold_numeric=0.0,
        impact_monthly=0.0,  # incident-prevention, not direct savings
        source="Peak-rightsizing detector",
        last_evaluated=None,
    )

    # --- RI / SP coverage (Commitments) --------------------------------
    # Without a real coverage % from the Reservations API we use the inverse
    # signal: if the ri_coverage rollup is suppressed (no buffer set), we
    # treat coverage as unknown -> healthy (no actionable signal).
    ri = next((f for f in items if f.detector == "ri_coverage"), None)
    ri_target_disp = f">= {int(ri_coverage_target_pct)}%"
    if ri:
        ri_g = Guardrail(
            id="azshc:ri-coverage",
            name="RI / Savings-Plan refund buffer",
            category="Commitments",
            description="Forward-looking commitment picks bounded by the cancellation-exposure buffer.",
            severity="medium",
            status="warning",          # rollup present means there's actionable savings
            enforcement="not-applicable",
            current_value=f"{ri.savings_monthly_usd:,.0f}/mo savings sitting in shortlist",
            current_numeric=ri.savings_monthly_usd,
            threshold=ri_target_disp,
            threshold_numeric=ri_coverage_target_pct,
            impact_monthly=round(ri.savings_monthly_usd, 2),
            source="RI-coverage detector",
            last_evaluated=None,
        )
    else:
        ri_g = Guardrail(
            id="azshc:ri-coverage",
            name="RI / Savings-Plan refund buffer",
            category="Commitments",
            description="Set a refund buffer to enable forward-looking commitment shortlisting.",
            severity="low",
            status="healthy",
            enforcement="not-applicable",
            current_value="no buffer set",
            current_numeric=None,
            threshold=ri_target_disp,
            threshold_numeric=ri_coverage_target_pct,
            impact_monthly=0.0,
            source="RI-coverage detector",
            last_evaluated=None,
        )

    return [vg, disks_g, peak_g, ri_g]


def derive_violations(guards: Iterable[Guardrail]) -> list[Violation]:
    """Each warning/critical guardrail produces one violation row."""
    out: list[Violation] = []
    for g in guards:
        if g.status == "healthy":
            continue
        out.append(Violation(
            id=_stable_id("violation", g.id, g.current_value or ""),
            guardrail_id=g.id,
            title=f"{g.name} — {g.current_value or 'breach'}",
            description=g.description,
            severity=g.severity,
            cost_impact=g.impact_monthly,
            owner="finops" if g.category in ("Commitments", "Optimization") else "needs-attribution",
            recommendation=_recommendation_for(g),
            date=_today(),
        ))
    return out


def _recommendation_for(g: Guardrail) -> str:
    if g.id == "azshc:visibility-gap":
        return "Enforce the Tag/CostCenter policy in audit mode for 30 days, then promote to deny."
    if g.id == "azshc:unattached-disks":
        return "Download the dry-run remediation script from the Findings tab; review then apply."
    if g.id == "azshc:peak-rightsizing":
        return "Open the Peak Rightsizing tab; cross-check Advisor's recs against the P95 view before acting."
    if g.id == "azshc:ri-coverage":
        return "Open the RI Coverage tab; set or raise the refund buffer to unlock the shortlist."
    if g.id.startswith("policy:"):
        return "Investigate non-compliant resources; remediate the underlying state."
    return "Review the source detector for context."


def _today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Azure adapter — policy state via Resource Graph
# ---------------------------------------------------------------------------

def _load_kql(name: str) -> str:
    return (KQL_DIR / f"{name}.kql").read_text()


async def fetch_policy_state() -> list[Guardrail]:
    """Pull cost-category policy assignments + compliance from ARG.

    Two queries (assignments + states), joined in Python. We don't surface a
    Guardrail per *resource* — only per *assignment* — so the SPA stays
    tractable on tenants with thousands of resources.
    """
    if settings().use_mock_data:
        from . import mock_data
        return list(mock_data.MOCK_POLICY_GUARDRAILS)

    sub = settings().target_subscription_id
    if not sub:
        return []

    # Lazy import to avoid coupling at startup
    from .detectors import _run_arg  # type: ignore[attr-defined]

    async def _do() -> list[Guardrail]:
        assignments, compliance = await asyncio.gather(
            _run_arg(_load_kql("policy_assignments")),
            _run_arg(_load_kql("policy_compliance")),
        )
        # Index compliance by assignmentId for the join.
        by_id: dict[str, dict] = {
            str(r.get("assignmentId", "")).lower(): r for r in compliance
        }

        out: list[Guardrail] = []
        for a in assignments:
            aid = str(a.get("id", "")).lower()
            comp = by_id.get(aid, {})
            non = int(comp.get("nonCompliant") or 0)
            total = int(comp.get("total") or 0)
            mode = (a.get("enforcementMode") or "").lower()
            enforcement: Enforcement = (
                "disabled" if mode == "disabled"
                else "enforced" if mode == "default"
                else "audit"  # treat 'doNotEnforce' / unknown as audit
            )
            if non == 0 and total > 0:
                status: Status = "healthy"
                severity: Severity = "low"
            elif non > 0 and enforcement == "enforced":
                status, severity = ("critical", "high")
            elif non > 0:
                status, severity = ("warning", "medium")
            else:
                status, severity = ("healthy", "low")

            out.append(Guardrail(
                id=f"policy:{aid}",
                name=str(a.get("effectiveDisplayName", "(unnamed policy)")),
                category="Policy",
                description="Azure Policy assignment — Cost category.",
                severity=severity,
                status=status,
                enforcement=enforcement,
                current_value=(f"{non} non-compliant of {total}" if total
                               else "no evaluations yet"),
                current_numeric=float(non),
                threshold="0 non-compliant",
                threshold_numeric=0.0,
                impact_monthly=0.0,  # Policy state has no $ — surfaces in detectors instead
                source="Azure Policy Insights",
                last_evaluated=str(comp.get("lastEvaluated") or "") or None,
            ))
        return out

    return await cache.get_or_fetch("guardrails:policy", _do, ttl_override=600)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def all_guardrails(findings: list[Finding], visibility_gap_pct: float) -> list[Guardrail]:
    derived = derive_from_findings(findings, visibility_gap_pct)
    policy  = await fetch_policy_state()
    return derived + policy


async def violations(findings: list[Finding], visibility_gap_pct: float) -> list[Violation]:
    guards = await all_guardrails(findings, visibility_gap_pct)
    return derive_violations(guards)


async def summary(findings: list[Finding], visibility_gap_pct: float) -> SummaryKPI:
    guards = await all_guardrails(findings, visibility_gap_pct)
    viols = derive_violations(guards)
    enforced = sum(1 for g in guards if g.enforcement == "enforced")
    healthy  = sum(1 for g in guards if g.status == "healthy")
    warning  = sum(1 for g in guards if g.status == "warning")
    critical = sum(1 for g in guards if g.status == "critical")
    high_sev = sum(1 for v in viols if v.severity == "high")
    overall: Status = (
        "critical" if critical > 0 or high_sev > 0
        else "warning" if warning > 0 or len(viols) > 0
        else "healthy"
    )
    return SummaryKPI(
        total_guardrails=len(guards),
        enforced=enforced,
        healthy=healthy,
        warning=warning,
        critical=critical,
        violations=len(viols),
        high_severity_violations=high_sev,
        overall_health=overall,
    )


def to_dict(obj) -> dict:
    """Helper: dataclass → plain dict for JSON serialisation."""
    return asdict(obj)
