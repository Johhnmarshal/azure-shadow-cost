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
GET  /api/queues                      Per-owner queue index (counts + savings totals) (PR5).
GET  /api/queues/{owner}.md           Per-owner Markdown queue download (PR5).
GET  /api/policies                    List the audit-mode Azure Policy starter pack (PR5).
GET  /api/policies/{slug}.json        Download one policy JSON (PR5).
GET  /api/policies/bundle.zip         Download the whole pack zipped (PR5).
GET  /api/workbooks                   List shipping Azure Workbook templates (PR5).
GET  /api/workbooks/{name}.json       Download one workbook template (PR5).
GET  /api/guardrails                  Policy Insights + derived guardrails (PR6).
GET  /api/guardrails/violations       Warning + critical guardrails as actionable rows (PR6).
GET  /api/guardrails/summary          KPI rollup for the Dashboard tile (PR6).
POST /api/cache/invalidate            Drops the in-memory cache (auth-gate this in v1.1).

Static SPA is mounted at "/" from ../frontend.
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (
    billing,
    detectors,
    enricher,
    guardrails,
    mock_data,
    peak_rightsizing,
    policy_pack,
    ri_coverage,
    script_builder,
    thresholds,
    workbooks,
)
from .az_clients import credential, subscriptions
from .cache import cache
from .config import settings
from .models import Finding, FindingsResponse


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("azshc")

app = FastAPI(title="Azure Shadow Cost", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---- Health & identity ----------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.get("/api/me")
async def me() -> dict[str, str]:
    cred = credential()
    return {
        "credential_class": type(cred).__name__,
        "target_subscription_id": settings().target_subscription_id or "(unset)",
        "use_mock_data": str(settings().use_mock_data),
    }


# ---- Billing context (PR2) ------------------------------------------------

async def _billing_context() -> billing.BillingContext:
    if settings().use_mock_data:
        return billing.BillingContext("USD", "$", "fallback")
    return await billing.context()


@app.get("/api/billing")
async def get_billing() -> dict[str, str]:
    ctx = await _billing_context()
    return ctx.to_dict()


# ---- Subscriptions --------------------------------------------------------

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


# ---- Findings -------------------------------------------------------------

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


# ---- PR3 — Peak rightsizing detail + thresholds ---------------------------

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


# ---- PR4 — RI/SP coverage with refund-buffer guardrail --------------------

@app.get("/api/ri-coverage")
async def get_ri_coverage(buffer: float | None = None) -> dict[str, object]:
    effective = buffer if buffer is not None else ri_coverage.env_buffer()
    return await ri_coverage.ri_coverage_details(effective)


# ---- PR5 — Per-owner queues -----------------------------------------------

async def _grouped_findings() -> tuple[dict[str, list[Finding]], billing.BillingContext]:
    items, ctx = await asyncio.gather(_findings(), _billing_context())
    om = enricher.load_owner_map()
    co = enricher.load_codeowners()
    return enricher.group_by_owner(items, om, co), ctx


@app.get("/api/queues")
async def get_queues() -> dict[str, object]:
    grouped, ctx = await _grouped_findings()
    rows = [
        {
            "owner": owner,
            "count": len(items),
            "monthly_savings": round(sum(f.savings_monthly_usd for f in items), 2),
            "annualised":      round(sum(f.savings_monthly_usd for f in items) * 12, 2),
        }
        for owner, items in grouped.items()
    ]
    rows.sort(key=lambda r: -r["monthly_savings"])
    return {
        "owners": rows,
        "currency_code": ctx.currency_code,
        "currency_glyph": ctx.glyph,
        "cached_at": detectors.stamp(),
    }


@app.get("/api/queues/{owner}.md")
async def get_queue_md(owner: str) -> Response:
    grouped, ctx = await _grouped_findings()
    items = grouped.get(owner)
    if not items:
        raise HTTPException(status_code=404, detail=f"no findings for owner '{owner}'")
    body = enricher.render_queue_md(owner, items, currency_glyph=ctx.glyph)
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="azshc-{owner}.md"'},
    )


# ---- PR5 — Audit-mode Azure Policy pack ------------------------------------

@app.get("/api/policies")
async def list_policies() -> list[dict[str, str]]:
    catalogue = policy_pack.all_policies(settings().required_tags)
    return [
        {
            "slug": slug,
            "displayName": pol["properties"]["displayName"],
            "description": pol["properties"]["description"],
        }
        for slug, pol in catalogue.items()
    ]


@app.get("/api/policies/{slug}.json")
async def get_policy(slug: str) -> Response:
    catalogue = policy_pack.all_policies(settings().required_tags)
    pol = catalogue.get(slug)
    if not pol:
        raise HTTPException(status_code=404, detail=f"policy '{slug}' not found")
    return Response(
        content=_json.dumps(pol, indent=2) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{slug}.audit.json"'},
    )


@app.get("/api/policies/bundle.zip")
async def get_policy_bundle() -> Response:
    blob = policy_pack.build_bundle_zip(settings().required_tags)
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="azshc-policy-pack.zip"'},
    )


# ---- PR5 — Azure Workbook templates ---------------------------------------

@app.get("/api/workbooks")
async def list_workbooks() -> list[dict[str, str]]:
    catalogue = workbooks.all_workbooks()
    titles = {
        "hidden-waste":     "Hidden Waste & Lifecycle",
        "peak-rightsizing": "Peak-Aware Rightsizing",
        "ri-coverage":      "RI / Savings-Plan Coverage",
    }
    return [{"name": k, "displayName": titles.get(k, k)} for k in catalogue.keys()]


@app.get("/api/workbooks/{name}.json")
async def get_workbook(name: str) -> Response:
    catalogue = workbooks.all_workbooks()
    wb = catalogue.get(name)
    if not wb:
        raise HTTPException(status_code=404, detail=f"workbook '{name}' not found")
    return Response(
        content=_json.dumps(wb, indent=2) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="azshc-{name}.workbook.json"'},
    )


# ---- PR6 — Guardrails (Policy Insights + derived) -------------------------

async def _findings_with_gap() -> tuple[list[Finding], float]:
    items = await _findings()
    return items, detectors.visibility_gap_pct(items)


@app.get("/api/guardrails")
async def get_guardrails() -> list[dict]:
    items, gap = await _findings_with_gap()
    rows = await guardrails.all_guardrails(items, gap)
    return [guardrails.to_dict(g) for g in rows]


@app.get("/api/guardrails/violations")
async def get_guardrail_violations() -> list[dict]:
    items, gap = await _findings_with_gap()
    rows = await guardrails.violations(items, gap)
    return [guardrails.to_dict(v) for v in rows]


@app.get("/api/guardrails/summary")
async def get_guardrail_summary() -> dict:
    items, gap = await _findings_with_gap()
    s = await guardrails.summary(items, gap)
    return guardrails.to_dict(s)


# ---- Cache control --------------------------------------------------------

@app.post("/api/cache/invalidate")
async def invalidate() -> dict[str, int]:
    return {"dropped": cache.invalidate("")}


# ---- Static SPA — mount last so /api/* takes precedence -------------------

_FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
if _FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")
    log.info("Mounted SPA from %s", _FRONTEND)
else:
    log.warning("Frontend directory not found at %s", _FRONTEND)
