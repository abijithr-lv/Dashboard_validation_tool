# Dashboard Validation Framework

**Catch dashboard problems before analysts and stakeholders do.**

A human-approved, AI-assisted validation engine that runs before every
dashboard refresh. Claude learns what to check once; a deterministic
Databricks job carries every week.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the exact cell-by-cell execution
flow — which file calls which, in what order.

---

## How it works

```
SETUP (once)                          EVERY WEEK (deterministic)
─────────────────────                 ───────────────────────────────
Drop PDF/screenshot in onboarding/    Databricks job reads registry YAML
       ↓                                          ↓
Claude derives spec + summary .md     Recomputes metrics from source tables
       ↓                                          ↓
You review & commit YAML + summary    Compares vs dashboard → PASS/DRIFT/FAIL
  (registry/, onboarding/)                        ↓
                                      Slack report posted
                                      On FAIL → Claude explains why
```

The raw PDF/screenshot itself is never committed — see
[onboarding/](onboarding/) below.

---

## Folder structure

```
dashboard_validation_framework/
├── registry/
│   └── <dashboard_name>.yaml       # one file per dashboard (human-approved)
├── engine/
│   ├── quality_checks.py           # 5 check types (freshness, reconciliation, …)
│   ├── orchestrator.py             # reads YAML, orchestrates checks (ValidationEngine)
│   ├── report.py                   # Slack Block Kit + console output
│   ├── audit_log.py                # appends every run's results to a Delta log table
│   └── validator.ipynb             # Databricks entry point — schedule this
├── triage/
│   └── agent.py                    # calls Claude API on FAIL to explain why
├── .claude/commands/
│   └── onboard-dashboard.md        # Claude Code slash-command skill (single copy)
├── onboarding/
│   ├── onboard_dashboard.md        # step-by-step onboarding guide
│   ├── <dashboard>.pdf              # drop your dashboard export here (gitignored)
│   └── <dashboard>_validation_summary.md  # generated — commit this one
├── ARCHITECTURE.md                 # cell-by-cell execution flow diagram
└── requirements.txt
```

---

## Quick start — adding this to a new project

### 1. Copy the folder

Drop `dashboard_validation_framework/` into the root of your project repo
(most teams do this by cloning this repo into a new one they own).

### 2. Create a registry YAML for your dashboard

The easiest way is to use the Claude Code skill (see
[onboarding/onboard_dashboard.md](onboarding/onboard_dashboard.md)):
export or screenshot your dashboard, save the file into `onboarding/`, then
run `/onboard-dashboard` in Claude Code. It reads the file straight from
that folder and generates both the registry YAML and a plain-English
`onboarding/<dashboard>_validation_summary.md` for you to review before
committing.

Or copy `registry/example_dashboard.yaml` (a blank template) and edit it:

```yaml
dashboard: my_dashboard_name
dashboard_table: myschema.my_dashboard
source_table:    myschema.my_source_silver

metrics:
  - name: impressions
    tolerance_pct: 1.0
    checks: [reconciliation, trend_sanity]

dimensions:
  - name: platform
    completeness_check: true
    required_values: [LinkedIn, Instagram, Facebook]   # must appear every week
    optional_values: []                                # legitimately sporadic — absence never flagged

checks:
  freshness:    { enabled: true }
  reconciliation: { enabled: true }
  parts_sum:    { enabled: true, pivot_columns: [platform] }
  trend_sanity: { enabled: true, max_wow_change_pct: 50.0 }
  completeness: { enabled: true }
```

Commit the YAML. This is the human-approval step — the job will not run a
check that isn't in this file.

### 3. Schedule the Databricks job

Import `engine/validator.ipynb` into your Databricks workspace
(Workspace → Import → this file).

Set the **job parameters** (Databricks widgets):

| Widget | Value |
|---|---|
| `dashboard_name` | matches your YAML filename (without `.yaml`) |
| `registry_root` | absolute path to `registry/` in your Databricks Repo |
| `slack_webhook` | Slack Incoming Webhook URL (or blank to skip Slack) |
| `run_week` | blank = auto-detect from `ids_coredata.dim_date` |
| `log_table` | `catalog.schema.table` — every run's results get appended here |

Schedule it to run **before** your dashboard refresh (e.g. 06:00 UTC if
refresh is at 06:30 UTC).

`log_table` is shared across every dashboard registry — the `dashboard` column
tells them apart. It's created automatically on first write; you don't need to
run any `CREATE TABLE` DDL yourself. See `engine/audit_log.py` for the exact
schema (one row per check result: `dashboard`, `run_week`, `check_name`,
`status`, `severity`, `expected`, `actual`, `gap`, `detail`, `triage_analysis`, …).

### 4. Set up the Anthropic API key (for triage)

`triage/agent.py` reads the key from the `ANTHROPIC_API_KEY` environment
variable — no code changes needed either way. This is a **one-time, per-cluster**
setup — new dashboards you onboard later don't repeat this step.

**Default path — most users don't have secret-scope permissions.**
Creating/using a Databricks Secret scope requires an elevated entitlement most
accounts don't have. If that's you, just set the key directly on your cluster:

*(Cluster → Edit → Advanced Options → Spark → Environment variables)*
```
ANTHROPIC_API_KEY=sk-ant-...
```
Only "Can Manage" on your own cluster is required. Trade-off: the raw key is
stored in plaintext in the cluster config, visible to anyone who can view that
cluster's settings — fine for a cluster with a small, trusted set of viewers,
not for a widely-shared one.

**If a workspace admin is available — more secure, no plaintext exposure.**
Have them create the scope once and grant your team `READ` access:
```bash
databricks secrets create-scope --scope dashboard-validation
databricks secrets put --scope dashboard-validation --key anthropic-api-key
```
Then set the cluster environment variable to reference it instead of the raw key:
```
ANTHROPIC_API_KEY={{secrets/dashboard-validation/anthropic-api-key}}
```
Anyone with `READ` on the scope can use this cluster without ever seeing the
actual key value.

Restart the cluster after either change.

### 5. Run it

Trigger the job manually for the first time. You should see:

```
[validator] Registry path: .../registry/my_dashboard.yaml
[engine] Running: freshness
[engine] Running: reconciliation / impressions
...
══════════════════════════════════════════════════════════════════════
  Dashboard : my_dashboard
  Week      : 2026-23
  Result    : PASS
  Summary   : 18 PASS  ·  0 DRIFT  ·  0 FAIL
══════════════════════════════════════════════════════════════════════
```

---

## Check types

| Check | What it does | FAIL condition |
|---|---|---|
| `freshness` | Latest date in dashboard == run_week | Any mismatch |
| `reconciliation` | Dashboard SUM(metric) ≈ source SUM(metric) | Gap > tolerance_pct × 3 |
| `parts_sum` | Per-platform dashboard subtotals ≈ source subtotals | 2+ platforms out of tolerance |
| `trend_sanity` | Change vs. the `lookback_weeks`-average baseline within bounds | \|change%\| > max_wow_change_pct × 1.5 |
| `completeness` | All expected dimension values present; values absent from the last `lookback_weeks` weeks are flagged as new | 2+ expected values missing |

DRIFT = approaching but not yet at the FAIL threshold, or a new dimension
value surfaced for review. Useful for early warning.

`lookback_weeks` (registry-level, default `1`) controls both of the above:
it's the trailing window `trend_sanity` averages over and the history window
`completeness` checks before calling a value "new."

---

## YAML registry schema

Full field reference:

```yaml
dashboard:       <string>   # display name (used in Slack, logs)
description:     <string>   # optional — for documentation

dashboard_table: <schema.table>   # the Delta table the BI tool reads
source_table:    <schema.table>   # the gold/silver source to recompute from
date_column:     <column_name>    # default: fiscal_yr_and_wk_desc
date_format:     <string>         # informational only — YYYY-WW
lookback_weeks:  <int>            # default 1 — trailing weeks for trend_sanity's
                                   # baseline average and completeness's new-value window

metrics:
  - name:          <column>       # must exist in both tables
    tolerance_pct: <float>        # max acceptable gap, e.g. 1.0 = 1%
    checks:        [reconciliation, trend_sanity]

derived_metrics:                  # optional, informational only — not checked by the engine
  - name:    <column>             # a ratio/formula derived from the metrics above
    formula: <string>             # e.g. "influenced_web_visits / impressions"

dimensions:
  - name:                <column>
    completeness_check:  true|false
    required_values:     [Value1, Value2, ...]   # must appear every week — missing = DRIFT/FAIL immediately
    optional_values:     [Value3, ...]           # legitimately sporadic — absence never flagged,
                                                   # presence never reported as "new" (event-driven
                                                   # segments, seasonal campaigns, near-zero-volume slices)
    # expected_values: [...]  # legacy alias for required_values, still supported
    # a value present this week but absent from BOTH lists AND from the
    # trailing lookback_weeks weeks is reported as new/unexpected (DRIFT)

expected_changes:                   # optional — known, already-scheduled dimension shifts
  - dimension:      <column>        # (source migrations, agency handoffs, wind-downs)
    value:          <string>
    change:         appears|disappears
    effective_week: <YYYY-WW>       # once run_week reaches this, the shift stops being flagged

checks:
  freshness:      { enabled: true|false }
  reconciliation: { enabled: true|false }
  parts_sum:      { enabled: true|false, pivot_columns: [<col>, ...] }
  # one independent check per column listed — catches a mislabeling bug that
  # shifts rows between two values of a column but leaves every other
  # breakdown (and the grand total) untouched
  trend_sanity:   { enabled: true|false, max_wow_change_pct: <float> }
  completeness:   { enabled: true|false }
```

---

## Adapting `dim_date` for other projects

`validator.ipynb` resolves `run_week` using `ids_coredata.dim_date`.
If your project uses a different date dimension, change this cell:

```python
# Replace the ids_coredata.dim_date query with your own fiscal calendar
result = spark.sql("SELECT MAX(your_week_col) FROM your_schema.your_dim_date WHERE ...")
```

---

## Technologies

Python · PySpark · Databricks · YAML · Anthropic API (Claude) · Slack Webhooks
