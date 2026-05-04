# Shadow Cost — v1

Live-data Azure FinOps console. Detects shadow cost across four categories,
generates safe (dry-run-default) `az` CLI remediation scripts per finding.

## What's in here

```
v1/
├── infra/              # Bicep — App Service + MI + role assignments
│   ├── main.bicep
│   ├── role-assignments.bicep
│   └── deploy.sh       # one-shot deploy + zip-deploy helper
├── backend/
│   ├── app.py          # FastAPI entry; mounts SPA + /api/*
│   ├── config.py       # env-driven settings
│   ├── az_clients.py   # DefaultAzureCredential + SDK client factory
│   ├── cache.py        # async TTL cache (Cost Mgmt is rate-limited)
│   ├── detectors.py    # all detectors live here
│   ├── pricing.py      # coarse $/month constants per SKU
│   ├── script_builder.py   # composes bash remediation from templates
│   ├── mock_data.py    # used when USE_MOCK_DATA=true
│   ├── models.py       # Pydantic — Finding / FindingsResponse
│   ├── kql/            # one .kql per detector
│   └── templates/      # one .sh per detector + shared _header.sh
├── frontend/
│   └── index.html      # SPA (charts + findings table + script download)
├── tests/test_smoke.py
├── requirements.txt
└── .env.example
```

## Local dev (no Azure account needed)

```bash
cd v1
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # edit if you want; mock mode is on by default
USE_MOCK_DATA=true uvicorn backend.app:app --reload --port 8000
# open http://localhost:8000
```

The SPA at `/` will hit `/api/findings` and render mock data identical in
shape to live results.

## Local dev against your real Azure subscription

```bash
az login
az account set --subscription <SUB_ID>
export TARGET_SUBSCRIPTION_ID=<SUB_ID>
export USE_MOCK_DATA=false
uvicorn backend.app:app --reload --port 8000
```

`DefaultAzureCredential` will pick up your `az login` automatically. Your
identity must have `Reader` on the subscription (and `Cost Management Reader`
for any spend joining; `Reservations Reader` at the billing scope for
commitment drift).

## Deploy to Azure App Service

```bash
cd v1/infra
RG=rg-shadowcost LOCATION=eastus APP_NAME=shadowcost \
  SUB_ID=$(az account show --query id -o tsv) \
  ./deploy.sh
```

The script:

1. Creates the resource group.
2. Deploys `main.bicep` (App Service Plan B1 + App Service with system-assigned MI).
3. Deploys `role-assignments.bicep` at subscription scope, granting the MI:
   - `Reader`
   - `Cost Management Reader`
4. Zip-deploys `backend/`, `frontend/`, and `requirements.txt`.

Open the returned `https://<site>.azurewebsites.net/` URL. First request
takes ~60s while gunicorn warms up.

### Optional roles (enable advanced features)

| Role | Scope | Enables |
|---|---|---|
| Reservations Reader | Billing account | `commitment_drift` detector returns real data |
| Resource Policy Reader | Subscription | Future: surface tagging-policy compliance state |

## Smoke tests

```bash
cd v1
USE_MOCK_DATA=true python -m pytest -q tests
```

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness probe |
| GET | `/api/me` | Resolved credential class + sub ID + mock flag |
| GET | `/api/subscriptions` | List subscriptions visible to the credential |
| GET | `/api/findings` | All detectors, returns `FindingsResponse` |
| GET | `/api/findings/{id}/script` | Download bash remediation (dry-run default) |
| POST | `/api/cache/invalidate` | Drop the in-memory cache |

## Detectors

| Category | Detector | Source |
|---|---|---|
| Orphaned & idle | `unattached_disks` | ARG `Microsoft.Compute/disks` where `diskState == 'Unattached'` |
| Orphaned & idle | `unused_public_ips` | ARG, Standard SKU, `ipConfiguration` is null |
| Orphaned & idle | `empty_app_service_plans` | ARG, `numberOfSites == 0` |
| Tagging | `tagging_gap` | ARG, computes set-difference vs. `REQUIRED_TAGS` |
| Commitment | `commitment_drift` | Consumption API `reservations_summaries` |
| Data plane | `storage_overprovisioned_redundancy` | ARG, non-prod tag + GRS/GZRS SKU |
| Data plane | `long_retention_log_analytics` | ARG, retention > 90d |
| Data plane | `overprovisioned_cosmos` | ARG, multi-write or multi-region in non-prod |

Each detector returns one or more `Finding` objects following the
ROI-engine contract; the SPA groups them onto KPI cards, gauge, doughnut,
ROI quadrant, owner bar, and the findings table.

## Roadmap (v1.1)

- Join detector findings with **actual** spend from Cost Management instead
  of using `pricing.py` constants.
- AAD Easy Auth on the App Service so the SPA can be shared with finance.
- Multi-subscription scope (currently single-sub via `TARGET_SUBSCRIPTION_ID`).
- Persist detector history to Cosmos / Storage so you can chart Visibility
  Gap drift week-over-week.
- Optional Teams webhook for "Do now" findings above a $ threshold.
