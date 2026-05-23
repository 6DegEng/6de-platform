"""CRUD operations for project_contacts."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


CONTACT_ROLES = (
    "client", "contractor", "architect", "inspector",
    "ahj", "subcontractor", "other",
)

CONTACT_ROLE_LABELS = {
    "client": "Client",
    "contractor": "Contractor",
    "architect": "Architect",
    "inspector": "Inspector",
    "ahj": "AHJ",
    "subcontractor": "Subcontractor",
    "other": "Other",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _log_activity(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    action: str,
    details: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO activity_log (entity_type, entity_id, action, details, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (entity_type, entity_id, action, json.dumps(details or {}), _now()),
    )


def list_project_contacts(
    conn: sqlite3.Connection,
    project_id: int,
    role_filter: str | None = None,
) -> list[sqlite3.Row]:
    if role_filter:
        return conn.execute(
            "SELECT * FROM project_contacts WHERE project_id = ? AND role = ? "
            "ORDER BY role, name",
            (project_id, role_filter),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM project_contacts WHERE project_id = ? "
        "ORDER BY role, name",
        (project_id,),
    ).fetchall()


def get_project_contact(
    conn: sqlite3.Connection,
    contact_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM project_contacts WHERE id = ?",
        (contact_id,),
    ).fetchone()


def create_project_contact(
    conn: sqlite3.Connection,
    project_id: int,
    name: str,
    role: str = "other",
    **kwargs: Any,
) -> int:
    if role not in CONTACT_ROLES:
        raise ValueError(f"Invalid role: {role!r}. Must be one of {CONTACT_ROLES}")
    now = _now()
    cur = conn.execute(
        "INSERT INTO project_contacts "
        "(project_id, name, role, email, phone, company, notes, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            name,
            role,
            kwargs.get("email"),
            kwargs.get("phone"),
            kwargs.get("company"),
            kwargs.get("notes"),
            now,
        ),
    )
    conn.commit()
    contact_id: int = cur.lastrowid  # type: ignore[assignment]
    _log_activity(
        conn, "project", project_id, "contact_added",
        {"contact_id": contact_id, "name": name, "role": role},
    )
    conn.commit()
    return contact_id


def update_project_contact(
    conn: sqlite3.Connection,
    contact_id: int,
    **kwargs: Any,
) -> None:
    if "role" in kwargs and kwargs["role"] not in CONTACT_ROLES:
        raise ValueError(
            f"Invalid role: {kwargs['role']!r}. Must be one of {CONTACT_ROLES}"
        )
    if not kwargs:
        return
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [contact_id]
    conn.execute(
        f"UPDATE project_contacts SET {set_clause} WHERE id = ?",
        values,
    )
    conn.commit()


def delete_project_contact(
    conn: sqlite3.Connection,
    contact_id: int,
) -> None:
    row = conn.execute(
        "SELECT project_id, name FROM project_contacts WHERE id = ?",
        (contact_id,),
    ).fetchone()
    conn.execute("DELETE FROM project_contacts WHERE id = ?", (contact_id,))
    conn.commit()
    if row:
        _log_activity(
            conn, "project", row["project_id"], "contact_removed",
            {"contact_id": contact_id, "name": row["name"]},
        )
        conn.commit()
