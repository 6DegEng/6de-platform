"""CRUD operations for the Permits and Contacts tables.

All functions accept a sqlite3.Connection (with row_factory=sqlite3.Row) as the
first argument so that callers own the connection lifecycle.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

from modules.activity_utils import sanitize_details

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PERMIT_COLS = [
    "project_id",
    "permit_number",
    "folio_number",
    "permit_type",
    "address",
    "status",
    "submitted_date",
    "approved_date",
    "expiration_date",
    "inspection_date",
    "jurisdiction",
    "inspector_name",
    "case_number",
    "cca_deadline",
    "extension_deadline",
    "notes",
]

_CONTACT_COLS = [
    "name",
    "title",
    "organization",
    "department",
    "email",
    "phone",
    "role_type",
    "notes",
]


def _today_str() -> str:
    return date.today().isoformat()


def _future_date_str(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


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
        (entity_type, entity_id, action, json.dumps(sanitize_details(details))),
    )


# ---------------------------------------------------------------------------
# Permits — CRUD
# ---------------------------------------------------------------------------


def list_permits(
    conn: sqlite3.Connection,
    project_id: int | None = None,
    status_filter: str | None = None,
    permit_type: str | None = None,
) -> list[sqlite3.Row]:
    """Return permits with optional filters, joined with project name."""
    sql = (
        "SELECT p.*, pr.job_number, pr.name AS project_name "
        "FROM permits p "
        "LEFT JOIN projects pr ON p.project_id = pr.id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if project_id is not None:
        sql += " AND p.project_id = ?"
        params.append(project_id)
    if status_filter:
        sql += " AND p.status = ?"
        params.append(status_filter)
    if permit_type:
        sql += " AND p.permit_type = ?"
        params.append(permit_type)
    sql += " ORDER BY p.created_at DESC"
    return conn.execute(sql, params).fetchall()


def get_permit(conn: sqlite3.Connection, permit_id: int) -> sqlite3.Row | None:
    """Return a single permit row or None."""
    return conn.execute(
        "SELECT p.*, pr.job_number, pr.name AS project_name "
        "FROM permits p "
        "LEFT JOIN projects pr ON p.project_id = pr.id "
        "WHERE p.id = ?",
        (permit_id,),
    ).fetchone()


def create_permit(
    conn: sqlite3.Connection,
    project_id: int,
    permit_type: str,
    **kwargs: Any,
) -> int:
    """Insert a new permit row and log the activity. Returns the new row id."""
    fields = ["project_id", "permit_type"]
    values: list[Any] = [project_id, permit_type]
    for col in _PERMIT_COLS:
        if col in ("project_id", "permit_type"):
            continue
        if col in kwargs and kwargs[col] is not None and kwargs[col] != "":
            fields.append(col)
            values.append(kwargs[col])

    placeholders = ", ".join("?" for _ in fields)
    col_names = ", ".join(fields)
    cur = conn.execute(
        f"INSERT INTO permits ({col_names}) VALUES ({placeholders})", values
    )
    permit_id = cur.lastrowid
    _log_activity(
        conn,
        "permit",
        permit_id,
        "created",
        {"permit_type": permit_type, "project_id": project_id},
    )
    conn.commit()
    return permit_id


def update_permit(conn: sqlite3.Connection, permit_id: int, **kwargs: Any) -> None:
    """Update permit fields and log the changes."""
    sets: list[str] = []
    values: list[Any] = []
    changes: dict[str, Any] = {}
    for col in _PERMIT_COLS:
        if col in kwargs:
            sets.append(f"{col} = ?")
            values.append(kwargs[col] if kwargs[col] != "" else None)
            changes[col] = kwargs[col]
    if not sets:
        return
    sets.append("updated_at = datetime('now')")
    values.append(permit_id)
    conn.execute(
        f"UPDATE permits SET {', '.join(sets)} WHERE id = ?", values
    )
    _log_activity(conn, "permit", permit_id, "updated", changes)
    conn.commit()


# ---------------------------------------------------------------------------
# Permits — Deadline / Alert Queries
# ---------------------------------------------------------------------------


def get_expiring_permits(
    conn: sqlite3.Connection, days_ahead: int = 30
) -> list[sqlite3.Row]:
    """Permits whose expiration_date falls within *days_ahead* from today."""
    return conn.execute(
        "SELECT p.*, pr.job_number, pr.name AS project_name "
        "FROM permits p "
        "LEFT JOIN projects pr ON p.project_id = pr.id "
        "WHERE p.expiration_date IS NOT NULL "
        "  AND p.expiration_date BETWEEN ? AND ? "
        "  AND p.status NOT IN ('closed', 'expired') "
        "ORDER BY p.expiration_date ASC",
        (_today_str(), _future_date_str(days_ahead)),
    ).fetchall()


def get_overdue_inspections(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Permits with an inspection_date in the past that are not closed."""
    return conn.execute(
        "SELECT p.*, pr.job_number, pr.name AS project_name "
        "FROM permits p "
        "LEFT JOIN projects pr ON p.project_id = pr.id "
        "WHERE p.inspection_date IS NOT NULL "
        "  AND p.inspection_date < ? "
        "  AND p.status NOT IN ('closed', 'expired', 'failed_inspection') "
        "ORDER BY p.inspection_date ASC",
        (_today_str(),),
    ).fetchall()


def get_cca_deadlines(
    conn: sqlite3.Connection, days_ahead: int = 60
) -> list[sqlite3.Row]:
    """Permits with an upcoming CCA deadline within *days_ahead*."""
    return conn.execute(
        "SELECT p.*, pr.job_number, pr.name AS project_name "
        "FROM permits p "
        "LEFT JOIN projects pr ON p.project_id = pr.id "
        "WHERE p.cca_deadline IS NOT NULL "
        "  AND p.cca_deadline BETWEEN ? AND ? "
        "  AND p.status NOT IN ('closed') "
        "ORDER BY p.cca_deadline ASC",
        (_today_str(), _future_date_str(days_ahead)),
    ).fetchall()


# ---------------------------------------------------------------------------
# Permits — Stats / Search
# ---------------------------------------------------------------------------


def get_permit_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return counts grouped by status and by permit_type."""
    by_status = {}
    for row in conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM permits GROUP BY status"
    ):
        by_status[row["status"]] = row["cnt"]

    by_type = {}
    for row in conn.execute(
        "SELECT permit_type, COUNT(*) AS cnt FROM permits GROUP BY permit_type"
    ):
        by_type[row["permit_type"]] = row["cnt"]

    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "by_type": by_type,
    }


def search_permits(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """Search permits by permit_number, folio_number, or address."""
    like = f"%{query}%"
    return conn.execute(
        "SELECT p.*, pr.job_number, pr.name AS project_name "
        "FROM permits p "
        "LEFT JOIN projects pr ON p.project_id = pr.id "
        "WHERE p.permit_number LIKE ? "
        "   OR p.folio_number  LIKE ? "
        "   OR p.address       LIKE ? "
        "ORDER BY p.created_at DESC",
        (like, like, like),
    ).fetchall()


# ---------------------------------------------------------------------------
# Contacts — CRUD
# ---------------------------------------------------------------------------


def list_contacts(
    conn: sqlite3.Connection, role_type: str | None = None
) -> list[sqlite3.Row]:
    """Return contacts, optionally filtered by role_type."""
    if role_type:
        return conn.execute(
            "SELECT * FROM contacts WHERE role_type = ? ORDER BY name", (role_type,)
        ).fetchall()
    return conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()


def create_contact(conn: sqlite3.Connection, name: str, **kwargs: Any) -> int:
    """Insert a new contact row. Returns the new row id."""
    fields = ["name"]
    values: list[Any] = [name]
    for col in _CONTACT_COLS:
        if col == "name":
            continue
        if col in kwargs and kwargs[col] is not None and kwargs[col] != "":
            fields.append(col)
            values.append(kwargs[col])

    placeholders = ", ".join("?" for _ in fields)
    col_names = ", ".join(fields)
    cur = conn.execute(
        f"INSERT INTO contacts ({col_names}) VALUES ({placeholders})", values
    )
    conn.commit()
    return cur.lastrowid


def update_contact(conn: sqlite3.Connection, contact_id: int, **kwargs: Any) -> None:
    """Update contact fields."""
    sets: list[str] = []
    values: list[Any] = []
    for col in _CONTACT_COLS:
        if col in kwargs:
            sets.append(f"{col} = ?")
            values.append(kwargs[col] if kwargs[col] != "" else None)
    if not sets:
        return
    values.append(contact_id)
    conn.execute(
        f"UPDATE contacts SET {', '.join(sets)} WHERE id = ?", values
    )
    conn.commit()
