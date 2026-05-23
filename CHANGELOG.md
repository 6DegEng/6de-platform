# Changelog

## Session 3a — Projects page UI uplift — 2026-05-23

The Projects page goes from a single vertical-expander list to a Monday-style 4-view board: Table / Kanban / Timeline / Calendar. Pilot module — the same pattern is planned for CRM, Bids, and Permits in later sessions.

### Architecture changes
- **Project fetch collapsed from 6× per rerun to 1×.** Old structure ran `list_projects()` inside each of 6 status tabs every rerun; new structure fetches once at the top of the page and filters in memory per view.
- **`ui:projects:*` session_state namespace** for persistent UI state across reruns: `view`, `focus`, `status_filter`, `expanded`, `_test_visible_ids`. Browser-reload (localStorage) deliberately out of scope.
- **New shared component:** `streamlit_app/components/status_pills.py` — single source of truth for `PROJECT_STATUSES`, `PROJECT_STATUS_COLORS`, `PROJECT_STATUS_LABELS`, and `render_status_pill(status)`. Page-local `_STATUS_COLORS` / `_STATUS_ICONS` dicts removed.
- **Color palette aligned to the prompt's hex codes globally:** `#1FBA66` active, `#F7B500` prospect, `#A85FFF` on_hold, `#9CA3AF` completed, `#374151` archived. Replaces the previous `formatters.py` palette across all consumers (not just Projects page).

### Table view (`f248467`)
- streamlit-aggrid grid, 520px tall, floating filter row, every column sortable.
- 9 editable columns: name, status (dropdown), address, city, county, scope, start_date (date editor), target_end_date (date editor), notes. job_number and client_name read-only.
- Status changes validated against `PROJECT_STATUSES` pre-DB; all saves flow through `modules/projects/crud.py:update_project()` which writes `activity_log` via the standard pattern.
- Status cell renders as a colored HTML pill via JsCode cellRenderer.
- Row deletion disabled (guardrail); mass-paste row creation disabled.
- Click a row → sets `ui:projects:focus = pid`; the detail panel below renders with the full 6-tab project view (`← Close` button keyed `t0_p{pid}` to dismiss).
- New module: `streamlit_app/components/project_grid.py` (`render_project_grid`, `handle_row_save`, `diff_row`, `projects_to_dataframe`, column-config tuples).

### Kanban view (`2cd7b3e`)
- One column per status (5 with "Show archived" toggle on, 4 with off — default). Cards show job_number, name (truncated to 40), client, target close.
- Per-card `st.selectbox` for status changes. Routes through `update_project()`.
- **DnD fallback explanation:** `streamlit-sortables 0.3.1` only accepts `list[str]` items; cannot render the rich card layout. Real cross-column DnD would need a custom Streamlit component (~1 day; filed as deferred TODO).
- Card styling: 4px colored left border in the status color, light gray background, padding 8px 12px, border-radius 4px.

### Timeline view (`afcf699`)
- Plotly Gantt-style; bars colored by status, sorted by `start_date` ascending.
- NULL handling: both NULL → omitted with footer count; only target → 1-day point at target; only start → open-ended bar from start_date to today.
- Today marker via red dashed `add_shape` vertical line.
- Click-to-open fallback: below-chart selectbox with `None` sentinel (Plotly events under Streamlit are unreliable).
- Added `plotly>=5.0,<7` to requirements.txt.

### Calendar view (`af891a9`, post-Gate 4)
- Real `streamlit-calendar` 1.4.0 FullCalendar integration.
- Each project surfaces as a `target_close` event (colored by status) + optional `start_date` event (▶-prefixed title) when start ≠ target.
- `eventClick` callback returns `extendedProps.project_id` → flips `ui:projects:focus`.
- Honors status segmented control + new "Show archived" checkbox.
- Header toolbar: prev/next/today, month/week/list views.

### Activity panel (`4fe2bc2`)
- 6th tab "Activity" on every project's detail view.
- New module: `modules/projects/activity.py` — `list_project_activity`, `count_project_activity`, `summarize_activity`. Milestone events folded in by default (toggleable) via `entity_id IN (SELECT id FROM milestones WHERE project_id=?)` — milestone-update payloads don't carry `project_id` so the JSON-extract subquery would miss them.
- Per scout §3: there is **no** `status_change` action — status changes are bundled into `action='updated'` with `"status"` in details. `summarize_activity()` recognizes that pattern explicitly.
- 25-row pagination. Details expander only appears for payloads with >3 keys (avoids noise on routine status changes).
- New module: `streamlit_app/components/activity_panel.py` (`render_activity_panel`).

### Dependencies (`578bdc5`, `bddb561`, `afcf699`)
- Added: `streamlit-aggrid>=1.2,<2`, `streamlit-sortables>=0.3,<1`, `streamlit-calendar>=1.4,<2`, `plotly>=5.0,<7`.
- Dropped: `streamlit-elements` — Gate 2 health-check found it RED (~32 months stale at v0.1.0). View-switcher uses `st.radio(horizontal=True)` per scout §9; no other downstream usage emerged.
- Side effect of `pip install -r requirements.txt`: env was drifted out-of-band, so `pandas 3.0.2 → 2.3.3` and `cryptography 48.0.0 → 45.0.7` got pulled back to the pins. No test regressions.

### Tests (`f2f1dbe`, `f248467`, `2cd7b3e`, `4fe2bc2`, `2b81d70`)
- Baseline: 110/110 pre-session → **134/134 post-session** (+24 net new).
- 4 required service-layer tests in `tests/test_projects_inline_edit.py` (routes-through-update_project, rejects-invalid-status, emits-activity_log, no-change-is-noop) + 3 `diff_row` unit tests.
- 4 Kanban tests in `tests/test_projects_kanban.py` (status-change-routes-through, show-archived-filter, rejects-invalid-status, statuses-match-schema).
- 7 activity tests in `tests/test_projects_activity.py` (returns-project-rows, paginates, milestone-flag, count-matches-list, status-change-summary, null-details-handled, milestone-completed-summary).
- 6 AppTest e2e smokes in `tests/test_3a_e2e_smoke.py` (view-switch-default, switch-to-kanban, switch-to-timeline, switch-to-calendar, detail-panel-6-tabs, view-persists-across-rerun).
- 3 expander-DOM tests in `tests/test_projects_search.py` rewritten to read `st.session_state["ui:projects:_test_visible_ids"]` (Gate 1 decision); structural Phase B test and 4 CRUD-layer tests untouched.

### Process notes
- **7-subagent sequential pipeline** with 4 gates (scout findings, dep-health, Table-view demo, final handoff). Gates worked — Gate 2 caught the streamlit-elements stale-dep and produced a no-impact drop; Gate 3 demo confirmed Table view before Kanban/Timeline shipped; Gate 4 produced the Calendar follow-up.
- Scout report at `docs/specs/3a_scout.md` (639 lines) was load-bearing — every subagent referenced it for service-layer surfaces, status enum source-of-truth, st.rerun risks, and palette decisions.
- Verification report at `docs/qa/session_3a_verification.md`.

### Deferred
- Real cross-column Kanban DnD (custom React component, ~1 day) — selectbox fallback works.
- Plotly bar-click-to-open — Plotly events under Streamlit are unreliable; below-chart selectbox is the workaround.
- Latent AppTest fixture bug: `PLATFORM_DB_PATH` env var read at import time defeats `monkeypatch.setenv` — AppTest tests effectively run against the live DB. Not 3a's bug.
- `datetime.utcnow()` deprecation in `modules/projects/crud.py:21` (31 warnings) — pre-existing; one-line fix on next CRUD touch.

### Version
- Bumped to v3.4 in `streamlit_app/Home.py`.

---

## Phase 2 — SharePoint Document Layer — 2026-05-22

Three back-to-back sessions stand up the SharePoint-as-document-store contract from `PLATFORM_GOAL_v1.md` Phase 2. Foundation → offline scaffolding + UI → live wire-up. The platform now writes generated PDFs to a real SharePoint document library via Microsoft Graph; the Documents tab on each project renders SharePoint URLs (or OneDrive paths for backfilled rows) and degrades gracefully when the Entra ID app reg is missing.

### Session 2a — module scaffold + stub auth boundary

- `modules/documents/sharepoint.py`: `get_graph_client()` boundary returns real `GraphServiceClient` when `MSGRAPH_CLIENT_ID` + `MSGRAPH_TENANT_ID` are set, otherwise `StubGraphClient` for offline dev.
- `_TokenStore`: Fernet-encrypted refresh-token persistence at `MSGRAPH_TOKEN_PATH`; key from `SIXDE_TOKEN_KEY`.
- `sanitize_filename` (Windows-illegal chars, whitespace normalization, 128-char segment cap), `encode_path` (preserves the intentional leading space in `01_ Active Projects`, percent-encodes at the Graph boundary).
- `upload_bytes` / `upload_large` / `get_link` / `delete` / `list_folder` / `ensure_project_folder` stub path complete; real-Graph branches raise `NotImplementedError` pointing to Session 2c.
- `record_upload` inserts `documents` row + writes `activity_log` from day one (S36 B4 directive).
- `documents` table gains `sharepoint_item_id`, `sharepoint_web_url`, `sharepoint_drive_id`, `sha256` via `_ALTER_COLUMNS`.
- 43 new unit tests (sanitization adversarials, path encoding, Fernet roundtrip, schema delta).

### Session 2b — backfill scanner + Documents tab

- `scripts/scan_existing_project_docs.py`: one-shot walker over the existing `06_Engineering/01_ Active Projects/` tree. Matches `{6-digit} - {name}` folders against `projects.job_number`, classifies each file via `classify_category()` into Calcs/Drawings/Permits/Billing/Correspondence, indexes metadata into `documents` without uploading. Idempotent. Writes one `activity_log` row per `--commit` run.
- `classify_category()` heuristic map confirmed against real subfolder names ("Drainage Calculations", "Dwgs", "PPT", "Geotechnical Engineering", etc.) — 26 mapping cases unit-tested.
- Documents tab on each project in `pages/1_Projects.py`: category-grouped listing, SharePoint URLs when populated, OneDrive-path fallback for backfilled rows, "SharePoint not configured" caption when env vars absent.
- B22: confirmed `__pycache__/` already in `.gitignore`; sweep ran clean.

### Session 2c — real msgraph-sdk wire-up

- Replaced `NotImplementedError` in 6 `RealGraphClient` methods with live Microsoft Graph calls (msgraph-sdk 1.58.0).
- Site/drive resolution: cached at module load via `client.sites.get_by_path(...).drive.get()`; new config keys `SIXDE_GRAPH_HOSTNAME` (default `6thdegreeengineering.sharepoint.com`) and `SIXDE_GRAPH_SITE_PATH` (default `/sites/6thDegreeEngineering`).
- `_ensure_folder`: `conflictBehavior=fail` + 409→GET fallback (NOT `rename` — would create `Calcs 1`, `Calcs 2` on re-runs).
- `_driveitem_to_dict()` projection at the SDK boundary keeps the camelCase dict contract — every caller (record_upload, Documents tab) is unchanged.
- New `DocumentMissingError(RuntimeError)` for 404 ODataErrors on `get_link()` / `delete()`. Callers wanting idempotent delete `except DocumentMissingError: pass`.
- `retry_with_backoff_async` wraps the 4 mutating methods. Structured detection via `ODataError.response_status_code` (429 or any 5xx) with string-match fallback. Honors `Retry-After` header (capped at `max_delay`); otherwise exponential schedule + jitter. Uses `asyncio.sleep` so the graph loop thread isn't blocked.
- Persistent event loop via a daemon thread (`_get_graph_loop` / `_run_on_graph_loop`) — fixes the proactor-cleanup race that crashed `get_link` after a successful upload on Windows because msgraph-sdk/MSAL/kiota bind to the first loop that touches them.
- Auth: dropped `offline_access` from explicit scopes (MSAL ≥1.36 raises on reserved scopes; refresh-token issuance is unaffected — MSAL adds it implicitly).
- `python-dotenv` loaded at startup so `.env` reaches the launcher process.
- 5 new retry/backoff unit tests using a fake `ODataError`; `asyncio.sleep` monkey-patched to a capturing no-op so tests don't actually sleep.
- Live smoke driver at `scripts/smoke_sharepoint_upload.py` round-trips a 1KB payload through upload → get_link → list_folder → delete → 404-check against the production tenant. This is the live-tier evidence; pytest-marked live test deferred.
- Verifier spec at `docs/specs/sharepoint_session_2c.md` documents the 9 stub-vs-SDK mismatches and the resolutions Juan picked.

### Tests
- 110/110 platform tests pass at Phase 2 close. Stub path remains the default when env vars are unset; every existing test still exercises it.

### Out of scope (filed for future sessions)
- `tests/test_sharepoint_live.py` (pytest-gated live test) — smoke script substitutes for now.
- `scripts/scan_existing_project_docs.py` against live SharePoint — manual single-file UI upload preferred for first prod-tier validation.
- streamlit-authenticator JWT key length (cosmetic warning), 12 completed projects still in active-projects folder, 3 disk-only projects missing from DB, 31 unclassified subfolder names — all in `docs/qa/session_2c_blocked.md` §TODOs.

### Version
- Bumped to v3.3 in `streamlit_app/Home.py`.

---

## Session 35 — 2026-05-14

### Bug Fixes (Critical)
- B24: Fixed `/Projects` crash from duplicate `st.form` keys when a project appears in both "All" and its status tab. Namespaced all edit-tab widget keys by `t{tab_idx}_p{pid}`.
- B25: Fixed `/Calculator` "common.db not found" by replacing hardcoded `C:\Users\juanc\...` with `Path.home()` in `config.py`. Improved user-facing error message with resolved path and env var hint.
- B26: Guarded empty-data bar charts on `/Home` to prevent Vega-Lite `Infinite extent` console warnings.

### Bug Fixes (Carryover)
- B8: Changed "+N this month" delta query from `created_at` (reflects import date) to `start_date` (reflects actual project start). Only counts active projects.
- B10: Consolidated dual Outstanding metric cards into one (Row 1), using the higher of invoice-based and project-based outstanding. Replaced the duplicate in Row 1c with Active Rate.

### Engineering Section (New)
- Renamed `8_Calculator.py` to Engineering page with three top-level tabs: Calculators, Package Auditor, Required-Checks Library.
- Created `calc_required_checks` table in `schema.sql` with 19 seeded IBC/ASCE/NDS code checks across 6 structure types (Glass Railing, Wall-Mounted Handrail, Steel Stair, Post-installed Anchor, Wood Connection).
- `modules/calculator/required_checks.py`: Seed data and idempotent loader.
- `modules/calculator/auditor.py`: `audit_calc_project()` compares calc outputs against required checks, produces `AuditReport` with pass/missing/weak findings. Conservative matching: code_ref + keyword matching.
- `modules/calculator/cover_sheet.py`: Generates Markdown cover sheet from ERP project + calc project + audit results + PE profile.
- Package Auditor tab: select linked project, run audit, view findings with red/yellow/green status, download report as `.md`.
- Required-Checks Library tab: browse all checks by structure type, add new checks via form.

### UI & Polish
- Centralized empty-state copy in `formatters.empty_state(kind)` — 9 entity types with actionable messages (B20 partial).
- Version bumped to v3.2.

### Tests
- 4 new smoke tests: `calc_required_checks` table exists, seed idempotency (re-seed produces same count, >=19), unique constraint, B24 regression guard (static scan for un-namespaced widget keys).
- All 9 tests pass.

## Session 33 — 2026-05-12

### Research & Roadmap (Phases 1-2)
- 6 parallel research agents: competitor scan, FL regulatory workflows, code audit, manual workflow audit, reference architecture review, plugin scaffolding
- 3-person synthesis team (Architect → Skeptic → Builder) produced `ROADMAP_v1.md` with 28 items classified into Now/Next/Later/Never
- Plugin architecture decision: LATER (flat modules/ works at current scale)

### Bug Fixes (Preflight)
- B1: Fixed calc bridge `address` → `project_address` column name; added `client_name` and `code_basis` fields
- B2: Fixed Financials page `Styler.rename` crash — reordered to `df.rename().style.format()`

### Y: Dependencies & Test Scaffolding
- Created `requirements.txt` with pinned dependency ranges
- Added `tests/test_smoke.py` with 5 smoke tests covering schema init, transaction dedup, invoice numbering, source column migration
- Added `transactions.source` column (TEXT DEFAULT 'excel_sync') for Z/B dedup mitigation

### AA: Authentication Layer
- `streamlit-authenticator` with bcrypt password hashing, cookie-based sessions (30-day expiry)
- Two roles: `admin` (Juan) and `viewer` — credentials in gitignored `auth_config.yaml`
- `streamlit_app/auth.py`: shared `require_auth()` gate, `show_logout_button()`, `get_current_role()`
- Auth wired into all 10 pages (Home + 9 subpages) — platform now requires login
- Version bumped to v3.1

### Z: Nightly Accounting Sync
- `scripts/sync_accounting.py`: SHA-256 hash-based change detection, reuses existing importers
- State tracked in `db/.sync_state.json`, dual logging to file + console
- Tags all synced transactions with `source = 'excel_sync'` for dedup safety
- Windows Task Scheduler setup instructions included

### C: Transaction Categorization Rules Engine
- `categorization_rules` table with pattern (regex), category, priority, active flag
- `modules/accounting/categorization.py`: 31 rules ported from VBA macro, `categorize_transaction()`, `categorize_all_uncategorized()`, auto-seeded on DB init
- New "Categorization" tab on Accounting page: summary metrics, Needs Review queue, pattern tester, full rules CRUD

### G: AR Aging Dashboard
- AR aging widget on Home dashboard with 6 colored metric cards (Current through 90+ days)
- Top delinquent clients callout when 90+ bucket > $0
- Uses existing `v_ar_aging` view and `get_ar_aging_summary()` from invoicing module

## Session 32 — 2026-05-12

### Relocated
- Moved platform from `06_Engineering/02_Services Library/01_Dev/03_Company_Platform/`
  to `02_Information Technology/07_Company_Platform/` (new dedicated git repo)
- Created `config.py` with environment-variable-driven paths for all external databases and the calculator exe

### Calculator Integration (Task 2)
- `1_Projects.py`: Added "Calculations" tab per project with linked calc outputs (pass/fail, standards, steps), "Open in Calculator" launch button, and "Link Calculator Project" form
- `8_Calculator.py`: Enhanced linked details with step-level drill-down, timestamps, and refresh button
- `modules/calculator/bridge.py`: Added `timestamp` and `steps` to calc output results

### Accounting (Task 3)
- Added `transactions`, `recurring_expenses`, `project_revenue` tables and `v_cashflow_monthly` view
- Added ALTER TABLE extensions: `projects.contract_value`, `amount_paid`, `outstanding_balance`, `cogs`, `profit`, `percent_complete`, `priority`, `action_by`, `next_action`; `clients.ytd_revenue`, `service_type`
- New `9_Accounting.py` page: Transactions (filterable table), Cashflow (monthly chart + category breakdown), Recurring Expenses (CRUD)
- Dashboard now shows Income/Expenses/Net YTD from transactions, recurring monthly burn, project outstanding

### Data Import (Task 4)
- `scripts/importers/import_project_tracker.py`: 65 projects, 62 proposals, 60 clients from `Project_Tracker_2026.xlsx`
- `scripts/importers/import_accounting.py`: 489 transactions, 38 project revenue snapshots, 8 recurring expenses from `Accounting_6DE_2026.xlsm`
- `scripts/importers/import_all.py`: Orchestrator with reconciliation report
- Dashboard now populated with live numbers (was previously all zeros)

### Dashboard Enhancements
- Three metric rows: Key Metrics, Financial Metrics (income/expenses/net/burn), Pipeline & Bids
- Recurring expense due-soon alerts in the alerts section
- Accounting quick action button
- Version bumped to v3.0
