"""CRUD operations for the Subconsultants and Purchase Orders module.

Manages the vendor roster (company info, specialty, W-9 / insurance status)
and per-project purchase orders with auto-generated PO numbers.

All functions accept a sqlite3.Connection (with row_factory=sqlite3.Row) as the
first argument so that callers own the connection lifecycle.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUB_COLS = [
    "company_name",
    "contact_name",
    "email",
    "phone",
    "specialty",
    "rate_card",
    "w9_on_file",
    "insurance_expiry",
    "notes",
]

_PO_COLS = [
    "project_id",
    "subconsultant_id",
    "po_number",
    "description",
    "amount",
    "markup_pct",
    "status",
    "issued_date",
    "notes",
]


def _today_str() -> str:
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
        (entity_type, entity_id, action, json.dumps(details or {})),
    )


def _generate_po_number(conn: sqlite3.Connection) -> str:
    """Generate the next PO-YYMMDD-N purchase order number.

    Uses today's date as the prefix and auto-increments the sequence.
    """
    prefix = f"PO-{date.today().strftime('%y%m%d')}"
    row = conn.execute(
        "SELECT po_number FROM purchase_orders "
        "WHERE po_number LIKE ? ORDER BY po_number DESC LIMIT 1",
        (f"{prefix}-%",),
    ).fetchone()
    seq = 1
    if row:
        try:
            seq = int(row["po_number"].rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    return f"{prefix}-{seq}"


# ---------------------------------------------------------------------------
# Subconsultants — CRUD
# ---------------------------------------------------------------------------


def list_subconsultants(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all subconsultants, ordered by company name."""
    return conn.execute(
        "SELECT * FROM subconsultants ORDER BY company_name"
    ).fetchall()


def get_subconsultant(
    conn: sqlite3.Connection, sub_id: int
) -> sqlite3.Row | None:
    """Return a single subconsultant row or None."""
    return conn.execute(
        "SELECT * FROM subconsultants WHERE id = ?", (sub_id,)
    ).fetchone()


def create_subconsultant(
    conn: sqlite3.Connection,
    company_name: str,
    **kwargs: Any,
) -> int:
    """Insert a new subconsultant and return its id."""
    fields = ["company_name"]
    values: list[Any] = [company_name]

    for col in _SUB_COLS:
        if col == "company_name":
            continue
        if col in kwargs and kwargs[col] is not None and kwargs[col] != "":
            fields.append(col)
            values.append(kwargs[col])

    placeholders = ", ".join("?" for _ in fields)
    col_names = ", ".join(fields)
    cur = conn.execute(
        f"INSERT INTO subconsultants ({col_names}) VALUES ({placeholders})",
        values,
    )
    sub_id = cur.lastrowid
    _log_activity(
        conn,
        "subconsultant",
        sub_id,
        "created",
        {"company_name": company_name},
    )
    conn.commit()
    return sub_id


def update_subconsultant(
    conn: sqlite3.Connection, sub_id: int, **kwargs: Any
) -> None:
    """Update subconsultant fields and log changes."""
    sets: list[str] = []
    values: list[Any] = []
    changes: dict[str, Any] = {}
    for col in _SUB_COLS:
        if col in kwargs:
            sets.append(f"{col} = ?")
            values.append(kwargs[col] if kwargs[col] != "" else None)
            changes[col] = kwargs[col]
    if not sets:
        return
    sets.append("updated_at = datetime('now')")
    values.append(sub_id)
    conn.execute(
        f"UPDATE subconsultants SET {', '.join(sets)} WHERE id = ?", values
    )
    _log_activity(conn, "subconsultant", sub_id, "updated", changes)
    conn.commit()


# ---------------------------------------------------------------------------
# Purchase Orders — CRUD
# ---------------------------------------------------------------------------


def list_purchase_orders(
    conn: sqlite3.Connection,
    project_id: int | None = None,
    subconsultant_id: int | None = None,
) -> list[sqlite3.Row]:
    """Return purchase orders with optional project/subconsultant filters.

    Joins projects and subconsultants for display names.
    """
    sql = (
        "SELECT po.*, p.job_number, p.name AS project_name, "
        "       s.company_name AS subconsultant_name "
        "FROM purchase_orders po "
        "LEFT JOIN projects p ON po.project_id = p.id "
        "LEFT JOIN subconsultants s ON po.subconsultant_id = s.id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if project_id is not None:
        sql += " AND po.project_id = ?"
        params.append(project_id)
    if subconsultant_id is not None:
        sql += " AND po.subconsultant_id = ?"
        params.append(subconsultant_id)
    sql += " ORDER BY po.created_at DESC"
    return conn.execute(sql, params).fetchall()


def create_purchase_order(
    conn: sqlite3.Connection,
    project_id: int,
    subconsultant_id: int,
    amount: float,
    **kwargs: Any,
) -> int:
    """Create a new purchase order with an auto-generated PO number.

    PO numbers follow the PO-YYMMDD-N format.
    Returns the new PO id.
    """
    po_number = _generate_po_number(conn)
    description = kwargs.get("description")
    markup_pct = kwargs.get("markup_pct", 15.0)
    status = kwargs.get("status", "draft")
    issued_date = kwargs.get("issued_date")
    notes = kwargs.get("notes")

    cur = conn.execute(
        "INSERT INTO purchase_orders "
        "(project_id, subconsultant_id, po_number, description, amount, "
        " markup_pct, status, issued_date, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            subconsultant_id,
            po_number,
            description,
            amount,
            markup_pct,
            status,
            issued_date,
            notes,
        ),
    )
    po_id = cur.lastrowid
    _log_activity(
        conn,
        "purchase_order",
        po_id,
        "created",
        {
            "po_number": po_number,
            "project_id": project_id,
            "subconsultant_id": subconsultant_id,
            "amount": amount,
        },
    )
    conn.commit()
    return po_id


def update_purchase_order(
    conn: sqlite3.Connection, po_id: int, **kwargs: Any
) -> None:
    """Update purchase order fields and log changes."""
    allowed = {
        "description", "amount", "markup_pct", "status",
        "issued_date", "notes",
    }
    sets: list[str] = []
    values: list[Any] = []
    changes: dict[str, Any] = {}
    for col in allowed:
        if col in kwargs:
            sets.append(f"{col} = ?")
            values.append(kwargs[col] if kwargs[col] != "" else None)
            changes[col] = kwargs[col]
    if not sets:
        return
    sets.append("updated_at = datetime('now')")
    values.append(po_id)
    conn.execute(
        f"UPDATE purchase_orders SET {', '.join(sets)} WHERE id = ?", values
    )
    _log_activity(conn, "purchase_order", po_id, "updated", changes)
    conn.commit()
