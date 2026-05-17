"""Tests for enricher — owner resolution + per-owner queue rendering.

Pure functions; no Azure dependencies.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("USE_MOCK_DATA", "true")
os.environ.setdefault("TARGET_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")

from backend import enricher  # noqa: E402
from backend.models import Finding  # noqa: E402


def _f(owner: str = "(untagged)", *, savings: float = 100.0,
       resource_ids: list[str] | None = None) -> Finding:
    return Finding(
        id="t:" + owner + ":" + str(savings),
        detector="t",
        category="Orphaned storage",
        resource="test resource",
        resource_ids=resource_ids or [],
        owner=owner, env="prod",
        savings_monthly_usd=savings, cost_source="estimate",
        effort_hours=1, risk="Low", tier="Crawl",
        business_value="test",
    )


# ---- YAML parsing ----------------------------------------------------------

def test_parse_owner_yaml_basic():
    text = """
defaults:
  fallback: needs-attribution

mappings:
  by_subscription:
    00000000-0000-0000-0000-000000000000: platform-team
  by_resource_group:
    rg-batch: data-eng
    rg-retail: retail-team
  by_resource_type:
    microsoft.web/serverfarms: web-team
"""
    om = enricher.parse_owner_yaml(text)
    assert om.by_subscription["00000000-0000-0000-0000-000000000000"] == "platform-team"
    assert om.by_resource_group["rg-batch"] == "data-eng"
    assert om.by_resource_group["rg-retail"] == "retail-team"
    assert om.by_resource_type["microsoft.web/serverfarms"] == "web-team"


def test_parse_owner_yaml_handles_comments():
    text = """
mappings:
  by_resource_group:
    # This is a comment
    rg-foo: foo-team   # inline comment
"""
    om = enricher.parse_owner_yaml(text)
    assert om.by_resource_group["rg-foo"] == "foo-team"


def test_parse_codeowners_skips_comments():
    text = """
# default owner
* default-team@org.example
/Microsoft.Compute/virtualMachines/* api-core@org.example

# blank line above is fine
"""
    rules = enricher.parse_codeowners(text)
    assert ("*", "default-team@org.example") in rules
    assert any(p.endswith("virtualMachines/*") for p, _ in rules)


# ---- resolve_owner ---------------------------------------------------------

def test_resolve_owner_uses_tag_when_present():
    f = _f(owner="api-core")
    assert enricher.resolve_owner(f) == "api-core"


def test_resolve_owner_routes_mixed_to_finops():
    f = _f(owner="mixed")
    assert enricher.resolve_owner(f) == "finops"


def test_resolve_owner_falls_back_to_yaml_by_resource_group():
    om = enricher.OwnerMap(by_resource_group={"rg-batch": "data-eng"})
    rid = "/subscriptions/abc/resourceGroups/rg-batch/providers/Microsoft.Compute/disks/d1"
    f = _f(owner="(untagged)", resource_ids=[rid])
    assert enricher.resolve_owner(f, owner_map=om) == "data-eng"


def test_resolve_owner_falls_back_to_yaml_by_subscription():
    om = enricher.OwnerMap(by_subscription={"abc": "platform-team"})
    rid = "/subscriptions/abc/providers/Microsoft.Authorization/policyAssignments/x"
    f = _f(owner="(untagged)", resource_ids=[rid])
    assert enricher.resolve_owner(f, owner_map=om) == "platform-team"


def test_resolve_owner_falls_back_to_codeowners():
    co = [("/Microsoft.Compute/virtualMachines/*", "api-core")]
    rid = "/subscriptions/abc/resourceGroups/rg-x/providers/Microsoft.Compute/virtualMachines/vm1"
    f = _f(owner="(untagged)", resource_ids=[rid])
    assert enricher.resolve_owner(f, codeowners=co) == "needs-attribution"


def test_resolve_owner_returns_needs_attribution_default():
    f = _f(owner="(untagged)", resource_ids=["/anything/strange"])
    assert enricher.resolve_owner(f) == enricher.NEEDS_ATTRIBUTION


def test_resolve_owner_uses_yaml_fallback():
    om = enricher.OwnerMap(fallback="needs-finops-routing")
    f = _f(owner="(untagged)", resource_ids=["/anything"])
    assert enricher.resolve_owner(f, owner_map=om) == "needs-finops-routing"


# ---- group_by_owner --------------------------------------------------------

def test_group_by_owner_sorts_within_buckets_by_savings_desc():
    findings = [
        _f(owner="alice", savings=100),
        _f(owner="alice", savings=300),
        _f(owner="bob",   savings=200),
    ]
    grouped = enricher.group_by_owner(findings)
    assert list(grouped.keys()) == ["alice", "bob"]
    assert [f.savings_monthly_usd for f in grouped["alice"]] == [300, 100]


# ---- render_queue_md -------------------------------------------------------

def test_render_queue_md_contains_finding_id_and_action_boxes():
    findings = [_f(owner="alice", savings=500)]
    md = enricher.render_queue_md("alice", findings, currency_glyph="£", today="2026-05-09")
    assert "alice — 2026-05-09" in md
    assert "£500" in md
    assert "[ ] accept" in md
    assert findings[0].id in md
