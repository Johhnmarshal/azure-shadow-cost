"""Smoke tests — runnable without Azure credentials.

Set ``USE_MOCK_DATA=true`` and the API serves a deterministic dataset.
Run with: ``pytest -q v1/tests``
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make `backend.*` importable when pytest is invoked from the repo root.
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
    # PR2 — currency context surfaces on every response
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
    assert body.get("currency_code") == "USD"  # mock-mode returns the stable USD context
    assert body.get("glyph") == "$"
    assert body.get("source") in ("detected", "override", "fallback")


def test_peak_rightsizing_endpoint() -> None:
    r = client.get("/api/peak-rightsizing")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body and "summary" in body and "thresholds" in body
    assert body["summary"]["total_vms"] == len(body["rows"])
    # Mock data has at least one advisor_unsafe row.
    assert body["summary"]["advisor_unsafe"] >= 1


def test_settings_get_and_post() -> None:
    r = client.get("/api/settings")
    assert r.status_code == 200
    t = r.json()
    assert "downsize_cpu_p95_max" in t
    # Update one field
    r = client.post("/api/settings", json={"downsize_cpu_p95_max": 55.0})
    assert r.status_code == 200
    assert r.json()["downsize_cpu_p95_max"] == 55.0
    # Invalid (downsize >= upsize) should 400
    r = client.post("/api/settings", json={"downsize_cpu_p95_max": 90.0})
    assert r.status_code == 400
    # Reset
    client.post("/api/settings", json={"downsize_cpu_p95_max": 40.0})


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
