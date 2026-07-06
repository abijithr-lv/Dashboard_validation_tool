"""
Individual check implementations for the Dashboard Validation Framework.

Each function returns a CheckResult. Spark SQL is used throughout so
checks run natively on Databricks without pulling data to the driver.

Check types
-----------
freshness      — latest date in dashboard == expected run_week
reconciliation — dashboard SUM(metric) ≈ source SUM(metric) within tolerance
parts_sum      — per-dimension subtotals in dashboard ≈ source subtotals
trend_sanity   — current week vs. the average of the trailing lookback_weeks
                 (lookback_weeks=1 reduces this to plain week-over-week)
completeness   — no expected dimension slice is silently missing, and any
                 slice not seen anywhere in the lookback window is flagged
                 as a new/unexpected value instead of being ignored
"""

from dataclasses import dataclass
from typing import Any, List, Optional
from enum import Enum


class Status(str, Enum):
    PASS = "PASS"
    DRIFT = "DRIFT"
    FAIL = "FAIL"


_SEVERITY = {Status.PASS: None, Status.DRIFT: "P3", Status.FAIL: "P2"}


@dataclass
class CheckResult:
    check_name: str
    metric: str
    status: Status
    expected: Any
    actual: Any
    gap: Optional[float] = None
    tolerance: Optional[float] = None
    detail: str = ""

    @property
    def severity(self) -> Optional[str]:
        return _SEVERITY[self.status]


# ── helpers ──────────────────────────────────────────────────────────────────

_NON_BUDGET = "(data_type != 'Budget' OR data_type IS NULL)"


def _scalar(spark, sql: str) -> Any:
    """Return the single value from a single-row, single-column query."""
    rows = spark.sql(sql).collect()
    if not rows:
        return None
    return rows[0][0]


def _pct_gap(expected: float, actual: float) -> float:
    # Spark returns DECIMAL columns (e.g. spend) as decimal.Decimal, which can't
    # be mixed with float in arithmetic — normalize both to float up front.
    expected = float(expected)
    actual = float(actual)
    if expected == 0:
        return 100.0 if actual != 0 else 0.0
    return abs(actual - expected) / abs(expected) * 100.0


# ── check implementations ─────────────────────────────────────────────────────

def run_freshness_check(
    spark,
    dashboard_table: str,
    expected_week: str,
    date_column: str = "fiscal_yr_and_wk_desc",
) -> CheckResult:
    """Fail if the latest date in the dashboard does not equal expected_week."""
    latest_week = _scalar(spark, f"""
        SELECT MAX({date_column})
        FROM {dashboard_table}
        WHERE {_NON_BUDGET}
    """)

    status = Status.PASS if latest_week == expected_week else Status.FAIL
    return CheckResult(
        check_name="freshness",
        metric="row_freshness",
        status=status,
        expected=expected_week,
        actual=latest_week,
        detail=f"Latest week in dashboard: {latest_week}",
    )


def run_reconciliation_check(
    spark,
    dashboard_table: str,
    source_table: str,
    metric: str,
    run_week: str,
    tolerance_pct: float,
    date_column: str = "fiscal_yr_and_wk_desc",
) -> CheckResult:
    """Dashboard SUM(metric) must match source SUM(metric) within tolerance_pct."""
    week_filter = f"{date_column} = '{run_week}' AND {_NON_BUDGET}"

    dashboard_val = _scalar(spark, f"""
        SELECT COALESCE(SUM({metric}), 0)
        FROM {dashboard_table}
        WHERE {week_filter}
    """) or 0.0

    source_val = _scalar(spark, f"""
        SELECT COALESCE(SUM({metric}), 0)
        FROM {source_table}
        WHERE {week_filter}
    """) or 0.0

    if source_val == 0 and dashboard_val == 0:
        return CheckResult(
            check_name="reconciliation",
            metric=metric,
            status=Status.PASS,
            expected=0,
            actual=0,
            detail="Both source and dashboard are zero — no data for this week",
        )

    gap_pct = _pct_gap(source_val, dashboard_val)

    if gap_pct <= tolerance_pct:
        status = Status.PASS
    elif gap_pct <= tolerance_pct * 3:
        status = Status.DRIFT
    else:
        status = Status.FAIL

    return CheckResult(
        check_name="reconciliation",
        metric=metric,
        status=status,
        expected=round(float(source_val), 2),
        actual=round(float(dashboard_val), 2),
        gap=round(float(dashboard_val) - float(source_val), 2),
        tolerance=tolerance_pct,
        detail=f"Gap: {gap_pct:.2f}%  (tolerance: ±{tolerance_pct}%)",
    )


def run_parts_sum_check(
    spark,
    dashboard_table: str,
    source_table: str,
    metric: str,
    run_week: str,
    pivot_column: str,
    tolerance_pct: float,
    date_column: str = "fiscal_yr_and_wk_desc",
) -> CheckResult:
    """Each pivot_column subtotal in dashboard must match the source subtotal."""
    week_filter = f"{date_column} = '{run_week}' AND {_NON_BUDGET}"

    dash_rows = spark.sql(f"""
        SELECT {pivot_column}, COALESCE(SUM({metric}), 0) AS total
        FROM {dashboard_table}
        WHERE {week_filter}
        GROUP BY {pivot_column}
    """).collect()

    src_rows = spark.sql(f"""
        SELECT {pivot_column}, COALESCE(SUM({metric}), 0) AS total
        FROM {source_table}
        WHERE {week_filter}
        GROUP BY {pivot_column}
    """).collect()

    dash_map = {r[pivot_column]: float(r["total"]) for r in dash_rows}
    src_map  = {r[pivot_column]: float(r["total"]) for r in src_rows}

    failing: List[str] = []
    for dim_val, src_val in src_map.items():
        if src_val == 0:
            continue
        dash_val = dash_map.get(dim_val, 0.0)
        gap_pct = _pct_gap(src_val, dash_val)
        if gap_pct > tolerance_pct:
            failing.append(
                f"{dim_val}: expected {src_val:,.0f}, got {dash_val:,.0f} ({gap_pct:.1f}%)"
            )

    if not failing:
        status = Status.PASS
    elif len(failing) == 1:
        status = Status.DRIFT
    else:
        status = Status.FAIL

    return CheckResult(
        check_name="parts_sum",
        metric=f"{metric}_by_{pivot_column}",
        status=status,
        expected=len(src_map),
        actual=len(dash_map),
        detail="; ".join(failing) if failing else f"All {pivot_column} subtotals match",
    )


def run_trend_sanity_check(
    spark,
    dashboard_table: str,
    metric: str,
    run_week: str,
    prev_weeks: List[str],
    max_wow_change_pct: float,
    date_column: str = "fiscal_yr_and_wk_desc",
) -> CheckResult:
    """Current week must be within max_wow_change_pct of the lookback baseline.

    prev_weeks is the lookback window, most-recent-first. With a single week
    this is a plain week-over-week comparison; with more weeks the baseline
    is the average of those weeks' totals, which smooths out one noisy week
    that would otherwise trip the threshold on its own.
    """
    non_budget_filter = _NON_BUDGET

    current_val = _scalar(spark, f"""
        SELECT COALESCE(SUM({metric}), 0)
        FROM {dashboard_table}
        WHERE {date_column} = '{run_week}' AND {non_budget_filter}
    """) or 0.0

    week_list = ", ".join(f"'{w}'" for w in prev_weeks)
    weekly_totals = spark.sql(f"""
        SELECT {date_column} AS wk, COALESCE(SUM({metric}), 0) AS total
        FROM {dashboard_table}
        WHERE {date_column} IN ({week_list}) AND {non_budget_filter}
        GROUP BY {date_column}
    """).collect()

    if not weekly_totals:
        return CheckResult(
            check_name="trend_sanity",
            metric=metric,
            status=Status.PASS,
            expected=None,
            actual=float(current_val),
            detail=f"No data in lookback window ({', '.join(prev_weeks)}) — trend check skipped",
        )

    baseline_val = sum(float(r["total"]) for r in weekly_totals) / len(weekly_totals)

    if baseline_val == 0:
        return CheckResult(
            check_name="trend_sanity",
            metric=metric,
            status=Status.PASS,
            expected=0.0,
            actual=float(current_val),
            detail=f"Lookback baseline is zero across {len(weekly_totals)} week(s) — trend check skipped",
        )

    wow_pct = (float(current_val) - baseline_val) / abs(baseline_val) * 100.0

    if abs(wow_pct) <= max_wow_change_pct:
        status = Status.PASS
    elif abs(wow_pct) <= max_wow_change_pct * 1.5:
        status = Status.DRIFT
    else:
        status = Status.FAIL

    baseline_label = "prior week" if len(weekly_totals) == 1 else f"{len(weekly_totals)}-week avg"
    return CheckResult(
        check_name="trend_sanity",
        metric=metric,
        status=status,
        expected=round(baseline_val, 2),
        actual=round(float(current_val), 2),
        gap=round(wow_pct, 2),
        tolerance=max_wow_change_pct,
        detail=f"Change vs {baseline_label}: {wow_pct:+.1f}%  (limit: ±{max_wow_change_pct}%)",
    )


def run_completeness_check(
    spark,
    dashboard_table: str,
    dimension: str,
    expected_values: List[str],
    run_week: str,
    prev_weeks: Optional[List[str]] = None,
    date_column: str = "fiscal_yr_and_wk_desc",
) -> CheckResult:
    """Every value in expected_values must appear in the current week's data.

    If prev_weeks is given, any current-week value that is neither an
    expected_value nor seen anywhere in that lookback window is reported as
    a new/unexpected value — a signal for a human to confirm it's a
    legitimate addition (new creative, new platform, ...) rather than a data
    bug, without failing the check outright.
    """
    present_rows = spark.sql(f"""
        SELECT DISTINCT {dimension}
        FROM {dashboard_table}
        WHERE {date_column} = '{run_week}' AND {_NON_BUDGET}
    """).collect()
    present = {r[dimension] for r in present_rows}

    missing = [v for v in expected_values if v not in present]

    new_values: List[str] = []
    if prev_weeks:
        week_list = ", ".join(f"'{w}'" for w in prev_weeks)
        historical_rows = spark.sql(f"""
            SELECT DISTINCT {dimension}
            FROM {dashboard_table}
            WHERE {date_column} IN ({week_list}) AND {_NON_BUDGET}
        """).collect()
        known = set(expected_values) | {r[dimension] for r in historical_rows}
        new_values = sorted(v for v in present if v not in known)

    if not missing:
        status = Status.PASS
    elif len(missing) == 1:
        status = Status.DRIFT
    else:
        status = Status.FAIL

    # A brand-new value doesn't fail the check on its own — surface it as
    # DRIFT for a human to confirm, rather than silently dropping it or
    # failing a check that's otherwise legitimately complete.
    if new_values and status == Status.PASS:
        status = Status.DRIFT

    detail_parts = [
        f"Missing {dimension} values: {missing}"
        if missing
        else f"All {len(expected_values)} expected {dimension} values present"
    ]
    if new_values:
        detail_parts.append(
            f"New {dimension} values not seen in prior {len(prev_weeks)} week(s): {new_values}"
        )

    return CheckResult(
        check_name="completeness",
        metric=f"{dimension}_completeness",
        status=status,
        expected=len(expected_values),
        actual=len(present),
        detail="  |  ".join(detail_parts),
    )
