# Onboarding a New Dashboard

Follow these steps to add a new dashboard to the validation framework.
Time estimate: 30–60 minutes for a well-understood dashboard.

---

## Step 1 — Gather facts about the dashboard

Before writing any YAML, answer these questions:

| Question | Where to find the answer |
|---|---|
| What is the dashboard table name? | Databricks catalog / Power BI data source settings |
| What is the source (silver/gold) table it reads from? | Pipeline code / ETL job config |
| What is the date column name? | `DESCRIBE TABLE <dashboard_table>` |
| What numeric metrics does the dashboard show? | Power BI field list / pipeline config |
| What dimensions does it break down by? | Power BI slicers / pivot axes |
| What platforms / segments are always expected? | Business stakeholder or past dashboard screenshots |

---

## Step 2 — Use the Claude Code skill (recommended)

Export or screenshot the dashboard (PDF export is best — it captures every
page including the glossary) and save the file into this `onboarding/`
folder, next to this guide. It's gitignored, so it won't get committed —
it's only there for Claude to read during this session.

If you're working in this repo, `.claude/commands/onboard-dashboard.md` is
already active — nothing to copy. In a Claude Code session:

```
/onboard-dashboard
```

Claude will confirm the file it found in `onboarding/`, read it, and guide
you through generating:
- `registry/<dashboard_name>.yaml` — the check config
- `onboarding/<dashboard_name>_validation_summary.md` — a plain-English
  summary of what's being checked, for a reviewer who won't read the YAML

Review both before saving. Once saved, commit those two files — leave the
raw PDF/screenshot uncommitted (see `.gitignore`).

If you copied only `engine/`, `triage/`, and `registry/` into a *different*
project, copy the skill file into that project's `.claude/commands/` instead:
```bash
cp dashboard_validation_framework/.claude/commands/onboard-dashboard.md \
   <your-project>/.claude/commands/onboard-dashboard.md
```

---

## Step 3 — Write the YAML manually (alternative)

Copy the blank template:

```bash
cp dashboard_validation_framework/registry/example_dashboard.yaml \
   dashboard_validation_framework/registry/<your_dashboard_name>.yaml
```

Edit the file. Minimum required fields:

```yaml
dashboard:       <your_dashboard_name>
dashboard_table: <schema>.<table>
source_table:    <schema>.<source_table>
date_column:     <date_column>

metrics:
  - name:          <metric_column>
    tolerance_pct: 1.0
    checks: [reconciliation, trend_sanity]

checks:
  freshness:    { enabled: true }
  reconciliation: { enabled: true }
```

---

## Step 4 — Verify the SQL manually

Before the job runs, test each metric's reconciliation manually in a
Databricks notebook:

```sql
-- Expected (source)
SELECT SUM(impressions)
FROM <source_table>
WHERE <date_column> = '2026-23'
  AND (data_type != 'Budget' OR data_type IS NULL);

-- Actual (dashboard)
SELECT SUM(impressions)
FROM <dashboard_table>
WHERE <date_column> = '2026-23'
  AND (data_type != 'Budget' OR data_type IS NULL);
```

If the numbers match (within your tolerance), the reconciliation check
will PASS. If they don't match, investigate the pipeline before enabling
the check — false positives from a misunderstood data model are worse
than no validation.

---

## Step 5 — Commit the YAML and the validation summary

```bash
git add dashboard_validation_framework/registry/<your_dashboard_name>.yaml
git add dashboard_validation_framework/onboarding/<your_dashboard_name>_validation_summary.md
git commit -m "Add validation registry for <your_dashboard_name>"
```

Do not add the raw PDF/screenshot — it's gitignored on purpose.

This is the **human-approval step**. Once committed, the job will run
these checks automatically every week.

---

## Step 6 — Schedule the Databricks job

1. Open `engine/validator.ipynb` in your Databricks workspace
   (Workspace → Import, or sync via Databricks Repos)

2. Create a new **Job** pointing to this notebook

3. Set the widget parameters:

   | Widget | Value |
   |---|---|
   | `dashboard_name` | your YAML filename without `.yaml` |
   | `registry_root` | absolute path to `registry/` in the repo |
   | `slack_webhook` | your Slack Incoming Webhook URL |
   | `run_week` | leave blank (auto-detect) |

4. Set the **schedule** to run before the dashboard refresh
   (e.g. 30 minutes before the pipeline writes to the dashboard table)

5. Run it once manually to confirm it works

---

## Step 7 — Add the Slack webhook

1. Go to your Slack workspace → Apps → Incoming Webhooks
2. Create a new webhook for the channel where alerts should go
3. Add the URL to the `slack_webhook` widget (or store it in a Databricks
   Secret and reference it in the notebook)

---

## Adjusting tolerances

Start with `tolerance_pct: 1.0` (1%) for all metrics.
After a few weeks of PASS results, tighten it if you want more sensitivity.
After DRIFT alerts that turned out to be false positives, loosen it.

The `max_wow_change_pct` for trend sanity defaults to 50%. For stable
metrics like spend, tighten it to 20–30%. For volatile metrics like
video_views, 50% or higher is reasonable.

---

## Lookback window (trend smoothing + new-value detection)

`lookback_weeks` (top-level YAML field, default `1`) controls two things:

- `trend_sanity` compares the current week against the *average* of the
  trailing `lookback_weeks` weeks instead of just the single prior week —
  useful if one week is naturally noisy and you don't want it to become
  next week's misleading baseline.
- `completeness` only flags a dimension value as new/unexpected if it's
  absent from `expected_values` **and** from all of the trailing
  `lookback_weeks` weeks. This surfaces genuinely new values (new creative,
  new platform) as DRIFT for review, without flagging values that just
  rotate in and out week to week.

```yaml
lookback_weeks: 4
```

Set it to `1` to fall back to plain week-over-week comparison with no
new-value detection window.

---

## Removing a check

To disable a check without deleting it:

```yaml
checks:
  trend_sanity: { enabled: false }
```

Commit the change. The job picks it up on the next run.
