# tools/

Reserved. Currently empty.

This directory exists to host stdlib-only Python sibling scripts in a future
release — for operators who want to run individual analyses from CI / cron /
GitHub Actions without standing up the FastAPI web app.

**Architectural decision (PR1).** Azure Shadow Cost is *web-app-first*. The
analyses live behind `/api/*` endpoints in `webapp/backend/`. This directory
is a deliberate empty hook so that pulling individual analyses out into CLI
form later doesn't require restructuring the repo.
