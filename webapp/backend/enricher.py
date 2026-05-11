"""Context enricher — owner attribution + per-owner Markdown queues.

For every finding, resolve a single owner via a three-tier precedence:

  1. **Azure Tag** (``Owner`` tag on the resource, surfaced as ``Finding.owner``).
  2. **YAML override** (``owners.yaml`` mapping by subscription / RG / type).
  3. **CODEOWNERS** (path-glob match against the resource ID).

If none match, the resource lands in the ``needs-attribution`` queue. That
queue exists by design — it's the FinOps team's signal that tagging is
broken in some corner of the tenant.

Grouping by owner produces a per-owner Markdown queue with accept / defer /
reject checkboxes. The intent is one tracker issue per owner, edited in
place each nightly run (PR-after-5 will add the GitHub Actions integration).

Pure functions for owner resolution and queue rendering — fully testable
without Azure or filesystem dependencies (the YAML/CODEOWNERS are passed in
as already-parsed structures).
"""
from __future__ import annotations

import fnmatch
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import settings
from .models import Finding


log = logging.getLogger("enricher")

NEEDS_ATTRIBUTION = "needs-attribution"


# ---------------------------------------------------------------------------
# Owner-resolution data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OwnerMap:
    """Parsed YAML mapping. All fields optional; missing = empty dict."""
    by_subscription:    dict[str, str] = field(default_factory=dict)
    by_resource_group:  dict[str, str] = field(default_factory=dict)
    by_resource_type:   dict[str, str] = field(default_factory=dict)
    fallback:           str | None = None


def parse_owner_yaml(text: str) -> OwnerMap:
    """Parse the YAML override file. Stdlib-only — no PyYAML dependency.

    Format (whitespace-tolerant):

        defaults:
          fallback: needs-attribution
        mappings:
          by_subscription:
            00000000-0000-0000-0000-000000000000: platform-team
          by_resource_group:
            rg-batch: data-eng
          by_resource_type:
            microsoft.web/serverfarms: web-team

    Comments (``#``) and blank lines are ignored. We hand-parse a tiny
    subset because the engines stay stdlib-only by design.
    """
    by_sub: dict[str, str] = {}
    by_rg:  dict[str, str] = {}
    by_typ: dict[str, str] = {}
    fallback: str | None = None

    section: str | None = None  # "by_subscription" | "by_resource_group" | "by_resource_type" | "defaults"
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        # Section headers (top-level keys ending with `:`).
        stripped = line.strip()
        if line == stripped + "" and stripped.endswith(":") and not line.startswith(" "):
            section = None  # outer header (mappings: / defaults:)
            continue
        # Two-space indent = subsection header (e.g. by_subscription:).
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            section = stripped[:-1].strip()
            continue
        # Four-space indent = key/value pair under a subsection.
        if line.startswith("    ") and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip().strip('"').strip("'")
            value = value.strip().strip('"').strip("'")
            if not key or not value:
                continue
            if section == "by_subscription":
                by_sub[key.lower()] = value
            elif section == "by_resource_group":
                by_rg[key.lower()] = value
            elif section == "by_resource_type":
                by_typ[key.lower()] = value
            elif section == "fallback" or key == "fallback":
                fallback = value
        # Two-space indent under defaults: fallback: <value>
        elif line.startswith("  ") and ":" in stripped and section is None:
            # Could be `fallback: foo` directly under `defaults:` — handle elsewhere
            pass

    return OwnerMap(by_subscription=by_sub, by_resource_group=by_rg,
                    by_resource_type=by_typ, fallback=fallback)


def parse_codeowners(text: str) -> list[tuple[str, str]]:
    """Parse a CODEOWNERS file into [(pattern, owner), ...] in file order.

    The first matching pattern wins (CODEOWNERS evaluates last-match-wins,
    but for resource paths we prefer first-match-wins to keep behaviour
    predictable for non-engineers). Comments + blank lines are skipped.
    """
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern, owner = parts[0], parts[1]
        out.append((pattern, owner))
    return out


# ---------------------------------------------------------------------------
# Resource-ID parsing
# ---------------------------------------------------------------------------

def _parse_resource_id(rid: str) -> dict[str, str]:
    """Extract subscriptionId / resourceGroup / resourceType from an ARM ID.

    Tolerates the small range of ID shapes we see in practice:

        /subscriptions/{sub}/resourceGroups/{rg}/providers/{ns}/{type}/{name}
        /subscriptions/{sub}/providers/{ns}/{type}/{name}        # sub-scoped
        anything else                                            # returns {}
    """
    parts = rid.split("/")
    out: dict[str, str] = {}
    for i, p in enumerate(parts):
        if p.lower() == "subscriptions" and i + 1 < len(parts):
            out["subscription"] = parts[i + 1].lower()
        elif p.lower() == "resourcegroups" and i + 1 < len(parts):
            out["resource_group"] = parts[i + 1].lower()
        elif p.lower() == "providers" and i + 2 < len(parts):
            ns, t = parts[i + 1], parts[i + 2]
            out["resource_type"] = f"{ns}/{t}".lower()
            break
    return out


# ---------------------------------------------------------------------------
# Owner resolution — pure
# ---------------------------------------------------------------------------

def resolve_owner(
    finding: Finding,
    owner_map: OwnerMap | None = None,
    codeowners: list[tuple[str, str]] | None = None,
) -> str:
    """Return the canonical owner for a finding.

    Precedence: Azure Tag (Finding.owner) → YAML → CODEOWNERS → fallback.

    "Mixed" owners on rollup findings (peak_rightsizing, ri_coverage) bypass
    the YAML/CODEOWNERS path — a rollup spans many resources, no single
    owner is correct, so we route to ``finops`` (the team that runs the
    cycle).
    """
    tag_owner = (finding.owner or "").strip()

    if tag_owner == "mixed":
        return "finops"
    if tag_owner and tag_owner != "(untagged)":
        return tag_owner

    # Try YAML / CODEOWNERS only when the tag was missing.
    om = owner_map or OwnerMap()
    co = codeowners or []

    for rid in finding.resource_ids:
        parts = _parse_resource_id(rid)
        if "resource_group" in parts and parts["resource_group"] in om.by_resource_group:
            return om.by_resource_group[parts["resource_group"]]
        if "subscription" in parts and parts["subscription"] in om.by_subscription:
            return om.by_subscription[parts["subscription"]]
        if "resource_type" in parts and parts["resource_type"] in om.by_resource_type:
            return om.by_resource_type[parts["resource_type"]]
        for pattern, owner in co:
            if fnmatch.fnmatch(rid.lower(), pattern.lower()):
                return owner

    return om.fallback or NEEDS_ATTRIBUTION


def group_by_owner(
    findings: Iterable[Finding],
    owner_map: OwnerMap | None = None,
    codeowners: list[tuple[str, str]] | None = None,
) -> dict[str, list[Finding]]:
    """Bucket findings by resolved owner. Owners are sorted alphabetically;
    within each bucket findings are sorted by descending monthly savings."""
    buckets: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        owner = resolve_owner(f, owner_map, codeowners)
        buckets[owner].append(f)
    return {
        k: sorted(v, key=lambda f: -f.savings_monthly_usd)
        for k, v in sorted(buckets.items())
    }


# ---------------------------------------------------------------------------
# Per-owner Markdown queue
# ---------------------------------------------------------------------------

def render_queue_md(
    owner: str,
    findings: list[Finding],
    *,
    currency_glyph: str = "$",
    today: str | None = None,
) -> str:
    """Render a per-owner Markdown queue with accept/defer/reject boxes.

    The format is intentionally trivially-parseable so a nightly automation
    can read accept/defer/reject states out of edited issue bodies. Each
    finding's ID prefixes its row so re-runs can match across edits.
    """
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total_monthly = sum(f.savings_monthly_usd for f in findings)
    total_annual  = total_monthly * 12

    lines: list[str] = []
    lines.append(f"# FinOps remediation queue — {owner} — {today}")
    lines.append("")
    lines.append(
        f"**{len(findings)} findings · ~{currency_glyph}{total_monthly:,.0f} / month "
        f"({currency_glyph}{total_annual:,.0f} / yr) recoverable.**"
    )
    lines.append("")
    lines.append("Reply `accept`, `defer`, or `reject` per row. Each row is prefixed by")
    lines.append("a stable finding ID so this issue can be re-edited safely each night.")
    lines.append("")
    lines.append("| Finding | Category | $/mo | Risk | Confidence | Action |")
    lines.append("|---|---|---:|---|---|---|")

    for f in findings:
        action = "[ ] accept · [ ] defer · [ ] reject"
        conf = f.confidence or "—"
        lines.append(
            f"| `{f.id}` · {f.resource} | {f.category} | "
            f"{currency_glyph}{f.savings_monthly_usd:,.0f} | "
            f"{f.risk} | {conf} | {action} |"
        )

    if any(f.business_value for f in findings):
        lines.append("")
        lines.append("## Business framing (top 3 by $/mo)")
        lines.append("")
        for f in findings[:3]:
            lines.append(f"- **{f.resource}** — {f.business_value}")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("> Generated by Azure Shadow Cost. Each row links back to the source detector.")
    return "\n".join(lines) + "\n"


def render_queues_index_md(grouped: dict[str, list[Finding]], *, currency_glyph: str = "$") -> str:
    """Top-level Markdown index — one row per owner with totals."""
    lines: list[str] = []
    lines.append("# Per-owner remediation queues")
    lines.append("")
    lines.append("| Owner | Findings | $/mo | Annualised |")
    lines.append("|---|---:|---:|---:|")
    grand_total = 0.0
    for owner, items in grouped.items():
        m = sum(f.savings_monthly_usd for f in items)
        lines.append(
            f"| **{owner}** | {len(items)} | "
            f"{currency_glyph}{m:,.0f} | {currency_glyph}{m*12:,.0f} |"
        )
        grand_total += m
    lines.append(
        f"| **TOTAL** | — | **{currency_glyph}{grand_total:,.0f}** | "
        f"**{currency_glyph}{grand_total*12:,.0f}** |"
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# File-loading helpers
# ---------------------------------------------------------------------------

def load_owner_map() -> OwnerMap:
    """Load the YAML override from ``settings().owners_yaml_path``. Returns
    an empty map if the file doesn't exist or fails to parse."""
    p = Path(settings().owners_yaml_path) if settings().owners_yaml_path else None
    if not p or not p.exists():
        return OwnerMap()
    try:
        return parse_owner_yaml(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — graceful degrade
        log.warning("owners.yaml parse failed: %s", e)
        return OwnerMap()


def load_codeowners() -> list[tuple[str, str]]:
    """Load CODEOWNERS from ``settings().codeowners_path``. Returns [] on miss."""
    p = Path(settings().codeowners_path) if settings().codeowners_path else None
    if not p or not p.exists():
        return []
    try:
        return parse_codeowners(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("CODEOWNERS parse failed: %s", e)
        return []
