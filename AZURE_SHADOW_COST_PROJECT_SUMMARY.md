# Azure Shadow Cost — Project Summary

> A self-contained handoff document. Copy-paste this into any AI chat (any model/provider) to instantly resume development with full context. No external links required to understand the project.

**Repository:** `github.com/Johhnmarshal/azure-shadow-cost` (private)
**Local path:** `C:\Users\oluwa\OneDrive\Documents\Claude\Projects\Shadow Cost Web App\v1`
**Branch:** `main` (all PRs merged) · **Status:** ✅ Roadmap complete (PR1–PR6) · **As of:** May 2026

---

## 1. Project Overview

**Azure Shadow Cost** is a FinOps web app that surfaces the cost-optimization, governance, and guardrail signals that **Azure Advisor under-prices or misses entirely**. It's built for tenants that are already "Advisor-green" but still bleed 10–30% of recoverable spend in places Advisor doesn't flag as cost recommendations.

### What it does
- Detects **shadow cost** across orphaned/idle infra, the allocation (tagging) gap, commitment drift, and data-plane waste.
- Replaces Advisor's **average-based** VM rightsizing with **peak-aware (P95/P99)** analysis and flags Advisor recommendations that would be *unsafe* at peak.
- Builds a **RI / Savings-Plan shortlist** bounded by a configurable cancellation-exposure buffer.
- Routes every finding to an **owner** and emits per-owner Markdown remediation queues.
- Ships an **audit-mode Azure Policy** starter pack + **Azure Workbook** JSON templates.
- Surfaces live **Policy Insights compliance** as Guardrails, with a Dashboard KPI and dedicated tab.

### Target users & business value
- **Primary:** FinOps analysts / cloud cost engineers on Azure.
- **Value:** turns "Advisor says we're optimized" into a prioritized, owner-attributed action list with real billed-£/$ impact — typically the next material savings tranche after Advisor is exhausted.

### Key differentiators 🔑
| Principle | Why it matters |
|---|---|
| **Read-only against Azure** | Every call is `GET` / `POST /query`. Nothing is ever deleted or modified by the app. |
| **Dry-run-safe remediation** | Generated `az` CLI scripts default to dry-run; require an explicit `--apply` to mutate. |
| **Managed-identity only** | No secrets in code. System-assigned MI needs just `Reader` + `Cost Management Reader`. |
| **Actuals, not list price** | Findings priced from Cost Management `ActualCost` (EA/MCA discounts baked in), with a flagged `estimate` fallback. |
| **Currency-aware** | Auto-detects tenant billing currency; no hard-coded `$`. |
| **Procurement-bounded commitments** | RI/SP shortlist respects an explicit cancellation-exposure buffer — no reckless defaults. |

---

## 2. Complete Feature List (mapped to PRs)

| PR | Title | Delivered |
|----|-------|-----------|
| **PR1** | Rebrand + lift root layout | Renamed to *Azure Shadow Cost*; code lifted into `webapp/`; sibling dirs `tools/ workbooks/ policies/ automation/ samples/`; `INSPIRATIONS.md` |
| **PR2** | Currency auto-detect + Cost Management actuals | `billing.py` (currency probe), `cost_actuals.py` (per-resource `/query` join); `cost_source` field (`actual`/`mixed`/`estimate`) on every finding; currency-aware SPA formatting |
| **PR3** | Peak-aware VM rightsizing + Advisor diff | `peak_rightsizing.py`; P95/P99 from Azure Monitor; deterministic decision tree; "Advisor-unsafe" headline metric; threshold settings modal; `sku_memory.py` downsize ladder |
| **PR4** | RI/SP coverage with refund-buffer guardrail | `ri_coverage.py`; family×region CV classification; greedy-pack into operator-set buffer; **no default buffer** UX; RI Coverage tab |
| **PR5** | Context enricher + Policy pack + Workbooks + automation | `enricher.py` (owner resolution + per-owner Markdown queues); `policy_pack.py` (5 audit-mode policies + zip); `workbooks.py` (3 Workbook templates); `automation/azshc-nightly.yml`; Downloads tab |
| **PR6** | Guardrails — Policy Insights via ARG + derived signals | `guardrails.py`; `kql/policy_assignments.kql` + `policy_compliance.kql`; Dashboard KPI + Guardrails tab. Shipped as **three sub-PRs**: |
| ↳ PR6a | Guardrails backend | Module + endpoints + tests + sample (no UI) |
| ↳ PR6b | Dashboard KPI card | Single KPI card calling `/api/guardrails/summary`; click-through to tab |
| ↳ PR6c | Guardrails tab | KPIs + severity/enforcement filter chips + guardrails table + violations panel |

---

## 3. Technical Architecture

### Frontend (SPA)
- **Single file:** `webapp/frontend/index.html` (vanilla JS + Chart.js via CDN, no build step).
- **Tabs:** Dashboard · Findings · Peak Rightsizing · RI Coverage · Guardrails · Downloads · About.
- Currency-aware number formatting via `Intl.NumberFormat`, fed by the auto-detected currency.
- `localStorage` persists the RI refund-buffer value across reloads.
- Served as static content by the FastAPI app (`StaticFiles` mount at `/`).

### Backend
- **Framework:** FastAPI (Python 3.11), `gunicorn` + `uvicorn` workers in production.
- **Auth to Azure:** `DefaultAzureCredential` — resolves to Managed Identity in App Service, `az login` locally.
- **Caching:** in-memory TTL cache (default 10 min) to respect Cost Management's ~5 req/min/sub throttle.

### API surface
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness probe |
| GET | `/api/me` | Resolved credential class + sub ID + mock flag |
| GET | `/api/billing` | Detected currency code + glyph |
| GET | `/api/subscriptions` | Subscriptions visible to the credential |
| GET | `/api/findings` | All detectors → `FindingsResponse` |
| GET | `/api/findings/{id}/script` | Dry-run-default bash remediation |
| GET | `/api/peak-rightsizing` | Per-VM peak detail + summary |
| GET / POST | `/api/settings` | Read / atomically update peak thresholds |
| GET | `/api/ri-coverage?buffer=N` | RI/SP coverage analysis (buffer required) |
| GET | `/api/queues` | Per-owner queue index |
| GET | `/api/queues/{owner}.md` | Per-owner Markdown queue download |
| GET | `/api/policies` · `/{slug}.json` · `/bundle.zip` | Audit-mode Policy pack |
| GET | `/api/workbooks` · `/{name}.json` | Azure Workbook templates |
| GET | `/api/guardrails` · `/violations` · `/summary` | Policy Insights + derived guardrails |
| POST | `/api/cache/invalidate` | Drop the in-memory cache |

### Azure services used
- **Azure Resource Graph (ARG)** — inventory KQL + Policy assignments/compliance (Policy Insights via ARG, no extra SDK).
- **Cost Management `/query`** — ActualCost pricing + PAYG consumption for RI analysis + currency detection.
- **Azure Monitor `metrics`** — P95/P99 CPU + memory for peak rightsizing.
- **Azure Advisor** (via ARG `AdvisorResources`) — the "Advisor-unsafe" diff.
- **Azure Policy Insights** (via ARG `policyresources` + `microsoft.policyinsights/policystates`) — guardrail compliance state.

### Data flow
```
Browser (SPA)  ──HTTP──►  FastAPI (App Service)
                              │  DefaultAzureCredential (Managed Identity)
        ┌─────────────────────┼───────────────────────────────┐
        ▼                     ▼                                ▼
 Resource Graph        Cost Management /query            Azure Monitor
 (inventory, policy)   (actuals, PAYG, currency)         (P95/P99 metrics)
```

### Mock vs Live mode
- **`USE_MOCK_DATA=true`** → deterministic fixtures from `mock_data.py`; every endpoint renders without an Azure subscription. Ideal for UI dev + tests.
- **`USE_MOCK_DATA=false`** → live Azure calls via the resolved credential.

---

## 4. Repository Structure

```
azure-shadow-cost/                 (repo root = the inner v1/ folder locally)
├── README.md                      Project intro + v0/v1 explanation
├── INSPIRATIONS.md                Credits for adapted open-source FinOps patterns
├── .gitignore
├── AZURE_SHADOW_COST_PROJECT_SUMMARY.md   ← this document
├── webapp/                        The running app
│   ├── backend/
│   │   ├── app.py                 FastAPI entry; all routes; mounts SPA
│   │   ├── config.py              Env-driven settings (Settings dataclass)
│   │   ├── az_clients.py          DefaultAzureCredential + SDK client factory
│   │   ├── cache.py               Async TTL cache
│   │   ├── models.py              Pydantic Finding / FindingsResponse
│   │   ├── detectors.py           Orphaned/idle, tagging, data-plane detectors
│   │   ├── peak_rightsizing.py    P95/P99 decision tree + Advisor diff (PR3)
│   │   ├── ri_coverage.py         CV classification + buffer pack (PR4)
│   │   ├── enricher.py            Owner resolution + per-owner queues (PR5)
│   │   ├── guardrails.py          Policy Insights + derived guardrails (PR6)
│   │   ├── billing.py             Currency auto-detect (PR2)
│   │   ├── cost_actuals.py        Cost Management ActualCost join (PR2)
│   │   ├── pricing.py             Coarse $/SKU fallback constants
│   │   ├── sku_memory.py          VM SKU → memory + downsize ladder
│   │   ├── thresholds.py          Peak-rightsizing thresholds (env + in-memory)
│   │   ├── policy_pack.py         Audit-mode Azure Policy generators (PR5)
│   │   ├── workbooks.py           Azure Workbook JSON generators (PR5)
│   │   ├── script_builder.py      Bash remediation script composer
│   │   ├── mock_data.py           Deterministic fixtures for mock mode
│   │   ├── owners_example.yaml    Reference owner-mapping YAML
│   │   ├── kql/                   8 Resource Graph queries
│   │   └── templates/             8 dry-run-default .sh remediation templates
│   ├── frontend/index.html        The SPA
│   ├── infra/                     main.bicep · role-assignments.bicep · deploy.sh
│   ├── tests/                     7 pytest files (smoke + per-module)
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md                  Local dev + deploy runbook
├── tools/                         (reserved) future stdlib CLI siblings
├── workbooks/ · policies/         READMEs (artifacts generated on demand)
├── automation/azshc-nightly.yml   GitHub Actions nightly per-owner issues
└── samples/                       Synthetic example outputs per analysis
```

---

## 5. How to Run Locally

```bash
cd webapp
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Mock mode (no Azure account)
```bash
# PowerShell
$env:USE_MOCK_DATA="true"
$env:TARGET_SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000000"
uvicorn backend.app:app --reload --port 8000
# open http://localhost:8000
```

### Live mode (your tenant)
```bash
az login
az account set --subscription <SUB_ID>
$env:USE_MOCK_DATA="false"
$env:TARGET_SUBSCRIPTION_ID="<SUB_ID>"
uvicorn backend.app:app --reload --port 8000
```
`DefaultAzureCredential` picks up your `az login`. You need `Reader` + `Cost Management Reader` on the subscription.

### Switch mock ↔ live
Flip the **`USE_MOCK_DATA`** env var (`true`/`false`) and restart uvicorn. Nothing else changes.

### Run tests
```bash
cd webapp
$env:USE_MOCK_DATA="true"
$env:TARGET_SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000000"
python -m pytest -q tests        # ~60 tests across 7 files
```

---

## 6. Deployment Guide (Azure App Service)

```bash
cd webapp/infra
# PowerShell — set inputs then run the one-shot deploy
$env:RG="rg-azshc"; $env:LOCATION="eastus"; $env:APP_NAME="azshc"
$env:SUB_ID=$(az account show --query id -o tsv)
./deploy.sh
```

The script:
1. Creates the resource group.
2. Deploys `main.bicep` — Linux App Service Plan (B1) + App Service with a **system-assigned managed identity**.
3. Deploys `role-assignments.bicep` at subscription scope, granting the MI:
   - **`Reader`**
   - **`Cost Management Reader`**
4. Zip-deploys `backend/`, `frontend/`, `requirements.txt`.

> First request takes ~60 s while gunicorn warms up. Open `https://<site>.azurewebsites.net/`.

### Required Azure permissions
| Role | Scope | Enables |
|---|---|---|
| **Reader** | Subscription | ARG inventory, Monitor metrics, Advisor, **Policy Insights (PR6)** |
| **Cost Management Reader** | Subscription | ActualCost pricing, currency detect, RI PAYG analysis |
| Reservations Reader *(optional)* | Billing account | Real RI utilization (not needed for PR4's forward-looking shortlist) |

✅ **Production-ready for read-only use** with a system-assigned managed identity and the two roles above. No secrets, no write permissions.

---

## 7. Current State & Status (May 2026)

### Complete & working
- All six PRs merged on `main` (`6104b28`).
- Every endpoint returns data in both mock and live mode.
- ~60 passing tests across 7 files.
- Deployable via Bicep; SPA renders all seven tabs.

### Known limitations
- **Single subscription** per deployment (`TARGET_SUBSCRIPTION_ID`).
- **No persistence** — each page load re-runs detectors against the cache; no historical trend store yet.
- **No per-user auth** — App Service identity is the only auth layer; add Easy Auth before sharing the URL.
- **Coarse pricing fallback** — resources with no billing row use `pricing.py` constants (flagged `estimate`).

### Branch status
- `main` — current, all PRs merged, local == origin (byte-for-byte; only CRLF/LF working-tree noise).
- Feature branches (`pr4-…`, `pr5-…`, `pr6a/b/c-…`) — merged; safe to delete.

---

## 8. Git History & PR Breakdown

```
6104b28  PR6c: Guardrails tab — KPIs + filter chips + table + violations (#9)
40e2726  PR6b: Dashboard KPI card for guardrails summary (#8)
fdef68d  PR6a: guardrails backend — Policy Insights via ARG (#7)
8dbb4ca  PR5: context enricher + per-owner queues + Policy pack + Workbook JSON
634b151  PR4: RI / Savings-Plan coverage with refund-buffer guardrail (#4)
cde4fe0  PR3: peak-aware VM rightsizing + Advisor diff + threshold settings (#3)
d71a92d  PR1: rebrand to Azure Shadow Cost; lift to webapp/ + sibling dirs
b15ea1f  fix: add missing six dep, ignore __pycache__
f9bfb5c  initial: v0 demo dashboard + v1 PoC
```
*(PR2 landed in the same window as the PR1 lift; PR5 squashed without a numbered tag.)*

---

## 9. Future Roadmap / Backlog

Prioritized, all deferred during the build:

1. **Multi-subscription scope** — fan ARG/Cost queries across a management group; `?sub=` on `/api/findings`.
2. **AAD Easy Auth** — per-user auth before sharing the URL beyond the FinOps team.
3. **SQLite persistence** — store detector runs to chart Visibility-Gap / coverage drift week-over-week.
4. **Cost Management actuals for every detector** — replace remaining `pricing.py` constants with real bill where a row exists.
5. **Power BI dataset export** — exec-friendly alternative to the in-Portal Workbooks.
6. **ServiceNow / Jira queue sinks** — alongside the GitHub Issues nightly.
7. **Slack / Teams weekly digest** — top-10 findings + week-over-week delta webhook.
8. **Existing-RI utilization detector** — the "commitment drift" view PR4 deferred (needs Reservations Reader).
9. **Per-finding stable fingerprints + label-based issue dedupe** — robust accept/defer/reject across nightly runs.
10. **Threshold + buffer persistence** — survive App Service restarts (currently in-memory).

---

## 10. Key Commands & Troubleshooting

```bash
# Start server (mock)
cd webapp; $env:USE_MOCK_DATA="true"; uvicorn backend.app:app --reload --port 8000

# Run tests
cd webapp; python -m pytest -q tests

# Quick endpoint checks
curl http://localhost:8000/api/guardrails/summary
curl "http://localhost:8000/api/ri-coverage?buffer=5000"
```

### Common issues (this environment)
| Symptom | Cause | Fix |
|---|---|---|
| `git status` shows ~70 files modified, equal +/- counts | OneDrive saves CRLF vs repo LF | `git checkout HEAD -- .` then `git config core.autocrlf true` |
| Python `unterminated string literal` at EOF | OneDrive truncated a file mid-write | Re-save the full file |
| `ModuleNotFoundError: six` | transitive dep of azure-mgmt-resourcegraph 8.0.0 | already pinned in `requirements.txt` |
| PowerShell `Missing expression after unary operator '--'` | bash-style `\` line continuation | use backticks `` ` `` or one-liners |
| Lost PR branch | deleted before merging the PR on github.com | recover via `git reflog` → `git branch <name> <sha>` |

### Branch cleanup
```powershell
git checkout main; git pull origin main
foreach ($b in "pr4-ri-coverage","pr5-enricher-policies-workbooks","pr6a-guardrails-backend","pr6b-guardrails-dashboard-kpi","pr6c-guardrails-tab") {
  git branch -d $b 2>$null; git push origin --delete $b 2>$null
}
```

---

## 11. How to Continue Development

### Best practices
- **Read-only stays sacred.** New detectors issue `GET`/`POST /query` only; remediation is always a dry-run-default script.
- **Pure functions + tests.** Keep decision logic (thresholds, classification, scoring) in pure functions; cover them in `tests/`.
- **Mock first.** Add fixtures to `mock_data.py` so the SPA renders without Azure, then wire the live path.
- **Currency-aware.** Return numeric values; let the SPA format with the detected currency.
- **One concern per PR.** Backend → endpoints → SPA, in that order, as PR6 demonstrated (6a/6b/6c).

### Recommended next steps (prioritized)
1. **AAD Easy Auth** (unblocks team sharing — highest leverage).
2. **Multi-subscription scope** (most-requested capability gap).
3. **SQLite persistence + drift charts** (turns point-in-time into trend).
4. **Power BI export** (exec audience).

### How to create the next PR
```powershell
git checkout main; git pull origin main
git checkout -b pr7-<short-slug>          # e.g. pr7-multi-subscription
# … make changes; add tests; add mock fixtures …
cd webapp; python -m pytest -q tests
git add -A
git commit -m "PR7: <imperative summary>

<bullet list of what changed and why>"
git push -u origin pr7-<short-slug>
gh pr create --title "PR7: <title>" --body "<summary>"
# Merge on github.com (Squash and merge) — then pull main + delete the branch.
```
**Conventions:** branch `pr<N>-<kebab-slug>`; commit subject `PR<N>: <imperative>`; body explains *why*; credit adapted patterns in `INSPIRATIONS.md`.

---

## ⚡ Quick Start (under 2 minutes)

```bash
git clone https://github.com/Johhnmarshal/azure-shadow-cost.git
cd azure-shadow-cost/webapp
pip install -r requirements.txt

# PowerShell
$env:USE_MOCK_DATA="true"
$env:TARGET_SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000000"
uvicorn backend.app:app --reload --port 8000
```
Open **http://localhost:8000** → you'll see all seven tabs populated with deterministic mock data (findings, peak rightsizing, RI coverage, guardrails, downloads). Flip `USE_MOCK_DATA` to `false` + `az login` to point it at a real subscription.

> **Production-ready for read-only use** with a system-assigned managed identity holding `Reader` + `Cost Management Reader`. No secrets, no write access, dry-run-default remediation.
