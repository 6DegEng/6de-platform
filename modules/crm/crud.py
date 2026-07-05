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
from modules.crm import stages as stage_config


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Since crm-polish phase 2 the pipeline stages live in the crm_stages config
# table (see modules/crm/stages.py). The tuples below are the seeded defaults
# and the fallback for databases where the config table is empty/missing.
STAGES = ("lead", "qualifying", "proposal_sent", "negotiating", "won", "lost", "dormant")

# "Active" = open pipeline stages only. Excludes the three terminal/closed
# stages (won = closed-won, lost = closed-lost, dormant = parked/inactive).
# At runtime the open set is read from crm_stages (active AND NOT is_closed);
# with the default seed it equals this tuple, so the KPI and any "active"
# list header agree by definition.
ACTIVE_STAGES = ("lead", "qualifying", "proposal_sent", "negotiating")
CLOSED_STAGES = ("won", "lost", "dormant")

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
    "lost_reason_id", "lost_note",
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
    """Return opportunities with optional filters, LEFT JOIN clients for client_name.

    Each row carries ``expected_revenue`` = estimated_value x probability/100
    (the prorated value that pipeline forecasts sum up).
    """
    sql = (
        "SELECT o.*, c.name AS client_name, "
        "       COALESCE(o.estimated_value, 0) * COALESCE(o.probability, 0) / 100.0 "
        "           AS expected_revenue "
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
        "SELECT o.*, c.name AS client_name, "
        "       COALESCE(o.estimated_value, 0) * COALESCE(o.probability, 0) / 100.0 "
        "           AS expected_revenue "
        "FROM opportunities o "
        "LEFT JOIN clients c ON o.client_id = c.id "
        "WHERE o.id = ?",
        (opp_id,),
    ).fetchone()


def _validate_stage_exists(conn: sqlite3.Connection, stage: str) -> None:
    """App-layer replacement for the retired DB CHECK on opportunities.stage.

    Raises ``ValueError`` for a stage key that is neither built-in nor
    present in the crm_stages config table.
    """
    if stage in STAGES:
        return
    if stage_config.get_stage_by_key(conn, stage) is None:
        raise ValueError(f"Unknown stage '{stage}'")


def create_opportunity(conn: sqlite3.Connection, name: str, **kwargs: Any) -> int:
    """Insert a new opportunity and return its id. Logs activity."""
    now = _now()
    fields = {"name": name, "created_at": now, "updated_at": now}
    for k, v in kwargs.items():
        if k in _OPP_ALLOWED_COLS and v is not None and v != "":
            fields[k] = v
    if "stage" in fields:
        _validate_stage_exists(conn, fields["stage"])

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
    if "stage" in filtered:
        _validate_stage_exists(conn, filtered["stage"])
    filtered["updated_at"] = _now()
    set_clause = ", ".join(f"{col} = ?" for col in filtered)
    values = list(filtered.values()) + [opp_id]
    conn.execute(
        f"UPDATE opportunities SET {set_clause} WHERE id = ?", values  # noqa: S608
    )
    _log_activity(conn, "opportunity", opp_id, "updated", filtered)
    conn.commit()


def allowed_next_stages(
    conn: sqlite3.Connection,
    current_stage: str,
    active_keys: list[str] | None = None,
) -> list[str]:
    """Stage keys an opportunity in *current_stage* may move to.

    Built-in stages keep the original forward-transition rules. Custom
    (user-added) stages are freely reachable from any stage and can move
    anywhere — a small firm doesn't need a transition matrix for its own
    columns. Inactive stages are never offered.

    Pass ``active_keys`` (ordered active stage keys) when the caller already
    loaded the stage config, to avoid a per-call query.
    """
    if active_keys is None:
        active_keys = [r["key"] for r in stage_config.list_stages(conn)]
    if not active_keys:
        active_keys = list(STAGES)
    custom_keys = [k for k in active_keys if k not in STAGES]

    if current_stage in _STAGE_TRANSITIONS:
        builtin = [
            s for s in _STAGE_TRANSITIONS[current_stage] if s in active_keys
        ]
        return builtin + [k for k in custom_keys if k != current_stage]
    # Custom current stage: anything active except itself.
    return [k for k in active_keys if k != current_stage]


def _is_lost_stage(conn: sqlite3.Connection, stage: str) -> bool:
    return stage in stage_config.lost_stage_keys(conn)


def advance_stage(
    conn: sqlite3.Connection,
    opp_id: int,
    new_stage: str,
    lost_reason_id: int | None = None,
    lost_note: str | None = None,
) -> None:
    """Move an opportunity to *new_stage*, validating the transition.

    - Applies the target stage's configured default probability (prorated
      revenue follows the stage unless the user edits it afterwards).
    - Moving into a lost-flagged stage records ``lost_reason_id`` /
      ``lost_note``; moving out of one clears them.

    Raises ``ValueError`` if the transition is not allowed.
    """
    opp = get_opportunity(conn, opp_id)
    if opp is None:
        raise ValueError(f"Opportunity {opp_id} not found")

    old_stage = opp["stage"]
    if old_stage in _STAGE_TRANSITIONS and new_stage in STAGES:
        allowed = _STAGE_TRANSITIONS[old_stage]
        if new_stage not in allowed:
            raise ValueError(
                f"Cannot transition from '{old_stage}' to '{new_stage}'. "
                f"Allowed transitions: {allowed}"
            )
    elif new_stage not in STAGES:
        # Custom target: must exist and be active in the config table.
        if stage_config.get_stage_by_key(conn, new_stage) is None:
            raise ValueError(f"Unknown stage '{new_stage}'")

    now = _now()
    new_probability = stage_config.stage_probability(conn, new_stage)
    if new_probability is None:
        new_probability = opp["probability"]

    going_lost = _is_lost_stage(conn, new_stage)
    leaving_lost = _is_lost_stage(conn, old_stage) and not going_lost

    if going_lost:
        conn.execute(
            "UPDATE opportunities "
            "SET stage = ?, probability = ?, lost_reason_id = ?, "
            "    lost_note = ?, updated_at = ? "
            "WHERE id = ?",
            (new_stage, new_probability, lost_reason_id, lost_note, now, opp_id),
        )
    elif leaving_lost:
        conn.execute(
            "UPDATE opportunities "
            "SET stage = ?, probability = ?, lost_reason_id = NULL, "
            "    lost_note = NULL, updated_at = ? "
            "WHERE id = ?",
            (new_stage, new_probability, now, opp_id),
        )
    else:
        conn.execute(
            "UPDATE opportunities "
            "SET stage = ?, probability = ?, updated_at = ? WHERE id = ?",
            (new_stage, new_probability, now, opp_id),
        )

    details: dict[str, Any] = {"old_stage": old_stage, "new_stage": new_stage}
    if going_lost and lost_reason_id is not None:
        details["lost_reason_id"] = lost_reason_id
    if going_lost and lost_note:
        details["lost_note"] = lost_note
    _log_activity(conn, "opportunity", opp_id, "stage_change", details)
    conn.commit()


def mark_lost(
    conn: sqlite3.Connection,
    opp_id: int,
    lost_reason_id: int | None = None,
    lost_note: str | None = None,
) -> None:
    """Move an opportunity to the (first) lost stage, recording why."""
    lost_keys = stage_config.lost_stage_keys(conn)
    advance_stage(
        conn, opp_id, lost_keys[0],
        lost_reason_id=lost_reason_id, lost_note=lost_note,
    )


def convert_to_project(conn: sqlite3.Connection, opp_id: int) -> int:
    """Create a project from a *won* opportunity, link them, and return the project id.

    Raises ``ValueError`` if the opportunity is not in 'won' stage.
    """
    opp = get_opportunity(conn, opp_id)
    if opp is None:
        raise ValueError(f"Opportunity {opp_id} not found")
    if opp["stage"] not in stage_config.won_stage_keys(conn):
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
    open_keys = stage_config.open_stage_keys(conn)
    if not open_keys:
        return {
            "by_stage": {},
            "total_pipeline_value": 0.0,
            "weighted_pipeline_total": 0.0,
            "active_count": 0,
        }
    placeholders = ", ".join("?" for _ in open_keys)
    rows = conn.execute(
        "SELECT stage, "
        "       COUNT(*) AS count, "
        "       COALESCE(SUM(estimated_value), 0) AS total_value, "
        "       COALESCE(SUM(estimated_value * probability / 100.0), 0) AS weighted_value "
        "FROM opportunities "
        f"WHERE stage IN ({placeholders}) "  # noqa: S608 — placeholders only
        "GROUP BY stage",
        open_keys,
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


def count_active_opportunities(conn: sqlite3.Connection) -> int:
    """Return the number of opportunities in an *active* (open) stage.

    Active stages are read from the crm_stages config table (active AND NOT
    is_closed); with the default seed that equals :data:`ACTIVE_STAGES` —
    every stage except the closed/terminal ones (won, lost, dormant). This
    is the canonical query behind the "Active Opportunities" KPI; the
    pipeline page uses the same source, so the two provably agree.
    """
    open_keys = stage_config.open_stage_keys(conn)
    if not open_keys:
        return 0
    placeholders = ", ".join("?" for _ in open_keys)
    row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM opportunities WHERE stage IN ({placeholders})",  # noqa: S608
        open_keys,
    ).fetchone()
    return row["cnt"]


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
    won_keys = stage_config.won_stage_keys(conn)
    lost_keys = stage_config.lost_stage_keys(conn)
    outcome_keys = tuple(won_keys) + tuple(lost_keys)

    placeholders = ", ".join("?" for _ in outcome_keys)
    where_parts: list[str] = [f"stage IN ({placeholders})"]
    params: list[Any] = list(outcome_keys)

    if date_from:
        where_parts.append("updated_at >= ?")
        params.append(date_from)
    if date_to:
        where_parts.append("updated_at <= ?")
        params.append(date_to)

    where_clause = " AND ".join(where_parts)

    rows = conn.execute(
        f"SELECT stage, COUNT(*) AS cnt, COALESCE(SUM(estimated_value), 0) AS total_val "  # noqa: S608
        f"FROM opportunities WHERE {where_clause} GROUP BY stage",
        params,
    ).fetchall()

    won = 0
    lost = 0
    won_value = 0.0
    for row in rows:
        if row["stage"] in won_keys:
            won += row["cnt"]
            won_value += row["total_val"]
        elif row["stage"] in lost_keys:
            lost += row["cnt"]

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


def get_lost_reason_breakdown(
    conn: sqlite3.Connection,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """Lost opportunities grouped by reason (count + value), biggest first.

    Opportunities lost without a recorded reason group under
    ``"(no reason recorded)"``.
    """
    lost_keys = stage_config.lost_stage_keys(conn)
    placeholders = ", ".join("?" for _ in lost_keys)
    where_parts: list[str] = [f"o.stage IN ({placeholders})"]
    params: list[Any] = list(lost_keys)

    if date_from:
        where_parts.append("o.updated_at >= ?")
        params.append(date_from)
    if date_to:
        where_parts.append("o.updated_at <= ?")
        params.append(date_to)

    where_clause = " AND ".join(where_parts)
    rows = conn.execute(
        f"SELECT COALESCE(lr.name, '(no reason recorded)') AS reason, "  # noqa: S608
        f"       COUNT(*) AS count, "
        f"       COALESCE(SUM(o.estimated_value), 0) AS total_value "
        f"FROM opportunities o "
        f"LEFT JOIN lost_reasons lr ON lr.id = o.lost_reason_id "
        f"WHERE {where_clause} "
        f"GROUP BY COALESCE(lr.name, '(no reason recorded)') "
        f"ORDER BY count DESC, total_value DESC",
        params,
    ).fetchall()
    return [
        {
            "reason": r["reason"],
            "count": r["count"],
            "total_value": r["total_value"],
        }
        for r in rows
    ]


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
