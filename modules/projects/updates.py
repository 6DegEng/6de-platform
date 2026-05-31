"""CRUD operations for project_updates."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


UPDATE_CATEGORIES = (
    "status", "permitting", "client_communication",
    "internal_note", "billing",
)

UPDATE_CATEGORY_LABELS = {
    "status": "Status",
    "permitting": "Permitting",
    "client_communication": "Client Communication",
    "internal_note": "Internal Note",
    "billing": "Billing",
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


def list_project_updates(
    conn: sqlite3.Connection,
    project_id: int,
    category_filter: str | None = None,
) -> list[sqlite3.Row]:
    if category_filter:
        return conn.execute(
            "SELECT * FROM project_updates WHERE project_id = ? AND category = ? "
            "ORDER BY created_at DESC, id DESC",
            (project_id, category_filter),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM project_updates WHERE project_id = ? "
        "ORDER BY created_at DESC, id DESC",
        (project_id,),
    ).fetchall()


def get_project_update(
    conn: sqlite3.Connection,
    update_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM project_updates WHERE id = ?",
        (update_id,),
    ).fetchone()


def create_project_update(
    conn: sqlite3.Connection,
    project_id: int,
    content: str,
    category: str = "status",
    author: str = "Juan",
) -> int:
    if category not in UPDATE_CATEGORIES:
        raise ValueError(
            f"Invalid category: {category!r}. Must be one of {UPDATE_CATEGORIES}"
        )
    now = _now()
    cur = conn.execute(
        "INSERT INTO project_updates "
        "(project_id, content, category, author, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, content, category, author, now),
    )
    conn.commit()
    update_id: int = cur.lastrowid  # type: ignore[assignment]
    _log_activity(
        conn, "project", project_id, "user_update",
        {"update_id": update_id, "category": category, "author": author},
    )
    conn.commit()
    return update_id


def delete_project_update(
    conn: sqlite3.Connection,
    update_id: int,
) -> None:
    row = conn.execute(
        "SELECT project_id FROM project_updates WHERE id = ?",
        (update_id,),
    ).fetchone()
    conn.execute("DELETE FROM project_updates WHERE id = ?", (update_id,))
    conn.commit()
    if row:
        _log_activity(
            conn, "project", row["project_id"], "update_deleted",
            {"update_id": update_id},
        )
        conn.commit()
