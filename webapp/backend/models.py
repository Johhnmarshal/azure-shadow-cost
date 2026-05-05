"""Shared data shapes for the API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Tier = Literal["Crawl", "Walk", "Run"]
Risk = Literal["Low", "Medium", "High"]
CostSource = Literal["actual", "estimate", "mixed"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]
Category = Literal[
    "Orphaned storage",
    "Idle compute",
    "Idle network",
    "Orphaned network",
    "Rightsizing",
    "Commitment",
    "Storage tiering",
    "Log/obs",
    "Architectural",
    "Tagging",
    "Data plane",
]


class Finding(BaseModel):
    """A single shadow-cost finding. Mirrors the FinOps ROI engine contract."""
    id: str = Field(..., description="Stable ID; usable as the script-download key.")
    detector: str = Field(..., description="Short detector name (e.g., unattached_disks).")
    category: Category
    resource: str = Field(..., description="Human-readable description: '47 unattached managed disks'.")
    resource_ids: list[str] = Field(default_factory=list, description="Azure resource IDs the script will operate on.")
    owner: str = Field(default="(untagged)", description="Owner tag value, or '(untagged)'.")
    env: str = Field(default="unknown", description="prod / nonprod / unknown.")
    savings_monthly_usd: float = Field(
        ..., ge=0,
        description=(
            "Estimated savings/month if remediated. The numeric value is in "
            "the tenant's billing currency (auto-detected via /api/billing) — "
            "the historical `_usd` suffix is retained for API back-compat."
        ),
    )
    cost_source: CostSource = Field(
        default="estimate",
        description=(
            "Where the savings figure came from: 'actual' (Cost Management "
            "billing rows), 'estimate' (pricing.py constants), or 'mixed' "
            "(some resources had bills, some didn't)."
        ),
    )
    effort_hours: float = Field(..., gt=0, description="Eng hours to remediate.")
    risk: Risk
    tier: Tier
    confidence: Confidence | None = Field(
        default=None,
        description="Detector confidence (HIGH/MEDIUM/LOW). Currently set by peak rightsizing only.",
    )
    proposed_size: str | None = Field(
        default=None,
        description="Target SKU when the detector proposes a specific size (peak rightsizing).",
    )
    business_value: str = Field(..., description="Business framing for leadership.")

    def hourly_return(self) -> float:
        return self.savings_monthly_usd / max(self.effort_hours, 0.5)


class FindingsResponse(BaseModel):
    findings: list[Finding]
    visibility_gap_pct: float = Field(..., description="% of analyzed spend missing a required tag.")
    total_savings_monthly_usd: float
    currency_code: str = Field(default="USD", description="ISO currency code in which all monetary fields are denominated.")
    currency_glyph: str = Field(default="$", description="Display glyph for currency_code.")
    cached_at: str = Field(..., description="ISO timestamp when this response was computed.")
