# automation/

GitHub Actions workflow(s) to run Azure Shadow Cost analyses on a schedule
and post results into a tracking system (GitHub Issues / Teams / Slack).

**Status:** populated by **PR5**.

Planned:

| File | Purpose |
|---|---|
| `azshc-nightly.yml` | 05:00 UTC nightly run; calls the webapp's `/api/findings` and `/api/queues/{owner}.md`; opens or updates one GitHub Issue per owner. |

The workflow assumes the web app is reachable at a known URL (App Service or
Container App) with AAD auth disabled or a service-account token configured.
The `gh` step uses `GITHUB_TOKEN` from the workflow's default scope.
