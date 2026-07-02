"""
Audit log — appends every validation run's check results to a Delta table.

Grain: one row per individual CheckResult, not one row per run. Run-level
fields (dashboard, run_week, run_timestamp, overall_status, triage_analysis)
are repeated on every row so the table stays flat and directly queryable
without a join — at ~15-20 rows per run this costs nothing.

Always appends. A re-run of the same week is a genuine historical event
(e.g. after a late-arriving partition changed the result), not a correction
to overwrite — if you need "latest result per week," query for it:

    SELECT * FROM (
      SELECT *, ROW_NUMBER() OVER (
        PARTITION BY dashboard, run_week ORDER BY run_timestamp DESC
      ) AS rn
      FROM <log_table>
    ) WHERE rn = 1
"""

from typing import Dict, List


def _build_log_rows(run_result: Dict) -> List[Dict]:
    """Flatten a run_result into one dict per CheckResult, ready for a Spark DataFrame."""
    dashboard       = run_result["dashboard"]
    run_week        = run_result["run_week"]
    run_timestamp   = run_result["run_timestamp"]
    overall_status  = run_result["overall_status"]
    triage_analysis = run_result.get("triage_analysis", "")
    run_id = f"{dashboard}_{run_week}_{run_timestamp}"

    rows = []
    for r in run_result["results"]:
        rows.append({
            "run_id":          run_id,
            "dashboard":       dashboard,
            "run_week":        run_week,
            "run_timestamp":   run_timestamp,
            "overall_status":  overall_status.value,
            "check_name":      r.check_name,
            "metric":          r.metric,
            "status":          r.status.value,
            "severity":        r.severity,
            "expected":        None if r.expected is None else str(r.expected),
            "actual":          None if r.actual is None else str(r.actual),
            "gap":             r.gap,
            "tolerance":       r.tolerance,
            "detail":          r.detail,
            "triage_analysis": triage_analysis,
        })
    return rows


def log_run(spark, run_result: Dict, log_table: str) -> None:
    """Append this run's check results to log_table (auto-created on first write)."""
    rows = _build_log_rows(run_result)
    if not rows:
        print("[audit_log] No check results to log — skipping")
        return

    df = spark.createDataFrame(rows)
    (
        df.write
          .format("delta")
          .mode("append")
          .option("mergeSchema", "true")
          .saveAsTable(log_table)
    )
    print(f"[audit_log] Logged {len(rows)} check results to {log_table}")
