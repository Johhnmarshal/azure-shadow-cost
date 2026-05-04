"""Coarse Azure unit-cost constants for $/month estimation.

These are intentionally conservative round-numbers. Replace with live pricing
from your EA / CSP agreement once you join Cost Management actuals into the
detectors (see TODO in v1.1).
"""
from __future__ import annotations

# Public IPs — Standard SKU is chargeable when idle.
PUBLIC_IP_STANDARD_MONTHLY_USD = 3.65

# Disk pricing per GB/month, by SKU family (East US list price, Q1 2026).
_DISK_PER_GB = {
    "Premium_LRS": 0.135,
    "PremiumV2_LRS": 0.10,
    "StandardSSD_LRS": 0.075,
    "Standard_LRS": 0.045,
    "UltraSSD_LRS": 0.32,
}


def disk_monthly_usd(sku: str, size_gb: int) -> float:
    rate = _DISK_PER_GB.get(sku, 0.10)
    return rate * max(0, size_gb)


# App Service Plan tiers — single-instance monthly list price.
_ASP_MONTHLY = {
    "F1":    0.0,
    "B1":    13.14,
    "B2":    26.28,
    "B3":    52.56,
    "S1":    73.0,
    "S2":   146.0,
    "S3":   292.0,
    "P1v3": 116.07,
    "P2v3": 232.14,
    "P3v3": 464.28,
    "P0v3":  54.75,
}


def app_service_plan_monthly_usd(sku: str) -> float:
    return _ASP_MONTHLY.get(sku, 70.0)
