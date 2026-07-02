# Dashboard Validation Framework

This folder is a self-contained tool that validates Power BI / Databricks dashboards
automatically before every refresh. It catches data quality issues before stakeholders see them.

## What this tool does

1. A YAML file (registry/) defines what to check for a dashboard — metrics, dimensions, tolerances.
2. A Databricks job (engine/validator.ipynb) reads the YAML and runs SQL checks every week.
3. Results are posted to Slack: PASS = quiet green line, FAIL = full breakdown.
4. On FAIL, Claude Haiku explains the root cause via the Anthropic API.
5. Every run — PASS, DRIFT, or FAIL — is appended to a Delta audit-log table
   (`engine/audit_log.py`, one row per check result) for trend analysis and audit.

See `ARCHITECTURE.md` for the exact cell-by-cell execution flow.

## Folder structure

```
dashboard_validation_framework/
├── registry/          ← one YAML file per dashboard (human-approved config)
├── engine/
│   ├── quality_checks.py ← 5 check types: freshness, reconciliation, parts_sum, trend_sanity, completeness
│   ├── orchestrator.py ← reads YAML, runs all checks (ValidationEngine)
│   ├── report.py       ← Slack Block Kit + console output
│   ├── audit_log.py    ← appends every run's results to a Delta log table
│   └── validator.ipynb       ← Databricks entry point, schedule this
├── triage/
│   └── agent.py               ← calls Claude Haiku on FAIL to explain why
├── .claude/commands/
│   └── onboard-dashboard.md      ← /onboard-dashboard Claude Code skill (single copy)
├── onboarding/
│   └── onboard_dashboard.md      ← step-by-step guide
├── QUICKSTART.md      ← one-page guide for new teams
├── README.md          ← full reference
├── ARCHITECTURE.md    ← cell-by-cell execution flow diagram
├── test_local.py      ← run this first: python test_local.py (no Spark needed)
└── requirements.txt   ← pyyaml, anthropic, requests
```

## Key design rule

Claude touches the dashboard ONCE at setup (screenshot → YAML). After that, every weekly
validation run is pure deterministic SQL — no AI in the verdict.

## Example registry

`registry/example_dashboard.yaml` is a blank template — every value in it is a
placeholder (`<catalog>.<schema>.<table>` etc.), not a real table. Copy it to
onboard a real dashboard, or run `/onboard-dashboard` to generate a filled-in
version from a screenshot. `test_local.py` validates against this template, so
the repo stays runnable with zero real dashboard config committed.

## To onboard a new dashboard

Run `/onboard-dashboard` in Claude Code. The skill will:
1. Ask for a dashboard screenshot
2. Extract metrics and dimensions from the screenshot
3. Ask only for what can't be seen (table names, column names)
4. Generate the YAML, save it to registry/, run test_local.py

## To run the local test (no Databricks needed)

```bash
cd dashboard_validation_framework
python test_local.py
```

## Dependencies

```bash
pip install pyyaml anthropic requests
```

PySpark is provided by Databricks — not listed in requirements.txt.
