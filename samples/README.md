# samples/

Synthetic example outputs of every analysis the web app produces. None of
the resource IDs, subscription names, owner identities, or numbers represent
a real environment.

**Status:** populated by **PR2-5**, one set of samples per analysis.

Planned subdirectories:

| Path | Source PR |
|---|---|
| `samples/findings.json` | PR2 — sample `/api/findings` response (deterministic mock data) |
| `samples/peak-rightsizing/` | PR3 — sample VM rightsizing CSV + Markdown |
| `samples/ri-coverage/` | PR4 — sample shortlist + buffer-exposure ledger |
| `samples/queues/` | PR5 — sample per-owner Markdown queues |
| `samples/policies/` | PR5 — sample Azure Policy JSON bundle |
| `samples/workbooks/` | PR5 — sample Azure Workbook JSON |

Use these to evaluate the report shape before pointing the app at your own
tenant.
