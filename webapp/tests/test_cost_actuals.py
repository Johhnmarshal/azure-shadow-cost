"""Tests for cost_actuals.py — per-resource pricing + fallback classification.

Mocks the Cost Management /query call so we can exercise the three
``cost_source`` outcomes (actual / mixed / estimate) deterministically.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("TARGET_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")

from backend import cost_actuals  # noqa: E402
from backend.cache import cache  # noqa: E402


def _column(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, type="String")


def _fake_result(rows: list[list]) -> SimpleNamespace:
    return SimpleNamespace(
        columns=[_column("Cost"), _column("ResourceId")],
        rows=rows,
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_all_actual() -> None:
    cache.invalidate("cost_actuals:")
    fake_client = MagicMock()
    fake_client.query.usage.return_value = _fake_result([
        [10.0, "/subscriptions/x/disks/a"],
        [20.0, "/subscriptions/x/disks/b"],
    ])
    with patch("backend.cost_actuals.cost_management", return_value=fake_client):
        total, src = _run(cost_actuals.price_resources([
            ("/subscriptions/x/disks/a", 999.0),
            ("/subscriptions/x/disks/b", 999.0),
        ]))
    assert total == 30.0
    assert src == "actual"


def test_all_estimate_when_query_returns_no_rows() -> None:
    cache.invalidate("cost_actuals:")
    fake_client = MagicMock()
    fake_client.query.usage.return_value = _fake_result([])
    with patch("backend.cost_actuals.cost_management", return_value=fake_client):
        total, src = _run(cost_actuals.price_resources([
            ("/subscriptions/x/disks/never-billed", 5.0),
            ("/subscriptions/x/disks/also-never", 7.0),
        ]))
    assert total == 12.0
    assert src == "estimate"


def test_mixed_when_some_resources_missing() -> None:
    cache.invalidate("cost_actuals:")
    fake_client = MagicMock()
    fake_client.query.usage.return_value = _fake_result([
        [50.0, "/subscriptions/x/disks/a"],
    ])
    with patch("backend.cost_actuals.cost_management", return_value=fake_client):
        total, src = _run(cost_actuals.price_resources([
            ("/subscriptions/x/disks/a", 999.0),  # actual = 50
            ("/subscriptions/x/disks/c", 8.0),    # fallback = 8
        ]))
    assert total == 58.0
    assert src == "mixed"


def test_resource_id_match_is_case_insensitive() -> None:
    cache.invalidate("cost_actuals:")
    fake_client = MagicMock()
    fake_client.query.usage.return_value = _fake_result([
        [11.0, "/SUBSCRIPTIONS/X/DISKS/UPPER"],
    ])
    with patch("backend.cost_actuals.cost_management", return_value=fake_client):
        total, src = _run(cost_actuals.price_resources([
            ("/subscriptions/x/disks/upper", 99.0),  # query in lower; row in upper
        ]))
    assert total == 11.0
    assert src == "actual"


def test_query_failure_returns_estimate() -> None:
    cache.invalidate("cost_actuals:")
    fake_client = MagicMock()
    fake_client.query.usage.side_effect = RuntimeError("rate limited")
    with patch("backend.cost_actuals.cost_management", return_value=fake_client):
        total, src = _run(cost_actuals.price_resources([
            ("/subscriptions/x/disks/a", 4.0),
            ("/subscriptions/x/disks/b", 6.0),
        ]))
    assert total == 10.0
    assert src == "estimate"
