# Changelog

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
