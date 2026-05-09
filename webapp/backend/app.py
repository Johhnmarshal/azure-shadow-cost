"""FastAPI entry point for Azure Shadow Cost.

Endpoints
---------
GET  /api/health                      Liveness probe.
GET  /api/me                          Returns the resolved identity (MI / SP / az login).
GET  /api/billing                     Detected tenant currency (PR2).
GET  /api/subscriptions               Lists subscriptions visible to the credential.
GET  /api/findings                    Runs all detectors, returns FindingsResponse.
GET  /api/findings/{id}/script        Returns the generated bash remediation as text/plain.
GET  /api/peak-rightsizing            Per-VM peak rightsizing detail + summary (PR3).
GET  /api/settings                    Current peak-rightsizing thresholds (PR3).
POST /api/settings                    Atomic update of one or more thresholds (PR3).
GET  /api/ri-coverage                 RI/SP coverage analysis with optional ?buffer (PR4).
POST /api/cache/invalidate            Drops the in-memory cache (auth-gate this in v1.1).

Static SPA is mounted at "/" from ../frontend.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import billing, detectors, mock_data, peak_rightsizing, ri_coverage, script_builder, thresholds
from .az_clients import credential, subscriptions
from .cache import cache
from .config import settings
from .models import Finding, FindingsResponse


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("azshc")

app = FastAPI(title="Azure Shadow Cost", version="1.0.0")

# CORS — leave permissive for local dev; tighten before sharing externally.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------------
# Health & identity
# ----------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.get("/api/me")
async def me() -> dict[str, str]:
    """Echo back which credential will be used. Useful for debugging MI."""
    cred = credential()
    return {
        "credential_class": type(cred).__name__,
        "target_subscription_id": settings().target_subscription_id or "(unset)",
        "use_mock_data": str(settings().use_mock_data),
    }


# ----------------------------------------------------------------------------
# Billing context (PR2)
# ----------------------------------------------------------------------------

async def _billing_context() -> billing.BillingContext:
    """Resolve currency. In mock mode return a stable USD context."""
    if settings().use_mock_data:
        return billing.BillingContext("USD", "$", "fallback")
    return await billing.context()


@app.get("/api/billing")
async def get_billing() -> dict[str, str]:
    ctx = await _billing_context()
    return ctx.to_dict()


# ----------------------------------------------------------------------------
# Subscriptions
# ----------------------------------------------------------------------------

@app.get("/api/subscriptions")
async def list_subscriptions() -> list[dict[str, str]]:
    if settings().use_mock_data:
        return [{"subscriptionId": "00000000-0000-0000-0000-000000000000", "displayName": "Mock Subscription"}]

    def _do() -> list[dict[str, str]]:
        return [
            {"subscriptionId": s.subscription_id, "displayName": s.display_name}
            for s in subscriptions().subscriptions.list()
        ]

    return await asyncio.to_thread(_do)


# ----------------------------------------------------------------------------
# Findings
# ----------------------------------------------------------------------------

async def _findings() -> list[Finding]:
    if settings().use_mock_data:
        return (
            list(mock_data.MOCK_FINDINGS)
            + list(mock_data.MOCK_PEAK_ROLLUPS)
            + list(mock_data.MOCK_RI_ROLLUPS)
        )
    base, peak, ri = await asyncio.gather(
        detectors.run_all(),
        peak_rightsizing.detect_peak_rightsizing(),
        ri_coverage.detect_ri_coverage(),
    )
    return base + peak + ri


@app.get("/api/findings", response_model=FindingsResponse)
async def get_findings() -> FindingsResponse:
    items, ctx = await asyncio.gather(_findings(), _billing_context())
    return FindingsResponse(
        findings=items,
        visibility_gap_pct=detectors.visibility_gap_pct(items),
        total_savings_monthly_usd=round(sum(f.savings_monthly_usd for f in items), 2),
        currency_code=ctx.currency_code,
        currency_glyph=ctx.glyph,
        cached_at=detectors.stamp(),
    )


@app.get("/api/findings/{finding_id}/script")
async def get_script(finding_id: str) -> Response:
    items = await _findings()
    match = next((f for f in items if f.id == finding_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="finding not found")
    try:
        body = script_builder.build(match.detector, match.resource_ids)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    filename = f"{match.detector}.sh"
    return Response(
        content=body,
        media_type="text/x-shellscript",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ----------------------------------------------------------------------------
# PR3 — Peak rightsizing detail + thresholds settings
# ----------------------------------------------------------------------------

@app.get("/api/peak-rightsizing")
async def get_peak_rightsizing() -> dict[str, object]:
    rows = await peak_rightsizing.peak_rightsizing_details()
    advisor_unsafe_n = sum(1 for r in rows if r.get("advisor_unsafe"))
    by_verdict: dict[str, int] = {}
    for r in rows:
        v = r.get("verdict", "UNKNOWN")
        by_verdict[v] = by_verdict.get(v, 0) + 1
    return {
        "rows": rows,
        "summary": {
            "total_vms": len(rows),
            "advisor_unsafe": advisor_unsafe_n,
            "by_verdict": by_verdict,
        },
        "thresholds": thresholds.to_dict(),
        "cached_at": detectors.stamp(),
    }


class ThresholdsPatch(BaseModel):
    """Subset of Thresholds fields. All optional — only sent fields are updated."""
    downsize_cpu_p95_max:       float | None = None
    downsize_mem_p95_max:       float | None = None
    downsize_cpu_p99_high_conf: float | None = None
    downsize_mem_p99_high_conf: float | None = None
    upsize_cpu_p95_min:         float | None = None
    upsize_mem_p95_min:         float | None = None
    min_data_coverage:          float | None = None


@app.get("/api/settings")
async def get_settings() -> dict[str, float]:
    return thresholds.to_dict()


@app.post("/api/settings")
async def post_settings(patch: ThresholdsPatch) -> dict[str, float]:
    fields = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    try:
        new = thresholds.update(**fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cache.invalidate("peak_rightsizing:")
    return thresholds.to_dict(new)


# ----------------------------------------------------------------------------
# PR4 — RI / SP coverage with refund-buffer guardrail
# ----------------------------------------------------------------------------

@app.get("/api/ri-coverage")
async def get_ri_coverage(buffer: float | None = None) -> dict[str, object]:
    """RI/SP coverage analysis. ``buffer`` is the operator's cancellation-
    exposure cap in tenant currency. If unset, falls back to AZSHC_REFUND_BUFFER
    env var. If still unset, returns analysis without shortlist + ``buffer_required: true``.
    """
    effective = buffer if buffer is not None else ri_coverage.env_buffer()
    return await ri_coverage.ri_coverage_details(effective)


# ----------------------------------------------------------------------------
# Cache control
# ----------------------------------------------------------------------------

@app.post("/api/cache/invalidate")
async def invalidate() -> dict[str, int]:
    return {"dropped": cache.invalidate("")}


# ----------------------------------------------------------------------------
# Static SPA — mount last so /api/* takes precedence
# ----------------------------------------------------------------------------

_FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
if _FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")
    log.info("Mounted SPA from %s", _FRONTEND)
else:
    log.warning("Frontend directory not found at %s", _FRONTEND)
