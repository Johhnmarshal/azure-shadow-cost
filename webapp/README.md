# Azure Shadow Cost

> **The shadow-cost surface Azure Advisor doesn't price.** A FinOps web app
> for an Advisor-green Azure tenant — surfaces the allocation gap,
> commitment drift, data-plane waste, peak-aware rightsizing risk, and
> per-owner remediation queues that a senior FinOps practitioner would find
> by hand.

Azure Shadow Cost is a single web app (FastAPI + SPA, deployed to Azure
App Service with a system-assigned Managed Identity) that pulls live data
from Resource Graph, Cost Management, Reservations and Azure Monitor,
detects waste across the categories Advisor under-prices, and emits
**dry-run-default** `az` CLI remediation scripts that humans review and
apply.

## Why it exists

If your tenant is "Advisor-green," the next 10–30% of recoverable spend
is hiding in places Advisor doesn't surface as cost recommendations:

- **Allocation gap** — resources missing required tags. You can't allocate
  what you can't attribute.
- **Commitment drift** — Reservations / Savings Plans you bought that are
  now under-utilized because workloads moved.
- **Data-plane waste** — storage on GZRS where LRS would do; Log Analytics
  retention set to 730 days by default; Cosmos with multi-region writes in
  non-prod.
- **Peak-aware rightsizing risk** — Advisor's average-based downsize logic
  is unsafe for spiky / batch / retail workloads. P95 and P99 catch the
  peak that justifies the current SKU.
- **PaaS sprawl** — empty App Service Plans, idle Log Analytics workspaces,
  dormant API Management.

## Repo layout

```
azure-shadow-cost/
├── webapp/                 # FastAPI backend + SPA frontend (the running app)
│   ├── backend/
│   ├── frontend/
│   ├── infra/              # Bicep — App Service + MI + role assignments
│   ├── tests/
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md           # local dev + deploy guide
├── tools/                  # (PR2+) optional sibling CLI scripts
├── workbooks/              # (PR5) Azure Workbook JSON outputs
├── policies/               # (PR5) audit-mode Azure Policy starter pack
├── automation/             # (PR5) GitHub Actions for nightly runs
├── samples/                # synthetic example outputs
├── INSPIRATIONS.md         # open-source patterns we've adapted
├── .gitignore
└── README.md               (this file)
```

## Quick start (local, no Azure needed)

```bash
cd webapp
pip install -r requirements.txt
USE_MOCK_DATA=true uvicorn backend.app:app --reload --port 8000
# open http://localhost:8000
```

Mock mode serves a deterministic findings dataset shaped identically to
live results, so the SPA renders without an Azure subscription.

## Quick start (against your tenant)

```bash
az login
az account set --subscription <SUB_ID>

cd webapp
export TARGET_SUBSCRIPTION_ID=<SUB_ID>
pip install -r requirements.txt
uvicorn backend.app:app --reload --port 8000
```

`DefaultAzureCredential` picks up your `az login`. Your identity needs
`Reader` and `Cost Management Reader` at the subscription scope. See
[`webapp/README.md`](webapp/README.md) for the full role matrix and
deploy-to-App-Service runbook.

## Roadmap (the five PRs)

This repo is built in five tightly-scoped pull requests. PR1 lands the
rebrand and the layout you're reading now. The next four ship the
analyses that close the gap with a manual senior FinOps review.

| # | Title | Headline output |
|---|---|---|
| **PR1** ✅ | Rename + lift root layout | `webapp/` + empty top-level dirs |
| **PR2** | Currency auto-detect + Cost Management actuals join | Every finding priced from real billed amounts (with `cost_source: actual` vs. `estimate` flag) |
| **PR3** | Peak-aware VM rightsizing detector + Advisor diff | "Advisor recommended this downsize but P95 says it's unsafe" — the metric that pays for the engine |
| **PR4** | RI / Savings-Plan coverage with refund-buffer guardrail | Risk-scored shortlist that fits inside *your* cancellation-exposure buffer |
| **PR5** | Context enricher + audit-mode Policy pack + Workbook JSON | Per-owner Markdown queues; downloadable Policy + Workbook starter packs |

PR-by-PR design notes are in each PR's commit message. The patterns we're
adapting from the broader open-source FinOps community are credited in
[`INSPIRATIONS.md`](INSPIRATIONS.md).

## Operating principles

These are the constraints the engine is designed around. They're worth
naming explicitly because they shape every PR:

1. **Read-only against Azure.** Every detector issues `GET` and
   `POST /query` calls. Nothing in this repo will delete, retag, or
   modify a live resource. Remediation is always a human decision,
   gated by the dry-run-default bash scripts the app emits.
2. **Web-app first, CLI optional.** The interactive UI is the primary
   surface. The `tools/` directory is a deliberate hook for future
   stdlib-only CLI siblings, not the main path.
3. **Live data, cached aggressively.** Cost Management is throttled
   to ~5 req/min/sub; ARG has its own quotas. The in-memory TTL cache
   defaults to 10 min. This is enough for a single-tenant app; multi-
   instance deployments would need Redis.
4. **Defaults are conservative.** Peak-rightsizing thresholds, the
   refund-buffer requirement (no default — explicit only), and the
   audit-then-deny Policy promotion pattern all err on the side of
   *not* shipping a wrong recommendation.

## Status & limitations

- **Single subscription per deployment.** Multi-sub support is on the
  PR5 follow-up backlog. `TARGET_SUBSCRIPTION_ID` is the current toggle.
- **No persistence yet.** Every page load re-runs the detectors against
  the cache. PR-after-5 adds a small SQLite store for trend / drift.
- **Auth is at the App Service identity layer.** Web users are not
  individually authenticated yet. Add Easy Auth before sharing externally.

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness probe |
| GET | `/api/me` | Resolved credential class + sub ID + mock flag |
| GET | `/api/billing` | Detected tenant currency code + glyph (PR2) |
| GET | `/api/subscriptions` | Subscriptions visible to the credential |
| GET | `/api/findings` | All detectors; `FindingsResponse` (incl. `currency_code` + per-finding `cost_source`) |
| GET | `/api/findings/{id}/script` | Bash remediation (dry-run default) |
| GET | `/api/peak-rightsizing` | Per-VM peak detail + summary (PR3) |
| GET | `/api/settings` | Current peak-rightsizing thresholds (PR3) |
| POST | `/api/settings` | Atomic threshold update (PR3) |
| GET | `/api/ri-coverage` | RI/SP coverage analysis with optional `?buffer` (PR4) |
| GET | `/api/queues` | Per-owner queue index — counts + savings totals (PR5) |
| GET | `/api/queues/{owner}.md` | Per-owner Markdown queue download (PR5) |
| GET | `/api/policies` | Catalogue of audit-mode Policy starter pack (PR5) |
| GET | `/api/policies/{slug}.json` | Single policy JSON download (PR5) |
| GET | `/api/policies/bundle.zip` | All policies + README in a zip (PR5) |
| GET | `/api/workbooks` | Catalogue of Azure Workbook templates (PR5) |
| GET | `/api/workbooks/{name}.json` | Single Workbook JSON download (PR5) |
| GET | `/api/guardrails` | Policy Insights + derived FinOps guardrails (PR6) |
| GET | `/api/guardrails/violations` | Warning + critical guardrails as actionable rows (PR6) |
| GET | `/api/guardrails/summary` | KPI rollup — total / enforced / healthy / warning / critical / violations (PR6) |
| POST | `/api/cache/invalidate` | Drop the in-memory cache |

## Owner attribution (PR5)

Findings route to a single owner via three-tier precedence:
**Azure Tag → YAML override (`AZSHC_OWNERS_YAML`) → CODEOWNERS (`AZSHC_CODEOWNERS`)**.
Resources that match nothing land in the `needs-attribution` queue —
that's by design; it's the FinOps team's signal that tagging is broken
in some corner of the tenant.

A reference YAML mapping ships at
[`backend/owners_example.yaml`](backend/owners_example.yaml). Copy to
`backend/owners.yaml` (or any path) and point `AZSHC_OWNERS_YAML` at it.

## Peak rightsizing (PR3)

Detectors `peak_advisor_unsafe`, `peak_downsize`, `peak_upsize` pull P95/P99
of `Percentage CPU` and `Available Memory Bytes` from Azure Monitor over
the last 30 days, apply a deterministic decision tree, and diff against
Azure Advisor's "Cost — Resize VM" recommendations. The headline metric is
*Advisor recs that would have been unsafe at P95* — see
[`samples/peak-rightsizing/peak-rightsizing-combined.md`](samples/peak-rightsizing/peak-rightsizing-combined.md)
for the report shape.

Excluded by design: `databricks-rg-*`, `MC_*`/`mc_*` resource groups,
VMs whose name starts with `aks-`. These are managed by their parent
service.

Thresholds default to the **Conservative** profile (40 / 50 / 80) and are
overridable per-run via the SPA's gear icon (saves to in-memory state) or
via `AZSHC_T_*` env vars on the App Service. See `webapp/.env.example`.

The downsize ladder + SKU memory map live in `webapp/backend/sku_memory.py`
— extend that module when your tenant uses VM families we don't list yet.

## Local dev (no Azure account)

```bash
cd webapp
pip install -r requirements.txt
USE_MOCK_DATA=true uvicorn backend.app:app --reload --port 8000
# open http://localhost:8000
```

Mock mode serves a deterministic dataset shaped identically to live results,
so the SPA renders without an Azure subscription.

## Tests

```bash
cd webapp
USE_MOCK_DATA=true python -m pytest -q tests
```