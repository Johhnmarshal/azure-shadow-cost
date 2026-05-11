# policies/

Audit-mode Azure Policy starter pack — five preventative controls that
complement the Azure Shadow Cost detectors.

The web app **generates** these on demand (so the policies stay in sync
with `REQUIRED_TAGS` and other configurable inputs); ready-made copies
for browsing and the bundle live under [`samples/policies/`](../samples/policies/).

## Pack contents

All five ship in **`audit`** effect. Promote to `deny` by changing the
assignment's `effect` parameter.

| Slug | Targets |
|---|---|
| `deny-untagged-resources` | Resources missing required allocation tags (`Owner`, `CostCenter`, `Environment`, `Application` by default). |
| `deny-unattached-disks` | Managed disks left in `Unattached` state. |
| `deny-unassigned-public-ip-standard` | Standard SKU public IPs without `ipConfiguration`. |
| `restrict-storage-redundancy-nonprod` | GRS / GZRS / RA-GZRS storage accounts in non-prod environments. |
| `cap-log-analytics-retention` | Log Analytics workspaces with `retentionInDays > 90`. |

## Adoption pattern

1. Run the engine. Pick the top 3 categories by recoverable £/$.
2. Assign the matching policy in **audit** mode at a pilot management
   group for 30 days.
3. Review compliance state — false-positive rate should approach zero.
4. Promote to `deny`.

## Download

From the running web app: open the **Downloads** tab → **Audit-mode Azure
Policy starter pack** → click **Download all (.zip)** for the bundle, or
**JSON** on each row for a single policy.

API surface:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/policies` | Catalogue of slugs + display names |
| GET | `/api/policies/{slug}.json` | One policy JSON |
| GET | `/api/policies/bundle.zip` | All five + a README, zipped |

## Caveats

`deny-unattached-disks` cannot enforce a "> N days" age window — Policy
evaluates `diskState` at write time only. Pair with a Workbook KQL filter
on `properties.timeCreated` to surface long-stale disks separately.
