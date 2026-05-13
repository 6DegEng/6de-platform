"""Smoke tests for money-touching tables: invoices, transactions, billing CRUD."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.billing.crud import _next_invoice_number  # noqa: E402


def test_schema_creates_core_tables(db):
    tables = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for t in ("clients", "projects", "invoices", "transactions", "proposals"):
        assert t in tables, f"Missing table: {t}"


def test_transactions_source_column_exists(db):
    cols = {
        r[1] for r in db.execute("PRAGMA table_info(transactions)").fetchall()
    }
    assert "source" in cols


def test_transaction_insert_and_dedup(db):
    db.execute(
        "INSERT INTO transactions (txn_date, amount, description, source) "
        "VALUES ('2026-01-15', -49.99, 'Adobe Creative Cloud', 'csv_import')"
    )
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO transactions (txn_date, amount, description) "
            "VALUES ('2026-01-15', -49.99, 'Adobe Creative Cloud')"
        )


def test_invoice_number_generation(db):
    db.execute(
        "INSERT INTO clients (name) VALUES ('Test Client')"
    )
    db.execute(
        "INSERT INTO projects (job_number, name, client_id) "
        "VALUES ('260512', 'Test Project', 1)"
    )
    db.commit()

    num1 = _next_invoice_number(db, "2026-05-12")
    assert num1 == "260512-1"

    db.execute(
        "INSERT INTO invoices (project_id, invoice_number, amount, issue_date) "
        "VALUES (1, '260512-1', 1000.00, '2026-05-12')"
    )
    db.commit()

    num2 = _next_invoice_number(db, "2026-05-12")
    assert num2 == "260512-2"


def test_invoice_unique_constraint(db):
    db.execute("INSERT INTO clients (name) VALUES ('C')")
    db.execute(
        "INSERT INTO projects (job_number, name, client_id) "
        "VALUES ('260101', 'P', 1)"
    )
    db.execute(
        "INSERT INTO invoices (project_id, invoice_number, amount, issue_date) "
        "VALUES (1, '260101-1', 500, '2026-01-01')"
    )
    db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO invoices (project_id, invoice_number, amount, issue_date) "
            "VALUES (1, '260101-1', 750, '2026-01-01')"
        )
