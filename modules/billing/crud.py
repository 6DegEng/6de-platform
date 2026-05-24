"""Billing & invoicing CRUD operations for 6th Degree Engineering.

Invoice numbers follow the YYMMDD-N format (e.g. 260512-1, 260512-2).
Proposals track scope/fee through draft -> sent -> accepted lifecycle.
All mutating operations log to the activity_log table.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from modules.activity_utils import sanitize_details


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    """ISO date string for today."""
    return date.today().isoformat()


def _log_activity(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    action: str,
    details: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO activity_log (entity_type, entity_id, action, details) "
        "VALUES (?, ?, ?, ?)",
        (entity_type, entity_id, action, json.dumps(sanitize_details(details)) if details else None),
    )


def _next_invoice_number(conn: sqlite3.Connection, issue_date: str) -> str:
    """Generate the next YYMMDD-N invoice number for the given date.

    Parses *issue_date* (ISO format YYYY-MM-DD) into the two-digit-year
    prefix, then finds the highest existing sequence number for that prefix
    and increments it.
    """
    dt = datetime.strptime(issue_date, "%Y-%m-%d")
    prefix = dt.strftime("%y%m%d")  # e.g. "260512"
    row = conn.execute(
        "SELECT invoice_number FROM invoices "
        "WHERE invoice_number LIKE ? ORDER BY invoice_number DESC LIMIT 1",
        (f"{prefix}-%",),
    ).fetchone()
    seq = 1
    if row:
        try:
            seq = int(row["invoice_number"].split("-")[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    return f"{prefix}-{seq}"


# ---------------------------------------------------------------------------
# Invoice CRUD
# ---------------------------------------------------------------------------

def list_invoices(
    conn: sqlite3.Connection,
    project_id: int | None = None,
    status_filter: str | None = None,
) -> list[sqlite3.Row]:
    """Return invoices with optional project / status filters."""
    query = (
        "SELECT i.*, p.job_number, p.name AS project_name "
        "FROM invoices i "
        "LEFT JOIN projects p ON p.id = i.project_id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if project_id is not None:
        query += " AND i.project_id = ?"
        params.append(project_id)
    if status_filter:
        query += " AND i.status = ?"
        params.append(status_filter)
    query += " ORDER BY i.issue_date DESC, i.id DESC"
    return conn.execute(query, params).fetchall()


def get_invoice(conn: sqlite3.Connection, invoice_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT i.*, p.job_number, p.name AS project_name "
        "FROM invoices i "
        "LEFT JOIN projects p ON p.id = i.project_id "
        "WHERE i.id = ?",
        (invoice_id,),
    ).fetchone()


def create_invoice(
    conn: sqlite3.Connection,
    project_id: int,
    amount: float,
    description: str | None = None,
    issue_date: str | None = None,
) -> int:
    """Create a new invoice and return its id.

    Automatically generates the next YYMMDD-N invoice_number for the
    issue_date (defaults to today). Sets due_date to 30 days from issue.
    """
    issue = issue_date or _today()
    inv_number = _next_invoice_number(conn, issue)
    due = (datetime.strptime(issue, "%Y-%m-%d") + timedelta(days=30)).strftime(
        "%Y-%m-%d"
    )
    cur = conn.execute(
        "INSERT INTO invoices "
        "(project_id, invoice_number, description, amount, status, issue_date, due_date) "
        "VALUES (?, ?, ?, ?, 'draft', ?, ?)",
        (project_id, inv_number, description, amount, issue, due),
    )
    invoice_id = cur.lastrowid
    _log_activity(
        conn,
        "invoice",
        invoice_id,
        "created",
        {"invoice_number": inv_number, "amount": amount, "project_id": project_id},
    )
    conn.commit()
    return invoice_id


def update_invoice(conn: sqlite3.Connection, invoice_id: int, **kwargs: Any) -> None:
    """Update arbitrary invoice fields. Keys must be valid column names."""
    if not kwargs:
        return
    allowed = {
        "description", "amount", "status", "issue_date", "due_date",
        "paid_date", "paid_amount", "payment_method", "file_path", "notes",
    }
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return
    filtered["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{col} = ?" for col in filtered)
    values = list(filtered.values()) + [invoice_id]
    conn.execute(
        f"UPDATE invoices SET {set_clause} WHERE id = ?", values  # noqa: S608
    )
    _log_activity(conn, "invoice", invoice_id, "updated", filtered)
    conn.commit()


def mark_paid(
    conn: sqlite3.Connection,
    invoice_id: int,
    paid_date: str | None = None,
    payment_method: str | None = None,
) -> None:
    """Mark an invoice as paid."""
    inv = get_invoice(conn, invoice_id)
    if inv is None:
        raise ValueError(f"Invoice {invoice_id} not found")
    pay_date = paid_date or _today()
    conn.execute(
        "UPDATE invoices SET status = 'paid', paid_date = ?, paid_amount = amount, "
        "payment_method = ?, updated_at = ? WHERE id = ?",
        (pay_date, payment_method, datetime.utcnow().isoformat(), invoice_id),
    )
    _log_activity(
        conn,
        "invoice",
        invoice_id,
        "status_change",
        {"old_status": inv["status"], "new_status": "paid", "paid_date": pay_date},
    )
    conn.commit()


def mark_overdue(conn: sqlite3.Connection) -> int:
    """Bulk-mark all unpaid invoices whose due_date has passed as overdue.

    Returns the number of invoices updated.
    """
    today = _today()
    cur = conn.execute(
        "UPDATE invoices SET status = 'overdue', updated_at = ? "
        "WHERE status IN ('draft', 'sent') AND due_date < ?",
        (datetime.utcnow().isoformat(), today),
    )
    count = cur.rowcount
    if count:
        # Log each affected invoice
        rows = conn.execute(
            "SELECT id FROM invoices WHERE status = 'overdue' AND updated_at >= ?",
            (today,),
        ).fetchall()
        for row in rows:
            _log_activity(
                conn, "invoice", row["id"], "status_change",
                {"new_status": "overdue", "reason": "past_due_date"},
            )
    conn.commit()
    return count


# ---------------------------------------------------------------------------
# Proposal CRUD
# ---------------------------------------------------------------------------

def list_proposals(
    conn: sqlite3.Connection,
    project_id: int | None = None,
    status_filter: str | None = None,
) -> list[sqlite3.Row]:
    query = (
        "SELECT pr.*, p.job_number, p.name AS project_name "
        "FROM proposals pr "
        "LEFT JOIN projects p ON p.id = pr.project_id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if project_id is not None:
        query += " AND pr.project_id = ?"
        params.append(project_id)
    if status_filter:
        query += " AND pr.status = ?"
        params.append(status_filter)
    query += " ORDER BY pr.created_at DESC"
    return conn.execute(query, params).fetchall()


def create_proposal(
    conn: sqlite3.Connection,
    project_id: int,
    fee_amount: float,
    scope_text: str | None = None,
) -> int:
    """Create a new proposal and return its id.

    Auto-generates proposal_number as 'P-YYMMDD-N'.
    """
    today_str = _today()
    dt = datetime.strptime(today_str, "%Y-%m-%d")
    prefix = f"P-{dt.strftime('%y%m%d')}"
    row = conn.execute(
        "SELECT proposal_number FROM proposals "
        "WHERE proposal_number LIKE ? ORDER BY proposal_number DESC LIMIT 1",
        (f"{prefix}-%",),
    ).fetchone()
    seq = 1
    if row:
        try:
            seq = int(row["proposal_number"].rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    prop_number = f"{prefix}-{seq}"
    cur = conn.execute(
        "INSERT INTO proposals "
        "(project_id, proposal_number, scope_text, fee_amount, status) "
        "VALUES (?, ?, ?, ?, 'draft')",
        (project_id, prop_number, scope_text, fee_amount),
    )
    proposal_id = cur.lastrowid
    _log_activity(
        conn,
        "proposal",
        proposal_id,
        "created",
        {"proposal_number": prop_number, "fee_amount": fee_amount},
    )
    conn.commit()
    return proposal_id


def update_proposal(
    conn: sqlite3.Connection, proposal_id: int, **kwargs: Any
) -> None:
    allowed = {
        "proposal_number", "scope_text", "fee_amount", "status",
        "sent_date", "accepted_date", "file_path", "notes",
    }
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return
    filtered["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{col} = ?" for col in filtered)
    values = list(filtered.values()) + [proposal_id]
    conn.execute(
        f"UPDATE proposals SET {set_clause} WHERE id = ?", values  # noqa: S608
    )
    _log_activity(conn, "proposal", proposal_id, "updated", filtered)
    conn.commit()


def accept_proposal(conn: sqlite3.Connection, proposal_id: int) -> None:
    """Mark a proposal as accepted and record the accepted_date."""
    today_str = _today()
    conn.execute(
        "UPDATE proposals SET status = 'accepted', accepted_date = ?, "
        "updated_at = ? WHERE id = ?",
        (today_str, datetime.utcnow().isoformat(), proposal_id),
    )
    _log_activity(
        conn,
        "proposal",
        proposal_id,
        "status_change",
        {"new_status": "accepted", "accepted_date": today_str},
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Reporting / Summaries
# ---------------------------------------------------------------------------

def get_billing_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Dashboard-level billing metrics.

    Returns dict with:
        total_outstanding - sum of unpaid sent/overdue invoices
        total_overdue     - sum of overdue invoices
        total_paid_ytd    - sum paid_amount this calendar year
        invoice_count_by_status - dict mapping status -> count
    """
    year_start = f"{date.today().year}-01-01"

    outstanding = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total "
        "FROM invoices WHERE status IN ('sent', 'overdue')"
    ).fetchone()["total"]

    overdue = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total "
        "FROM invoices WHERE status = 'overdue'"
    ).fetchone()["total"]

    paid_ytd = conn.execute(
        "SELECT COALESCE(SUM(paid_amount), 0) AS total "
        "FROM invoices WHERE status = 'paid' AND paid_date >= ?",
        (year_start,),
    ).fetchone()["total"]

    counts_rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM invoices GROUP BY status"
    ).fetchall()
    counts = {r["status"]: r["cnt"] for r in counts_rows}

    return {
        "total_outstanding": outstanding,
        "total_overdue": overdue,
        "total_paid_ytd": paid_ytd,
        "invoice_count_by_status": counts,
    }


def get_project_billing(
    conn: sqlite3.Connection, project_id: int
) -> dict[str, Any]:
    """All billing data for a single project."""
    proposals = list_proposals(conn, project_id=project_id)
    invoices = list_invoices(conn, project_id=project_id)
    total_invoiced = sum(r["amount"] for r in invoices)
    total_paid = sum(r["paid_amount"] or 0 for r in invoices)
    total_proposed = sum(r["fee_amount"] for r in proposals)
    return {
        "proposals": proposals,
        "invoices": invoices,
        "total_invoiced": total_invoiced,
        "total_paid": total_paid,
        "total_proposed": total_proposed,
        "balance_due": total_invoiced - total_paid,
    }
