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
    assert len(body["findings"]) > 0
    f0 = body["findings"][0]
    for key in ("id", "detector", "category", "savings_monthly_usd", "tier", "risk"):
        assert key in f0, f"missing {key}"


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
