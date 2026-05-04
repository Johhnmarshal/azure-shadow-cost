"""Runtime configuration for Shadow Cost.

Reads from environment variables (App Service appSettings or local .env). Keep
this module import-cheap so it can be imported at startup without side effects.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _csv_env(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [t.strip() for t in raw.split(",") if t.strip()]


@dataclass(frozen=True)
class Settings:
    """All app settings live here. Override via env vars in App Service."""
    # Subscription the detectors operate on. The MI must have Reader on it.
    target_subscription_id: str = field(
        default_factory=lambda: os.environ.get("TARGET_SUBSCRIPTION_ID", "")
    )
    # Mandatory tag keys. Drives the Visibility Gap calculation.
    required_tags: list[str] = field(
        default_factory=lambda: _csv_env(
            "REQUIRED_TAGS", "Owner,CostCenter,Environment,Application"
        )
    )
    # Reporting currency. Cost Management returns billing currency by default.
    reporting_currency: str = field(
        default_factory=lambda: os.environ.get("REPORTING_CURRENCY", "USD")
    )
    # Cache TTL for ARG/Cost Management responses (seconds). Cost Management is
    # heavily rate-limited (~5 req/min/sub), so default to 10 minutes.
    cache_ttl_seconds: int = field(
        default_factory=lambda: int(os.environ.get("CACHE_TTL_SECONDS", "600"))
    )
    # When true, /api/* endpoints return a deterministic mock dataset. Useful
    # for local UI development without Azure credentials.
    use_mock_data: bool = field(
        default_factory=lambda: os.environ.get("USE_MOCK_DATA", "false").lower() == "true"
    )


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
