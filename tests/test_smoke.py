"""Smoke tests for the 6DE Platform — schema, billing, auditor, widget keys."""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.billing.crud import _next_invoice_number  # noqa: E402
from modules.calculator.required_checks import seed_required_checks  # noqa: E402


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


# ---------------------------------------------------------------------------
# Session 35: calc_required_checks + auditor
# ---------------------------------------------------------------------------

def test_calc_required_checks_table_exists(db):
    tables = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "calc_required_checks" in tables


def test_calc_required_checks_seed_idempotent(db):
    n1 = db.execute("SELECT COUNT(*) FROM calc_required_checks").fetchone()[0]
    seed_required_checks(db)
    n2 = db.execute("SELECT COUNT(*) FROM calc_required_checks").fetchone()[0]
    assert n1 == n2 and n1 >= 19


def test_calc_required_checks_unique_constraint(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO calc_required_checks "
            "(structure_type, check_label, code_ref, severity) "
            "VALUES (?, ?, ?, ?)",
            (
                "Glass Railing (with base shoe)",
                "Top rail 50 plf line load",
                "IBC 1607.8.1.1",
                "required",
            ),
        )


def test_no_duplicate_widget_keys_in_projects_page():
    """B24 regression guard: per-row widget keys must be namespaced by tab index."""
    src = (
        _PLATFORM_ROOT / "streamlit_app" / "pages" / "1_Projects.py"
    ).read_text(encoding="utf-8")
    pattern = re.compile(r'key=f"([a-zA-Z_]+)_\{pid\}"')
    offenders = pattern.findall(src)
    assert not offenders, (
        f"Found per-row widget keys not namespaced by tab: "
        f"{offenders}. Use key_ns = f't{{tab_idx}}_p{{pid}}'."
    )
