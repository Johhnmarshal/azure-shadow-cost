"""Shared data shapes for the API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Tier = Literal["Crawl", "Walk", "Run"]
Risk = Literal["Low", "Medium", "High"]
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
    savings_monthly_usd: float = Field(..., ge=0, description="Estimated $/month saved if remediated.")
    effort_hours: float = Field(..., gt=0, description="Eng hours to remediate.")
    risk: Risk
    tier: Tier
    business_value: str = Field(..., description="Business framing for leadership.")

    def hourly_return(self) -> float:
        return self.savings_monthly_usd / max(self.effort_hours, 0.5)


class FindingsResponse(BaseModel):
    findings: list[Finding]
    visibility_gap_pct: float = Field(..., description="% of analyzed spend missing a required tag.")
    total_savings_monthly_usd: float
    cached_at: str = Field(..., description="ISO timestamp when this response was computed.")
