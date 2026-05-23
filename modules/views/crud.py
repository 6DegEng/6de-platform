"""CRUD operations for saved views.

Saved views store user-defined grid configurations (filters, visible columns,
sort order) that persist across sessions. Views can be private (visible only
to their owner) or shared (visible to all users).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def list_views(
    conn: sqlite3.Connection,
    user_id: str = "default",
) -> list[sqlite3.Row]:
    """Return all views the user can see: own views + shared views."""
    return conn.execute(
        "SELECT * FROM saved_views "
        "WHERE owner_user_id = ? OR scope = 'shared' "
        "ORDER BY name",
        (user_id,),
    ).fetchall()


def get_view(conn: sqlite3.Connection, view_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM saved_views WHERE id = ?", (view_id,)
    ).fetchone()


def create_view(
    conn: sqlite3.Connection,
    user_id: str,
    name: str,
    *,
    scope: str = "private",
    filters: dict | None = None,
    columns: list[str] | None = None,
    sort: dict | None = None,
) -> int:
    """Create a saved view and return its id."""
    if scope not in ("private", "shared"):
        raise ValueError(f"Invalid scope: {scope!r}")

    now = _now()
    cur = conn.execute(
        "INSERT INTO saved_views "
        "(owner_user_id, name, scope, filters_json, columns_json, sort_json, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            name,
            scope,
            json.dumps(filters) if filters else None,
            json.dumps(columns) if columns else None,
            json.dumps(sort) if sort else None,
            now,
            now,
        ),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def update_view(
    conn: sqlite3.Connection,
    view_id: int,
    user_id: str,
    **kwargs: Any,
) -> None:
    """Update a view. Only the owner can update."""
    row = get_view(conn, view_id)
    if row is None:
        raise ValueError(f"View {view_id} not found")
    if row["owner_user_id"] != user_id:
        raise PermissionError("Only the view owner can update it")

    updates: dict[str, Any] = {}
    for key in ("name", "scope"):
        if key in kwargs:
            updates[key] = kwargs[key]
    for key in ("filters", "columns", "sort"):
        json_key = f"{key}_json"
        if key in kwargs:
            updates[json_key] = json.dumps(kwargs[key]) if kwargs[key] is not None else None

    if not updates:
        return

    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [view_id]
    conn.execute(f"UPDATE saved_views SET {set_clause} WHERE id = ?", values)
    conn.commit()


def delete_view(
    conn: sqlite3.Connection,
    view_id: int,
    user_id: str,
) -> None:
    """Delete a view. Only the owner can delete."""
    row = get_view(conn, view_id)
    if row is None:
        raise ValueError(f"View {view_id} not found")
    if row["owner_user_id"] != user_id:
        raise PermissionError("Only the view owner can delete it")
    conn.execute("DELETE FROM saved_views WHERE id = ?", (view_id,))
    conn.commit()


def duplicate_view(
    conn: sqlite3.Connection,
    view_id: int,
    user_id: str,
    new_name: str | None = None,
) -> int:
    """Duplicate a view (any user can duplicate a shared view)."""
    row = get_view(conn, view_id)
    if row is None:
        raise ValueError(f"View {view_id} not found")
    if row["scope"] != "shared" and row["owner_user_id"] != user_id:
        raise PermissionError("Cannot duplicate a private view you don't own")

    name = new_name or f"{row['name']} (copy)"
    return create_view(
        conn,
        user_id,
        name,
        scope="private",
        filters=json.loads(row["filters_json"]) if row["filters_json"] else None,
        columns=json.loads(row["columns_json"]) if row["columns_json"] else None,
        sort=json.loads(row["sort_json"]) if row["sort_json"] else None,
    )


def hydrate_view(view_row: sqlite3.Row) -> dict[str, Any]:
    """Parse a saved_views row into a dict with deserialized JSON fields.

    Skips missing column keys for backward compatibility.
    """
    result: dict[str, Any] = {
        "id": view_row["id"],
        "name": view_row["name"],
        "scope": view_row["scope"],
        "owner_user_id": view_row["owner_user_id"],
    }
    for key in ("filters_json", "columns_json", "sort_json"):
        raw = view_row[key]
        short_key = key.replace("_json", "")
        result[short_key] = json.loads(raw) if raw else None
    return result
