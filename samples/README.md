# samples/

Synthetic example outputs of every analysis the web app produces. Resource
IDs, owners, and numbers are illustrative only — none represent any real
environment.

| Path | Description | Source |
|---|---|---|
| [`findings.json`](findings.json) | Sample `/api/findings` response (currency_code, cost_source, etc.) | PR2 ✅ |
| [`peak-rightsizing/peak-rightsizing-combined.md`](peak-rightsizing/peak-rightsizing-combined.md) | Combined per-VM rightsizing report with Advisor-unsafe diff | PR3 ✅ |
| [`peak-rightsizing/sample.csv`](peak-rightsizing/sample.csv) | Per-VM CSV — verdict, confidence, advisor_unsafe, proposed SKU | PR3 ✅ |
| `ri-coverage/` | Coverage gap map + risk-scored shortlist | PR4 (planned) |
| `queues/` | Per-owner Markdown remediation queues | PR5 (planned) |
| `policies/` | Audit-mode Azure Policy JSON bundle | PR5 (planned) |
| `workbooks/` | Azure Workbook JSON exports | PR5 (planned) |

Use these to evaluate the report shape before pointing the app at your
own tenant. Reproduce them locally with:

```bash
cd webapp
USE_MOCK_DATA=true uvicorn backend.app:app --port 8000
# then GET /api/findings, /api/peak-rightsizing, etc.
```
