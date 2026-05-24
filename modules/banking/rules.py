"""CRUD operations for categorization rules.

Thin wrapper around the categorization_rules table, providing create/read/
update/delete operations for the Accounting UI's rule editor.

The matching engine itself lives in ``modules.accounting.categorization``.
This module only manages the rule *data*.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional


def create_rule(
    conn: sqlite3.Connection,
    pattern: str,
    category: str,
    priority: int = 100,
    *,
    is_active: bool = True,
) -> int:
    """Insert a new categorization rule.  Returns the new row id.

    Raises
    ------
    ValueError
        If ``pattern`` is not a valid regex or is empty.
    sqlite3.IntegrityError
        If the pattern already exists (UNIQUE constraint).
    """
    pattern = pattern.strip()
    category = category.strip()
    if not pattern:
        raise ValueError("Pattern must not be empty.")
    if not category:
        raise ValueError("Category must not be empty.")

    # Validate regex before inserting
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Invalid regex pattern: {exc}") from exc

    cur = conn.execute(
        "INSERT INTO categorization_rules (pattern, category, priority, is_active) "
        "VALUES (?, ?, ?, ?)",
        (pattern, category, priority, 1 if is_active else 0),
    )
    conn.commit()
    return cur.lastrowid


def update_rule(
    conn: sqlite3.Connection,
    rule_id: int,
    *,
    pattern: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> bool:
    """Update fields on an existing rule.  Returns True if a row was changed."""
    sets: list[str] = []
    params: list = []

    if pattern is not None:
        pattern = pattern.strip()
        if not pattern:
            raise ValueError("Pattern must not be empty.")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern: {exc}") from exc
        sets.append("pattern = ?")
        params.append(pattern)

    if category is not None:
        category = category.strip()
        if not category:
            raise ValueError("Category must not be empty.")
        sets.append("category = ?")
        params.append(category)

    if priority is not None:
        sets.append("priority = ?")
        params.append(priority)

    if is_active is not None:
        sets.append("is_active = ?")
        params.append(1 if is_active else 0)

    if not sets:
        return False

    params.append(rule_id)
    cur = conn.execute(
        f"UPDATE categorization_rules SET {', '.join(sets)} WHERE id = ?",
        params,
    )
    conn.commit()
    return cur.rowcount > 0


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> bool:
    """Delete a categorization rule.  Returns True if a row was deleted."""
    cur = conn.execute(
        "DELETE FROM categorization_rules WHERE id = ?", (rule_id,)
    )
    conn.commit()
    return cur.rowcount > 0


def get_rule(conn: sqlite3.Connection, rule_id: int) -> Optional[dict]:
    """Fetch a single rule by id.  Returns None if not found."""
    row = conn.execute(
        "SELECT * FROM categorization_rules WHERE id = ?", (rule_id,)
    ).fetchone()
    return dict(row) if row else None


def list_rules(
    conn: sqlite3.Connection,
    *,
    active_only: bool = False,
) -> list[dict]:
    """Return all rules ordered by priority ASC, id ASC."""
    sql = "SELECT * FROM categorization_rules"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY priority ASC, id ASC"
    return [dict(r) for r in conn.execute(sql).fetchall()]


def test_pattern(
    conn: sqlite3.Connection,
    description: str,
) -> Optional[dict]:
    """Test which rule would match a given description.

    Returns a dict with the matching rule's fields, or None.
    """
    if not description:
        return None

    rows = conn.execute(
        "SELECT * FROM categorization_rules "
        "WHERE is_active = 1 ORDER BY priority ASC, id ASC"
    ).fetchall()

    for row in rows:
        try:
            if re.search(row["pattern"], description, re.IGNORECASE):
                return dict(row)
        except re.error:
            continue

    return None
