"""Tests for modules/invoicing/crud.py — previously uncovered.

Covers invoice generation from unbilled time + expenses (amount math, source-row
stamping, exclusion filters, empty-range error), line-item CRUD, the AR aging
summary, and payment schedules.
"""
from __future__ import annotations

import re

import pytest

from modules.invoicing.crud import (
    create_line_item,
    create_payment_schedule,
    generate_invoice_from_time,
    get_ar_aging_summary,
    get_invoice_line_items,
    list_payment_schedules,
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _employee(db, name="Juan Castillo", role="professional_engineer"):
    return db.execute(
        "INSERT INTO employees (name, role) VALUES (?, ?)", (name, role)
    ).lastrowid


def _project(db, job_number="260501", name="Tower Recert", client_id=None):
    return db.execute(
        "INSERT INTO projects (job_number, name, client_id) VALUES (?, ?, ?)",
        (job_number, name, client_id),
    ).lastrowid


def _client(db, name="Acme Assn", company="Acme Association LLC"):
    return db.execute(
        "INSERT INTO clients (name, company) VALUES (?, ?)", (name, company)
    ).lastrowid


def _time(db, project_id, employee_id, *, entry_date="2026-05-10", hours=10.0,
          role="professional_engineer", rate=150.0, multiplier=1.0, billable=1,
          description="Review"):
    return db.execute(
        "INSERT INTO time_entries "
        "(employee_id, project_id, entry_date, hours, role, rate, multiplier, "
        " billable, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (employee_id, project_id, entry_date, hours, role, rate, multiplier,
         billable, description),
    ).lastrowid


def _expense(db, project_id, *, expense_date="2026-05-10", category="filing_fees",
             amount=100.0, markup_pct=15.0, reimbursable=1, description="Permit"):
    return db.execute(
        "INSERT INTO expenses "
        "(project_id, expense_date, category, description, amount, markup_pct, "
        " reimbursable) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, expense_date, category, description, amount, markup_pct,
         reimbursable),
    ).lastrowid


def _invoice(db, project_id, number, *, amount, status="sent",
             issue_date="2026-01-01", due_date="2020-01-01", paid_amount=0.0):
    return db.execute(
        "INSERT INTO invoices "
        "(project_id, invoice_number, amount, status, issue_date, due_date, paid_amount) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, number, amount, status, issue_date, due_date, paid_amount),
    ).lastrowid


# ---------------------------------------------------------------------------
# generate_invoice_from_time
# ---------------------------------------------------------------------------

def test_generate_invoice_combines_time_and_expenses(db):
    emp = _employee(db)
    pid = _project(db)
    _time(db, pid, emp, hours=10.0, rate=150.0, multiplier=1.0)   # 1500.00
    _expense(db, pid, amount=100.0, markup_pct=15.0)               # 115.00
    db.commit()

    inv_id = generate_invoice_from_time(db, pid, "2026-05-01", "2026-05-31")

    inv = db.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,)).fetchone()
    assert inv["amount"] == 1615.0
    assert inv["status"] == "draft"
    assert re.fullmatch(r"\d{6}-\d+", inv["invoice_number"])

    lines = get_invoice_line_items(db, inv_id)
    assert len(lines) == 2
    by_type = {ln["line_type"]: ln for ln in lines}
    assert by_type["time"]["amount"] == 1500.0
    assert by_type["expense"]["amount"] == 115.0


def test_generate_invoice_stamps_source_rows(db):
    emp = _employee(db)
    pid = _project(db)
    te = _time(db, pid, emp)
    ex = _expense(db, pid)
    db.commit()

    inv_id = generate_invoice_from_time(db, pid, "2026-05-01", "2026-05-31")

    assert db.execute("SELECT invoice_id FROM time_entries WHERE id = ?", (te,)).fetchone()["invoice_id"] == inv_id
    assert db.execute("SELECT invoice_id FROM expenses WHERE id = ?", (ex,)).fetchone()["invoice_id"] == inv_id


def test_generate_invoice_excludes_nonbillable_and_out_of_range(db):
    emp = _employee(db)
    pid = _project(db)
    _time(db, pid, emp, billable=0, hours=99.0, rate=999.0)             # non-billable
    _time(db, pid, emp, entry_date="2026-01-01", hours=99.0, rate=999.0)  # out of range
    _expense(db, pid, reimbursable=0, amount=999.0)                     # non-reimbursable
    _time(db, pid, emp, hours=2.0, rate=100.0, multiplier=1.0)          # the only billable in-range -> 200
    db.commit()

    inv_id = generate_invoice_from_time(db, pid, "2026-05-01", "2026-05-31")
    inv = db.execute("SELECT amount FROM invoices WHERE id = ?", (inv_id,)).fetchone()
    assert inv["amount"] == 200.0
    assert len(get_invoice_line_items(db, inv_id)) == 1


def test_generate_invoice_raises_when_nothing_billable(db):
    emp = _employee(db)
    pid = _project(db)
    _time(db, pid, emp, entry_date="2026-01-01")  # out of range
    db.commit()
    with pytest.raises(ValueError):
        generate_invoice_from_time(db, pid, "2026-05-01", "2026-05-31")


def test_generate_invoice_respects_multiplier(db):
    emp = _employee(db)
    pid = _project(db)
    _time(db, pid, emp, hours=4.0, rate=200.0, multiplier=1.5)  # 1200.00
    db.commit()
    inv_id = generate_invoice_from_time(db, pid, "2026-05-01", "2026-05-31")
    line = get_invoice_line_items(db, inv_id)[0]
    assert line["amount"] == 1200.0
    assert line["unit_rate"] == 300.0  # rate * multiplier


# ---------------------------------------------------------------------------
# line items
# ---------------------------------------------------------------------------

def test_create_and_list_line_items_ordered(db):
    pid = _project(db)
    inv = _invoice(db, pid, "260101-1", amount=0.0, status="draft")
    db.commit()
    create_line_item(db, inv, "fixed_fee", 500.0, description="B", sort_order=2)
    create_line_item(db, inv, "adjustment", -50.0, description="A", sort_order=1)

    lines = get_invoice_line_items(db, inv)
    assert [ln["description"] for ln in lines] == ["A", "B"]


# ---------------------------------------------------------------------------
# AR aging summary
# ---------------------------------------------------------------------------

def test_ar_aging_summary_buckets_and_balance(db):
    pid = _project(db)
    # due 2020-01-01 => far past due => 90+ bucket; balance = amount - paid
    _invoice(db, pid, "200101-1", amount=1000.0, status="sent", paid_amount=250.0)
    # draft invoices are excluded from v_ar_aging (status filter sent/overdue)
    _invoice(db, pid, "200101-2", amount=9999.0, status="draft")
    db.commit()

    summary = get_ar_aging_summary(db)
    assert set(summary) == {"current", "1-30", "31-60", "61-90", "90+"}
    assert summary["90+"] == 750.0
    assert sum(summary.values()) == 750.0  # draft excluded


# ---------------------------------------------------------------------------
# payment schedules
# ---------------------------------------------------------------------------

def test_payment_schedule_create_and_list(db):
    pid = _project(db)
    db.commit()
    create_payment_schedule(db, pid, [
        {"description": "Deposit", "percentage": 50.0, "due_trigger": "on_acceptance"},
        {"description": "Final", "percentage": 50.0, "due_trigger": "on_completion"},
    ])
    rows = list_payment_schedules(db, pid)
    assert [r["description"] for r in rows] == ["Deposit", "Final"]
    assert [r["sort_order"] for r in rows] == [0, 1]
