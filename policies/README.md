# policies/

Audit-mode Azure Policy starter pack — one definition per shadow-cost
category that has a meaningful preventative control.

**Status:** populated by **PR5**.

Planned definitions (all ship in `audit` effect):

| File | Targets |
|---|---|
| `deny-untagged-resources.json` | Resources missing required allocation tags |
| `deny-create-unattached-disks.json` | Managed-disk creation without an attached owner |
| `deny-create-standard-public-ip-unassociated.json` | Standard public IPs without ipConfiguration |
| `restrict-storage-redundancy-nonprod.json` | GRS / GZRS in environments tagged non-prod |
| `cap-log-analytics-retention.json` | LA workspaces with retention > 90 days |

**Adoption pattern:**

1. Download the bundle from the web app.
2. Assign in `audit` mode at a pilot management-group scope.
3. Watch compliance state for 30 days; remediate false positives.
4. Promote to `deny` by changing `parameters.effect` in the assignment.

The web app generates these on demand — they are not committed pre-built.
