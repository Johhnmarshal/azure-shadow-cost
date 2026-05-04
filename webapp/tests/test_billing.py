"""Tests for billing.py — currency detection + override semantics.

Runs without Azure credentials. The Cost Management call inside
``_probe_currency`` is replaced via ``unittest.mock`` so the test exercises
parsing of the result-shape rather than the network call.
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
os.environ["REPORTING_CURRENCY"] = "auto"  # ensure we exercise the detection path

from backend import billing  # noqa: E402
from backend.cache import cache  # noqa: E402
from backend.config import settings  # noqa: E402


def _column(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, type="String")


def _fake_cm_result(currency: str = "GBP") -> SimpleNamespace:
    return SimpleNamespace(
        columns=[_column("Cost"), _column("Currency")],
        rows=[[42.50, currency]],
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_glyph_lookup() -> None:
    assert billing._glyph_for("GBP") == "£"
    assert billing._glyph_for("EUR") == "€"
    assert billing._glyph_for("USD") == "$"
    # Unknown ISO codes fall through to the code itself.
    assert billing._glyph_for("XYZ") == "XYZ"


def test_detected_currency_from_query() -> None:
    cache.invalidate("billing:")
    fake_client = MagicMock()
    fake_client.query.usage.return_value = _fake_cm_result("GBP")

    with patch("backend.billing.cost_management", return_value=fake_client):
        ctx = _run(billing.context())

    assert ctx.currency_code == "GBP"
    assert ctx.glyph == "£"
    assert ctx.source == "detected"


def test_override_takes_precedence() -> None:
    cache.invalidate("billing:")
    settings.cache_clear()  # frozen Settings cached via lru_cache
    os.environ["REPORTING_CURRENCY"] = "EUR"
    try:
        ctx = _run(billing.context())
        assert ctx.currency_code == "EUR"
        assert ctx.glyph == "€"
        assert ctx.source == "override"
    finally:
        os.environ["REPORTING_CURRENCY"] = "auto"
        settings.cache_clear()


def test_failed_probe_falls_back() -> None:
    cache.invalidate("billing:")
    settings.cache_clear()

    fake_client = MagicMock()
    fake_client.query.usage.side_effect = RuntimeError("403 forbidden")

    with patch("backend.billing.cost_management", return_value=fake_client):
        ctx = _run(billing.context())

    assert ctx.currency_code == "USD"
    assert ctx.glyph == "$"
    assert ctx.source == "fallback"
