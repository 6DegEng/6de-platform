"""Configurable CRM stage + lost-reason configuration (crm-polish phase 2).

The ``crm_stages`` table replaces the hardcoded stage tuple as the source of
truth for the pipeline. It is seeded with the original seven stages so
behavior is unchanged out of the box:

    lead -> qualifying -> proposal_sent -> negotiating -> won/lost/dormant

Semantics:
- ``is_won`` / ``is_lost`` mark the terminal outcome stages (win-rate math).
- ``is_closed`` marks any stage excluded from the *open* pipeline — won,
  lost, and dormant (parked) are all closed.
- ``probability`` is the default deal probability applied when an
  opportunity moves into the stage (prorated / expected revenue).
- ``active = 0`` hides a stage from the UI and from pipeline totals without
  touching the opportunities that still sit in it.

The ``lost_reasons`` table is a small why-we-lost taxonomy referenced by
``opportunities.lost_reason_id``.

All helpers fall back to the seeded defaults when the config tables do not
exist yet (databases opened before the migration pass runs).
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any

from modules.activity_utils import sanitize_details

# ---------------------------------------------------------------------------
# Seed data — mirrors the original hardcoded pipeline exactly.
# (key, name, sequence, probability, is_won, is_lost, is_closed)
# ---------------------------------------------------------------------------
DEFAULT_STAGES: tuple[tuple[str, str, int, int, int, int, int], ...] = (
    ("lead",          "Lead",          10,  20, 0, 0, 0),
    ("qualifying",    "Qualifying",    20,  40, 0, 0, 0),
    ("proposal_sent", "Proposal Sent", 30,  60, 0, 0, 0),
    ("negotiating",   "Negotiating",   40,  80, 0, 0, 0),
    ("won",           "Won",           50, 100, 1, 0, 1),
    ("lost",          "Lost",          60,   0, 0, 1, 1),
    ("dormant",       "Dormant",       70,   0, 0, 0, 1),
)

DEFAULT_LOST_REASONS: tuple[str, ...] = (
    "Price",
    "Went with competitor",
    "No response / went dark",
    "Project cancelled",
    "Other",
)

_STAGE_EDITABLE_COLS = {"name", "sequence", "probability", "active"}


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


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
# Seeds — idempotent, called from db.init_db() / db.ensure_db()
# ---------------------------------------------------------------------------
def seed_crm_stages(conn: sqlite3.Connection) -> None:
    """Insert the default stages if the table is empty. Idempotent."""
    count = conn.execute("SELECT COUNT(*) FROM crm_stages").fetchone()[0]
    if count > 0:
        return
    now = _now()
    for key, name, seq, prob, is_won, is_lost, is_closed in DEFAULT_STAGES:
        conn.execute(
            "INSERT OR IGNORE INTO crm_stages "
            "(key, name, sequence, probability, is_won, is_lost, is_closed, "
            " active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (key, name, seq, prob, is_won, is_lost, is_closed, now, now),
        )


def seed_lost_reasons(conn: sqlite3.Connection) -> None:
    """Insert the default lost reasons if the table is empty. Idempotent."""
    count = conn.execute("SELECT COUNT(*) FROM lost_reasons").fetchone()[0]
    if count > 0:
        return
    now = _now()
    for name in DEFAULT_LOST_REASONS:
        conn.execute(
            "INSERT OR IGNORE INTO lost_reasons (name, active, created_at) "
            "VALUES (?, 1, ?)",
            (name, now),
        )


# ---------------------------------------------------------------------------
# Stage reads
# ---------------------------------------------------------------------------
def list_stages(
    conn: sqlite3.Connection, include_inactive: bool = False
) -> list[sqlite3.Row]:
    """Return stage config rows ordered by sequence.

    Falls back to an empty list if the crm_stages table does not exist yet
    (pre-migration database) — callers use the DEFAULT_* fallbacks then.
    """
    sql = "SELECT * FROM crm_stages"
    if not include_inactive:
        sql += " WHERE active = 1"
    sql += " ORDER BY sequence, id"
    try:
        return conn.execute(sql).fetchall()
    except sqlite3.OperationalError:
        return []


def get_stage_by_key(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    try:
        return conn.execute(
            "SELECT * FROM crm_stages WHERE key = ?", (key,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None


def open_stage_keys(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Keys of active, non-closed stages — the open pipeline definition.

    Defaults to the original active set when the config table is missing
    or empty so pre-migration databases keep their current behavior.
    """
    rows = list_stages(conn)
    if not rows:
        return tuple(s[0] for s in DEFAULT_STAGES if not s[6])
    return tuple(r["key"] for r in rows if not r["is_closed"])


def won_stage_keys(conn: sqlite3.Connection) -> tuple[str, ...]:
    rows = list_stages(conn)
    if not rows:
        return ("won",)
    return tuple(r["key"] for r in rows if r["is_won"]) or ("won",)


def lost_stage_keys(conn: sqlite3.Connection) -> tuple[str, ...]:
    rows = list_stages(conn)
    if not rows:
        return ("lost",)
    return tuple(r["key"] for r in rows if r["is_lost"]) or ("lost",)


def stage_labels(conn: sqlite3.Connection) -> dict[str, str]:
    """key -> display name for every stage (incl. inactive, for old data)."""
    rows = list_stages(conn, include_inactive=True)
    if not rows:
        return {s[0]: s[1] for s in DEFAULT_STAGES}
    return {r["key"]: r["name"] for r in rows}


def stage_probability(conn: sqlite3.Connection, key: str) -> int | None:
    """Configured default probability for a stage key, or None if unknown."""
    row = get_stage_by_key(conn, key)
    if row is not None:
        return row["probability"]
    for s in DEFAULT_STAGES:
        if s[0] == key:
            return s[3]
    return None


# ---------------------------------------------------------------------------
# Stage writes
# ---------------------------------------------------------------------------
def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "stage"


def create_stage(
    conn: sqlite3.Connection,
    name: str,
    probability: int = 50,
    kind: str = "open",
    sequence: int | None = None,
) -> int:
    """Add a pipeline stage. ``kind`` is one of open/won/lost/closed.

    The stable ``key`` is derived from the name (unique slug); renames later
    only touch the display name. Returns the new stage id.
    """
    if kind not in ("open", "won", "lost", "closed"):
        raise ValueError(f"Unknown stage kind {kind!r}")
    if not name or not name.strip():
        raise ValueError("Stage name is required")
    probability = max(0, min(100, int(probability)))

    base = _slugify(name)
    key = base
    suffix = 2
    while get_stage_by_key(conn, key) is not None:
        key = f"{base}_{suffix}"
        suffix += 1

    if sequence is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS mx FROM crm_stages"
        ).fetchone()
        sequence = int(row["mx"]) + 10

    is_won = 1 if kind == "won" else 0
    is_lost = 1 if kind == "lost" else 0
    is_closed = 1 if kind in ("won", "lost", "closed") else 0
    now = _now()
    cur = conn.execute(
        "INSERT INTO crm_stages "
        "(key, name, sequence, probability, is_won, is_lost, is_closed, "
        " active, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
        (key, name.strip(), sequence, probability, is_won, is_lost, is_closed,
         now, now),
    )
    stage_id: int = cur.lastrowid  # type: ignore[assignment]
    _log_activity(
        conn, "crm_stage", stage_id, "created",
        {"key": key, "name": name.strip(), "kind": kind,
         "probability": probability},
    )
    conn.commit()
    return stage_id


def update_stage(conn: sqlite3.Connection, stage_id: int, **kwargs: Any) -> None:
    """Rename / reorder / re-probability / (de)activate a stage.

    Only name, sequence, probability, and active are editable — the key and
    the won/lost/closed flags are fixed so historical analytics stay stable.
    """
    filtered = {k: v for k, v in kwargs.items() if k in _STAGE_EDITABLE_COLS}
    if not filtered:
        return
    if "probability" in filtered:
        filtered["probability"] = max(0, min(100, int(filtered["probability"])))
    if "active" in filtered:
        filtered["active"] = 1 if filtered["active"] else 0
    filtered["updated_at"] = _now()
    set_clause = ", ".join(f"{col} = ?" for col in filtered)
    values = list(filtered.values()) + [stage_id]
    conn.execute(
        f"UPDATE crm_stages SET {set_clause} WHERE id = ?", values  # noqa: S608
    )
    _log_activity(conn, "crm_stage", stage_id, "updated", filtered)
    conn.commit()


# ---------------------------------------------------------------------------
# Lost reasons
# ---------------------------------------------------------------------------
def list_lost_reasons(
    conn: sqlite3.Connection, include_inactive: bool = False
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM lost_reasons"
    if not include_inactive:
        sql += " WHERE active = 1"
    sql += " ORDER BY id"
    try:
        return conn.execute(sql).fetchall()
    except sqlite3.OperationalError:
        return []


def create_lost_reason(conn: sqlite3.Connection, name: str) -> int:
    if not name or not name.strip():
        raise ValueError("Lost reason name is required")
    cur = conn.execute(
        "INSERT INTO lost_reasons (name, active, created_at) VALUES (?, 1, ?)",
        (name.strip(), _now()),
    )
    reason_id: int = cur.lastrowid  # type: ignore[assignment]
    _log_activity(conn, "lost_reason", reason_id, "created", {"name": name.strip()})
    conn.commit()
    return reason_id


def set_lost_reason_active(
    conn: sqlite3.Connection, reason_id: int, active: bool
) -> None:
    conn.execute(
        "UPDATE lost_reasons SET active = ? WHERE id = ?",
        (1 if active else 0, reason_id),
    )
    _log_activity(
        conn, "lost_reason", reason_id, "updated", {"active": 1 if active else 0}
    )
    conn.commit()
