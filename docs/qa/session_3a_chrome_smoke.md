# Session 3a — Chrome Smoke Test (post-merge)

**Date:** 2026-05-23
**Build:** main @ `bcc46b8` (v3.4)
**Tester:** Claude (Cowork) via Chrome connector, Home Desktop browser
**Launcher:** `launcher.py` → `streamlit run streamlit_app/Home.py` on port 8502, headless

## Scope

Walk the four Projects views (Table, Kanban, Timeline, Calendar) on the live v3.4 build, capture console errors and visible regressions before Session 3b begins. This is a smoke test, not full QA — `docs/archive/session_3a_verification.md` (the merge-time verification) remains the authoritative pass record.

## Result summary

| Surface             | Status  | Notes                                                                 |
|---------------------|---------|-----------------------------------------------------------------------|
| Home / Dashboard    | PASS    | KPIs render, AR Aging, Recent Activity, Quick Actions all populate.   |
| Projects > Table    | YELLOW  | Two render bugs + AG Grid module errors (see findings 1-3).           |
| Projects > Kanban   | PASS    | 4 status columns, empty column handled cleanly, dropdowns work.       |
| Projects > Timeline | YELLOW  | Y-axis project labels truncated to 1-2 chars (see finding 4).         |
| Projects > Calendar | PASS    | Month grid renders, today highlighted, month/week/list toggle works.  |

No crashes, no 500s, no broken navigation. All four views load and stay interactive. Issues are cosmetic / configuration, not functional.

## Findings

### 1. Table view — `<span>` HTML leaking into Status cells (RENDER BUG)

The narrow Status column between "Project" and "Client" displays the literal text `<sp` in every row. The HTML span tag intended to render a colored status pill is being HTML-escaped and rendered as text instead of parsed as markup.

- **Reproduce:** Projects page → Table view → look at the second column from left.
- **Likely cause:** an aggrid `cellRenderer` returning an HTML string without the `allowHtml` / `html=True` flag, or a `value_formatter` escaping output. Most likely in the JsCode-style renderer for the status column in `streamlit_app/pages/1_Projects.py` (or the table-view helper module).
- **Severity:** Medium. Functional impact zero (you can still filter and click); cosmetic impact high (the column reads as noise).
- **Fix in 3b subagent 6 (ui-polish):** make the status renderer return HTML correctly. Same change can wire the priority pill from 3b.

### 2. Table view — column headers truncated to one or two characters (UX BUG)

Headers display as `J..`, `S..`, `S..`, `T..` for Job#, Status, Status (?), and Type. Default column widths are too narrow for the header text.

- **Reproduce:** same as above; check column headers.
- **Severity:** Low. Reorderable / resizable by drag, but defaults should be readable.
- **Fix in 3b subagent 6:** set explicit `min_width` per column in the gridOptions and / or enable `autoSizeStrategy: { type: 'fitGridWidth' }` with weighted widths.

### 3. Table view — AG Grid `#200` module-not-registered errors (CONSOLE NOISE)

Three errors logged on every Table view render:

```
AG Grid error #200 — sideBar / SideBarModule not registered
AG Grid error #200 — rowGroupPanelShow / RowGroupingPanelModule not registered
AG Grid error #200 — enableRowGroup / RowGroupingModule not registered
```

The gridOptions reference enterprise features (`sideBar`, `rowGroupPanelShow`, `enableRowGroup`) but the community build of streamlit-aggrid doesn't register them. The grid still functions — just without those features.

- **Severity:** Low. Pure console noise; doesn't block rendering.
- **Fix options:** (a) strip the enterprise options from gridOptions if we don't want them, (b) accept the warnings if we do plan to upgrade to the enterprise build. Subagent 6 can decide.

### 4. Timeline view — Y-axis project labels truncated (LAYOUT BUG)

Project names on the Gantt left axis show as 1-2 character fragments (`o`, `V`, `ir`, `St`, `L1`, etc.). The left padding / label container width is too narrow to fit the project name strings.

- **Reproduce:** Projects → Timeline → look at left edge of the chart.
- **Likely cause:** matplotlib / altair / plotly y-tick label area is auto-sized to a default that doesn't accommodate the actual string lengths. Could also be a fixed pixel width set in the spec.
- **Severity:** Medium. The Timeline view is much less useful without project labels.
- **Fix in 3b subagent 6:** widen the y-axis label region (e.g., `tick.label.padding` / `axis.labelLimit` in altair, or `margin.l` in plotly) to fit the longest project name (~40 chars). Optional: render labels as `<job#> — <short name>`.

### 5. Home — Vega-Lite warnings about empty data ranges (CONSOLE NOISE)

Multiple warnings on Dashboard load:

```
WARN Scale bindings are currently only supported for scales with unbinned, continuous domains.
WARN Dropping "fit-y" because spec has discrete height.
WARN Infinite extent for field "Count_start": [Infinity, -Infinity]
WARN Infinite extent for field "Count_end": [Infinity, -Infinity]
```

The "Infinite extent" warnings indicate a chart receiving an empty dataset and trying to compute a range. Probably the AR Aging chart (all zeros today) or a calendar / cashflow series with no data in the visible window.

- **Severity:** Low. Charts still render (with placeholder / empty state).
- **Fix:** in the chart code, short-circuit and render an "(no data)" placeholder when the source df is empty, instead of handing an empty df to Vega.

## Confirmed working

- Sidebar navigation (Home / Projects / Billing / Permits / CRM / Timekeeping / Financials / Bids / Calculator / Accounting)
- Login session persisting (no re-auth prompt)
- Status pill filters (All / Active / Prospect / On Hold / Completed / Archived)
- Search bar
- View switcher between all four view modes
- "Show archived" toggle
- Calendar month / week / list view toggle
- Kanban empty-state ("Empty" in zero-count columns)
- Today's date (May 23) highlighted in calendar

## Next session impact

All findings are queued for Session 3b's **subagent 6 (ui-polish)**. The existing 3b prompt already calls for column additions (priority, action_by, next_action, percent_complete); the fixes above slot in alongside that work. No new subagent needed — just expand 6's scope.

The 3b prompt has been updated to reference this doc.

---

## Addendum � pytest finding from 2026-05-23 cleanup verification

### 6. `test_list_project_activity_paginates` is wall-clock-dependent (FLAKY TEST)

After the cleanup commit, `python -m pytest -q` reported 133 passed, 1 failed. The failing test is **not** affected by the cleanup (the diff only moves archived files; no code or test files changed). Re-running the single test in isolation also fails consistently � confirming it is timing-dependent, not a regression.

**Root cause.** `modules/projects/crud.py::_now()` uses `datetime.utcnow()` to stamp `create_project()` rows. The test `tests/test_projects_activity.py::test_list_project_activity_paginates` inserts 25 `updated` rows with hard-coded timestamps `2026-05-23 12:00:00` through `2026-05-23 12:24:00`, then asserts that the create row (sorted DESC by `created_at`) lands at the bottom of page 2. That assertion only holds while the `created_at` of the create row is **before** `12:00:00 UTC`. After 12:00 UTC (08:00 EDT), the create row sorts ahead of one or more update rows, pushing an `updated` row into the page-2 slot instead.

**Severity.** Low � pure test-side bug, no application defect.

**Fix.** Two options for Session 3b's verifier subagent to apply:

- (preferred) Hand the create row an explicit timestamp older than `12:00:00` via the test setup, e.g., by mocking `_now()` to return `2026-05-23 11:00:00` during the `create_project()` call. Eliminates wall-clock dependence entirely.
- (alternative) Shift the test's hard-coded timestamps far into the future (e.g., `2030-01-01 12:00:00`+) so the create row is always older than any inserted row.

While Session 3b is touching `modules/projects/crud.py::_now()` anyway (status workflow + user-update logging), it's the right moment to also switch from deprecated `utcnow()` to `datetime.now(datetime.UTC)` � the deprecation warning is already firing in CI.
