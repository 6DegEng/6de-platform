"""Tests for the QuickBooks Online invoice CSV export (credential-free slice).

Covers: header-only when empty, one-row-per-line-item mapping, summary row for
invoices without line items, status filtering, id filtering, customer-name
fallback chain, value formatting, and read-only (no-mutation) behavior.
"""
from __future__ import annotations

import csv
import io

from modules.integrations.quickbooks import (
    QBO_CSV_COLUMNS,
    export_invoices_to_qbo_csv,
    fetch_exportable_invoices,
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _client(conn, name="Acme Condo Assn", company="Acme Condo Association LLC"):
    cur = conn.execute(
        "INSERT INTO clients (name, company) VALUES (?, ?)", (name, company)
    )
    return cur.lastrowid


def _project(conn, job_number, name="Tower Recert", client_id=None):
    cur = conn.execute(
        "INSERT INTO projects (job_number, name, client_id) VALUES (?, ?, ?)",
        (job_number, name, client_id),
    )
    return cur.lastrowid


def _invoice(conn, project_id, number, *, amount=0.0, status="sent",
             issue_date="2026-05-01", due_date="2026-05-31", description="Phase 1 fee"):
    cur = conn.execute(
        "INSERT INTO invoices "
        "(project_id, invoice_number, description, amount, status, issue_date, due_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, number, description, amount, status, issue_date, due_date),
    )
    return cur.lastrowid


def _line(conn, invoice_id, line_type, amount, *, description="", quantity=1,
          unit_rate=0.0, sort_order=0):
    conn.execute(
        "INSERT INTO invoice_line_items "
        "(invoice_id, line_type, description, quantity, unit_rate, amount, sort_order) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (invoice_id, line_type, description, quantity, unit_rate, amount, sort_order),
    )


def _parse(csv_text):
    return list(csv.DictReader(io.StringIO(csv_text)))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_export_returns_header_only(db):
    out = export_invoices_to_qbo_csv(db)
    lines = out.strip().splitlines()
    assert lines == [",".join(QBO_CSV_COLUMNS)]


def test_invoice_with_line_items_one_row_each(db):
    cid = _client(db)
    pid = _project(db, "260501", client_id=cid)
    inv = _invoice(db, pid, "260501-1", amount=1500.0)
    _line(db, inv, "time", 1000.0, description="PE review", quantity=5, unit_rate=200.0, sort_order=1)
    _line(db, inv, "expense", 500.0, description="Permit fee", quantity=1, unit_rate=500.0, sort_order=2)
    db.commit()

    rows = _parse(export_invoices_to_qbo_csv(db))
    assert len(rows) == 2
    assert {r["Item"] for r in rows} == {"Engineering Services", "Reimbursable Expenses"}
    assert all(r["Customer"] == "Acme Condo Association LLC" for r in rows)
    assert all(r["InvoiceNo"] == "260501-1" for r in rows)
    assert all(r["InvoiceDate"] == "2026-05-01" and r["DueDate"] == "2026-05-31" for r in rows)

    time_row = next(r for r in rows if r["Item"] == "Engineering Services")
    assert time_row["ItemQuantity"] == "5"
    assert time_row["ItemRate"] == "200.00"
    assert time_row["ItemAmount"] == "1000.00"
    assert "Job 260501" in time_row["Memo"]


def test_invoice_without_line_items_emits_summary_row(db):
    cid = _client(db, company="")  # force fallback to contact name
    pid = _project(db, "260502", client_id=cid)
    _invoice(db, pid, "260502-1", amount=2750.5, description="Fixed fee — SIRS")
    db.commit()

    rows = _parse(export_invoices_to_qbo_csv(db))
    assert len(rows) == 1
    r = rows[0]
    assert r["Item"] == "Engineering Services"
    assert r["ItemQuantity"] == "1"
    assert r["ItemAmount"] == "2750.50"
    assert r["ItemDescription"] == "Fixed fee — SIRS"
    assert r["Customer"] == "Acme Condo Assn"  # company blank → contact name


def test_default_status_filter_excludes_draft_and_void(db):
    pid = _project(db, "260503")
    _invoice(db, pid, "260503-1", amount=100.0, status="draft")
    _invoice(db, pid, "260503-2", amount=200.0, status="void")
    _invoice(db, pid, "260503-3", amount=300.0, status="paid")
    db.commit()

    rows = _parse(export_invoices_to_qbo_csv(db))
    assert len(rows) == 1
    assert rows[0]["InvoiceNo"] == "260503-3"


def test_invoice_ids_filter_restricts_output(db):
    pid = _project(db, "260504")
    keep = _invoice(db, pid, "260504-1", amount=100.0)
    _invoice(db, pid, "260504-2", amount=200.0)
    db.commit()

    rows = _parse(export_invoices_to_qbo_csv(db, invoice_ids=[keep]))
    assert [r["InvoiceNo"] for r in rows] == ["260504-1"]

    # Empty id list → nothing exported (header only).
    assert _parse(export_invoices_to_qbo_csv(db, invoice_ids=[])) == []


def test_customer_fallback_to_project_when_no_client(db):
    pid = _project(db, "260505", name="Bayside Garage", client_id=None)
    _invoice(db, pid, "260505-1", amount=400.0)
    db.commit()

    rows = _parse(export_invoices_to_qbo_csv(db))
    assert rows[0]["Customer"] == "260505 - Bayside Garage"


def test_fractional_quantity_formatting(db):
    pid = _project(db, "260506")
    inv = _invoice(db, pid, "260506-1", amount=375.0)
    _line(db, inv, "time", 375.0, description="Partial", quantity=2.5, unit_rate=150.0)
    db.commit()

    rows = _parse(export_invoices_to_qbo_csv(db))
    assert rows[0]["ItemQuantity"] == "2.5"
    assert rows[0]["ItemRate"] == "150.00"


def test_export_does_not_mutate_db(db):
    pid = _project(db, "260507")
    _invoice(db, pid, "260507-1", amount=100.0)
    db.commit()

    before = db.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()["n"]
    before_lines = db.execute("SELECT COUNT(*) AS n FROM invoice_line_items").fetchone()["n"]
    export_invoices_to_qbo_csv(db)
    after = db.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()["n"]
    after_lines = db.execute("SELECT COUNT(*) AS n FROM invoice_line_items").fetchone()["n"]
    assert (before, before_lines) == (after, after_lines)


def test_fetch_orders_by_invoice_number(db):
    pid = _project(db, "260508")
    _invoice(db, pid, "260508-2", amount=2.0)
    _invoice(db, pid, "260508-1", amount=1.0)
    db.commit()

    rows = fetch_exportable_invoices(db)
    assert [r["invoice_number"] for r in rows] == ["260508-1", "260508-2"]
