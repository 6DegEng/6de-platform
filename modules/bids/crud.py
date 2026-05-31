"""CRUD operations for the Government Bids module.

Tracks bid opportunities from portals like MFMP, DemandStar, BidNet,
Sam.gov, and county-direct solicitations.  Supports go/no-go decisions,
deadline tracking, and pipeline statistics.

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

_BID_COLS = [
    "opportunity_id",
    "portal",
    "solicitation_number",
    "title",
    "agency",
    "submission_deadline",
    "question_deadline",
    "pre_bid_date",
    "estimated_value",
    "status",
    "go_no_go_date",
    "go_no_go_notes",
    "compliance_items",
    "file_path",
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
        (entity_type, entity_id, action, json.dumps(sanitize_details(details))),
    )


# ---------------------------------------------------------------------------
# Bids — CRUD
# ---------------------------------------------------------------------------


def list_bids(
    conn: sqlite3.Connection,
    status: str | None = None,
    portal: str | None = None,
) -> list[sqlite3.Row]:
    """Return bid opportunities with optional status/portal filters.

    LEFT JOINs on opportunities to include the linked opportunity name.
    """
    sql = (
        "SELECT b.*, o.name AS opportunity_name "
        "FROM bid_opportunities b "
        "LEFT JOIN opportunities o ON b.opportunity_id = o.id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if status:
        sql += " AND b.status = ?"
        params.append(status)
    if portal:
        sql += " AND b.portal = ?"
        params.append(portal)
    sql += " ORDER BY b.submission_deadline ASC, b.created_at DESC"
    return conn.execute(sql, params).fetchall()


def get_bid(conn: sqlite3.Connection, bid_id: int) -> sqlite3.Row | None:
    """Return a single bid row or None."""
    return conn.execute(
        "SELECT b.*, o.name AS opportunity_name "
        "FROM bid_opportunities b "
        "LEFT JOIN opportunities o ON b.opportunity_id = o.id "
        "WHERE b.id = ?",
        (bid_id,),
    ).fetchone()


def create_bid(
    conn: sqlite3.Connection,
    title: str,
    portal: str,
    **kwargs: Any,
) -> int:
    """Insert a new bid opportunity and return its id."""
    fields = ["title", "portal"]
    values: list[Any] = [title, portal]

    for col in _BID_COLS:
        if col in ("title", "portal"):
            continue
        if col in kwargs and kwargs[col] is not None and kwargs[col] != "":
            fields.append(col)
            values.append(kwargs[col])

    placeholders = ", ".join("?" for _ in fields)
    col_names = ", ".join(fields)
    cur = conn.execute(
        f"INSERT INTO bid_opportunities ({col_names}) VALUES ({placeholders})",
        values,
    )
    bid_id = cur.lastrowid
    _log_activity(
        conn,
        "bid",
        bid_id,
        "created",
        {"title": title, "portal": portal},
    )
    conn.commit()
    return bid_id


def update_bid(conn: sqlite3.Connection, bid_id: int, **kwargs: Any) -> None:
    """Update bid fields and log the changes."""
    sets: list[str] = []
    values: list[Any] = []
    changes: dict[str, Any] = {}
    for col in _BID_COLS:
        if col in kwargs:
            sets.append(f"{col} = ?")
            values.append(kwargs[col] if kwargs[col] != "" else None)
            changes[col] = kwargs[col]
    if not sets:
        return
    sets.append("updated_at = datetime('now')")
    values.append(bid_id)
    conn.execute(
        f"UPDATE bid_opportunities SET {', '.join(sets)} WHERE id = ?", values
    )
    _log_activity(conn, "bid", bid_id, "updated", changes)
    conn.commit()


def set_go_no_go(
    conn: sqlite3.Connection,
    bid_id: int,
    decision: str,
    notes: str | None = None,
) -> None:
    """Record a go/no-go decision on a bid.

    Sets status to 'go' or 'no_go', records the date and optional notes.
    """
    if decision not in ("go", "no_go"):
        raise ValueError(f"Decision must be 'go' or 'no_go', got '{decision}'")

    today = _today_str()
    conn.execute(
        "UPDATE bid_opportunities "
        "SET status = ?, go_no_go_date = ?, go_no_go_notes = ?, "
        "    updated_at = datetime('now') "
        "WHERE id = ?",
        (decision, today, notes, bid_id),
    )
    _log_activity(
        conn,
        "bid",
        bid_id,
        "go_no_go",
        {"decision": decision, "date": today, "notes": notes},
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Deadline queries
# ---------------------------------------------------------------------------


def get_upcoming_deadlines(
    conn: sqlite3.Connection,
    days_ahead: int = 14,
) -> list[sqlite3.Row]:
    """Return bids with a submission_deadline within *days_ahead* days.

    Only includes bids whose status is monitoring, go, or preparing.
    """
    today = _today_str()
    future = (date.today() + timedelta(days=days_ahead)).isoformat()
    return conn.execute(
        "SELECT b.*, o.name AS opportunity_name "
        "FROM bid_opportunities b "
        "LEFT JOIN opportunities o ON b.opportunity_id = o.id "
        "WHERE b.submission_deadline IS NOT NULL "
        "  AND b.submission_deadline BETWEEN ? AND ? "
        "  AND b.status IN ('monitoring', 'go', 'preparing') "
        "ORDER BY b.submission_deadline ASC",
        (today, future),
    ).fetchall()


# ---------------------------------------------------------------------------
# Stats & Search
# ---------------------------------------------------------------------------


def get_bid_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return bid pipeline statistics.

    Returns a dict with:
        total       -- total bid count
        by_status   -- dict mapping status -> count
        by_portal   -- dict mapping portal -> count
        win_rate    -- float percentage (won / (won + lost)) or 0.0
    """
    by_status: dict[str, int] = {}
    for row in conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM bid_opportunities GROUP BY status"
    ):
        by_status[row["status"]] = row["cnt"]

    by_portal: dict[str, int] = {}
    for row in conn.execute(
        "SELECT portal, COUNT(*) AS cnt FROM bid_opportunities GROUP BY portal"
    ):
        by_portal[row["portal"]] = row["cnt"]

    total = sum(by_status.values())
    won = by_status.get("won", 0)
    lost = by_status.get("lost", 0)
    win_rate = round((won / (won + lost)) * 100, 1) if (won + lost) > 0 else 0.0

    return {
        "total": total,
        "by_status": by_status,
        "by_portal": by_portal,
        "win_rate": win_rate,
    }


def search_bids(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """Search bids by title, agency, or solicitation_number."""
    like = f"%{query}%"
    return conn.execute(
        "SELECT b.*, o.name AS opportunity_name "
        "FROM bid_opportunities b "
        "LEFT JOIN opportunities o ON b.opportunity_id = o.id "
        "WHERE b.title LIKE ? "
        "   OR b.agency LIKE ? "
        "   OR b.solicitation_number LIKE ? "
        "ORDER BY b.submission_deadline ASC",
        (like, like, like),
    ).fetchall()
