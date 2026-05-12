"""Enhanced invoicing operations for 6th Degree Engineering.

Supplements the core billing module (modules/billing/crud.py) with:
- Time-and-expense invoice generation
- Invoice line item management
- AR aging reports
- Payment schedule management

Invoice numbers follow the YYMMDD-N format established by billing.crud.
All mutating operations log to the activity_log table.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any


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
        (entity_type, entity_id, action, json.dumps(details) if details else None),
    )


def _next_invoice_number(conn: sqlite3.Connection, issue_date: str) -> str:
    """Generate the next YYMMDD-N invoice number for the given date.

    Mirrors the logic in billing.crud to maintain consistent numbering.
    """
    dt = datetime.strptime(issue_date, "%Y-%m-%d")
    prefix = dt.strftime("%y%m%d")
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
# Invoice generation from time entries + expenses
# ---------------------------------------------------------------------------

def generate_invoice_from_time(
    conn: sqlite3.Connection,
    project_id: int,
    date_from: str,
    date_to: str,
) -> int:
    """Generate an invoice from unbilled time entries and expenses.

    Pulls all unbilled (invoice_id IS NULL) time_entries and reimbursable
    expenses for *project_id* in the date range [date_from, date_to],
    creates an invoice with line items, and stamps each source row with
    the new invoice_id.

    Returns the new invoice id.

    Raises ValueError if no billable entries are found.
    """
    # --- Gather unbilled time entries ---
    time_rows = conn.execute(
        "SELECT id, employee_id, entry_date, hours, role, rate, multiplier, "
        "       description "
        "FROM time_entries "
        "WHERE project_id = ? "
        "  AND invoice_id IS NULL "
        "  AND billable = 1 "
        "  AND entry_date BETWEEN ? AND ? "
        "ORDER BY entry_date, id",
        (project_id, date_from, date_to),
    ).fetchall()

    # --- Gather unbilled reimbursable expenses ---
    expense_rows = conn.execute(
        "SELECT id, expense_date, category, description, amount, markup_pct "
        "FROM expenses "
        "WHERE project_id = ? "
        "  AND invoice_id IS NULL "
        "  AND reimbursable = 1 "
        "  AND expense_date BETWEEN ? AND ? "
        "ORDER BY expense_date, id",
        (project_id, date_from, date_to),
    ).fetchall()

    if not time_rows and not expense_rows:
        raise ValueError(
            f"No unbilled time entries or expenses found for project {project_id} "
            f"between {date_from} and {date_to}."
        )

    # --- Create the invoice ---
    issue = _today()
    inv_number = _next_invoice_number(conn, issue)
    due = (datetime.strptime(issue, "%Y-%m-%d") + timedelta(days=30)).strftime(
        "%Y-%m-%d"
    )

    # Build description
    proj = conn.execute(
        "SELECT job_number, name FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    proj_label = f"{proj['job_number']} - {proj['name']}" if proj else f"Project {project_id}"
    description = f"Time & expense invoice for {proj_label} ({date_from} to {date_to})"

    total = 0.0
    sort_order = 0

    cur = conn.execute(
        "INSERT INTO invoices "
        "(project_id, invoice_number, description, amount, status, issue_date, due_date) "
        "VALUES (?, ?, ?, 0, 'draft', ?, ?)",
        (project_id, inv_number, description, issue, due),
    )
    invoice_id = cur.lastrowid

    # --- Create line items for time entries ---
    for te in time_rows:
        line_amount = round(te["hours"] * te["rate"] * te["multiplier"], 2)
        total += line_amount
        sort_order += 1
        role_label = te["role"].replace("_", " ").title() if te["role"] else "Labor"
        line_desc = f"{role_label}: {te['description'] or te['entry_date']}"

        conn.execute(
            "INSERT INTO invoice_line_items "
            "(invoice_id, line_type, description, quantity, unit_rate, amount, "
            " time_entry_id, sort_order) "
            "VALUES (?, 'time', ?, ?, ?, ?, ?, ?)",
            (
                invoice_id,
                line_desc,
                te["hours"],
                round(te["rate"] * te["multiplier"], 2),
                line_amount,
                te["id"],
                sort_order,
            ),
        )

        # Stamp time entry with invoice_id
        conn.execute(
            "UPDATE time_entries SET invoice_id = ? WHERE id = ?",
            (invoice_id, te["id"]),
        )

    # --- Create line items for expenses ---
    for exp in expense_rows:
        markup = exp["markup_pct"] or 0.0
        line_amount = round(exp["amount"] * (1 + markup / 100.0), 2)
        total += line_amount
        sort_order += 1
        category_label = (exp["category"] or "expense").replace("_", " ").title()
        line_desc = f"{category_label}: {exp['description'] or exp['expense_date']}"

        conn.execute(
            "INSERT INTO invoice_line_items "
            "(invoice_id, line_type, description, quantity, unit_rate, amount, "
            " expense_id, sort_order) "
            "VALUES (?, 'expense', ?, 1, ?, ?, ?, ?)",
            (
                invoice_id,
                line_desc,
                exp["amount"],
                line_amount,
                exp["id"],
                sort_order,
            ),
        )

        # Stamp expense with invoice_id
        conn.execute(
            "UPDATE expenses SET invoice_id = ? WHERE id = ?",
            (invoice_id, exp["id"]),
        )

    # --- Update invoice total ---
    total = round(total, 2)
    conn.execute(
        "UPDATE invoices SET amount = ? WHERE id = ?",
        (total, invoice_id),
    )

    # --- Audit log ---
    _log_activity(
        conn,
        "invoice",
        invoice_id,
        "generated_from_time",
        {
            "invoice_number": inv_number,
            "project_id": project_id,
            "date_from": date_from,
            "date_to": date_to,
            "time_entry_count": len(time_rows),
            "expense_count": len(expense_rows),
            "total": total,
        },
    )
    conn.commit()
    return invoice_id


# ---------------------------------------------------------------------------
# Invoice line items
# ---------------------------------------------------------------------------

def get_invoice_line_items(
    conn: sqlite3.Connection, invoice_id: int
) -> list[sqlite3.Row]:
    """Return all line items for an invoice, ordered by sort_order."""
    return conn.execute(
        "SELECT * FROM invoice_line_items "
        "WHERE invoice_id = ? ORDER BY sort_order, id",
        (invoice_id,),
    ).fetchall()


def create_line_item(
    conn: sqlite3.Connection,
    invoice_id: int,
    line_type: str,
    amount: float,
    **kwargs: Any,
) -> int:
    """Create a single invoice line item and return its id.

    Optional kwargs: description, quantity, unit_rate, time_entry_id,
    expense_id, sort_order.
    """
    description = kwargs.get("description")
    quantity = kwargs.get("quantity", 1)
    unit_rate = kwargs.get("unit_rate", amount)
    time_entry_id = kwargs.get("time_entry_id")
    expense_id = kwargs.get("expense_id")
    sort_order = kwargs.get("sort_order", 0)

    cur = conn.execute(
        "INSERT INTO invoice_line_items "
        "(invoice_id, line_type, description, quantity, unit_rate, amount, "
        " time_entry_id, expense_id, sort_order) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            invoice_id,
            line_type,
            description,
            quantity,
            unit_rate,
            amount,
            time_entry_id,
            expense_id,
            sort_order,
        ),
    )
    line_id = cur.lastrowid
    _log_activity(
        conn,
        "invoice_line_item",
        line_id,
        "created",
        {"invoice_id": invoice_id, "line_type": line_type, "amount": amount},
    )
    conn.commit()
    return line_id


# ---------------------------------------------------------------------------
# AR Aging
# ---------------------------------------------------------------------------

def get_ar_aging_report(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return the full AR aging report from the v_ar_aging view."""
    return conn.execute(
        "SELECT * FROM v_ar_aging ORDER BY days_past_due DESC"
    ).fetchall()


def get_ar_aging_summary(conn: sqlite3.Connection) -> dict[str, float]:
    """Return total outstanding by aging bucket.

    Keys: current, 1-30, 31-60, 61-90, 90+.
    """
    rows = conn.execute(
        "SELECT aging_bucket, COALESCE(SUM(balance_due), 0) AS total "
        "FROM v_ar_aging GROUP BY aging_bucket"
    ).fetchall()

    # Initialize all buckets to zero
    summary: dict[str, float] = {
        "current": 0.0,
        "1-30": 0.0,
        "31-60": 0.0,
        "61-90": 0.0,
        "90+": 0.0,
    }
    for row in rows:
        bucket = row["aging_bucket"]
        if bucket in summary:
            summary[bucket] = row["total"]

    return summary


# ---------------------------------------------------------------------------
# Payment schedules
# ---------------------------------------------------------------------------

def create_payment_schedule(
    conn: sqlite3.Connection,
    project_id: int,
    schedules: list[dict],
) -> None:
    """Bulk-create payment schedule entries for a project.

    Each dict in *schedules* should contain:
        - description (str)
        - percentage (float)
        - due_trigger (str): on_acceptance | on_submission | on_completion |
                             net_30 | net_60 | custom_date
        - due_date (str, optional): required when due_trigger = custom_date
        - amount (float, optional): override amount instead of percentage-based
    """
    for idx, sched in enumerate(schedules):
        conn.execute(
            "INSERT INTO payment_schedules "
            "(project_id, description, percentage, amount, due_trigger, "
            " due_date, status, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (
                project_id,
                sched["description"],
                sched["percentage"],
                sched.get("amount"),
                sched.get("due_trigger"),
                sched.get("due_date"),
                idx,
            ),
        )
    _log_activity(
        conn,
        "payment_schedule",
        project_id,
        "created",
        {"project_id": project_id, "schedule_count": len(schedules)},
    )
    conn.commit()


def list_payment_schedules(
    conn: sqlite3.Connection, project_id: int
) -> list[sqlite3.Row]:
    """Return all payment schedule entries for a project, ordered by sort_order."""
    return conn.execute(
        "SELECT ps.*, p.job_number, p.name AS project_name "
        "FROM payment_schedules ps "
        "LEFT JOIN projects p ON p.id = ps.project_id "
        "WHERE ps.project_id = ? "
        "ORDER BY ps.sort_order, ps.id",
        (project_id,),
    ).fetchall()
