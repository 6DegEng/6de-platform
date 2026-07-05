"""CRUD operations for the projects module.

All functions expect an ``sqlite3.Connection`` returned by ``db.ensure_db()``
(i.e. with ``row_factory = sqlite3.Row`` and ``foreign_keys = ON``).

Prefer derived/computed fields over mirrored status columns — compute at
read time rather than duplicating state that can drift.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from modules.activity_utils import nan_to_none, sanitize_details


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _generate_job_number(conn: sqlite3.Connection) -> str:
    """Generate the next available job number in YYMMDD format.

    Uses today's date as the base.  If a project with that job number
    already exists, appends an alphabetic suffix (a, b, c ...).
    """
    today = date.today().strftime("%y%m%d")
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM projects WHERE job_number LIKE ? || '%'",
        (today,),
    ).fetchone()
    if row["cnt"] == 0:
        return today
    # Append letter suffix for same-day duplicates
    suffix = chr(ord("a") + row["cnt"])
    return f"{today}{suffix}"


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
        (entity_type, entity_id, action, json.dumps(sanitize_details(details)), _now()),
    )


# ---------------------------------------------------------------------------
# Projects — CRUD
# ---------------------------------------------------------------------------

def list_projects(
    conn: sqlite3.Connection,
    status_filter: str | None = None,
) -> list[sqlite3.Row]:
    """Return all projects, optionally filtered by status.

    Results are ordered by ``job_number DESC`` (most recent first).
    """
    if status_filter:
        rows = conn.execute(
            "SELECT p.*, c.name AS client_name "
            "FROM projects p LEFT JOIN clients c ON p.client_id = c.id "
            "WHERE p.status = ? ORDER BY p.job_number DESC",
            (status_filter,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT p.*, c.name AS client_name "
            "FROM projects p LEFT JOIN clients c ON p.client_id = c.id "
            "ORDER BY p.job_number DESC",
        ).fetchall()
    return rows


def get_project(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    """Fetch a single project by ID, or ``None`` if not found."""
    return conn.execute(
        "SELECT p.*, c.name AS client_name "
        "FROM projects p LEFT JOIN clients c ON p.client_id = c.id "
        "WHERE p.id = ?",
        (project_id,),
    ).fetchone()


def create_project(conn: sqlite3.Connection, **kwargs: Any) -> int:
    """Insert a new project and return its ``id``.

    If ``job_number`` is not provided it is auto-generated from today's date.
    All remaining keyword arguments are mapped to column names in the
    ``projects`` table.
    """
    if "job_number" not in kwargs or not kwargs["job_number"]:
        kwargs["job_number"] = _generate_job_number(conn)

    now = _now()
    kwargs.setdefault("created_at", now)
    kwargs.setdefault("updated_at", now)

    # Build a folder_path from the job_number and name if not provided
    if "folder_path" not in kwargs and "name" in kwargs:
        kwargs["folder_path"] = f"{kwargs['job_number']} - {kwargs['name']}"

    kwargs = {k: nan_to_none(v) for k, v in kwargs.items()}
    columns = ", ".join(kwargs.keys())
    placeholders = ", ".join("?" for _ in kwargs)
    values = list(kwargs.values())

    cur = conn.execute(
        f"INSERT INTO projects ({columns}) VALUES ({placeholders})",
        values,
    )
    conn.commit()

    project_id: int = cur.lastrowid  # type: ignore[assignment]
    _log_activity(conn, "project", project_id, "created", kwargs)
    conn.commit()
    return project_id


def update_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    unarchive: bool = False,
    **kwargs: Any,
) -> None:
    """Update fields on an existing project.

    Automatically sets ``updated_at`` to now and logs the change to
    ``activity_log``. Status changes are validated against the workflow
    and emit a dedicated ``status_changed`` activity row.
    """
    from modules.projects.workflow import (
        clamp_percent_complete,
        validate_priority,
        validate_status_transition,
    )

    if "status" in kwargs:
        old_row = conn.execute(
            "SELECT status FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if old_row:
            old_status = old_row["status"]
            new_status = kwargs["status"]
            if old_status != new_status:
                validate_status_transition(
                    old_status, new_status, unarchive=unarchive
                )

    if "priority" in kwargs and kwargs["priority"] is not None:
        validate_priority(kwargs["priority"])

    if "percent_complete" in kwargs and kwargs["percent_complete"] is not None:
        kwargs["percent_complete"] = clamp_percent_complete(
            kwargs["percent_complete"]
        )

    kwargs = {k: nan_to_none(v) for k, v in kwargs.items()}
    kwargs["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [project_id]
    conn.execute(
        f"UPDATE projects SET {set_clause} WHERE id = ?",
        values,
    )
    conn.commit()

    if "status" in kwargs and old_row and old_row["status"] != kwargs["status"]:
        _log_activity(
            conn, "project", project_id, "status_changed",
            {"from": old_row["status"], "to": kwargs["status"]},
        )
    else:
        _log_activity(conn, "project", project_id, "updated", kwargs)
    conn.commit()


def delete_project(conn: sqlite3.Connection, project_id: int) -> None:
    """Delete a project and its related records (via CASCADE)."""
    _log_activity(conn, "project", project_id, "deleted")
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

def list_milestones(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    """Return milestones for a project, ordered by sort_order then due_date."""
    return conn.execute(
        "SELECT * FROM milestones WHERE project_id = ? "
        "ORDER BY sort_order, due_date",
        (project_id,),
    ).fetchall()


def create_milestone(
    conn: sqlite3.Connection,
    project_id: int,
    name: str,
    due_date: str | None = None,
) -> int:
    """Create a new milestone and return its ``id``."""
    # Determine next sort_order
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order "
        "FROM milestones WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    sort_order = row["next_order"]

    cur = conn.execute(
        "INSERT INTO milestones (project_id, name, due_date, sort_order, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, name, due_date, sort_order, _now()),
    )
    conn.commit()
    _log_activity(
        conn,
        "milestone",
        cur.lastrowid,  # type: ignore[arg-type]
        "created",
        {"project_id": project_id, "name": name},
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def update_milestone(conn: sqlite3.Connection, milestone_id: int, **kwargs: Any) -> None:
    """Update fields on a milestone."""
    if not kwargs:
        return
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [milestone_id]
    conn.execute(
        f"UPDATE milestones SET {set_clause} WHERE id = ?",
        values,
    )
    conn.commit()
    _log_activity(conn, "milestone", milestone_id, "updated", kwargs)
    conn.commit()


# ---------------------------------------------------------------------------
# Stats & Search
# ---------------------------------------------------------------------------

def get_project_stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Return project counts grouped by status plus a total.

    Returns a dict like::

        {"total": 12, "active": 5, "prospect": 3, ...}
    """
    from modules.status_colors import WORKING_STATUSES

    rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM projects GROUP BY status"
    ).fetchall()
    stats: dict[str, int] = {row["status"]: row["cnt"] for row in rows}
    stats["total"] = sum(stats.values())
    # "Working" = the ACTIVE lifecycle bucket (active/drafting/ahj_permitting/
    # inspection/revisions) — definition ratified by Juan 2026-06-12.
    stats["working"] = sum(stats.get(s, 0) for s in WORKING_STATUSES)
    return stats


def search_projects(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """Search projects by name, address, or job_number (case-insensitive)."""
    like = f"%{query}%"
    return conn.execute(
        "SELECT p.*, c.name AS client_name "
        "FROM projects p LEFT JOIN clients c ON p.client_id = c.id "
        "WHERE p.name LIKE ? OR p.address LIKE ? OR p.job_number LIKE ? "
        "ORDER BY p.job_number DESC",
        (like, like, like),
    ).fetchall()
