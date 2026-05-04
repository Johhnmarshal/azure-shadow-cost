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
