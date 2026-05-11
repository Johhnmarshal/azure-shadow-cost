"""Smoke tests — runnable without Azure credentials.

Set ``USE_MOCK_DATA=true`` and the API serves a deterministic dataset.
Run with: ``pytest -q v1/tests``
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("USE_MOCK_DATA", "true")
os.environ.setdefault("TARGET_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402


client = TestClient(app)


def test_health() -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_findings_shape() -> None:
    r = client.get("/api/findings")
    assert r.status_code == 200
    body = r.json()
    assert "findings" in body
    assert "visibility_gap_pct" in body
    assert "total_savings_monthly_usd" in body
    assert "currency_code" in body and len(body["currency_code"]) == 3
    assert "currency_glyph" in body and body["currency_glyph"]
    assert len(body["findings"]) > 0
    f0 = body["findings"][0]
    for key in ("id", "detector", "category", "savings_monthly_usd",
                "cost_source", "tier", "risk"):
        assert key in f0, f"missing {key}"
    assert f0["cost_source"] in ("actual", "estimate", "mixed")


def test_billing_endpoint() -> None:
    r = client.get("/api/billing")
    assert r.status_code == 200
    body = r.json()
    assert body.get("currency_code") == "USD"
    assert body.get("glyph") == "$"
    assert body.get("source") in ("detected", "override", "fallback")


def test_peak_rightsizing_endpoint() -> None:
    r = client.get("/api/peak-rightsizing")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body and "summary" in body and "thresholds" in body
    assert body["summary"]["total_vms"] == len(body["rows"])
    assert body["summary"]["advisor_unsafe"] >= 1


def test_settings_get_and_post() -> None:
    r = client.get("/api/settings")
    assert r.status_code == 200
    t = r.json()
    assert "downsize_cpu_p95_max" in t
    r = client.post("/api/settings", json={"downsize_cpu_p95_max": 55.0})
    assert r.status_code == 200
    assert r.json()["downsize_cpu_p95_max"] == 55.0
    r = client.post("/api/settings", json={"downsize_cpu_p95_max": 90.0})
    assert r.status_code == 400
    client.post("/api/settings", json={"downsize_cpu_p95_max": 40.0})


def test_ri_coverage_no_buffer() -> None:
    r = client.get("/api/ri-coverage")
    assert r.status_code == 200
    body = r.json()
    assert body["buffer_required"] is True
    assert body["shortlist"] == []
    assert len(body["groups"]) >= 1
    assert "rejected_high_risk" in body


def test_ri_coverage_with_buffer() -> None:
    r = client.get("/api/ri-coverage?buffer=5000")
    assert r.status_code == 200
    body = r.json()
    assert body["buffer"] == 5000
    assert body["buffer_required"] is False
    assert isinstance(body["shortlist"], list)
    assert isinstance(body["running_exposure"], (int, float))
    assert body["running_exposure"] <= 5000
    assert len(body["shortlist"]) >= 1
    for g in body["shortlist"]:
        assert g["risk"] in ("LOW", "MEDIUM")


def test_script_download() -> None:
    findings = client.get("/api/findings").json()["findings"]
    fid = findings[0]["id"]
    r = client.get(f"/api/findings/{fid}/script")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/x-shellscript")
    body = r.text
    assert "DRY-RUN BY DEFAULT" in body
    assert "az account set --subscription" in body
    assert "RESOURCE_IDS=(" in body


def test_unknown_finding_404() -> None:
    r = client.get("/api/findings/does-not-exist/script")
    assert r.status_code == 404


# ---- PR5 — queues / policies / workbooks -----------------------------------

def test_queues_endpoint() -> None:
    r = client.get("/api/queues")
    assert r.status_code == 200
    body = r.json()
    assert "owners" in body and isinstance(body["owners"], list)
    assert "currency_code" in body
    assert len(body["owners"]) >= 1
    o0 = body["owners"][0]
    for key in ("owner", "count", "monthly_savings", "annualised"):
        assert key in o0


def test_queue_md_download() -> None:
    owners = client.get("/api/queues").json()["owners"]
    name = owners[0]["owner"]
    r = client.get(f"/api/queues/{name}.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert name in r.text
    assert "[ ] accept" in r.text


def test_policies_list_and_download() -> None:
    r = client.get("/api/policies")
    assert r.status_code == 200
    cats = r.json()
    assert isinstance(cats, list) and len(cats) >= 5
    slug = cats[0]["slug"]
    r = client.get(f"/api/policies/{slug}.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    pol = json.loads(r.text)
    assert pol["type"] == "Microsoft.Authorization/policyDefinitions"


def test_policy_bundle_zip() -> None:
    r = client.get("/api/policies/bundle.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert len(r.content) > 500


def test_workbooks_list_and_download() -> None:
    r = client.get("/api/workbooks")
    assert r.status_code == 200
    items = r.json()
    assert {i["name"] for i in items} == {"hidden-waste", "peak-rightsizing", "ri-coverage"}
    name = items[0]["name"]
    r = client.get(f"/api/workbooks/{name}.json")
    assert r.status_code == 200
    wb = json.loads(r.text)
    assert wb.get("version") == "Notebook/1.0"
