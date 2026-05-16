"""Tests for guardrails — pure-function derive_from_findings + violations.

The ARG-dependent ``fetch_policy_state`` is exercised in mock mode via the
smoke tests against ``/api/guardrails``; here we focus on the deterministic
verdict logic.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("USE_MOCK_DATA", "true")
os.environ.setdefault("TARGET_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")

import pytest  # noqa: E402

from backend import guardrails as gr  # noqa: E402
from backend.models import Finding  # noqa: E402


def _f(detector: str = "t",
       owner: str = "(untagged)",
       savings: float = 100.0,
       resource_ids: list[str] | None = None) -> Finding:
    return Finding(
        id=f"t:{detector}:{savings}",
        detector=detector,
        category="Orphaned storage",
        resource="test resource",
        resource_ids=resource_ids or [],
        owner=owner, env="prod",
        savings_monthly_usd=savings, cost_source="estimate",
        effort_hours=1, risk="Low", tier="Crawl",
        business_value="test",
    )


# ---- Visibility-gap thresholds --------------------------------------------

@pytest.mark.parametrize("gap, expected_status, expected_severity", [
    (0.0,  "healthy",  "low"),
    (5.0,  "healthy",  "low"),
    (10.1, "warning",  "medium"),
    (25.0, "warning",  "medium"),
    (25.1, "critical", "high"),
    (75.0, "critical", "high"),
])
def test_visibility_gap_status(gap, expected_status, expected_severity):
    s, sv = gr._visibility_gap_status(gap)
    assert s == expected_status
    assert sv == expected_severity


# ---- Waste status (proportional to monthly impact) ------------------------

@pytest.mark.parametrize("impact, expected_status, expected_severity", [
    (0.0,    "healthy",  "low"),
    (100.0,  "warning",  "low"),
    (1000.0, "warning",  "medium"),
    (6000.0, "critical", "high"),
])
def test_waste_status(impact, expected_status, expected_severity):
    s, sv = gr._waste_status(impact)
    assert s == expected_status
    assert sv == expected_severity


# ---- derive_from_findings -------------------------------------------------

def test_derive_visibility_gap_picks_up_untagged_spend():
    findings = [
        _f("unattached_disks", owner="(untagged)", savings=1000),
        _f("tagging_gap",      owner="(untagged)", savings=500),
        _f("empty_app_service_plans", owner="web-team", savings=200),
    ]
    guards = gr.derive_from_findings(findings, visibility_gap_pct=18.0)
    vg = next(g for g in guards if g.id == "azshc:visibility-gap")
    assert vg.status == "warning"
    assert vg.severity == "medium"
    assert vg.current_numeric == 18.0
    # Untagged + mixed savings flow to impact_monthly
    assert vg.impact_monthly == 1500.0


def test_derive_unattached_disks_critical_above_5k():
    findings = [
        _f("unattached_disks", savings=6000, resource_ids=["r1", "r2", "r3"]),
    ]
    guards = gr.derive_from_findings(findings, visibility_gap_pct=0.0)
    disks = next(g for g in guards if g.id == "azshc:unattached-disks")
    assert disks.status == "critical"
    assert disks.severity == "high"
    assert disks.current_numeric == 3.0
    assert disks.impact_monthly == 6000.0


def test_derive_peak_rightsizing_critical_when_advisor_unsafe():
    findings = [
        _f("peak_advisor_unsafe", resource_ids=["vm1", "vm2"]),
    ]
    guards = gr.derive_from_findings(findings, visibility_gap_pct=0.0)
    peak = next(g for g in guards if g.id == "azshc:peak-rightsizing")
    assert peak.status == "critical"
    assert peak.severity == "high"
    assert peak.current_numeric == 2.0


def test_derive_peak_rightsizing_healthy_with_no_advisor_unsafe():
    guards = gr.derive_from_findings([], visibility_gap_pct=0.0)
    peak = next(g for g in guards if g.id == "azshc:peak-rightsizing")
    assert peak.status == "healthy"
    assert peak.severity == "low"
    assert peak.current_numeric == 0.0


def test_derive_ri_coverage_warning_when_rollup_present():
    findings = [_f("ri_coverage", owner="finops", savings=820)]
    guards = gr.derive_from_findings(findings, visibility_gap_pct=0.0)
    ri = next(g for g in guards if g.id == "azshc:ri-coverage")
    assert ri.status == "warning"
    assert ri.impact_monthly == 820.0


def test_derive_ri_coverage_healthy_when_buffer_unset():
    guards = gr.derive_from_findings([], visibility_gap_pct=0.0)
    ri = next(g for g in guards if g.id == "azshc:ri-coverage")
    assert ri.status == "healthy"
    assert ri.current_value == "no buffer set"
    assert ri.impact_monthly == 0.0


def test_derive_emits_exactly_four_guardrails():
    """Sanity: the derived set is stable in count."""
    guards = gr.derive_from_findings([], visibility_gap_pct=0.0)
    ids = {g.id for g in guards}
    assert ids == {
        "azshc:visibility-gap",
        "azshc:unattached-disks",
        "azshc:peak-rightsizing",
        "azshc:ri-coverage",
    }


# ---- derive_violations ----------------------------------------------------

def test_derive_violations_skips_healthy():
    findings = [_f("unattached_disks", savings=0)]
    guards = gr.derive_from_findings(findings, visibility_gap_pct=0.0)
    viols = gr.derive_violations(guards)
    # All four derived guardrails should be healthy → no violations.
    assert viols == []


def test_derive_violations_attributes_owner_by_category():
    findings = [_f("peak_advisor_unsafe", resource_ids=["vm1"])]
    guards = gr.derive_from_findings(findings, visibility_gap_pct=0.0)
    viols = gr.derive_violations(guards)
    peak_v = next(v for v in viols if v.guardrail_id == "azshc:peak-rightsizing")
    # Optimization category → finops owner.
    assert peak_v.owner == "finops"


def test_derive_violations_attributes_governance_to_needs_attribution():
    guards = gr.derive_from_findings([], visibility_gap_pct=30.0)
    viols = gr.derive_violations(guards)
    vg_v = next(v for v in viols if v.guardrail_id == "azshc:visibility-gap")
    assert vg_v.owner == "needs-attribution"
