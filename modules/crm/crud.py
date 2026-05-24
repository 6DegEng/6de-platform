"""CRM / Pipeline CRUD operations for 6th Degree Engineering.

Manages the opportunities pipeline (lead -> qualifying -> proposal_sent ->
negotiating -> won/lost/dormant) and the clients table.  All mutating
operations log to the activity_log table.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Any

from modules.activity_utils import sanitize_details


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STAGES = ("lead", "qualifying", "proposal_sent", "negotiating", "won", "lost", "dormant")

SERVICE_LINES = (
    "structural", "civil", "sirs", "forensics", "pools",
    "recertification", "threshold", "government", "other",
)

SOURCES = (
    "referral", "repeat", "website", "bid_portal",
    "cold_outreach", "conference", "other",
)

# Valid forward transitions — each stage maps to the stages it may move to.
_STAGE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "lead":          ("qualifying", "lost", "dormant"),
    "qualifying":    ("proposal_sent", "lost", "dormant"),
    "proposal_sent": ("negotiating", "won", "lost", "dormant"),
    "negotiating":   ("won", "lost", "dormant"),
    "won":           ("dormant",),
    "lost":          ("lead", "dormant"),
    "dormant":       ("lead",),
}

_OPP_ALLOWED_COLS = {
    "client_id", "project_id", "name", "service_line", "stage",
    "estimated_value", "probability", "source", "close_date",
    "contact_name", "contact_email", "contact_phone", "notes",
}

_CLIENT_ALLOWED_COLS = {
    "name", "company", "email", "phone", "address", "notes",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
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
# Opportunities — CRUD
# ---------------------------------------------------------------------------

def list_opportunities(
    conn: sqlite3.Connection,
    stage: str | None = None,
    service_line: str | None = None,
    client_id: int | None = None,
) -> list[sqlite3.Row]:
    """Return opportunities with optional filters, LEFT JOIN clients for client_name."""
    sql = (
        "SELECT o.*, c.name AS client_name "
        "FROM opportunities o "
        "LEFT JOIN clients c ON o.client_id = c.id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if stage is not None:
        sql += " AND o.stage = ?"
        params.append(stage)
    if service_line is not None:
        sql += " AND o.service_line = ?"
        params.append(service_line)
    if client_id is not None:
        sql += " AND o.client_id = ?"
        params.append(client_id)
    sql += " ORDER BY o.updated_at DESC"
    return conn.execute(sql, params).fetchall()


def get_opportunity(conn: sqlite3.Connection, opp_id: int) -> sqlite3.Row | None:
    """Fetch a single opportunity by ID, or None if not found."""
    return conn.execute(
        "SELECT o.*, c.name AS client_name "
        "FROM opportunities o "
        "LEFT JOIN clients c ON o.client_id = c.id "
        "WHERE o.id = ?",
        (opp_id,),
    ).fetchone()


def create_opportunity(conn: sqlite3.Connection, name: str, **kwargs: Any) -> int:
    """Insert a new opportunity and return its id. Logs activity."""
    now = _now()
    fields = {"name": name, "created_at": now, "updated_at": now}
    for k, v in kwargs.items():
        if k in _OPP_ALLOWED_COLS and v is not None and v != "":
            fields[k] = v

    columns = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    values = list(fields.values())

    cur = conn.execute(
        f"INSERT INTO opportunities ({columns}) VALUES ({placeholders})", values
    )
    opp_id: int = cur.lastrowid  # type: ignore[assignment]
    _log_activity(conn, "opportunity", opp_id, "created", {"name": name, **kwargs})
    conn.commit()
    return opp_id


def update_opportunity(conn: sqlite3.Connection, opp_id: int, **kwargs: Any) -> None:
    """Update fields on an existing opportunity."""
    filtered = {k: v for k, v in kwargs.items() if k in _OPP_ALLOWED_COLS}
    if not filtered:
        return
    filtered["updated_at"] = _now()
    set_clause = ", ".join(f"{col} = ?" for col in filtered)
    values = list(filtered.values()) + [opp_id]
    conn.execute(
        f"UPDATE opportunities SET {set_clause} WHERE id = ?", values  # noqa: S608
    )
    _log_activity(conn, "opportunity", opp_id, "updated", filtered)
    conn.commit()


def advance_stage(conn: sqlite3.Connection, opp_id: int, new_stage: str) -> None:
    """Move an opportunity to *new_stage*, validating the transition.

    Raises ``ValueError`` if the transition is not allowed.
    """
    opp = get_opportunity(conn, opp_id)
    if opp is None:
        raise ValueError(f"Opportunity {opp_id} not found")

    old_stage = opp["stage"]
    allowed = _STAGE_TRANSITIONS.get(old_stage, ())
    if new_stage not in allowed:
        raise ValueError(
            f"Cannot transition from '{old_stage}' to '{new_stage}'. "
            f"Allowed transitions: {allowed}"
        )

    now = _now()
    conn.execute(
        "UPDATE opportunities SET stage = ?, updated_at = ? WHERE id = ?",
        (new_stage, now, opp_id),
    )
    _log_activity(
        conn,
        "opportunity",
        opp_id,
        "stage_change",
        {"old_stage": old_stage, "new_stage": new_stage},
    )
    conn.commit()


def convert_to_project(conn: sqlite3.Connection, opp_id: int) -> int:
    """Create a project from a *won* opportunity, link them, and return the project id.

    Raises ``ValueError`` if the opportunity is not in 'won' stage.
    """
    opp = get_opportunity(conn, opp_id)
    if opp is None:
        raise ValueError(f"Opportunity {opp_id} not found")
    if opp["stage"] != "won":
        raise ValueError(
            f"Only 'won' opportunities can be converted. Current stage: '{opp['stage']}'"
        )

    # Generate job number (same logic as projects crud)
    today_prefix = date.today().strftime("%y%m%d")
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM projects WHERE job_number LIKE ? || '%'",
        (today_prefix,),
    ).fetchone()
    if row["cnt"] == 0:
        job_number = today_prefix
    else:
        suffix = chr(ord("a") + row["cnt"])
        job_number = f"{today_prefix}{suffix}"

    now = _now()
    folder_path = f"{job_number} - {opp['name']}"

    cur = conn.execute(
        "INSERT INTO projects "
        "(job_number, name, client_id, status, scope, folder_path, created_at, updated_at) "
        "VALUES (?, ?, ?, 'active', ?, ?, ?, ?)",
        (job_number, opp["name"], opp["client_id"], opp["notes"], folder_path, now, now),
    )
    project_id: int = cur.lastrowid  # type: ignore[assignment]

    # Link opportunity to project
    conn.execute(
        "UPDATE opportunities SET project_id = ?, updated_at = ? WHERE id = ?",
        (project_id, now, opp_id),
    )

    _log_activity(
        conn, "project", project_id, "created",
        {"source": "opportunity", "opportunity_id": opp_id, "job_number": job_number},
    )
    _log_activity(
        conn, "opportunity", opp_id, "converted_to_project",
        {"project_id": project_id, "job_number": job_number},
    )
    conn.commit()
    return project_id


# ---------------------------------------------------------------------------
# Pipeline Analytics
# ---------------------------------------------------------------------------

def get_pipeline_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return count + value by stage and the weighted pipeline total.

    Returns::

        {
            "by_stage": {"lead": {"count": 3, "total_value": 15000, "weighted_value": 3750}, ...},
            "total_pipeline_value": 50000,
            "weighted_pipeline_total": 22500,
            "active_count": 12,
        }
    """
    rows = conn.execute(
        "SELECT stage, "
        "       COUNT(*) AS count, "
        "       COALESCE(SUM(estimated_value), 0) AS total_value, "
        "       COALESCE(SUM(estimated_value * probability / 100.0), 0) AS weighted_value "
        "FROM opportunities "
        "WHERE stage NOT IN ('lost', 'dormant') "
        "GROUP BY stage"
    ).fetchall()

    by_stage: dict[str, dict[str, Any]] = {}
    total_value = 0.0
    weighted_total = 0.0
    active_count = 0

    for row in rows:
        by_stage[row["stage"]] = {
            "count": row["count"],
            "total_value": row["total_value"],
            "weighted_value": row["weighted_value"],
        }
        total_value += row["total_value"]
        weighted_total += row["weighted_value"]
        active_count += row["count"]

    return {
        "by_stage": by_stage,
        "total_pipeline_value": total_value,
        "weighted_pipeline_total": weighted_total,
        "active_count": active_count,
    }


def get_win_loss_stats(
    conn: sqlite3.Connection,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Return win/loss statistics over the given date range.

    Returns::

        {
            "total_won": 5,
            "total_lost": 3,
            "win_rate": 62.5,
            "avg_deal_size": 12500.0,
            "total_won_value": 62500.0,
        }
    """
    where_parts: list[str] = ["stage IN ('won', 'lost')"]
    params: list[Any] = []

    if date_from:
        where_parts.append("updated_at >= ?")
        params.append(date_from)
    if date_to:
        where_parts.append("updated_at <= ?")
        params.append(date_to)

    where_clause = " AND ".join(where_parts)

    rows = conn.execute(
        f"SELECT stage, COUNT(*) AS cnt, COALESCE(SUM(estimated_value), 0) AS total_val "
        f"FROM opportunities WHERE {where_clause} GROUP BY stage",
        params,
    ).fetchall()

    won = 0
    lost = 0
    won_value = 0.0
    for row in rows:
        if row["stage"] == "won":
            won = row["cnt"]
            won_value = row["total_val"]
        elif row["stage"] == "lost":
            lost = row["cnt"]

    total = won + lost
    win_rate = (won / total * 100) if total > 0 else 0.0
    avg_deal = (won_value / won) if won > 0 else 0.0

    return {
        "total_won": won,
        "total_lost": lost,
        "win_rate": round(win_rate, 1),
        "avg_deal_size": round(avg_deal, 2),
        "total_won_value": won_value,
    }


# ---------------------------------------------------------------------------
# Opportunity Search
# ---------------------------------------------------------------------------

def search_opportunities(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """Search opportunities by name, contact_name, contact_email, or notes."""
    like = f"%{query}%"
    return conn.execute(
        "SELECT o.*, c.name AS client_name "
        "FROM opportunities o "
        "LEFT JOIN clients c ON o.client_id = c.id "
        "WHERE o.name LIKE ? "
        "   OR o.contact_name  LIKE ? "
        "   OR o.contact_email LIKE ? "
        "   OR o.notes         LIKE ? "
        "ORDER BY o.updated_at DESC",
        (like, like, like, like),
    ).fetchall()


# ---------------------------------------------------------------------------
# Clients — CRUD
# ---------------------------------------------------------------------------

def list_clients(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all clients ordered by name."""
    return conn.execute(
        "SELECT * FROM clients ORDER BY name"
    ).fetchall()


def get_client(conn: sqlite3.Connection, client_id: int) -> sqlite3.Row | None:
    """Fetch a single client by ID, or None if not found."""
    return conn.execute(
        "SELECT * FROM clients WHERE id = ?", (client_id,)
    ).fetchone()


def create_client(conn: sqlite3.Connection, name: str, **kwargs: Any) -> int:
    """Insert a new client and return its id."""
    now = _now()
    fields: dict[str, Any] = {"name": name, "created_at": now, "updated_at": now}
    for k, v in kwargs.items():
        if k in _CLIENT_ALLOWED_COLS and v is not None and v != "":
            fields[k] = v

    columns = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    values = list(fields.values())

    cur = conn.execute(
        f"INSERT INTO clients ({columns}) VALUES ({placeholders})", values
    )
    client_id: int = cur.lastrowid  # type: ignore[assignment]
    _log_activity(conn, "client", client_id, "created", {"name": name})
    conn.commit()
    return client_id


def update_client(conn: sqlite3.Connection, client_id: int, **kwargs: Any) -> None:
    """Update fields on an existing client."""
    filtered = {k: v for k, v in kwargs.items() if k in _CLIENT_ALLOWED_COLS}
    if not filtered:
        return
    filtered["updated_at"] = _now()
    set_clause = ", ".join(f"{col} = ?" for col in filtered)
    values = list(filtered.values()) + [client_id]
    conn.execute(
        f"UPDATE clients SET {set_clause} WHERE id = ?", values  # noqa: S608
    )
    _log_activity(conn, "client", client_id, "updated", filtered)
    conn.commit()
