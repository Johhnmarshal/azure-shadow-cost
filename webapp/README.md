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
  individually authenticated yet. Add Easy Auth before sharing the URL
  beyond the FinOps team.

## Contributing

Issues and PRs welcome. The webapp deliberately avoids heavyweight Python
dependencies; please justify any new requirement in `webapp/requirements.txt`.

## License

MIT.
