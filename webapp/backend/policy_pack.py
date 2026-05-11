"""Audit-mode Azure Policy starter pack (PR5).

Generates `Microsoft.Authorization/policyDefinitions` JSON for the top
preventative controls that complement the Azure Shadow Cost detectors. All
ship in **audit** effect — they emit non-compliant events to Activity Log
and Defender for Cloud but do **not** block resource creation.

Adoption pattern (codified in the README and the policy descriptions):

  1. Run the engine, pick the top 3 categories by recoverable £/$.
  2. Assign the corresponding policy in audit mode at a pilot management
     group for 30 days.
  3. Review compliance state — false-positive rate should approach zero.
  4. Promote to ``deny`` by changing the parameter on the assignment.

The two categories with caveats (``stopped_not_deallocated``, ``old_snapshots``)
ship with a ``_note`` field documenting why the policy alone isn't sufficient
and what to pair it with — borrowed from the FinOps Engine convention.

The /api/policies endpoints in app.py hand these dicts back to the SPA's
Downloads tab; the SPA writes them as JSON files for the operator to
``az policy definition create --rules @file``.
"""
from __future__ import annotations

import json
import zipfile
from io import BytesIO
from typing import Iterable


# ---------------------------------------------------------------------------
# Per-policy generators
# ---------------------------------------------------------------------------

def _policy(
    name: str,
    *,
    display_name: str,
    description: str,
    if_expression: dict,
    note: str | None = None,
    required_tags: list[str] | None = None,
) -> dict:
    """Build a Microsoft.Authorization/policyDefinitions payload."""
    parameters = {
        "effect": {
            "type": "String",
            "metadata": {
                "displayName": "Effect",
                "description": "Audit, AuditIfNotExists, Deny, or Disabled.",
            },
            "allowedValues": ["Audit", "AuditIfNotExists", "Deny", "Disabled"],
            "defaultValue": "Audit",
        }
    }
    if required_tags is not None:
        parameters["requiredTags"] = {
            "type": "Array",
            "metadata": {
                "displayName": "Required tags",
                "description": "Tag keys that must be present on every resource in scope.",
            },
            "defaultValue": required_tags,
        }

    pol: dict = {
        "name": name,
        "type": "Microsoft.Authorization/policyDefinitions",
        "apiVersion": "2021-06-01",
        "properties": {
            "displayName": display_name,
            "description": description,
            "policyType": "Custom",
            "mode": "Indexed",
            "metadata": {"category": "Cost", "version": "1.0.0", "source": "Azure Shadow Cost"},
            "parameters": parameters,
            "policyRule": {
                "if": if_expression,
                "then": {"effect": "[parameters('effect')]"},
            },
        },
    }
    if note:
        pol["properties"]["metadata"]["_note"] = note
    return pol


def deny_untagged_resources(required_tags: list[str]) -> dict:
    """Audit any resource missing one of the configured required tag keys."""
    if_clauses = [
        {"field": f"tags['{t}']", "exists": "false"} for t in required_tags
    ]
    return _policy(
        "azshc-deny-untagged-resources",
        display_name="Audit: resources missing required allocation tags",
        description=(
            "Surfaces every resource whose tag set is incomplete relative to "
            "the FinOps allocation taxonomy. Drives the Visibility Gap metric. "
            "Promote to Deny once the audit-mode false-positive rate is zero."
        ),
        if_expression={"anyOf": if_clauses},
        required_tags=required_tags,
    )


def deny_unattached_managed_disks() -> dict:
    return _policy(
        "azshc-deny-unattached-disks",
        display_name="Audit: unattached managed disks (>7 days)",
        description=(
            "Catches managed disks left in 'Unattached' state — the single "
            "largest hidden-waste category in most tenants. Pair with the "
            "AzShadowCost detector for $/mo pricing from Cost Management actuals."
        ),
        if_expression={
            "allOf": [
                {"field": "type", "equals": "Microsoft.Compute/disks"},
                {"field": "Microsoft.Compute/disks/diskState", "equals": "Unattached"},
            ]
        },
        note=(
            "Policy alone cannot enforce the >7-day window — diskState is "
            "evaluated at write time only. Pair with a Workbook KQL filter "
            "on properties.timeCreated for the actual age check."
        ),
    )


def deny_unassigned_public_ip_standard() -> dict:
    return _policy(
        "azshc-deny-unassigned-public-ip-standard",
        display_name="Audit: Standard SKU public IPs without ipConfiguration",
        description=(
            "Standard SKU public IPs are chargeable when idle. This policy "
            "audits any creation of a Standard PIP that lacks an ipConfiguration "
            "association — typically a Bicep / Terraform mistake."
        ),
        if_expression={
            "allOf": [
                {"field": "type", "equals": "Microsoft.Network/publicIPAddresses"},
                {"field": "Microsoft.Network/publicIPAddresses/sku.name", "equals": "Standard"},
                {"field": "Microsoft.Network/publicIPAddresses/ipConfiguration.id", "exists": "false"},
            ]
        },
    )


def restrict_storage_redundancy_nonprod() -> dict:
    return _policy(
        "azshc-restrict-storage-redundancy-nonprod",
        display_name="Audit: non-prod storage on geo/zone redundancy",
        description=(
            "Storage accounts tagged Environment=dev/test/staging/sandbox/nonprod "
            "default to LRS to halve their bill; GRS / GZRS / RA-GRS in non-prod "
            "is almost always a misconfiguration."
        ),
        if_expression={
            "allOf": [
                {"field": "type", "equals": "Microsoft.Storage/storageAccounts"},
                {
                    "field": "tags['Environment']",
                    "in": ["dev", "development", "test", "qa", "staging", "sandbox", "nonprod", "non-prod"],
                },
                {
                    "field": "Microsoft.Storage/storageAccounts/sku.name",
                    "in": ["Standard_GRS", "Standard_GZRS", "Standard_RAGRS", "Standard_RAGZRS", "Premium_ZRS"],
                },
            ]
        },
    )


def cap_log_analytics_retention() -> dict:
    return _policy(
        "azshc-cap-log-analytics-retention",
        display_name="Audit: Log Analytics retention > 90 days",
        description=(
            "Workspaces with >90-day hot retention are expensive (£2.30/GB-mo "
            "vs. archive's £0.02/GB-mo). Cap at 90 days hot; route long-tail "
            "to the Archive tier."
        ),
        if_expression={
            "allOf": [
                {"field": "type", "equals": "Microsoft.OperationalInsights/workspaces"},
                {"field": "Microsoft.OperationalInsights/workspaces/retentionInDays", "greater": 90},
            ]
        },
    )


# ---------------------------------------------------------------------------
# Catalogue + zip bundling
# ---------------------------------------------------------------------------

def all_policies(required_tags: list[str]) -> dict[str, dict]:
    """Return {category_slug: policy_json} for every shipping policy."""
    return {
        "deny-untagged-resources":               deny_untagged_resources(required_tags),
        "deny-unattached-disks":                 deny_unattached_managed_disks(),
        "deny-unassigned-public-ip-standard":    deny_unassigned_public_ip_standard(),
        "restrict-storage-redundancy-nonprod":   restrict_storage_redundancy_nonprod(),
        "cap-log-analytics-retention":           cap_log_analytics_retention(),
    }


def build_bundle_zip(required_tags: list[str]) -> bytes:
    """Return a zip blob with one policy JSON per category, plus a README."""
    buf = BytesIO()
    catalogue = all_policies(required_tags)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for slug, pol in catalogue.items():
            z.writestr(f"{slug}.audit.json", json.dumps(pol, indent=2) + "\n")
        z.writestr("README.md", _bundle_readme(catalogue.keys()))
    return buf.getvalue()


def _bundle_readme(slugs: Iterable[str]) -> str:
    rows = "\n".join(f"- `{s}.audit.json`" for s in slugs)
    return f"""# Azure Shadow Cost — audit-mode Policy starter pack

All policies in this bundle ship in **audit** effect. They surface
non-compliant resources to Activity Log and Defender for Cloud but do not
block creation.

Adoption pattern:

1. Pick the top 3 categories by recoverable £/$ from your latest Azure
   Shadow Cost run.
2. Assign the matching policy in audit mode at a pilot management group
   for 30 days.
3. Review compliance state — false-positive rate should approach zero.
4. Promote to `deny` by changing the assignment's `effect` parameter.

## Files

{rows}

## How to deploy one

```bash
az policy definition create \\
  --name azshc-deny-untagged-resources \\
  --rules @deny-untagged-resources.audit.json \\
  --mode Indexed
```

Then assign it at a management-group scope and monitor for ~30 days
before promoting to `deny`.
"""
