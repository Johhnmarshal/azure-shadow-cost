# Inspirations

Azure Shadow Cost is built independently. It is **not** a fork of, nor a
runtime dependency on, any other FinOps tool. We reimplement every
analysis from first principles inside the webapp's FastAPI backend.

That said, the FinOps practitioner community has converged on a few
patterns that are demonstrably better than what each cloud's native
tooling ships, and we've borrowed those ideas where they're sound.
This file names them — both as good engineering hygiene, and so that
when a reader wonders "have you considered…?" the answer is yes,
deliberately, and here's why.

## Patterns we've adapted

### 1. Peak-aware rightsizing (P95 / P99 vs. average)

**Problem with the native approach.** Azure Advisor's "Cost — Resize
Virtual Machine" recommendation is derived from *average* CPU over its
observation window. For a steady-state workload that's fine. For
batch / retail / CI workloads that idle 90% of the day and saturate at
peak, the average is structurally low while the peak is at 100% —
Advisor will recommend a downsize that causes a pager event.

**The community pattern.** Decide on **percentile** metrics (P95 or
P99) rather than averages, and *diff* the result against Advisor's
recommendation list. The headline number is "Advisor recs that would
have been unsafe at P95" — surface that explicitly.

**Where it lands.** PR3 (`webapp/backend/peak_rightsizing.py`).

### 2. Hidden-waste detection priced from actual bill

**Problem with the native approach.** Native portal views and even most
SaaS FinOps tools rely on list price for pricing waste findings. List
price ignores Enterprise Agreement / MCA discounts, regional pricing,
Hybrid Benefit, and dev/test rates — the actual £ of the finding can be
30–60% off.

**The community pattern.** Join the inventory of orphaned / idle
resources to **Cost Management `/query` ActualCost** keyed by resource
ID. Fall back to list price *only* when no billing record exists (e.g.
never-attached ASR replica disks), and tag those rows `cost_source:
estimate` so reviewers can sort them last.

**Where it lands.** PR2 (`webapp/backend/cost_actuals.py`).

### 3. RI / Savings-Plan shortlist bounded by a cancellation-exposure buffer

**Problem with the native approach.** The portal *Reservations →
Recommendations* view shows you the top single-SKU savings opportunity.
It does not stack-rank across SKUs by *risk*, and it doesn't account
for the cancellation fee you'd pay if forecast turns out worse than
expected. So procurement has no defensible cap.

**The community pattern.** Aggregate by family × region (the natural
commitment unit), score each group's stability via month-over-month
coefficient of variation, pick a product per group (RI 1Y for stable,
Compute SP 1Y for variable), then **greedy-pack the highest-savings
LOW-risk picks into a configurable cancellation-exposure buffer** in
the operator's billing currency. The binding constraint becomes the
buffer, which is a procurement decision, not a forecast.

**Where it lands.** PR4 (`webapp/backend/ri_coverage.py`).

### 4. Per-owner remediation queues with HIGH/MED/LOW confidence

**Problem with the native approach.** A flat list of findings doesn't
get acted on. Every domain owner needs *their* findings, with a
clear-enough rationale that an engineer who didn't run the analysis
trusts the result.

**The community pattern.** Resolve owner per finding (Tag → YAML →
CODEOWNERS), score each finding HIGH / MED / LOW based on the
detector's signal strength, and emit a per-owner Markdown queue with
`accept` / `defer` / `reject` checkboxes. Open one tracker issue per
owner, edit it in place across runs.

**Where it lands.** PR5 (`webapp/backend/enricher.py`).

### 5. Audit-then-deny Azure Policy promotion

**Problem with the native approach.** Cleanup scripts only treat the
symptom. The next untagged disk, the next idle public IP, the next
unattached NIC will be created by the same automation tomorrow.

**The community pattern.** For each top-N waste category by £, ship an
**audit-mode** Azure Policy. Run it for 30 days against a pilot
management group. If the false-positive rate is acceptable, promote
the assignment to `deny`. The policy now prevents the waste from
recurring.

**Where it lands.** PR5 (`webapp/backend/policies.py` +
`policies/` JSON definitions).

### 6. Currency auto-detect via `az billing account list`

**Problem with the native approach.** Most FinOps tools either hard-
code USD or hard-code the maintainer's local currency. Operators on a
different billing currency search-replace the symbol in source.

**The community pattern.** Read the tenant's billing currency once at
startup, parameterise the displayed glyph and the buffer flag. The
numeric values are already in the billing currency — auto-detect just
stops the label lying.

**Where it lands.** PR2 (`webapp/backend/billing.py`).

## What we did *not* adopt

A few patterns are common in the community but didn't fit our shape:

- **CLI-only delivery.** Some open-source FinOps engines are stdlib-only
  Python scripts that emit Markdown / CSV. We chose web-app-first because
  an interactive console serves an Azure-UK FinOps function better than
  a directory of CSVs. The `tools/` directory is a deliberate hook for
  if/when CLI siblings are wanted.
- **GitHub Issues as the primary tracker.** We support it (PR5's
  `automation/azshc-nightly.yml`), but the SPA is the canonical surface.
  Issues are an output, not the input.
- **Auto-remediation.** Some tools ship a "delete the orphan" flag.
  We don't, and won't. Every remediation is a human decision in this
  app, regardless of category.

## Licensing

Every borrowed pattern above is independently reimplemented in this
repo's source. No third-party source is copied or vendored. Where
external snippets or specific phrasing are quoted in inline comments,
they are attributed in place.

If you spot an inspiration we should credit but haven't, please open an
issue.
