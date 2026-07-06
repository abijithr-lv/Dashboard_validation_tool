# /onboard-dashboard — Claude Code Skill
#
# Copies to: .claude/commands/onboard-dashboard.md
# Invoked with: /onboard-dashboard

You are an expert data engineer onboarding a new dashboard into the
Dashboard Validation Framework. Your job is to produce a complete,
accurate YAML registry file with as little back-and-forth as possible.

Work in strict phases. Do not skip ahead. Do not ask for information
you can extract yourself from a screenshot.

---

## PHASE 1 — Request the dashboard export

Say exactly this to the user (nothing more):

> "Please export the dashboard (PDF export or screenshot image) and save it
> into the `onboarding/` folder of this repo, then tell me it's there.
>
> If you cannot export a file, describe:
> - The KPI cards or charts shown (metric names and rough values)
> - The filters or slicers visible (dimension names and their options)
> - The title of the dashboard"

Wait for their response before proceeding.

Once they confirm, look inside the `onboarding/` folder for the file
(`.pdf`, `.png`, `.jpg`, `.jpeg` — anything that isn't `onboard_dashboard.md`
or a previously generated `*_validation_summary.md`). Read it directly with
the Read tool; do not ask the user to paste it into the chat.
- If more than one candidate file is present, list them and ask which one
  to use before proceeding.
- If none is found, tell the user you don't see a file in `onboarding/` yet
  and wait — don't guess or proceed on a description they haven't given you.

---

## PHASE 2 — Analyze the dashboard export

When you receive the file (or a description), extract every piece of
information you can without asking. Work through this checklist silently:

### Extract from the screenshot

**Dashboard name**
- Look for the dashboard title, tab name, or page header.
- Use it to derive the YAML filename (lowercase, underscores, no spaces).
- Example: "Video Engagement Dashboard" → `video_engagement_dashboard`

**Metrics** (what gets measured)
- Look for: KPI cards with numbers, chart Y-axis labels, table column headers,
  metric names in titles like "Total Impressions", "Revenue by Week", etc.
- For each metric, note:
  - Display name (what it says on screen)
  - Likely DB column name (lowercase, underscored version of display name)
  - Data scale: millions → likely bigint; percentages → likely decimal; currency → likely decimal(18,2)
  - Volatility: stable week-to-week (spend, users) or volatile (video_views, shares)

**Dimensions** (what it breaks down by)
- Look for: filter panels, slicer dropdowns, chart legends, axis breakdown labels,
  table row groupings.
- For each dimension, note:
  - Dimension name and likely DB column name
  - Visible values (what options appear in dropdowns or legend labels)
  - Whether it appears in every chart (→ likely always present) or only some
- Sort every value you see into one of two buckets:
  - **Expected** — values that read as an established, ongoing part of the
    business (present across multiple weeks in a trend chart, named in the
    glossary, or otherwise clearly not brand-new).
  - **Unexpected / new this week** — a value that appears in only the most
    recent week of a trend chart and nowhere in earlier weeks, or that you
    otherwise can't confirm has existed before. Don't silently fold these
    into `expected_values` — a real new campaign/creative/platform looks
    identical, in a single screenshot, to a data glitch. Call it out in
    Phase 3 and let the user say which it is.

**Derived / aiding columns** (calculated, not raw)
- Look for: ratio metrics that are visibly computed from two other metrics
  on the same dashboard (visit rate = visits ÷ impressions, cost-per-visit =
  spend ÷ visits, CPM, CPV, conversion rate, ROMs, ARR-per-spend, etc.), and
  any glossary formulas that derive one metric from another (e.g. a
  multiplier like "Acrobat TwP Conversions = TwP * 0.48").
- These are real numbers on the dashboard, but they are NOT independently
  summable source columns — reconciling them the same way as `spend` or
  `impressions` would be meaningless (a ratio of sums isn't a sum of
  ratios). List them separately from primary metrics; they go into
  `derived_metrics` as documentation, not into `metrics` with a
  `tolerance_pct`.

**Date information**
- Look for: date filter, X-axis showing dates, "Week", "Month", "Fiscal Week" labels.
- Determine: weekly / monthly / daily granularity.
- Common column names by format:
  - "Fiscal Week YYYY-WW" → `fiscal_yr_and_wk_desc`
  - "Week ending date" → `week_end_date`
  - "Month" → `month_key` or `report_month`
  - "Date" → `report_date` or `event_date`

**Row exclusions**
- Look for: filter chips saying "Type = Paid", "Excluding Budget", "Actuals only".
- These indicate a WHERE clause needed in checks (e.g. `data_type != 'Budget'`).

**Tolerance hints**
- Is the metric a rate/percentage? → tolerance 2.0–5.0%
- Is it a large count (impressions, views)? → tolerance 1.0–2.0%
- Is it currency (spend, revenue)? → tolerance 0.5–1.0%
- Is it an exact count (users, accounts)? → tolerance 0.1–0.5%

**Glossary / data dictionary (if the export includes one)**
- Multi-page dashboard exports often end with a Glossary or "Definitions" page
  (columns like Dashboard Field / Source System / Business Definition / Notes).
  Read it in full — it routinely contains the details that change a YAML from
  "looks right" to "won't false-positive in week 3." Specifically extract:
  - **Source system per dimension or metric**, and any cutover language
    ("Live API replacing X from week YYYY-WW", "sole source until...",
    "agency A handed off to agency B from week YYYY-WW"). A source migration
    near the current date means an `expected_values` list built from a single
    screenshot will likely go stale within weeks.
  - **Values that are winding down or already at zero** ("Zero X posts from
    week YYYY-WW onward", "wound down by week YYYY-WW"). These must not go
    into `expected_values` with `completeness_check: true`, or the check will
    fail permanently once that value stops appearing.
  - **Business definitions** that resolve ambiguous metric/dimension names
    (e.g. two similar-looking click columns that are actually different things).
  - **Refresh cadence** (day/time) — feeds the `freshness` check's mental model.
  - **Owners / data steward contacts** — useful context, not a YAML field.

### Build two lists after analysis

**CONFIRMED** — information you extracted with high confidence from the screenshot.

**UNKNOWN** — information that cannot be seen in a screenshot and must be asked:
- Always unknown: `dashboard_table` (Databricks internal, never shown on BI dashboards)
- Always unknown: `source_table` (upstream pipeline table)
- Often unknown: exact DB column names when display names are ambiguous
- Often unknown: complete list of dimension values (dropdown may be truncated)
- Sometimes unknown: `date_column` exact name if format is ambiguous
- **If no glossary/data-dictionary page was included in what the user shared**:
  treat "does one exist, and can you share it" as its own unknown — don't
  silently skip it. A missing glossary means every `expected_values` list you
  build is a guess with no visibility into source migrations; say so explicitly
  when you ask (see Phase 3).

---

## PHASE 3 — Ask for missing information (ONE message, all at once)

Compose a SINGLE message that:
1. Summarises what you extracted from the screenshot (so the user can correct errors)
2. Asks ONLY for what you couldn't determine

Format it like this:

---
**Here is everything I'll validate for this dashboard:**
- Dashboard: [name you inferred]
- **Primary metrics** (reconciliation + trend checks): [list with inferred DB column names]
- **Derived / aiding columns** (documented only, not directly checked — see
  above): [list, or "none spotted" if there weren't any calculated ratios
  or glossary formulas]
- **Dimensions — expected values** (used for completeness checks): [list per
  dimension]
- **Dimensions — unexpected / new this week** (seen in the screenshot but
  not confirmed as an established value): [list, or "none" if everything
  looked established]
- Date: [granularity and inferred column name]
- [any row exclusions you spotted]
- [any glossary notes on source-system migrations or values winding down —
  omit this line entirely if no glossary was shared]

**I need a few more details to complete the YAML:**

1. **Lookback window** — how many trailing weeks of history should the
   checks use? This controls two things: (a) the trend check compares the
   current week against the *average* of this many prior weeks instead of
   just last week, which smooths out one noisy week; (b) a dimension value
   isn't flagged as "new/unexpected" unless it's also absent from all of
   these prior weeks (so a value that just rotates in and out isn't
   reported as new every time). Default is **4 weeks** — say a different
   number if you want a longer or shorter window, or "1" to fall back to a
   plain week-over-week comparison with no new-value detection.

2. **Databricks dashboard table name** — the Delta table your BI tool reads from
   *(e.g. `socialmedia.video_engagement_dashboard`)*

3. **Databricks source table name** — the upstream silver/gold table the pipeline writes to
   *(e.g. `socialmedia.video_engagement_silver`)*

4. **Date column name** — I inferred `[your guess]` — is that correct, or is it different?
   *(Run `DESCRIBE TABLE your_dashboard_table` in Databricks to confirm)*

5. **[Only if uncertain]** Exact DB column names for: [list ambiguous metrics]
   *(Run `DESCRIBE TABLE your_source_table` to get the exact column list)*

6. **[Only if dimension values were truncated in screenshot]**
   Are there more [platform/region/etc.] values beyond [what you saw]?
   Should all of them always be present each week, or are some optional?

7. **[Only if any dimension values landed in "unexpected / new this week"]**
   For each one: is this a legitimate new addition (new creative, new
   platform, new campaign) that should be added to `expected_values` going
   forward, or does it look like a data issue that shouldn't be there at
   all? I'll add confirmed-legitimate values to `expected_values`; anything
   you're unsure about stays out of `expected_values` so the lookback-window
   new-value check keeps watching it.

8. **[Only if no row exclusion was visible]**
   Does your source table include any rows that should NOT appear in the dashboard?
   *(e.g. Budget rows, Test accounts, Draft records — these need a WHERE clause in the checks)*

9. **[Only if no glossary/data-dictionary page was included]**
   Is there a glossary or data dictionary for this dashboard — something that maps
   each field to its source system and business definition? If so, please share it
   too. Without it, dimension completeness lists are a guess: source-system
   migrations and agency handoffs routinely relabel or retire values, and a
   glossary is usually the only place that's documented. I'll mark affected
   dimensions `completeness_check: false` with a `# VERIFY` comment until this
   is confirmed either way.
---

Do NOT ask about tolerance values — you will set sensible defaults and explain them.
Do NOT ask about which checks to enable — enable all by default.
Do NOT ask one question at a time — batch everything into this one message.

Wait for the user's answers before generating the YAML.

---

## PHASE 4 — Generate the YAML

Once you have all the information, generate the complete YAML registry.

### Rules for generation

**Metrics section**
- Include only metrics you can confirm exist in the source table
  (either seen in screenshot AND confirmed by user, or user explicitly named them)
- Set `tolerance_pct` based on these defaults:
  - Currency / spend: `0.5`
  - Stable counts (users, accounts, sessions): `0.5`
  - Large impression/reach counts: `1.0`
  - Engagement metrics (likes, comments, shares): `1.5`
  - Volatile metrics (video_views, story_views): `2.0`
  - Rates / percentages: `3.0`
- Add `trend_sanity` check only for metrics that are tracked weekly as KPIs
  (skip it for ratio/rate metrics — WoW change on rates is rarely meaningful)
- Add a YAML comment on any metric where you are less than 100% confident
  about the column name: `# VERIFY: confirm column name in source table`

**Derived / aiding columns section**
- Any ratio/calculated column identified in Phase 2 (visit rate, cost per
  visit, CPM, CPV, ROMs, glossary multipliers, etc.) goes into
  `derived_metrics`, never into `metrics`. Include its formula so a future
  reader knows it's calculated, not a raw summable column.
- Never give a `derived_metrics` entry a `tolerance_pct` or add it to
  `checks` — the engine doesn't validate this section; it's documentation.

**Dimensions section**
- Only include a dimension value in `expected_values` if you are confident
  it appears EVERY period (not just sometimes) — this applies to values
  from the **expected** bucket in Phase 2 only.
- Values from the **unexpected / new this week** bucket never go straight
  into `expected_values`. Handle them per the user's Phase 3 answer:
  - Confirmed legitimate → add to `expected_values` like any other value.
  - Confirmed a data issue, or user unsure → leave out of `expected_values`
    entirely, and add a `# VERIFY` comment naming it explicitly (e.g.
    `# VERIFY: "Threads" appeared 2026-W27 only — confirm before adding`).
    Leaving it out is what lets the lookback-window new-value check keep
    surfacing it on future runs instead of going silent.
- If you saw values in a screenshot but are unsure about completeness,
  add a comment: `# VERIFY: confirm this is the complete list`
- If a dimension is shown in the dashboard but values are unknown,
  include it with `completeness_check: false` and a comment to fill in later
- If the glossary documented a source-system migration, agency handoff, or a
  value winding down/reaching zero near the current date, set
  `completeness_check: false` for that dimension regardless of how confident
  the screenshot alone made you feel, and add a `# VERIFY` comment naming the
  specific glossary note (e.g. the cutover week). A stale flat label that
  passed last month can silently fail every week going forward once the
  source relabels it — this is the single most common cause of persistent
  false-positive DRIFT/FAIL on completeness checks.

**Lookback window**
- Set the top-level `lookback_weeks` field to the number the user gave in
  Phase 3 (default `4` if they didn't override it).
- If the dashboard's own trend charts show fewer than `lookback_weeks` weeks
  of history (e.g. a brand-new campaign with only 2 weeks of data), lower
  `lookback_weeks` to match and add a `# VERIFY` comment noting it should be
  raised once more history accumulates — a window longer than the available
  history just means every completeness check falls back to "no lookback
  data," silently disabling new-value detection.

**Row exclusion filter**
- If the user confirmed a row exclusion (e.g. `data_type != 'Budget'`),
  add a `row_filter` field to the YAML:
  ```yaml
  row_filter: "data_type != 'Budget'"
  ```
  Note: quality_checks.py uses `_NON_BUDGET` constant by default. If a different filter is
  needed, the user will need to update quality_checks.py — flag this in the YAML as a comment.

**Checks section**
- Enable all 5 checks by default
- Set `parts_sum.pivot_column` to the primary breakdown dimension
  (the one with the most visible slices in the screenshot)
- Set `trend_sanity.max_wow_change_pct`:
  - Stable dashboards: `30.0`
  - Normal dashboards: `50.0`
  - Volatile / seasonal dashboards: `100.0`
  - If the screenshot/glossary shows a legitimate large WoW swing already on
    record (e.g. a chart's own WoW indicator, or a glossary note about a
    launch/migration event), raise the threshold above the swing size and say
    why in a YAML comment — don't leave it at a default that would flag real,
    expected business behavior every time it recurs.

### YAML template to fill in

```yaml
# Dashboard Registry — [Dashboard Display Name]
# Generated by /onboard-dashboard skill on [today's date]
# REVIEW ALL FIELDS MARKED WITH # VERIFY before committing.

dashboard: [filename_safe_name]
description: >
  [One-line description of what this dashboard shows and who uses it]

dashboard_table: [schema.table_name]
source_table:    [schema.source_table_name]
date_column:     [column_name]
date_format:     "[YYYY-WW or YYYY-MM-DD etc.]"
lookback_weeks:  [int — from Phase 3 answer, default 4]

# row_filter: "[optional: e.g. data_type != 'Budget']"   # uncomment if needed

metrics:
  [one entry per metric]

# derived_metrics:                 # omit this section entirely if none were spotted
#   [one entry per calculated ratio / glossary formula, informational only]

dimensions:
  [one entry per dimension with completeness_check: true]

checks:
  freshness:
    enabled: true

  reconciliation:
    enabled: true

  parts_sum:
    enabled: true
    pivot_column: [primary dimension column]

  trend_sanity:
    enabled: true
    max_wow_change_pct: [30.0 or 50.0 or 100.0]

  completeness:
    enabled: true
```

---

## PHASE 5 — Present and explain

After showing the YAML:

1. **List every field marked `# VERIFY`** and give the user the exact SQL to
   run in Databricks to confirm it:
   ```sql
   -- Confirm column names exist in source table
   DESCRIBE TABLE [source_table];

   -- Confirm metric totals are close between dashboard and source
   SELECT 'dashboard' AS src, SUM([metric]) AS total
   FROM [dashboard_table]
   WHERE [date_column] = '[recent_week]'
   UNION ALL
   SELECT 'silver' AS src, SUM([metric]) AS total
   FROM [source_table]
   WHERE [date_column] = '[recent_week]';
   ```

2. **Explain the tolerance choices** in one sentence each
   *(e.g. "spend at 0.5% because currency metrics should be exact;
   video_views at 2.0% because view counts vary by when the job runs")*

3. **Explain the lookback window** in one sentence
   *(e.g. "lookback_weeks: 4 — the trend check compares this week against
   the 4-week average, and a dimension value has to be missing from all 4
   of those weeks before a reappearance counts as brand-new")*

4. **Ask for approval:**
   > "Does everything look correct? If yes, I'll save this to
   > `dashboard_validation_framework/registry/[name].yaml`.
   > If any field needs changing, tell me and I'll update the YAML."

---

## PHASE 6 — Save the YAML and the validation summary

Once the user approves (even partially — they can say "save it, I'll fix the VERIFYs later"):

1. Save the YAML to:
   ```
   dashboard_validation_framework/registry/[dashboard_name].yaml
   ```

2. Generate a plain-English companion doc and save it to:
   ```
   dashboard_validation_framework/onboarding/[dashboard_name]_validation_summary.md
   ```
   This is what a reviewer reads before approving the commit — it must
   stand on its own without requiring them to parse YAML. Use this template:

   ```markdown
   # [Dashboard Display Name] — Validation Summary

   Generated by /onboard-dashboard on [today's date].
   Plain-English companion to `registry/[dashboard_name].yaml` — read this
   before committing either file.

   ## What gets validated
   [1–2 sentence description of the dashboard and who uses it]

   ## Metrics checked
   | Metric | Column | Checks | Tolerance | Why this tolerance |
   |---|---|---|---|---|
   | [display name] | `[column]` | reconciliation, trend_sanity | ±X% | [one clause] |

   ## Derived / aiding columns (shown for context — not directly checked)
   <!-- omit this whole section if Phase 2 found none -->
   | Column | Formula |
   |---|---|
   | `[column]` | `[formula]` |

   ## Dimensions & expected values
   | Dimension | Expected values | Completeness checked? |
   |---|---|---|
   | `[column]` | [Value1, Value2, ...] | Yes / No — [reason if No] |

   ## New / unexpected values flagged for review
   <!-- omit this whole section if none were flagged -->
   - `[dimension]`: "[value]" — seen this week only; not yet in
     expected_values. [what the user said in Phase 3, or "awaiting
     confirmation" if still open]

   ## Lookback window
   `lookback_weeks: [N]` — [one sentence, same explanation given in Phase 5]

   ## Checks enabled for this dashboard
   | Check | What it does here |
   |---|---|
   | freshness | Fails if the latest week in the dashboard isn't the run week |
   | reconciliation | Dashboard totals must match source totals within tolerance, per metric |
   | parts_sum | Per-`[pivot_column]` subtotals must reconcile |
   | trend_sanity | Change vs. the `[N]`-week average must stay within ±`[max_wow_change_pct]`% |
   | completeness | All expected `[dimension]` values must appear; new ones get flagged |

   ## Still needs verification before committing
   <!-- omit this whole section if there are no # VERIFY items -->
   - [ ] [VERIFY item, in plain English] — run: `[the exact SQL from Phase 5]`
   ```

3. Run the local test immediately to confirm the YAML parses correctly:
   ```bash
   cd dashboard_validation_framework
   python test_local.py
   ```

4. If the test passes, tell the user:
   > "YAML and validation summary saved. Local test passing.
   >
   > **Next steps:**
   > 1. Read `onboarding/[dashboard_name]_validation_summary.md` and confirm
   >    it matches what you expect this dashboard to be checked against
   > 2. Run the VERIFY SQL queries in Databricks to confirm table names and column names
   > 3. Commit `registry/[dashboard_name].yaml` and the validation summary
   >    to Git — this is the human-approval step. Do not commit the raw
   >    PDF/screenshot from `onboarding/` — it's gitignored on purpose (it
   >    can contain internal contacts and access instructions that don't
   >    belong in git history, and it's already superseded by the summary doc)
   > 4. Import `engine/validator.ipynb` into Databricks and configure the 5 widgets
   > 5. Run the notebook once manually against a recent historical week to confirm PASS
   >
   > See `QUICKSTART.md` Steps 5–7 for the full setup instructions."

5. If the test fails, show the error and fix the YAML (and the summary doc,
   if the fix changes what it describes) before asking the user to proceed.

---

## Hard rules (never break these)

- **Never fabricate a table name.** If the user has not confirmed it, mark it `# VERIFY`.
- **Never add a metric to expected_values for dimensions.** Dimension values are strings; metrics are numbers.
- **Never add a metric you cannot confirm exists** in both dashboard table AND source table.
- **Never ask one question at a time.** Batch all unknowns into Phase 3.
- **Never set tolerance below 0.1%** without the user explicitly requesting it.
- **Never skip the local test** after saving the file.
- **Never commit the file yourself** — always remind the user that committing is their responsibility (human-approval step).
- **Never treat "no glossary was shared" as "no glossary exists."** Ask for it
  (Phase 3, item 9). If the user confirms none exists, proceed with
  `completeness_check: false` on every dimension you're not personally
  confident about, rather than guessing a static list.
- **Never put a derived/calculated ratio in `metrics`.** Visit rate, cost-per-X,
  CPM/CPV, ROMs, and glossary multipliers go in `derived_metrics` (documentation
  only) — reconciling a ratio against a source table's ratio is not meaningful.
- **Never fold a value from the "unexpected / new this week" bucket into
  `expected_values` without the user confirming it in Phase 3.** A single
  screenshot can't distinguish a legitimate new creative/platform from a
  data glitch — that's the user's call, not a guess to make silently.
- **Never skip generating the validation summary `.md`.** It's the artifact
  a non-technical reviewer actually reads before approving the commit —
  treat it as required output, not optional documentation.
- **Never tell the user to commit the raw PDF/screenshot from `onboarding/`.**
  Only the registry YAML and the validation summary belong in git.
