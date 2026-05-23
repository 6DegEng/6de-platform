# Session 32 Notes — 2026-05-12

## What Worked

- **Platform relocation** went smoothly. `config.py` with env-var defaults eliminates all hard-coded relative paths. The old `01_Dev` repo was cleaned up with `git rm`.
- **Excel importers** successfully loaded real data on the first run (after fixing openpyxl read-only mode issues). The `import_all.py` orchestrator handles dependency order correctly.
- **Data quality** is solid: 65 real projects + 53 prospect stubs from proposals match the Excel tracker. 489 of 501 valid transaction rows imported (12 were deduped by UNIQUE constraint).
- **Parallel agent development** again cut the build time significantly — importers, accounting page, and calculator integration were built simultaneously.

## What Didn't Work (and fixes)

- **openpyxl `read_only=True` with `.xlsm`**: `EmptyCell` objects lack the `.row` attribute, causing `AttributeError`. Fixed by using `getattr(cell, "row", fallback)` and pre-loading rows into lists for the recurring expenses parser.
- **Recurring expenses sub-table detection**: The phrase "renews annually" in an E&O insurance note matched the "yearly" keyword, causing the detector to pick the wrong header row. Fixed by requiring both "recurring" AND "yearly/monthly" in the match.
- **Transaction match rate** is only 2% — most transaction descriptions don't contain 6-digit project numbers. This is expected for general operating expenses (rent, software, insurance). Project-linked transactions (invoices paid by clients with project references in the description) do match.
- **Port 8502 in use** from the old session. Had to kill the old process before relaunching from the new location.

## Follow-Up Decisions (Task 5)

### 1. Decommission Excel Workbooks
**Recommendation:** Yes, once Juan confirms parity. Archive to `00_Archive/` with date stamp. Add a banner row in each saying "READ-ONLY — superseded by ERP."
**Status:** Awaiting Juan's review of imported data vs. Excel totals.

### 2. Bi-directional Sync vs. One-Shot Import
**Recommendation:** One-shot import (option A — single source of truth in ERP). The accounting workbook may still be touched by the accountant; if so, build a one-way re-sync that only adds new transactions (the UNIQUE constraint already handles this). Don't build two-way sync.
**Status:** Decision needed from Juan about accountant workflow.

### 3. Outlook / Banking Integration
**Noted as future task.** Pulling transactions directly from bank API (Plaid or similar) would eliminate the Excel middleman entirely. Not urgent — the current quarterly import is sufficient.

### 4. Auth / Multi-User
**Critical before sharing.** Options: (a) Streamlit built-in auth (`st.secrets` with password), (b) reverse proxy with basic auth, (c) Azure AD SSO if deploying to cloud. For a single-user firm, (a) is sufficient.
**Status:** Not implemented. Required before the platform leaves Juan's machine.

### 5. Backups
**Recommendation:** Add a daily copy script: `cp platform.db → 02_IT/00_Archive/platform_backups/YYYY-MM-DD.db`. Can be a Windows Task Scheduler job or a Python script in `scripts/backup.py`. The DB is ~250KB currently — daily copies are trivial.
**Status:** Not implemented. Should be set up before going into production.

## Calculator Integration Assessment (Task 2c)

**Can we embed calc modules directly as Streamlit pages?**

Yes — the calc engine is already Streamlit-based (`structural/streamlit_app/main.py`, `drainage/streamlit_app/forms/drainage_main.py`, `inspection/streamlit_app/forms/sirs_main.py`). It runs on port 8501 via PyWebView, and its UI is standard Streamlit with `st.form`, `st.tabs`, and `st.columns`.

**However, I recommend NOT doing this yet.** Reasons:
1. The calc engine manages its own database state (`common.db`, `structural.db`) independently. Merging UIs without merging the data layer would create two sources of truth.
2. The calc modules have deep import chains (`common/pdf_generator.py`, `common/calc_emission.py`, `common/citations.py`) that assume a specific `sys.path` structure rooted at `01_Python Calc Engine/`.
3. The `--preselect_scope` flag suggests the calc UI has session-state patterns that may conflict with the ERP's page routing.
4. The current bridge pattern (read-only from common.db + launch button for the exe) is clean and low-risk.

**Recommended path:** Keep the bridge pattern for now. When the calc engine is mature enough to share a UI, refactor it as a proper Python package with `setup.py`/`pyproject.toml` and install it into the ERP's environment.

## Counts Summary

| Entity | Count |
|---|---|
| Projects | 118 (45 active, 53 prospect, 20 completed) |
| Clients | 60 |
| Proposals | 62 ($406,500 total) |
| Transactions | 489 |
| Project Revenue | 38 snapshots |
| Recurring Expenses | 8 |
| Income YTD | $93,133 |
| Expenses YTD | $73,288 |
| Net Cashflow YTD | $19,846 |
| Monthly Burn | $1,694 |
