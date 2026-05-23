"""CRUD operations for project_notes."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


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


def list_project_notes(
    conn: sqlite3.Connection,
    project_id: int,
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM project_notes WHERE project_id = ? "
        "ORDER BY created_at DESC, id DESC",
        (project_id,),
    ).fetchall()


def get_project_note(
    conn: sqlite3.Connection,
    note_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM project_notes WHERE id = ?",
        (note_id,),
    ).fetchone()


def create_project_note(
    conn: sqlite3.Connection,
    project_id: int,
    content: str,
    author: str = "Juan",
) -> int:
    now = _now()
    cur = conn.execute(
        "INSERT INTO project_notes (project_id, content, author, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, content, author, now, now),
    )
    conn.commit()
    note_id: int = cur.lastrowid  # type: ignore[assignment]
    _log_activity(
        conn, "project", project_id, "note_added",
        {"note_id": note_id, "author": author},
    )
    conn.commit()
    return note_id


def update_project_note(
    conn: sqlite3.Connection,
    note_id: int,
    content: str,
) -> None:
    conn.execute(
        "UPDATE project_notes SET content = ?, updated_at = ? WHERE id = ?",
        (content, _now(), note_id),
    )
    conn.commit()


def delete_project_note(
    conn: sqlite3.Connection,
    note_id: int,
) -> None:
    row = conn.execute(
        "SELECT project_id FROM project_notes WHERE id = ?", (note_id,)
    ).fetchone()
    conn.execute("DELETE FROM project_notes WHERE id = ?", (note_id,))
    conn.commit()
    if row:
        _log_activity(
            conn, "project", row["project_id"], "note_deleted",
            {"note_id": note_id},
        )
        conn.commit()
