# Bank CSV Import -- Phase 0 Spec (v1)

**Date:** 2026-05-24
**Branch:** `feature/bank-csv-import`
**Status:** Phase 0 -- CSV import only. Plaid is deferred to Phase 1.

---

## 1. Schema Additions

The platform uses a single `db/schema.sql` file with idempotent `CREATE TABLE IF NOT EXISTS` and an `_ALTER_COLUMNS` list in `db/__init__.py` for incremental column additions. No separate migration files. New schema objects follow the same pattern.

### 1.1 `bank_connections` (new table)

Tracks import sources. For Phase 0, `source` is always `'csv'`.

```sql
CREATE TABLE IF NOT EXISTS bank_connections (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT    NOT NULL DEFAULT 'csv',   -- 'csv' | 'plaid' | 'manual'
    institution_name  TEXT,                             -- e.g. 'Bank of America'
    account_mask      TEXT,                             -- last 4 digits
    account_type      TEXT,                             -- 'checking' | 'savings' | 'credit'
    status            TEXT    NOT NULL DEFAULT 'active',
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

### 1.2 `sync_runs` (new table)

Audit trail for each CSV upload (and later, each Plaid sync).

```sql
CREATE TABLE IF NOT EXISTS sync_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_connection_id  INTEGER REFERENCES bank_connections(id),
    started_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at        TEXT,
    transactions_added  INTEGER DEFAULT 0,
    transactions_updated INTEGER DEFAULT 0,
    file_name           TEXT,
    error_message       TEXT
);
```

### 1.3 `transactions` extensions (ALTER COLUMN additions)

Added via `_ALTER_COLUMNS` in `db/__init__.py`:

| Column | Type | Purpose |
|--------|------|---------|
| `source` | `TEXT DEFAULT 'excel_sync'` | **Already exists.** Values: `'excel_sync'`, `'csv'`, `'plaid'`, `'manual'` |
| `external_id` | `TEXT` | Dedup key for Plaid (Phase 1). For CSV: row hash |
| `bank_connection_id` | `INTEGER` | FK to `bank_connections.id` |
| `auto_categorized` | `INTEGER DEFAULT 0` | 1 if categorization engine assigned the category |
| `needs_review` | `INTEGER DEFAULT 0` | 1 if no rule matched (uncategorized) |
| `sync_run_id` | `INTEGER` | FK to `sync_runs.id` for traceability |

### 1.4 `categorization_rules` (already exists)

No changes needed. The existing table and engine are reused as-is.

---

## 2. BofA CSV Column Mapping

Bank of America online banking exports CSV with these columns:

| BofA CSV Column | Our Schema Column | Notes |
|-----------------|-------------------|-------|
| `Date` | `txn_date` | Format: `MM/DD/YYYY`. Parse to `YYYY-MM-DD` |
| `Description` | `description` | Free text, used for categorization matching |
| `Amount` | `amount` | Negative = debit/expense, positive = credit/income |
| `Running Bal.` | `balance` | Running balance after transaction |

The BofA CSV has no header row in some exports -- the parser detects this by checking if the first row's first field parses as a date.

Additional derived fields:
- `account`: Set to the `institution_name` + `account_mask` from the selected `bank_connection`
- `account_type`: `'Debit'` if amount < 0, `'Credit'` if amount >= 0
- `txn_type`: Derived from description keywords (e.g., "ZELLE", "ATM", "CHECK")
- `month`: Extracted from `txn_date` as integer (1-12)
- `source`: Always `'csv'` for this phase
- `expense_category`: Filled by categorization engine

---

## 3. Categorization Rules Matching Algorithm

The existing engine in `modules/accounting/categorization.py` is reused:

1. Load all active rules from `categorization_rules` table, ordered by `priority ASC`, then `id ASC`
2. For each transaction's `description`:
   a. Iterate rules in priority order
   b. `re.search(pattern, description, re.IGNORECASE)`
   c. First match wins -- assign that rule's `category` to `expense_category`
   d. Set `auto_categorized = 1`
3. If no rule matches:
   a. Leave `expense_category` as NULL
   b. Set `needs_review = 1`

The VBA-ported default rules (40+ patterns) are already seeded at DB init.

---

## 4. CSV Parser Design

Module: `modules/banking/csv_import.py`

### `parse_bofa_csv(file_content: str | BinaryIO) -> list[dict]`

1. Read CSV content (handle both file paths and uploaded file objects)
2. Detect header row: if first row contains "Date" or "Description", skip it
3. For each data row:
   - Parse date from MM/DD/YYYY to YYYY-MM-DD
   - Parse amount as float (handle commas in numbers)
   - Parse running balance as float
   - Clean description (strip whitespace, normalize Unicode)
4. Skip empty/malformed rows with warnings
5. Return list of dicts with keys: `txn_date`, `description`, `amount`, `balance`

### `categorize(transactions: list[dict], conn: Connection) -> list[dict]`

1. For each transaction dict, call `categorize_transaction(conn, description)`
2. Set `expense_category`, `auto_categorized`, `needs_review` accordingly
3. Return enriched list

### `compute_row_hash(txn: dict) -> str`

SHA-256 of `f"{txn_date}|{amount}|{description}"` -- used as `external_id` for dedup.

### `commit_transactions(conn, transactions, sync_run_id, bank_connection_id) -> int`

1. For each transaction:
   - Check for duplicate via `external_id` or existing UNIQUE constraint
   - INSERT OR IGNORE
2. Return count of rows actually inserted

---

## 5. UI Integration in 9_Accounting.py

### Location

Add a new tab "CSV Import" to the existing tab bar at line 112:

```python
tab_txn, tab_cashflow, tab_recurring, tab_categorization, tab_csv_import = st.tabs(
    ["Transactions", "Cashflow", "Recurring Expenses", "Categorization", "CSV Import"]
)
```

This is at line 112, well beyond the forbidden lines 1-30.

### CSV Import Tab Flow

1. **Bank Connection Setup** (one-time)
   - Selectbox for institution (default "Bank of America")
   - Text input for account last-4 digits
   - Account type radio (Checking / Savings / Credit)
   - Save button creates/updates `bank_connections` row

2. **File Upload**
   - `st.file_uploader("Upload BofA CSV", type=["csv"])`
   - On upload: parse immediately, show preview

3. **Preview Table**
   - DataFrame showing parsed transactions with columns:
     Date, Description, Amount, Balance, Category (auto-assigned), Review?
   - Color-code: green = auto-categorized, yellow = needs review
   - Summary metrics: total rows, categorized count, needs-review count, date range

4. **Confirm & Import**
   - Button: "Import N Transactions"
   - On click: write to DB, create sync_run record, show success
   - Duplicate handling: show count of skipped duplicates

5. **Import History**
   - Table of past sync_runs: date, file name, rows added, rows skipped

---

## 6. Dedup Strategy

Two-layer dedup:
1. **Row hash** (`external_id`): SHA-256 of date+amount+description. Prevents re-importing the same CSV.
2. **Existing UNIQUE constraint**: `(txn_date, amount, description)` on transactions table. INSERT OR IGNORE skips collisions.

---

## 7. Blockers

- **No real BofA CSV sample** exists at `samples/bofa_sample.csv`. Parser built against known BofA format documentation. Testing uses synthetic data matching the format. A real sample should be added (with PII scrubbed) for validation.

---

## 8. Future Work (Phase 1+)

- Plaid integration as `source='plaid'` via the same `bank_connections` / `sync_runs` model
- Auto-reconciliation: match incoming payments against open invoices
- AI-assisted categorization for ambiguous transactions
- Multi-account support with per-account dashboards
