# samples/

Synthetic example outputs of every analysis the web app produces. Resource
IDs, owners, and numbers are illustrative only — none represent any real
environment.

| Path | Description | Source |
|---|---|---|
| [`findings.json`](findings.json) | Sample `/api/findings` response (currency_code, cost_source, etc.) | PR2 |
| [`peak-rightsizing/peak-rightsizing-combined.md`](peak-rightsizing/peak-rightsizing-combined.md) | Combined per-VM rightsizing report with Advisor-unsafe diff | PR3 |
| [`peak-rightsizing/sample.csv`](peak-rightsizing/sample.csv) | Per-VM CSV — verdict, confidence, advisor_unsafe, proposed SKU | PR3 |
| [`ri-coverage/ri-shortlist.md`](ri-coverage/ri-shortlist.md) | RI/SP risk-scored shortlist within a 5,000 buffer | PR4 |
| [`ri-coverage/ri-coverage.csv`](ri-coverage/ri-coverage.csv) | Per-group CSV — stability, CV, savings, exposure | PR4 |
| [`queues/contoso-app-team.md`](queues/contoso-app-team.md) | Per-owner remediation queue with accept/defer/reject checkboxes | PR5 |
| [`policies/deny-untagged-resources.audit.json`](policies/deny-untagged-resources.audit.json) | Sample audit-mode Azure Policy JSON | PR5 |
| [`workbooks/azshc-hidden-waste.json`](workbooks/azshc-hidden-waste.json) | Sample Azure Workbook template (Hidden Waste) | PR5 |

Use these to evaluate the report shape before pointing the app at your own
tenant. Reproduce them locally with:

```bash
cd webapp
USE_MOCK_DATA=true uvicorn backend.app:app --port 8000
# then GET /api/findings, /api/peak-rightsizing, /api/ri-coverage,
# /api/queues, /api/policies, /api/workbooks, etc.
```
