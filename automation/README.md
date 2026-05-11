# automation/

GitHub Actions workflow to run Azure Shadow Cost analyses on a schedule and
post per-owner queues as tracker issues.

| File | Purpose |
|---|---|
| [`azshc-nightly.yml`](azshc-nightly.yml) | 05:00 UTC nightly. Calls the deployed web app's `/api/queues`, then opens or edits one issue per owner with the per-owner Markdown queue body. Label-based dedupe so re-runs edit in place. |

## Setup

1. Deploy the web app (`webapp/infra/deploy.sh`) and note the Azure App
   Service hostname.
2. Add a repo secret **`AZSHC_BASE_URL`** pointing to it
   (e.g., `https://azshc-abc123.azurewebsites.net`).
3. *(Optional but recommended for prod.)* Enable AAD Easy Auth on the App
   Service and provide a token via repo secret **`AZSHC_TOKEN`** so the
   workflow can authenticate.
4. Move `azshc-nightly.yml` into `.github/workflows/` of whichever repo will
   host the issues — keeping it under `automation/` here means it ships
   with the source but doesn't trigger on this repo. (Symlink or copy as
   appropriate for your fork-vs-main strategy.)

## What it does

- For every owner returned by `/api/queues`, downloads the per-owner
  Markdown (`/api/queues/{owner}.md`) and creates or edits a tracker issue
  labelled `azshc:owner=<owner>`. The Markdown contains
  accept / defer / reject checkboxes per finding so engineers can act in
  place; tomorrow's run picks up new findings without disturbing
  yesterday's resolution choices.
- Skips owners with zero findings.
- Honours `workflow_dispatch` so you can run it on demand from the Actions
  tab during a FinOps session.

## Out of scope (deliberately)

- **Auto-remediation.** The workflow is read-only against Azure; it only
  writes tracker issues. To execute the bash scripts the web app generates,
  set up a separate workflow with appropriate Azure RBAC — that decision
  is left to operators because it's tenant-policy-bound.
- **Slack / Teams notification.** Hooks for these are PR-after-5; the
  GitHub Issues sink is the v0 supported delivery.
