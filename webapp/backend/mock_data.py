"""Deterministic mock findings for local UI development.

Use by setting ``USE_MOCK_DATA=true`` in your environment. The shapes mirror
what the live detectors would return so the SPA renders identically.

PR2: every mock finding now carries a ``cost_source`` so the SPA's pill
renders without an Azure billing context. Values are spread across
``actual``, ``mixed``, and ``estimate`` to exercise all three rendering paths.
"""
from __future__ import annotations

from .models import Finding


MOCK_FINDINGS: list[Finding] = [
    Finding(
        id="mock:unattached_disks",
        detector="unattached_disks",
        category="Orphaned storage",
        resource="612 unattached managed disks",
        resource_ids=[f"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Compute/disks/mock-disk-{i}" for i in range(5)],
        owner="(untagged)", env="prod",
        savings_monthly_usd=5200, cost_source="actual", effort_hours=3,
        risk="Low", tier="Crawl",
        business_value="Frees ~62k/yr (tenant currency); pair with deny-mode policy on disk creation.",
    ),
    Finding(
        id="mock:unused_public_ips",
        detector="unused_public_ips",
        category="Orphaned network",
        resource="118 unattached Standard public IPs",
        resource_ids=[f"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Network/publicIPAddresses/mock-pip-{i}" for i in range(5)],
        owner="(untagged)", env="nonprod",
        savings_monthly_usd=420, cost_source="actual", effort_hours=1,
        risk="Low", tier="Crawl",
        business_value="Pure waste. Add Azure Policy deny-mode after a 14d audit.",
    ),
    Finding(
        id="mock:empty_asp",
        detector="empty_app_service_plans",
        category="Idle compute",
        resource="14 App Service Plans with zero hosted apps",
        resource_ids=[f"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Web/serverfarms/mock-asp-{i}" for i in range(5)],
        owner="web-team", env="nonprod",
        savings_monthly_usd=920, cost_source="mixed", effort_hours=2,
        risk="Low", tier="Crawl",
        business_value="Plans bill regardless of attached sites. Confirm with each owner before delete.",
    ),
    Finding(
        id="mock:tagging_storage",
        detector="tagging_gap",
        category="Tagging",
        resource="847 storage accounts missing required tags",
        resource_ids=[f"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Storage/storageAccounts/mockstg{i}" for i in range(5)],
        owner="(untagged)", env="unknown",
        savings_monthly_usd=21175, cost_source="mixed", effort_hours=28,
        risk="Low", tier="Crawl",
        business_value="Closes the Visibility Gap. Required before any rightsizing or commitment decision.",
    ),
    Finding(
        id="mock:tagging_vms",
        detector="tagging_gap",
        category="Tagging",
        resource="312 VMs missing required tags",
        resource_ids=[f"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Compute/virtualMachines/mock-vm-{i}" for i in range(5)],
        owner="(untagged)", env="unknown",
        savings_monthly_usd=7800, cost_source="actual", effort_hours=12,
        risk="Low", tier="Crawl",
        business_value="Largest source of unattributed compute spend; tag, then chargeback.",
    ),
    Finding(
        id="mock:commitment_drift",
        detector="commitment_drift",
        category="Commitment",
        resource="6 reservations under 70% utilization (last 30d)",
        resource_ids=["mock-reservation-1", "mock-reservation-2"],
        owner="finops", env="prod",
        savings_monthly_usd=8400, cost_source="estimate", effort_hours=10,
        risk="Medium", tier="Walk",
        business_value="Exchange or right-size before renewal. Underused commitments lock today's inefficiency in for 1–3 years.",
    ),
    Finding(
        id="mock:storage_overprov",
        detector="storage_overprovisioned_redundancy",
        category="Data plane",
        resource="38 non-prod storage accounts on geo/zone redundancy",
        resource_ids=[f"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Storage/storageAccounts/mockgrs{i}" for i in range(5)],
        owner="mixed", env="nonprod",
        savings_monthly_usd=3200, cost_source="actual", effort_hours=8,
        risk="Medium", tier="Walk",
        business_value="LRS is sufficient for ephemeral non-prod. Confirm DR per account before applying.",
    ),
    Finding(
        id="mock:la_retention",
        detector="long_retention_log_analytics",
        category="Log/obs",
        resource="22 Log Analytics workspaces with retention > 90 days",
        resource_ids=[f"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.OperationalInsights/workspaces/mock-la-{i}" for i in range(5)],
        owner="obs-team", env="prod",
        savings_monthly_usd=1760, cost_source="mixed", effort_hours=22,
        risk="Medium", tier="Walk",
        business_value="Move >90d retention to the Archive tier; queries against archived logs incur per-GB cost only when needed.",
    ),
    Finding(
        id="mock:cosmos_overprov",
        detector="overprovisioned_cosmos",
        category="Data plane",
        resource="9 non-prod Cosmos DB accounts with multi-region writes",
        resource_ids=[f"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.DocumentDB/databaseAccounts/mock-cosmos-{i}" for i in range(5)],
        owner="data-platform", env="nonprod",
        savings_monthly_usd=2250, cost_source="estimate", effort_hours=18,
        risk="Medium", tier="Walk",
        business_value="Single-region writes are sufficient for non-prod. Multi-region adds 2–3x RU cost.",
    ),
]


# ---------------------------------------------------------------------------
# PR3 — Peak rightsizing rollups (appear in /api/findings)
# ---------------------------------------------------------------------------

_PEAK_VM = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Compute/virtualMachines"


MOCK_PEAK_ROLLUPS: list[Finding] = [
    Finding(
        id="mock:peak_advisor_unsafe",
        detector="peak_advisor_unsafe",
        category="Rightsizing",
        resource="2 Advisor downsize recs flagged unsafe at P95",
        resource_ids=[f"{_PEAK_VM}/vm-batch-night-04", f"{_PEAK_VM}/vm-retail-checkout-01"],
        owner="mixed", env="prod",
        savings_monthly_usd=0, cost_source="estimate", effort_hours=2,
        risk="High", tier="Walk", confidence="HIGH",
        business_value=(
            "Advisor's average-based logic would have downsized these VMs into a peak-hour outage. "
            "This is the metric that pays for the engine — every avoided incident dwarfs years of savings."
        ),
    ),
    Finding(
        id="mock:peak_downsize",
        detector="peak_downsize",
        category="Rightsizing",
        resource="3 VMs flagged for safe downsize at P95/P99",
        resource_ids=[
            f"{_PEAK_VM}/vm-api-core-01|Standard_D4s_v5",
            f"{_PEAK_VM}/vm-api-core-02|Standard_D4s_v5",
            f"{_PEAK_VM}/vm-stage-runner-03|Standard_D2s_v5",
        ],
        owner="mixed", env="mixed",
        savings_monthly_usd=0, cost_source="estimate", effort_hours=2,
        risk="Medium", tier="Walk", confidence="HIGH",
        business_value=(
            "Downsize ladder one step per VM; never skip steps. Coordinate maintenance window — resize "
            "triggers a reboot. Aim for a 7-day baseline + 7-day post-change soak per batch."
        ),
    ),
    Finding(
        id="mock:peak_upsize",
        detector="peak_upsize",
        category="Rightsizing",
        resource="1 VM at peak saturation — upsize candidate",
        resource_ids=[f"{_PEAK_VM}/vm-billing-svc-01"],
        owner="billing-team", env="prod",
        savings_monthly_usd=0, cost_source="estimate", effort_hours=1,
        risk="High", tier="Walk", confidence="HIGH",
        business_value=(
            "P95 sustained above the upsize floor. Review for upsize, autoscale group expansion, "
            "or workload split before users start noticing."
        ),
    ),
]


# Per-VM detail rows for the SPA's Peak Rightsizing tab.
MOCK_PEAK_DETAILS: list[dict] = [
    {
        "id": f"{_PEAK_VM}/vm-batch-night-04", "name": "vm-batch-night-04",
        "resourceGroup": "rg-batch", "location": "uksouth",
        "size": "Standard_E16ds_v5", "owner": "data-eng", "env": "prod",
        "cpu_p95": 18.4, "cpu_p99": 92.7,    # bursty: low avg, but P99 saturated
        "mem_p95_used": 22.0, "mem_p99_used": 88.0,
        "coverage": 0.96,
        "verdict": "KEEP", "confidence": "MEDIUM",
        "advisor_advised": True, "advisor_unsafe": True,
        "proposed_size": None,
    },
    {
        "id": f"{_PEAK_VM}/vm-retail-checkout-01", "name": "vm-retail-checkout-01",
        "resourceGroup": "rg-retail", "location": "uksouth",
        "size": "Standard_D8s_v5", "owner": "retail-team", "env": "prod",
        "cpu_p95": 14.2, "cpu_p99": 95.1,
        "mem_p95_used": 30.5, "mem_p99_used": 41.0,
        "coverage": 0.99,
        "verdict": "KEEP", "confidence": "MEDIUM",
        "advisor_advised": True, "advisor_unsafe": True,
        "proposed_size": None,
    },
    {
        "id": f"{_PEAK_VM}/vm-api-core-01", "name": "vm-api-core-01",
        "resourceGroup": "rg-api", "location": "uksouth",
        "size": "Standard_D8s_v5", "owner": "api-core", "env": "prod",
        "cpu_p95": 28.0, "cpu_p99": 41.0,
        "mem_p95_used": 38.0, "mem_p99_used": 52.0,
        "coverage": 0.98,
        "verdict": "DOWNSIZE_CANDIDATE", "confidence": "HIGH",
        "advisor_advised": False, "advisor_unsafe": False,
        "proposed_size": "Standard_D4s_v5",
    },
    {
        "id": f"{_PEAK_VM}/vm-api-core-02", "name": "vm-api-core-02",
        "resourceGroup": "rg-api", "location": "uksouth",
        "size": "Standard_D8s_v5", "owner": "api-core", "env": "prod",
        "cpu_p95": 30.5, "cpu_p99": 44.2,
        "mem_p95_used": 35.0, "mem_p99_used": 49.0,
        "coverage": 0.97,
        "verdict": "DOWNSIZE_CANDIDATE", "confidence": "HIGH",
        "advisor_advised": True, "advisor_unsafe": False,
        "proposed_size": "Standard_D4s_v5",
    },
    {
        "id": f"{_PEAK_VM}/vm-stage-runner-03", "name": "vm-stage-runner-03",
        "resourceGroup": "rg-staging", "location": "ukwest",
        "size": "Standard_D4s_v5", "owner": "ci-platform", "env": "nonprod",
        "cpu_p95": 12.0, "cpu_p99": 20.0,
        "mem_p95_used": 25.0, "mem_p99_used": 33.0,
        "coverage": 0.91,
        "verdict": "DOWNSIZE_CANDIDATE", "confidence": "HIGH",
        "advisor_advised": False, "advisor_unsafe": False,
        "proposed_size": "Standard_D2s_v5",
    },
    {
        "id": f"{_PEAK_VM}/vm-billing-svc-01", "name": "vm-billing-svc-01",
        "resourceGroup": "rg-billing", "location": "uksouth",
        "size": "Standard_D4s_v5", "owner": "billing-team", "env": "prod",
        "cpu_p95": 86.0, "cpu_p99": 97.0,
        "mem_p95_used": 70.0, "mem_p99_used": 82.0,
        "coverage": 0.99,
        "verdict": "UPSIZE_WARNING", "confidence": "HIGH",
        "advisor_advised": False, "advisor_unsafe": False,
        "proposed_size": None,
    },
    {
        "id": f"{_PEAK_VM}/vm-ml-research-02", "name": "vm-ml-research-02",
        "resourceGroup": "rg-ml", "location": "uksouth",
        "size": "Standard_E8s_v5", "owner": "ml-research", "env": "nonprod",
        "cpu_p95": 4.0, "cpu_p99": 6.0,
        "mem_p95_used": 8.0, "mem_p99_used": 11.0,
        "coverage": 0.45,  # below min_data_coverage
        "verdict": "INSUFFICIENT_DATA", "confidence": "LOW",
        "advisor_advised": False, "advisor_unsafe": False,
        "proposed_size": None,
    },
]
