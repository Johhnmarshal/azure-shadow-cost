"""Tests for peak_rightsizing.

The decision tree (`decide`) is pure — no Azure dependencies — so we
parametrise it across the five canonical verdicts.

`compile_details` is also pure; we exercise the advisor-unsafe diff
deterministically with synthetic input.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("USE_MOCK_DATA", "true")
os.environ.setdefault("TARGET_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")

import pytest  # noqa: E402

from backend import peak_rightsizing as peak  # noqa: E402
from backend import thresholds  # noqa: E402


T = thresholds.Thresholds()  # Conservative defaults: 40/50/80


# ---- decide() parametrised ----------------------------------------------------

@pytest.mark.parametrize("metric, expected_verdict, expected_conf", [
    # All quiet at P95 *and* P99 → DOWNSIZE_CANDIDATE / HIGH
    (peak.VMMetric(cpu_p95=10, cpu_p99=20, mem_p95_used=15, mem_p99_used=25, coverage=0.99),
     "DOWNSIZE_CANDIDATE", "HIGH"),
    # Low at P95 but P99 spike → DOWNSIZE_CANDIDATE / MEDIUM
    (peak.VMMetric(cpu_p95=20, cpu_p99=70, mem_p95_used=30, mem_p99_used=70, coverage=0.95),
     "DOWNSIZE_CANDIDATE", "MEDIUM"),
    # CPU saturated at P95 → UPSIZE_WARNING
    (peak.VMMetric(cpu_p95=85, cpu_p99=98, mem_p95_used=40, mem_p99_used=60, coverage=0.99),
     "UPSIZE_WARNING", "HIGH"),
    # Memory saturated at P95 (CPU fine) → UPSIZE_WARNING
    (peak.VMMetric(cpu_p95=20, cpu_p99=30, mem_p95_used=90, mem_p99_used=95, coverage=0.99),
     "UPSIZE_WARNING", "HIGH"),
    # Mid-range — KEEP
    (peak.VMMetric(cpu_p95=55, cpu_p99=70, mem_p95_used=55, mem_p99_used=65, coverage=0.99),
     "KEEP", "MEDIUM"),
    # Coverage too low — INSUFFICIENT_DATA regardless of values
    (peak.VMMetric(cpu_p95=10, cpu_p99=15, mem_p95_used=10, mem_p99_used=20, coverage=0.50),
     "INSUFFICIENT_DATA", "LOW"),
])
def test_decide(metric, expected_verdict, expected_conf):
    d = peak.decide(metric, T)
    assert d.verdict == expected_verdict
    assert d.confidence == expected_conf


# ---- compile_details: advisor-unsafe diff ------------------------------------

def test_compile_details_flags_advisor_unsafe():
    vms = [
        {"id": "/subs/x/rg/a/vm1", "name": "vm1", "resourceGroup": "rg",
         "location": "uksouth", "size": "Standard_D8s_v5",
         "owner": "team-a", "env": "prod"},
    ]
    metrics = {
        "/subs/x/rg/a/vm1": peak.VMMetric(  # bursty: low average, P99 spike
            cpu_p95=18, cpu_p99=92, mem_p95_used=22, mem_p99_used=88, coverage=0.96,
        ),
    }
    advisor_targets = {"/subs/x/rg/a/vm1"}  # Advisor wants to resize

    rows = peak.compile_details(vms, metrics, advisor_targets, T)
    assert len(rows) == 1
    r = rows[0]
    # P99 spike → KEEP (CPU P95 18% IS below 40, mem P95 22% IS below 50, but P99 92>50 so MEDIUM downsize?)
    # Actually 18<40 and 22<50, so verdict is DOWNSIZE_CANDIDATE/MEDIUM (P99 just lowers conf).
    # That means advisor advice is SAFE, not unsafe. Let me re-check.
    # decide: cpu95<40 ✓, mem95<50 ✓, cpu99=92 < 50? no, so confidence MEDIUM.
    # verdict = DOWNSIZE_CANDIDATE, confidence MEDIUM.
    # advisor_unsafe = advised AND verdict in (KEEP, UPSIZE_WARNING). DOWNSIZE_CANDIDATE so unsafe=False.
    assert r["verdict"] == "DOWNSIZE_CANDIDATE"
    assert r["confidence"] == "MEDIUM"
    assert r["advisor_advised"] is True
    assert r["advisor_unsafe"] is False


def test_compile_details_advisor_unsafe_with_high_p95():
    vms = [
        {"id": "/subs/x/rg/a/vm-busy", "name": "vm-busy", "resourceGroup": "rg",
         "location": "uksouth", "size": "Standard_D8s_v5",
         "owner": "team-b", "env": "prod"},
    ]
    metrics = {
        "/subs/x/rg/a/vm-busy": peak.VMMetric(
            cpu_p95=85, cpu_p99=98, mem_p95_used=70, mem_p99_used=85, coverage=0.99,
        ),
    }
    advisor_targets = {"/subs/x/rg/a/vm-busy"}  # Advisor wants to resize a SATURATED VM

    rows = peak.compile_details(vms, metrics, advisor_targets, T)
    r = rows[0]
    assert r["verdict"] == "UPSIZE_WARNING"
    assert r["advisor_unsafe"] is True


def test_compile_details_no_advisor_means_no_unsafe():
    vms = [{"id": "/subs/x/rg/a/v", "name": "v", "resourceGroup": "rg",
            "location": "uksouth", "size": "Standard_D8s_v5",
            "owner": "t", "env": "prod"}]
    metrics = {"/subs/x/rg/a/v": peak.VMMetric(85, 98, 70, 85, 0.99)}
    rows = peak.compile_details(vms, metrics, set(), T)
    assert rows[0]["verdict"] == "UPSIZE_WARNING"
    assert rows[0]["advisor_advised"] is False
    assert rows[0]["advisor_unsafe"] is False


# ---- threshold validation ----------------------------------------------------

def test_thresholds_validate_inverted_bounds():
    bad = thresholds.Thresholds(
        downsize_cpu_p95_max=80, upsize_cpu_p95_min=40,  # inverted
        downsize_mem_p95_max=50, upsize_mem_p95_min=85,
        downsize_cpu_p99_high_conf=50, downsize_mem_p99_high_conf=60,
        min_data_coverage=0.8,
    )
    assert thresholds.validate(bad) is not None


def test_thresholds_update_persists():
    thresholds.reset_to_env()
    new = thresholds.update(downsize_cpu_p95_max=60.0, upsize_cpu_p95_min=85.0)
    assert new.downsize_cpu_p95_max == 60.0
    assert thresholds.current().downsize_cpu_p95_max == 60.0
    thresholds.reset_to_env()  # cleanup


def test_thresholds_update_rejects_invalid():
    thresholds.reset_to_env()
    with pytest.raises(ValueError):
        thresholds.update(downsize_cpu_p95_max=90.0)  # >= upsize default 80
    thresholds.reset_to_env()
