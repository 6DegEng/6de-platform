"""CRUD operations for the Documents module.

Provides a generic document-linking system that ties files (proposals, invoices,
calc PDFs, drawings, etc.) to any entity in the platform via entity_type and
entity_id.  Only manages DB records -- physical file operations are handled
externally.

All functions accept a sqlite3.Connection (with row_factory=sqlite3.Row) as the
first argument so that callers own the connection lifecycle.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Documents — CRUD
# ---------------------------------------------------------------------------


def link_document(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    file_name: str,
    file_path: str,
    doc_type: str,
    **kwargs: Any,
) -> int:
    """Create a document record linking a file to an entity.

    Returns the new document id.
    """
    version = kwargs.get("version", 1)
    notes = kwargs.get("notes")

    cur = conn.execute(
        "INSERT INTO documents "
        "(entity_type, entity_id, doc_type, file_name, file_path, version, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (entity_type, entity_id, doc_type, file_name, file_path, version, notes),
    )
    doc_id = cur.lastrowid
    _log_activity(
        conn,
        "document",
        doc_id,
        "created",
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "doc_type": doc_type,
            "file_name": file_name,
        },
    )
    conn.commit()
    return doc_id


def list_documents(
    conn: sqlite3.Connection,
    entity_type: str | None = None,
    entity_id: int | None = None,
    doc_type: str | None = None,
) -> list[sqlite3.Row]:
    """Return documents with optional filters.

    All filters are AND-combined when provided.
    """
    sql = "SELECT * FROM documents WHERE 1=1"
    params: list[Any] = []
    if entity_type:
        sql += " AND entity_type = ?"
        params.append(entity_type)
    if entity_id is not None:
        sql += " AND entity_id = ?"
        params.append(entity_id)
    if doc_type:
        sql += " AND doc_type = ?"
        params.append(doc_type)
    sql += " ORDER BY created_at DESC"
    return conn.execute(sql, params).fetchall()


def get_document(conn: sqlite3.Connection, doc_id: int) -> sqlite3.Row | None:
    """Return a single document row or None."""
    return conn.execute(
        "SELECT * FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()


def delete_document(conn: sqlite3.Connection, doc_id: int) -> None:
    """Delete a document DB record (does NOT remove the physical file)."""
    doc = get_document(conn, doc_id)
    if doc is None:
        return
    _log_activity(
        conn,
        "document",
        doc_id,
        "deleted",
        {
            "entity_type": doc["entity_type"],
            "entity_id": doc["entity_id"],
            "file_name": doc["file_name"],
        },
    )
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()


def get_document_count(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
) -> int:
    """Return the number of documents linked to a specific entity."""
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM documents "
        "WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    ).fetchone()
    return row["cnt"] if row else 0
