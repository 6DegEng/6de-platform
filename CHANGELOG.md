# Changelog

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
