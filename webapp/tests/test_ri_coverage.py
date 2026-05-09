"""Tests for ri_coverage.

Pure analytics — no Azure dependencies. CV math, classification boundaries,
and greedy-pack behaviour against the configured buffer.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("USE_MOCK_DATA", "true")
os.environ.setdefault("TARGET_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")

import pytest  # noqa: E402

from backend import ri_coverage as ric  # noqa: E402


# ---- cv() -------------------------------------------------------------------

def test_cv_empty():
    assert ric.cv([]) == (0.0, 0.0, 0.0)


def test_cv_zero_mean():
    mean, stddev, c = ric.cv([0.0, 0.0, 0.0])
    assert (mean, stddev, c) == (0.0, 0.0, 0.0)


def test_cv_stable_near_zero():
    mean, stddev, c = ric.cv([100.0, 100.0, 100.0])
    assert mean == 100.0
    assert stddev == 0.0
    assert c == 0.0


def test_cv_high_variance():
    mean, _, c = ric.cv([100.0, 200.0, 300.0])
    assert mean == 200.0
    assert c > 0.30   # crosses into UNSTABLE


# ---- classify() -------------------------------------------------------------

@pytest.mark.parametrize("cv_value, expected_stability, expected_risk", [
    (0.05, "STABLE",   "LOW"),       # well under 15%
    (0.14, "STABLE",   "LOW"),       # just under boundary
    (0.15, "VARIABLE", "MEDIUM"),    # at boundary -> VARIABLE
    (0.25, "VARIABLE", "MEDIUM"),    # mid-range
    (0.30, "UNSTABLE", "HIGH"),      # at 30% boundary -> UNSTABLE
    (0.99, "UNSTABLE", "HIGH"),      # very high
])
def test_classify(cv_value, expected_stability, expected_risk):
    stability, risk, _, _ = ric.classify(cv_value)
    assert stability == expected_stability
    assert risk == expected_risk


# ---- analyse_group end-to-end ----------------------------------------------

def test_analyse_group_stable():
    g = ric.analyse_group("Dsv5", "uksouth", [18000, 17800, 18200])
    assert g.stability == "STABLE"
    assert g.risk == "LOW"
    assert g.product == "VM RI 1Y"
    assert g.commit_pct == 0.80
    assert g.savings_rate == 0.30
    # annual_commit = mean * 12 * 0.80 ≈ 18000 * 12 * 0.8 = 172800
    assert 172000 < g.annual_commit < 173000
    # cancellation_exposure = annual_commit * 0.12 ≈ 20736
    assert 20000 < g.cancellation_exposure < 22000


def test_analyse_group_unstable():
    g = ric.analyse_group("Mv2", "uksouth", [4000, 1500, 8000])
    assert g.stability == "UNSTABLE"
    assert g.risk == "HIGH"
    assert g.commit_pct == 0.30   # heavily reduced commit


# ---- build_shortlist greedy pack -------------------------------------------

def _g(family: str, savings: float, exposure: float, risk: str) -> ric.GroupAnalysis:
    """Quick GroupAnalysis builder for tests."""
    return ric.GroupAnalysis(
        family=family, region="uksouth",
        monthly_costs=(0.0,), monthly_mean=0.0, monthly_stddev=0.0, cv=0.0,
        stability="STABLE" if risk == "LOW" else "VARIABLE" if risk == "MEDIUM" else "UNSTABLE",
        risk=risk,  # type: ignore[arg-type]
        product="x", commit_pct=0.8, savings_rate=0.3,
        annual_payg=0.0, annual_commit=exposure / 0.12,
        annual_savings=savings,
        cancellation_exposure=exposure,
    )


def test_shortlist_packs_highest_savings_first_within_buffer():
    # Three LOW-risk groups; only two fit in a 1500 buffer.
    groups = [
        _g("A", savings=3000, exposure=1000, risk="LOW"),
        _g("B", savings=2000, exposure=600,  risk="LOW"),
        _g("C", savings=1000, exposure=500,  risk="LOW"),
    ]
    out = ric.build_shortlist(groups, buffer=1500)
    families = [g.family for g in out["shortlist"]]
    # Highest savings (A=1000) goes first; B (600) doesn't fit (1000+600=1600 > 1500),
    # so packer skips it and tries C (500). 1000+500=1500 OK.
    assert families == ["A", "C"]
    assert out["running_exposure"] == 1500.0
    assert out["total_annual_savings"] == 4000.0
    over = [g.family for g in out["rejected_over_buffer"]]
    assert over == ["B"]


def test_shortlist_excludes_high_risk_from_pack():
    groups = [
        _g("LOW",    savings=500,  exposure=100, risk="LOW"),
        _g("MED",    savings=400,  exposure=80,  risk="MEDIUM"),
        _g("UNSTAB", savings=10000, exposure=200, risk="HIGH"),
    ]
    out = ric.build_shortlist(groups, buffer=10000)
    short_families = {g.family for g in out["shortlist"]}
    assert short_families == {"LOW", "MED"}
    assert [g.family for g in out["rejected_high_risk"]] == ["UNSTAB"]


def test_shortlist_zero_buffer_returns_empty():
    groups = [_g("A", savings=1000, exposure=100, risk="LOW")]
    out = ric.build_shortlist(groups, buffer=0)
    assert out["shortlist"] == []
    assert out["rejected_over_buffer"] == groups


# ---- env_buffer parsing -----------------------------------------------------

def test_env_buffer_parsing():
    os.environ.pop("AZSHC_REFUND_BUFFER", None)
    assert ric.env_buffer() is None

    os.environ["AZSHC_REFUND_BUFFER"] = ""
    assert ric.env_buffer() is None

    os.environ["AZSHC_REFUND_BUFFER"] = "5000"
    assert ric.env_buffer() == 5000.0

    os.environ["AZSHC_REFUND_BUFFER"] = "-100"
    assert ric.env_buffer() is None  # negative refused

    os.environ["AZSHC_REFUND_BUFFER"] = "not-a-number"
    assert ric.env_buffer() is None

    os.environ.pop("AZSHC_REFUND_BUFFER", None)
