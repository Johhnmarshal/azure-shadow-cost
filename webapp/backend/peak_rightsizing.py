"""Peak-aware VM rightsizing detector + Advisor diff.

Pulls 30 days of P95/P99 CPU + memory from Azure Monitor for every
non-managed VM in the configured subscription. Applies a deterministic
decision tree (thresholds.Thresholds). Diffs against Advisor's
"Cost — Resize Virtual Machine" recommendations; the headline number is
*Advisor recs that would have been unsafe at P95*.

Module surface
--------------
* ``decide(metric, thresholds)``  — pure decision logic, fully testable.
* ``compile_details(...)``        — pure assembly of per-VM detail rows.
* ``detect_peak_rightsizing()``   — async; emits one rollup ``Finding``
  per verdict class for the main dashboard.
* ``peak_rightsizing_details()``  — async; returns a list of per-VM dicts
  for the SPA's Peak Rightsizing tab.

Excluded by design
------------------
* ``databricks-rg-*`` and ``MC_*`` / ``mc_*`` resource groups.
* VMs whose name starts ``aks-`` (AKS node pool).

Exclusions live in the KQL (``kql/vm_inventory.kql``) — that keeps the
Python pure decision logic.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from . import sku_memory, thresholds
from .az_clients import monitor
from .cache import cache
from .config import settings
from .models import Finding


log = logging.getLogger("peak_rightsizing")
KQL_DIR = Path(__file__).parent / "kql"


Verdict    = Literal["DOWNSIZE_CANDIDATE", "UPSIZE_WARNING", "KEEP", "INSUFFICIENT_DATA"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


# ---------------------------------------------------------------------------
# Pure decision tree (no Azure dependencies — fully unit-testable)
# ---------------------------------------------------------------------------

@dataclass
class VMMetric:
    """Aggregated metrics for one VM over the analysis window."""
    cpu_p95: float | None       # 0-100
    cpu_p99: float | None       # 0-100
    mem_p95_used: float | None  # 0-100, derived from Available Memory and SKU memory
    mem_p99_used: float | None  # 0-100
    coverage: float             # 0-1, fraction of expected hourly buckets present


@dataclass
class VMDecision:
    verdict: Verdict
    confidence: Confidence


def decide(m: VMMetric, t: thresholds.Thresholds) -> VMDecision:
    """Return the verdict + confidence for a single VM."""
    if m.coverage < t.min_data_coverage:
        return VMDecision("INSUFFICIENT_DATA", "LOW")

    cpu95 = m.cpu_p95 or 0.0
    mem95 = m.mem_p95_used or 0.0
    cpu99 = m.cpu_p99 or 0.0
    mem99 = m.mem_p99_used or 0.0

    # Upsize takes precedence — any single dimension above the upsize floor
    # means the current SKU isn't safe to downsize even if the other is low.
    if cpu95 >= t.upsize_cpu_p95_min or mem95 >= t.upsize_mem_p95_min:
        return VMDecision("UPSIZE_WARNING", "HIGH")

    if cpu95 < t.downsize_cpu_p95_max and mem95 < t.downsize_mem_p95_max:
        if cpu99 < t.downsize_cpu_p99_high_conf and mem99 < t.downsize_mem_p99_high_conf:
            return VMDecision("DOWNSIZE_CANDIDATE", "HIGH")
        return VMDecision("DOWNSIZE_CANDIDATE", "MEDIUM")

    return VMDecision("KEEP", "MEDIUM")


def compile_details(
    vms: list[dict[str, Any]],
    metrics: dict[str, VMMetric],
    advisor_resize_targets: set[str],
    t: thresholds.Thresholds,
) -> list[dict[str, Any]]:
    """Assemble per-VM detail rows. Pure — no Azure deps. Testable.

    ``advisor_resize_targets`` is the lowercased VM ID set returned by
    :data:`AdvisorResources` filtered to ``isResize == true``.
    """
    rows: list[dict[str, Any]] = []
    for v in vms:
        vid = v["id"]
        m = metrics.get(vid.lower(), VMMetric(None, None, None, None, 0.0))
        d = decide(m, t)
        proposed = sku_memory.proposed_downsize(v.get("size", "")) if d.verdict == "DOWNSIZE_CANDIDATE" else None
        advised = vid.lower() in advisor_resize_targets
        # The headline diff: Advisor wants a resize but our P95 says it'd be unsafe.
        unsafe = advised and d.verdict in ("KEEP", "UPSIZE_WARNING")
        rows.append({
            "id": vid,
            "name": v.get("name", ""),
            "resourceGroup": v.get("resourceGroup", ""),
            "location": v.get("location", ""),
            "size": v.get("size", ""),
            "owner": v.get("owner", "(untagged)"),
            "env": v.get("env", "unknown"),
            "cpu_p95": m.cpu_p95,
            "cpu_p99": m.cpu_p99,
            "mem_p95_used": m.mem_p95_used,
            "mem_p99_used": m.mem_p99_used,
            "coverage": round(m.coverage, 3),
            "verdict": d.verdict,
            "confidence": d.confidence,
            "advisor_advised": advised,
            "advisor_unsafe": unsafe,
            "proposed_size": proposed,
        })
    return rows


# ---------------------------------------------------------------------------
# Azure adapters — Resource Graph + Monitor metrics
# ---------------------------------------------------------------------------

async def _arg(kql_name: str) -> list[dict[str, Any]]:
    """Run a KQL file via Resource Graph. We import lazily to avoid coupling
    to the detectors module at import time."""
    from . import detectors
    text = (KQL_DIR / f"{kql_name}.kql").read_text()
    return await detectors._run_arg(text)  # type: ignore[attr-defined]


_METRIC_NAMES = "Percentage CPU,Available Memory Bytes"
_INTERVAL = "PT1H"


async def _vm_metrics(vm_id: str, sku: str, days: int = 30) -> VMMetric:
    """Pull P95/P99 of CPU + memory for one VM. Concurrent-safe."""
    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(days=days)
    timespan = f"{start.isoformat()}/{end.isoformat()}"
    expected_buckets = days * 24

    def _do() -> VMMetric:
        try:
            client = monitor()
            result = client.metrics.list(
                resource_uri=vm_id,
                timespan=timespan,
                interval=_INTERVAL,
                metricnames=_METRIC_NAMES,
                aggregation="Average,Maximum,Minimum",
            )
        except Exception as e:  # noqa: BLE001 — graceful degrade per VM
            log.warning("monitor.metrics.list failed for %s: %s", vm_id.split("/")[-1], e)
            return VMMetric(None, None, None, None, 0.0)

        cpu_avg: list[float] = []
        cpu_max: list[float] = []
        mem_min_bytes: list[float] = []
        mem_avg_bytes: list[float] = []
        for m in (result.value or []):
            for ts in (m.timeseries or []):
                for d in (ts.data or []):
                    if m.name.value == "Percentage CPU":
                        if d.average is not None: cpu_avg.append(float(d.average))
                        if d.maximum is not None: cpu_max.append(float(d.maximum))
                    elif m.name.value == "Available Memory Bytes":
                        if d.minimum is not None: mem_min_bytes.append(float(d.minimum))
                        if d.average is not None: mem_avg_bytes.append(float(d.average))

        # Convert memory bytes → % used. Requires SKU memory.
        total_gb = sku_memory.memory_gb(sku)
        mem_used_p95 = mem_used_p99 = None
        if total_gb and mem_min_bytes:
            total_bytes = total_gb * (1024 ** 3)
            used = [max(0.0, (1.0 - (b / total_bytes)) * 100.0) for b in mem_min_bytes]
            mem_used_p95 = _percentile(used, 0.95)
            mem_used_p99 = _percentile(used, 0.99)

        cpu_p95 = _percentile(cpu_max, 0.95) if cpu_max else None
        cpu_p99 = _percentile(cpu_max, 0.99) if cpu_max else None
        coverage = min(1.0, len(cpu_avg) / expected_buckets) if expected_buckets else 0.0

        return VMMetric(cpu_p95, cpu_p99, mem_used_p95, mem_used_p99, coverage)

    return await asyncio.to_thread(_do)


def _percentile(values: list[float], p: float) -> float:
    """Approximate percentile using linear interpolation. Pure stdlib."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


async def _gather_metrics(vms: list[dict[str, Any]], concurrency: int = 8) -> dict[str, VMMetric]:
    """Concurrent metric pulls, capped at ``concurrency`` to respect Monitor's rate limit."""
    sem = asyncio.Semaphore(concurrency)

    async def _one(v: dict[str, Any]) -> tuple[str, VMMetric]:
        async with sem:
            return v["id"].lower(), await _vm_metrics(v["id"], v.get("size", ""))

    pairs = await asyncio.gather(*(_one(v) for v in vms))
    return dict(pairs)


async def _advisor_resize_targets() -> set[str]:
    rows = await _arg("advisor_cost_recs")
    return {
        str(r.get("impactedValue", "")).lower()
        for r in rows if r.get("isResize")
    }


# ---------------------------------------------------------------------------
# Public async entry points
# ---------------------------------------------------------------------------

async def _all_details() -> list[dict[str, Any]]:
    async def _fetch() -> list[dict[str, Any]]:
        vms = await _arg("vm_inventory")
        if not vms:
            return []
        metrics, advisor_targets = await asyncio.gather(
            _gather_metrics(vms),
            _advisor_resize_targets(),
        )
        return compile_details(vms, metrics, advisor_targets, thresholds.current())

    # Cache for 1h — Monitor metric calls are slow and rate-limited.
    return await cache.get_or_fetch("peak_rightsizing:details", _fetch, ttl_override=3600)


async def peak_rightsizing_details() -> list[dict[str, Any]]:
    """Per-VM detail for the SPA's Peak Rightsizing tab."""
    if settings().use_mock_data:
        from . import mock_data
        return list(mock_data.MOCK_PEAK_DETAILS)
    return await _all_details()


async def detect_peak_rightsizing() -> list[Finding]:
    """One rollup Finding per non-trivial verdict class for the dashboard."""
    if settings().use_mock_data:
        # Mock mode: use the rollup mocks in mock_data.
        from . import mock_data
        return list(mock_data.MOCK_PEAK_ROLLUPS)

    rows = await _all_details()
    if not rows:
        return []

    by_verdict: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_verdict.setdefault(r["verdict"], []).append(r)

    out: list[Finding] = []
    advisor_unsafe = [r for r in rows if r["advisor_unsafe"]]

    if advisor_unsafe:
        out.append(_finding_advisor_unsafe(advisor_unsafe))
    if by_verdict.get("DOWNSIZE_CANDIDATE"):
        out.append(_finding_downsize(by_verdict["DOWNSIZE_CANDIDATE"]))
    if by_verdict.get("UPSIZE_WARNING"):
        out.append(_finding_upsize(by_verdict["UPSIZE_WARNING"]))

    return out


# ---------------------------------------------------------------------------
# Finding builders
# ---------------------------------------------------------------------------

def _stable_id(detector: str, *parts: str) -> str:
    return f"{detector}:{uuid.uuid5(uuid.NAMESPACE_URL, ':'.join(parts) or detector)}"


def _finding_advisor_unsafe(rows: list[dict[str, Any]]) -> Finding:
    return Finding(
        id=_stable_id("peak_advisor_unsafe", *(r["id"] for r in rows[:25])),
        detector="peak_advisor_unsafe",
        category="Rightsizing",
        resource=f"{len(rows)} Advisor downsize recs flagged unsafe at P95",
        resource_ids=[r["id"] for r in rows],
        owner="mixed",
        env="mixed",
        savings_monthly_usd=0.0,
        cost_source="estimate",
        effort_hours=max(1, len(rows) * 0.25),
        risk="High",
        tier="Walk",
        confidence="HIGH",
        business_value=(
            "Advisor's average-based logic would have downsized these VMs into a peak-hour outage. "
            "This is the metric that pays for the engine — every avoided incident dwarfs years of savings."
        ),
    )


def _finding_downsize(rows: list[dict[str, Any]]) -> Finding:
    # Without a per-SKU price API, savings is left at 0 for the rollup; PR2's
    # cost_actuals join will populate it once we group by per-VM CM /query.
    rids: list[str] = []
    for r in rows:
        target = r.get("proposed_size") or ""
        rids.append(f"{r['id']}|{target}")
    return Finding(
        id=_stable_id("peak_downsize", *(r["id"] for r in rows[:25])),
        detector="peak_downsize",
        category="Rightsizing",
        resource=f"{len(rows)} VMs flagged for safe downsize at P95/P99",
        resource_ids=rids,
        owner="mixed",
        env="mixed",
        savings_monthly_usd=0.0,
        cost_source="estimate",
        effort_hours=max(1, len(rows) * 0.5),
        risk="Medium",
        tier="Walk",
        confidence=("HIGH" if all(r["confidence"] == "HIGH" for r in rows) else "MEDIUM"),
        business_value=(
            "Downsize ladder one step per VM; never skip steps. Coordinate maintenance window — resize "
            "triggers a reboot. Aim for a 7-day baseline + 7-day post-change soak per batch."
        ),
        proposed_size=None,  # per-VM in resource_ids
    )


def _finding_upsize(rows: list[dict[str, Any]]) -> Finding:
    return Finding(
        id=_stable_id("peak_upsize", *(r["id"] for r in rows[:25])),
        detector="peak_upsize",
        category="Rightsizing",
        resource=f"{len(rows)} VMs at peak saturation — upsize candidate",
        resource_ids=[r["id"] for r in rows],
        owner="mixed",
        env="mixed",
        savings_monthly_usd=0.0,
        cost_source="estimate",
        effort_hours=max(1, len(rows)),
        risk="High",
        tier="Walk",
        confidence="HIGH",
        business_value=(
            "P95 sustained above the upsize floor. Review for upsize, autoscale group expansion, "
            "or workload split before users start noticing. Not a cost saving — an incident-prevention finding."
        ),
    )
