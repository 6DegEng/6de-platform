"""Integration test: CSV parse -> categorize -> commit round-trip.

Tests the full pipeline from raw CSV text to rows in the transactions
table, including dedup on re-import.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.banking.csv_import import (
    parse_bofa_csv,
    categorize as categorize_parsed,
    commit_transactions,
    create_sync_run,
    complete_sync_run,
    get_or_create_bank_connection,
    get_sync_history,
)
from modules.accounting.categorization import seed_rules_from_vba


@pytest.fixture
def db():
    """In-memory DB with all required tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE categorization_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 100,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE bank_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'csv',
            institution_name TEXT,
            account_mask TEXT,
            account_type TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bank_connection_id INTEGER REFERENCES bank_connections(id),
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT,
            transactions_added INTEGER DEFAULT 0,
            transactions_updated INTEGER DEFAULT 0,
            file_name TEXT,
            error_message TEXT
        );

        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            txn_date TEXT NOT NULL,
            account TEXT,
            account_type TEXT,
            description TEXT,
            amount REAL NOT NULL,
            balance REAL,
            expense_category TEXT,
            txn_type TEXT,
            project_id INTEGER,
            month INTEGER,
            source_row INTEGER,
            imported_at TEXT NOT NULL DEFAULT (datetime('now')),
            source TEXT DEFAULT 'excel_sync',
            external_id TEXT,
            bank_connection_id INTEGER,
            auto_categorized INTEGER DEFAULT 0,
            needs_review INTEGER DEFAULT 0,
            sync_run_id INTEGER,
            UNIQUE (txn_date, amount, description)
        );
    """)
    seed_rules_from_vba(conn)
    yield conn
    conn.close()


SAMPLE_CSV = (
    "Date,Description,Amount,Running Bal.\n"
    "05/01/2026,ZELLE PAYMENT FROM JOHN DOE,2500.00,15000.00\n"
    "05/02/2026,UBER EATS ORDER,-32.50,14967.50\n"
    "05/03/2026,MICROSOFT 365 SUBSCRIPTION,-22.00,14945.50\n"
    "05/04/2026,COMPLETELY UNKNOWN VENDOR,-99.99,14845.51\n"
    "05/05/2026,PUBLIX SUPER MARKETS,-45.67,14799.84\n"
)


class TestFullRoundTrip:
    def test_parse_categorize_commit(self, db):
        """Full pipeline: parse -> categorize -> commit -> verify DB rows."""
        # 1. Parse
        txns, warnings = parse_bofa_csv(SAMPLE_CSV)
        assert len(txns) == 5
        assert len(warnings) == 0

        # 2. Categorize
        txns = categorize_parsed(txns, db)

        # Verify categorization results
        cats = {t["description"]: t.get("expense_category") for t in txns}
        assert cats["ZELLE PAYMENT FROM JOHN DOE"] == "Engineering Revenue"
        assert cats["UBER EATS ORDER"] == "Meals & Entertainment"
        assert cats["MICROSOFT 365 SUBSCRIPTION"] == "Software Subscriptions"
        assert cats["COMPLETELY UNKNOWN VENDOR"] is None
        assert cats["PUBLIX SUPER MARKETS"] == "Office Groceries"

        # 3. Create bank connection + sync run
        bc_id = get_or_create_bank_connection(db, "Bank of America", "1234", "checking")
        run_id = create_sync_run(db, bc_id, "test_sample.csv")

        # 4. Commit
        inserted, skipped = commit_transactions(db, txns, run_id, bc_id)
        assert inserted == 5
        assert skipped == 0

        # 5. Complete sync run
        complete_sync_run(db, run_id, inserted, 0)

        # 6. Verify DB state
        rows = db.execute(
            "SELECT * FROM transactions ORDER BY txn_date"
        ).fetchall()
        assert len(rows) == 5

        # Check first row details
        r0 = dict(rows[0])
        assert r0["txn_date"] == "2026-05-01"
        assert r0["description"] == "ZELLE PAYMENT FROM JOHN DOE"
        assert r0["amount"] == 2500.0
        assert r0["balance"] == 15000.0
        assert r0["expense_category"] == "Engineering Revenue"
        assert r0["source"] == "csv"
        assert r0["bank_connection_id"] == bc_id
        assert r0["sync_run_id"] == run_id
        assert r0["auto_categorized"] == 1
        assert r0["needs_review"] == 0

        # Check uncategorized row
        unknown = [dict(r) for r in rows if r["description"] == "COMPLETELY UNKNOWN VENDOR"][0]
        assert unknown["expense_category"] is None
        assert unknown["auto_categorized"] == 0
        assert unknown["needs_review"] == 1

    def test_dedup_on_reimport(self, db):
        """Re-importing the same CSV should skip all duplicates."""
        bc_id = get_or_create_bank_connection(db, "Bank of America", "1234", "checking")

        # First import
        txns, _ = parse_bofa_csv(SAMPLE_CSV)
        txns = categorize_parsed(txns, db)
        run1 = create_sync_run(db, bc_id, "import1.csv")
        inserted1, skipped1 = commit_transactions(db, txns, run1, bc_id)
        assert inserted1 == 5
        assert skipped1 == 0

        # Second import of same data
        txns2, _ = parse_bofa_csv(SAMPLE_CSV)
        txns2 = categorize_parsed(txns2, db)
        run2 = create_sync_run(db, bc_id, "import2.csv")
        inserted2, skipped2 = commit_transactions(db, txns2, run2, bc_id)
        assert inserted2 == 0
        assert skipped2 == 5

        # DB still has exactly 5 rows
        count = db.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()["c"]
        assert count == 5

    def test_sync_history(self, db):
        """Verify sync_runs are recorded and retrievable."""
        bc_id = get_or_create_bank_connection(db, "Bank of America", "5678", "checking")
        run_id = create_sync_run(db, bc_id, "history_test.csv")
        complete_sync_run(db, run_id, 10, 2)

        history = get_sync_history(db, limit=10)
        assert len(history) >= 1
        latest = history[0]
        assert latest["file_name"] == "history_test.csv"
        assert latest["transactions_added"] == 10
        assert latest["transactions_updated"] == 2
        assert latest["institution_name"] == "Bank of America"
        assert latest["account_mask"] == "5678"

    def test_bank_connection_idempotent(self, db):
        """get_or_create should return same id for same institution+mask."""
        id1 = get_or_create_bank_connection(db, "Bank of America", "1234", "checking")
        id2 = get_or_create_bank_connection(db, "Bank of America", "1234", "checking")
        assert id1 == id2

    def test_bank_connection_different_accounts(self, db):
        """Different masks should create different connections."""
        id1 = get_or_create_bank_connection(db, "Bank of America", "1234", "checking")
        id2 = get_or_create_bank_connection(db, "Bank of America", "5678", "savings")
        assert id1 != id2

    def test_sync_run_error_recorded(self, db):
        """Error messages should be stored in the sync run."""
        bc_id = get_or_create_bank_connection(db, "Bank of America", "9999", "checking")
        run_id = create_sync_run(db, bc_id, "error_test.csv")
        complete_sync_run(db, run_id, 0, 0, "Test error message")

        row = db.execute(
            "SELECT * FROM sync_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row["error_message"] == "Test error message"
        assert row["completed_at"] is not None
