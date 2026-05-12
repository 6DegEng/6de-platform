# Changelog

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
