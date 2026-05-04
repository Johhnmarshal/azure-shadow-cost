"""FastAPI entry point for Shadow Cost v1.

Endpoints
---------
GET  /api/health                      Liveness probe.
GET  /api/me                          Returns the resolved identity (MI / SP / az login).
GET  /api/subscriptions               Lists subscriptions visible to the credential.
GET  /api/findings                    Runs all detectors, returns FindingsResponse.
GET  /api/findings/{id}/script        Returns the generated bash remediation as text/plain.
POST /api/cache/invalidate            Drops the in-memory cache (auth-gate this in v1.1).

Static SPA is mounted at "/" from ../frontend.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import detectors, mock_data, script_builder
from .az_clients import credential, subscriptions
from .cache import cache
from .config import settings
from .models import Finding, FindingsResponse


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("shadowcost")

app = FastAPI(title="Shadow Cost", version="1.0.0")

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
# Subscriptions
# ----------------------------------------------------------------------------

@app.get("/api/subscriptions")
async def list_subscriptions() -> list[dict[str, str]]:
    if settings().use_mock_data:
        return [{"subscriptionId": "00000000-0000-0000-0000-000000000000", "displayName": "Mock Subscription"}]
    import asyncio

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
        return list(mock_data.MOCK_FINDINGS)
    return await detectors.run_all()


@app.get("/api/findings", response_model=FindingsResponse)
async def get_findings() -> FindingsResponse:
    items = await _findings()
    return FindingsResponse(
        findings=items,
        visibility_gap_pct=detectors.visibility_gap_pct(items),
        total_savings_monthly_usd=round(sum(f.savings_monthly_usd for f in items), 2),
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
