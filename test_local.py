"""
Local test — no Spark, no Databricks needed.

Tests:
  1. YAML registry loads and has required keys
  2. CheckResult dataclass works correctly
  3. Report module builds correct Slack messages (PASS and FAIL)
  4. Triage prompt builder produces a non-empty prompt
  5. All imports resolve without error
  6. Audit log module flattens a run into one log row per CheckResult

Run from the repo root:
    cd dashboard_validation_framework
    python test_local.py
"""

import sys, os
sys.stdout.reconfigure(encoding='utf-8')

# Make engine/ and triage/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "triage"))

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "registry", "example_dashboard.yaml")

PASS  = "\033[92m  PASS\033[0m"
FAIL  = "\033[91m  FAIL\033[0m"

results = []

def check(name, fn):
    try:
        fn()
        print(f"{PASS}  {name}")
        results.append(True)
    except Exception as e:
        print(f"{FAIL}  {name}")
        print(f"         Error: {e}")
        results.append(False)

print("\n" + "═" * 60)
print("  Dashboard Validation Framework — Local Tests")
print("═" * 60 + "\n")

# ── Test 1: imports ──────────────────────────────────────────────────────────
def t_imports():
    import yaml
    from quality_checks import CheckResult, Status
    from report import build_slack_message, print_console_report
    from agent import _build_prompt

check("All imports resolve (quality_checks, orchestrator, report, agent, yaml)", t_imports)

# ── Test 2: YAML loads ───────────────────────────────────────────────────────
def t_yaml_loads():
    import yaml
    with open(REGISTRY_PATH) as f:
        reg = yaml.safe_load(f)
    assert "dashboard" in reg,       "Missing 'dashboard' key"
    assert "dashboard_table" in reg, "Missing 'dashboard_table' key"
    assert "source_table" in reg,    "Missing 'source_table' key"
    assert "metrics" in reg,         "Missing 'metrics' key"
    assert len(reg["metrics"]) > 0,  "metrics list is empty"

check("YAML registry loads and has required keys", t_yaml_loads)

# ── Test 3: YAML metric structure ────────────────────────────────────────────
def t_yaml_metrics():
    import yaml
    with open(REGISTRY_PATH) as f:
        reg = yaml.safe_load(f)
    for m in reg["metrics"]:
        assert "name" in m,          f"Metric missing 'name': {m}"
        assert "tolerance_pct" in m, f"Metric '{m['name']}' missing 'tolerance_pct'"
        assert "checks" in m,        f"Metric '{m['name']}' missing 'checks'"
    metric_names = [m["name"] for m in reg["metrics"]]
    print(f"         Metrics defined: {metric_names}")

check("All YAML metrics have name, tolerance_pct, checks", t_yaml_metrics)

# ── Test 4: CheckResult dataclass ────────────────────────────────────────────
def t_check_result():
    from quality_checks import CheckResult, Status
    r = CheckResult(
        check_name="reconciliation",
        metric="impressions",
        status=Status.PASS,
        expected=1_000_000,
        actual=1_005_000,
        gap=5000,
        tolerance=1.0,
        detail="Gap: 0.5%  (tolerance: ±1.0%)"
    )
    assert r.status == Status.PASS
    assert r.severity is None          # PASS has no severity
    f = CheckResult("freshness", "row_freshness", Status.FAIL, "2026-23", "2026-22", detail="Stale")
    assert f.severity == "P2"
    d = CheckResult("trend_sanity", "impressions", Status.DRIFT, 1_000_000, 1_400_000, detail="WoW +40%")
    assert d.severity == "P3"

check("CheckResult: PASS/DRIFT/FAIL statuses and severity labels", t_check_result)

# ── Test 5: Reporter — PASS message ─────────────────────────────────────────
def t_reporter_pass():
    from quality_checks import CheckResult, Status
    from report import build_slack_message

    run_result = {
        "dashboard":      "test_dashboard",
        "run_week":       "2026-23",
        "run_timestamp":  "2026-07-01T06:00:00",
        "summary":        {"total": 3, "pass": 3, "drift": 0, "fail": 0},
        "overall_status": Status.PASS,
        "results": [
            CheckResult("freshness",      "row_freshness", Status.PASS, "2026-23", "2026-23"),
            CheckResult("reconciliation", "impressions",   Status.PASS, 1_000_000, 1_005_000),
            CheckResult("completeness",   "platform_completeness", Status.PASS, 8, 8),
        ],
        "triage_analysis": "",
    }
    msg = build_slack_message(run_result)
    assert "blocks" in msg
    assert "PASS" in msg["text"]
    assert "3 / 3" in msg["text"] or "3/3" in msg["text"]
    print(f"         Slack text: {msg['text']}")

check("Reporter builds correct PASS Slack message", t_reporter_pass)

# ── Test 6: Reporter — FAIL message ─────────────────────────────────────────
def t_reporter_fail():
    from quality_checks import CheckResult, Status
    from report import build_slack_message

    run_result = {
        "dashboard":      "test_dashboard",
        "run_week":       "2026-23",
        "run_timestamp":  "2026-07-01T06:00:00",
        "summary":        {"total": 3, "pass": 2, "drift": 0, "fail": 1},
        "overall_status": Status.FAIL,
        "results": [
            CheckResult("freshness",      "row_freshness", Status.PASS, "2026-23", "2026-23"),
            CheckResult("reconciliation", "impressions",   Status.FAIL, 1_000_000, 850_000,
                        gap=-150_000, tolerance=1.0, detail="Gap: 15.0%  (tolerance: ±1.0%)"),
            CheckResult("completeness",   "platform_completeness", Status.PASS, 8, 8),
        ],
        "triage_analysis": "APAC partition missing from last night's load.",
    }
    msg = build_slack_message(run_result)
    assert "blocks" in msg
    assert "FAIL" in msg["text"]
    # Triage text must appear in the blocks
    combined = " ".join(
        b.get("text", {}).get("text", "")
        for b in msg["blocks"] if isinstance(b.get("text"), dict)
    )
    assert "APAC" in combined, "Triage text not found in Slack blocks"
    assert "impressions" in combined, "Failing metric not in Slack blocks"
    print(f"         Slack text: {msg['text']}")

check("Reporter builds correct FAIL Slack message with triage text", t_reporter_fail)

# ── Test 7: Console report prints without error ──────────────────────────────
def t_console_report():
    from quality_checks import CheckResult, Status
    from report import print_console_report
    import io, contextlib

    run_result = {
        "dashboard":      "test_dashboard",
        "run_week":       "2026-23",
        "run_timestamp":  "2026-07-01T06:00:00",
        "summary":        {"total": 2, "pass": 1, "drift": 0, "fail": 1},
        "overall_status": Status.FAIL,
        "results": [
            CheckResult("freshness",      "row_freshness", Status.PASS, "2026-23", "2026-23"),
            CheckResult("reconciliation", "impressions",   Status.FAIL, 1_000_000, 850_000,
                        gap=-150_000, tolerance=1.0, detail="Gap: 15.0%"),
        ],
        "triage_analysis": "Root cause: missing partition.",
    }
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_console_report(run_result)
    output = buf.getvalue()
    assert "FAIL" in output
    assert "impressions" in output
    assert "Root cause" in output

check("Console report prints PASS/FAIL breakdown and triage text", t_console_report)

# ── Test 8: Triage prompt builder ────────────────────────────────────────────
def t_triage_prompt():
    from quality_checks import CheckResult, Status
    from agent import _build_prompt

    run_result = {
        "dashboard": "example_dashboard",
        "run_week":  "2026-23",
        "results": [
            CheckResult("reconciliation", "impressions", Status.FAIL, 1_000_000, 850_000,
                        gap=-150_000, tolerance=1.0, detail="Gap: 15.0%  (tolerance: ±1.0%)"),
        ],
        "overall_status": Status.FAIL,
    }
    prompt = _build_prompt(run_result)
    assert "example_dashboard" in prompt
    assert "2026-23" in prompt
    assert "impressions" in prompt
    assert len(prompt) > 200, "Prompt too short"
    print(f"         Prompt length: {len(prompt)} chars")

check("Triage prompt builder includes dashboard, week, and failing check details", t_triage_prompt)

# ── Test 9: ValidationEngine — YAML load only (no Spark) ────────────────────
def t_engine_yaml_load():
    import yaml
    from pathlib import Path
    # Replicate the YAML loading part of ValidationEngine without instantiating Spark
    path = Path(REGISTRY_PATH)
    assert path.exists(), f"Registry file not found: {REGISTRY_PATH}"
    with open(path) as f:
        reg = yaml.safe_load(f)
    assert reg["dashboard"] == "example_dashboard"
    assert "." in reg["dashboard_table"], "dashboard_table should be catalog/schema-qualified"
    assert "." in reg["source_table"], "source_table should be catalog/schema-qualified"
    print(f"         Dashboard table : {reg['dashboard_table']}")
    print(f"         Source table    : {reg['source_table']}")
    print(f"         Metrics         : {[m['name'] for m in reg['metrics']]}")

check("ValidationEngine: YAML parses correctly with correct table names", t_engine_yaml_load)

# ── Test 10: History — flattens a run into one row per CheckResult (no Spark) ──
def t_history_rows():
    from quality_checks import CheckResult, Status
    from audit_log import _build_log_rows

    run_result = {
        "dashboard":      "test_dashboard",
        "run_week":       "2026-23",
        "run_timestamp":  "2026-07-01T06:00:00",
        "overall_status": Status.FAIL,
        "results": [
            CheckResult("freshness",      "row_freshness", Status.PASS, "2026-23", "2026-23"),
            CheckResult("reconciliation", "impressions",   Status.FAIL, 1_000_000, 850_000,
                        gap=-150_000, tolerance=1.0, detail="Gap: 15.0%"),
        ],
        "triage_analysis": "Root cause: missing partition.",
    }
    rows = _build_log_rows(run_result)
    assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"
    assert all(r["dashboard"] == "test_dashboard" for r in rows), "dashboard not repeated on every row"
    assert all(r["run_week"] == "2026-23" for r in rows)
    assert all(r["triage_analysis"] == "Root cause: missing partition." for r in rows)
    assert rows[0]["status"] == "PASS" and rows[0]["severity"] is None
    assert rows[1]["status"] == "FAIL" and rows[1]["severity"] == "P2"
    assert rows[1]["expected"] == "1000000" and rows[1]["actual"] == "850000"
    assert rows[0]["run_id"] == rows[1]["run_id"], "same run must share one run_id"
    print(f"         Row keys: {sorted(rows[0].keys())}")

check("Audit log flattens a run into one log row per CheckResult", t_history_rows)

# ── Test 11: Orchestrator — lookback week math (no Spark) ──────────────────────
def t_lookback_weeks():
    from orchestrator import ValidationEngine

    assert ValidationEngine._prev_week("2026-05") == "2026-04"
    assert ValidationEngine._prev_week("2026-01") == "2025-52"  # year rollover
    assert ValidationEngine._lookback_weeks("2026-05", 3) == ["2026-04", "2026-03", "2026-02"]
    assert ValidationEngine._lookback_weeks("2026-01", 2) == ["2025-52", "2025-51"]
    assert ValidationEngine._lookback_weeks("2026-05", 0) == ["2026-04"]  # n<1 clamps to 1

check("ValidationEngine: _prev_week / _lookback_weeks compute correct trailing fiscal weeks", t_lookback_weeks)

# ── Test 12: Completeness check flags new/unexpected dimension values ─────────
def t_completeness_new_values():
    from unittest.mock import MagicMock
    from quality_checks import run_completeness_check, Status

    class _Row:
        def __init__(self, val):
            self._val = val
        def __getitem__(self, key):
            return self._val

    spark = MagicMock()
    # First call: current-week distinct values. Second call: lookback-window distinct values.
    spark.sql.return_value.collect.side_effect = [
        [_Row("LinkedIn"), _Row("Instagram"), _Row("Threads")],  # present this week
        [_Row("LinkedIn"), _Row("Instagram"), _Row("Facebook")],  # seen in lookback window
    ]

    result = run_completeness_check(
        spark, "schema.dashboard", "platform",
        expected_values=["LinkedIn", "Instagram", "Facebook"],
        run_week="2026-05", prev_weeks=["2026-04", "2026-03"],
    )
    # Facebook missing this week -> DRIFT on its own; Threads is new (not expected, not in lookback)
    assert result.status == Status.DRIFT
    assert "Threads" in result.detail
    assert "Facebook" in result.detail

check("Completeness check flags missing AND new/unexpected dimension values", t_completeness_new_values)

# ── Test 12b: 2+ missing required values escalates to FAIL, not just DRIFT ────
def t_completeness_fail_on_multiple_missing():
    from unittest.mock import MagicMock
    from quality_checks import run_completeness_check, Status

    class _Row:
        def __init__(self, val):
            self._val = val
        def __getitem__(self, key):
            return self._val

    spark = MagicMock()
    # Only LinkedIn present; both Instagram and Facebook are missing this week.
    spark.sql.return_value.collect.side_effect = [
        [_Row("LinkedIn")],
        [_Row("LinkedIn"), _Row("Instagram"), _Row("Facebook")],
    ]

    result = run_completeness_check(
        spark, "schema.dashboard", "platform",
        expected_values=["LinkedIn", "Instagram", "Facebook"],
        run_week="2026-05", prev_weeks=["2026-04"],
    )
    assert result.status == Status.FAIL, f"2+ missing required values should FAIL, got {result.status}"
    assert "Instagram" in result.detail and "Facebook" in result.detail

check("Completeness escalates to FAIL when 2+ required values are missing", t_completeness_fail_on_multiple_missing)

# ── Test 13: parts_sum runs once per pivot column, not just once overall ─────
def t_parts_sum_multi_pivot():
    from unittest.mock import MagicMock, patch
    import orchestrator
    from quality_checks import CheckResult, Status

    engine = orchestrator.ValidationEngine.__new__(orchestrator.ValidationEngine)
    engine.spark = MagicMock()
    engine.registry = {
        "dashboard": "test_dashboard",
        "dashboard_table": "schema.dashboard",
        "source_table": "schema.source",
        "date_column": "fiscal_yr_and_wk_desc",
        "lookback_weeks": 1,
        "metrics": [{"name": "interactions", "tolerance_pct": 1.0, "checks": ["reconciliation"]}],
        "dimensions": [],
        "checks": {
            "freshness": {"enabled": False},
            "reconciliation": {"enabled": False},
            "parts_sum": {"enabled": True, "pivot_columns": ["gtm_segment", "content_framework_pillar"]},
            "trend_sanity": {"enabled": False},
            "completeness": {"enabled": False},
        },
    }

    with patch("orchestrator.run_parts_sum_check") as mock_parts_sum:
        mock_parts_sum.return_value = CheckResult("parts_sum", "interactions_by_x", Status.PASS, 1, 1)
        result = engine.run(run_week="2026-05")

    pivot_cols_called = [call.args[5] for call in mock_parts_sum.call_args_list]
    assert pivot_cols_called == ["gtm_segment", "content_framework_pillar"], (
        f"Expected one call per pivot column, got: {pivot_cols_called}"
    )
    assert len(result["results"]) == 2, "Each pivot column should produce its own independent CheckResult"

check("parts_sum runs independently per configured pivot column", t_parts_sum_multi_pivot)

# ── Test 14: optional_values — absence is silent, presence isn't "new" ───────
def t_completeness_optional_values():
    from unittest.mock import MagicMock
    from quality_checks import run_completeness_check, Status

    class _Row:
        def __init__(self, val):
            self._val = val
        def __getitem__(self, key):
            return self._val

    def make_spark(present, historical):
        spark = MagicMock()
        spark.sql.return_value.collect.side_effect = [
            [_Row(v) for v in present],
            [_Row(v) for v in historical],
        ]
        return spark

    # Case A: "Summit" (optional) absent this week -> must NOT count as missing.
    spark = make_spark(
        present=["Firefly", "Photoshop"],
        historical=["Firefly", "Photoshop"],
    )
    result = run_completeness_check(
        spark, "schema.dashboard", "gtm_segment",
        expected_values=["Firefly", "Photoshop"],
        run_week="2026-05", prev_weeks=["2026-04"],
        optional_values=["Summit"],
    )
    assert result.status == Status.PASS, f"Optional absence should PASS, got {result.status}: {result.detail}"

    # Case B: "Summit" reappears after being absent from the lookback window
    # -> known optional value, must NOT be flagged as new/unexpected.
    spark = make_spark(
        present=["Firefly", "Photoshop", "Summit"],
        historical=["Firefly", "Photoshop"],
    )
    result = run_completeness_check(
        spark, "schema.dashboard", "gtm_segment",
        expected_values=["Firefly", "Photoshop"],
        run_week="2026-05", prev_weeks=["2026-04"],
        optional_values=["Summit"],
    )
    assert result.status == Status.PASS, f"Optional presence should PASS, got {result.status}: {result.detail}"
    assert "Summit" not in result.detail, "Optional value must not be reported as new"

    # Case C: control — a required value missing still alerts as before.
    spark = make_spark(
        present=["Firefly"],
        historical=["Firefly", "Photoshop"],
    )
    result = run_completeness_check(
        spark, "schema.dashboard", "gtm_segment",
        expected_values=["Firefly", "Photoshop"],
        run_week="2026-05", prev_weeks=["2026-04"],
        optional_values=["Summit"],
    )
    assert result.status == Status.DRIFT, f"Missing required value should DRIFT, got {result.status}"
    assert "Photoshop" in result.detail

check("Completeness: optional_values absent silently, present without 'new' flag, required still alerts", t_completeness_optional_values)

# ── Test 16: sanity_range flags any row violating a logically-impossible rule ──
def t_sanity_range_check():
    from unittest.mock import MagicMock
    from quality_checks import run_sanity_range_check, Status

    # Case A: no violations -> PASS
    spark = MagicMock()
    spark.sql.return_value.collect.return_value = [{"total": 1000, "violations": 0}]
    result = run_sanity_range_check(
        spark, "schema.dashboard", "spend_non_negative", "spend < 0", run_week="2026-05",
    )
    assert result.status == Status.PASS, f"Zero violations should PASS, got {result.status}"

    # Case B: even a single violation -> FAIL, no DRIFT tier for a logically-impossible rule
    spark = MagicMock()
    spark.sql.return_value.collect.return_value = [{"total": 1000, "violations": 1}]
    result = run_sanity_range_check(
        spark, "schema.dashboard", "clicks_le_interactions",
        "link_clicks > interactions", run_week="2026-05",
    )
    assert result.status == Status.FAIL, f"Any violation should FAIL, got {result.status}"
    assert "clicks_le_interactions" in result.detail

check("sanity_range: zero violations PASS, any violation FAILs immediately (no DRIFT tier)", t_sanity_range_check)

# ── Summary ──────────────────────────────────────────────────────────────────
passed = sum(results)
total  = len(results)
print()
print("═" * 60)
if passed == total:
    print(f"\033[92m  All {total} tests passed.\033[0m")
else:
    print(f"\033[91m  {passed}/{total} tests passed. Fix errors above before running on Databricks.\033[0m")
print("═" * 60 + "\n")

sys.exit(0 if passed == total else 1)
