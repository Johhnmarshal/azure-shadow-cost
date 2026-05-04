"""Bash remediation-script generator.

Every detector ID maps to a template under ``backend/templates``. The builder
substitutes the resource IDs and the target subscription. Generated scripts
are dry-run by default; the user must pass ``--apply`` to mutate state.
"""
from __future__ import annotations

from pathlib import Path

from .config import settings


TEMPLATE_DIR = Path(__file__).parent / "templates"

# Map detector name → template filename.
_TEMPLATES = {
    "unattached_disks":              "delete_unattached_disks.sh",
    "unused_public_ips":             "release_unused_public_ips.sh",
    "empty_app_service_plans":       "delete_empty_app_service_plans.sh",
    "tagging_gap":                   "apply_required_tags.sh",
    "long_retention_log_analytics":  "set_log_analytics_retention.sh",
    "storage_overprovisioned_redundancy": "downgrade_storage_redundancy.sh",
    "overprovisioned_cosmos":        "disable_cosmos_multi_region.sh",
    "commitment_drift":              "review_commitment_drift.sh",
    "commitment_advisory":           "review_commitment_drift.sh",
}


def build(detector: str, resource_ids: list[str]) -> str:
    """Return the full bash script as a string, ready for download."""
    name = _TEMPLATES.get(detector)
    if not name:
        raise KeyError(f"No remediation template for detector '{detector}'")

    body = (TEMPLATE_DIR / name).read_text()
    header = (TEMPLATE_DIR / "_header.sh").read_text()

    # Format the Azure resource ID list as a bash array.
    bash_array = "\n".join(f'  "{rid}"' for rid in resource_ids)
    if not bash_array:
        bash_array = '  # no resources matched at generation time'

    return (
        header
        .replace("__SUBSCRIPTION__", settings().target_subscription_id or "<set-me>")
        .replace("__DETECTOR__", detector)
        + "\n\nRESOURCE_IDS=(\n" + bash_array + "\n)\n\n"
        + body
    )
