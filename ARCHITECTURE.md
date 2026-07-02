# Architecture — how a run actually executes

This traces one scheduled run of `engine/validator.ipynb` end to end: which
cell calls which file, in what order, and what each call returns.

## Cell-by-cell execution

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  engine/validator.ipynb  — Databricks entry point (scheduled job)            │
└──────────────────────────────────────────────────────────────────────────────┘

 cell-0  Banner / docs only — no code runs

 cell-1  Read widgets → DASHBOARD_NAME, RUN_WEEK_PARAM, SLACK_WEBHOOK,
         REGISTRY_ROOT, LOG_TABLE

 cell-2  Resolve RUN_WEEK
           ├─ widget filled?  → use RUN_WEEK_PARAM
           └─ blank?          → spark.sql(...) against ids_coredata.dim_date

 cell-3  %pip install pyyaml anthropic requests

 cell-4  sys.path.insert(engine_dir, triage_dir)     ← makes cells 5-9 importable

 cell-5  from orchestrator import ValidationEngine   [engine/orchestrator.py]
           │
           ├─ ValidationEngine(spark, registry_path)
           │     └─ yaml.safe_load(registry/<DASHBOARD_NAME>.yaml)   ◄── registry YAML
           │
           └─ engine.run(run_week=RUN_WEEK)
                 │
                 └─ from quality_checks import ...   [engine/quality_checks.py]
                       ├─ run_freshness_check()
                       ├─ run_reconciliation_check()   (per metric)
                       ├─ run_trend_sanity_check()      (per metric)
                       ├─ run_parts_sum_check()         (per reconciled metric)
                       └─ run_completeness_check()      (per dimension)
                 │
                 └─► returns run_result = {dashboard, run_week, run_timestamp,
                                            summary, results[], overall_status}

 cell-6  from report import print_console_report     [engine/report.py]
           └─ prints PASS/DRIFT/FAIL breakdown to notebook output
              (uses Status from quality_checks.py internally)

 cell-7  from agent import run_triage                [triage/agent.py]
         from quality_checks import Status
           │
           └─ if overall_status != PASS:
                 run_triage(run_result)
                   ├─ _build_prompt(run_result)        (uses CheckResult/Status)
                   ├─ reads ANTHROPIC_API_KEY env var
                   └─ anthropic.Anthropic().messages.create(...)  ──► Claude API
              run_result["triage_analysis"] = <Claude's explanation>

 cell-8  from report import send_slack_report         [engine/report.py]
           └─ if SLACK_WEBHOOK:
                 build_slack_message(run_result)   (uses Status)
                 requests.post(SLACK_WEBHOOK, json=payload)  ──► Slack

 cell-9  from audit_log import log_run                [engine/audit_log.py]
           └─ _build_log_rows(run_result)   (flattens results[] → 1 row/check)
              spark.createDataFrame(rows)
                .write.format("delta").mode("append")
                .saveAsTable(LOG_TABLE)              ──► Delta table (always runs)

 cell-10 if overall_status == FAIL:
           raise RuntimeError(...)                   ──► job turns red in Databricks
```

## Module dependency shape

`quality_checks.py` is the one shared foundation everything else imports from.
Nothing imports from `orchestrator.py`, `report.py`, or `agent.py`.

```
                 quality_checks.py
                 (CheckResult, Status, 5 check fns)
                        ▲   ▲   ▲
                        │   │   │
              orchestrator report agent
                   │        │      │
                   └────────┼──────┘
                            │
                      audit_log.py  (depends only on the run_result dict shape,
                                      not on quality_checks directly)
                            │
                      validator.ipynb  (imports all of the above, in this order)
```

## What runs outside this flow

- **`.claude/commands/onboard-dashboard.md`** — a design-time, human-in-the-loop
  Claude Code skill that *produces* the registry YAML `validator.ipynb` later
  reads. It never executes as part of a scheduled run.
- **`test_local.py`** — a standalone script (`python test_local.py`) that
  sanity-checks imports, YAML structure, and message-building without Spark.
  Run manually, separate from the notebook.
