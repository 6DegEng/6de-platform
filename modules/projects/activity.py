"""Per-project activity_log query + summary helpers.

Session 3a — subagent 6. The Activity tab (6th tab on each project's
detail view) reads from the shared ``activity_log`` table that
``modules.projects.crud._log_activity`` writes to. This module exposes
the read-side contract: a paginated, newest-first listing of activity
rows for one project, plus a ``summarize_activity`` helper that turns
each row into a human-readable one-liner.

There is **no** ``status_change`` action in this codebase — status
changes are bundled into an ``updated`` action with a ``"status"`` key
in the details JSON (see scout report §3). ``summarize_activity``
recognizes that pattern explicitly.

Milestone events use ``entity_type='milestone'`` and are scoped to a
project by joining against the ``milestones`` table on
``project_id``. The milestone-create payload includes ``project_id``
in its details JSON, but milestone-update payloads do NOT (they only
carry the changed kwargs). To get both consistently, the query uses
the ``entity_id IN (SELECT id FROM milestones WHERE project_id=?)``
shape — that's a single subquery and avoids parsing JSON twice. The
JSON-extract approach was rejected because milestone-update payloads
lack ``project_id``.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from streamlit_app.components.status_pills import PROJECT_STATUS_LABELS


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def list_project_activity(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    limit: int = 25,
    offset: int = 0,
    include_milestones: bool = True,
) -> list[sqlite3.Row]:
    """Newest-first activity for a single project.

    Always returns rows where ``entity_type='project' AND entity_id=?``.
    When ``include_milestones=True``, the result also includes rows
    where ``entity_type='milestone' AND entity_id IN (SELECT id FROM
    milestones WHERE project_id=?)`` — that picks up both
    milestone-create AND milestone-update events without needing to
    parse the details JSON (milestone-update payloads do not carry
    ``project_id``).

    Ordering: ``created_at DESC, id DESC`` — the id tiebreak handles
    same-second writes (project-create + milestone-create executed in
    the same call would otherwise sort unstably).

    Returns ``list[sqlite3.Row]`` so the renderer can access
    ``row["created_at"]``, ``row["entity_type"]``, ``row["entity_id"]``,
    ``row["action"]``, ``row["details"]`` by name.
    """
    if include_milestones:
        sql = (
            "SELECT * FROM activity_log "
            "WHERE (entity_type='project' AND entity_id=?) "
            "   OR (entity_type='milestone' "
            "       AND entity_id IN (SELECT id FROM milestones WHERE project_id=?)) "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT ? OFFSET ?"
        )
        params: tuple[Any, ...] = (project_id, project_id, limit, offset)
    else:
        sql = (
            "SELECT * FROM activity_log "
            "WHERE entity_type='project' AND entity_id=? "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT ? OFFSET ?"
        )
        params = (project_id, limit, offset)
    return conn.execute(sql, params).fetchall()


def count_project_activity(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    include_milestones: bool = True,
) -> int:
    """Total activity rows for one project (for pagination math)."""
    if include_milestones:
        sql = (
            "SELECT COUNT(*) FROM activity_log "
            "WHERE (entity_type='project' AND entity_id=?) "
            "   OR (entity_type='milestone' "
            "       AND entity_id IN (SELECT id FROM milestones WHERE project_id=?))"
        )
        params: tuple[Any, ...] = (project_id, project_id)
    else:
        sql = (
            "SELECT COUNT(*) FROM activity_log "
            "WHERE entity_type='project' AND entity_id=?"
        )
        params = (project_id,)
    return int(conn.execute(sql, params).fetchone()[0])


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def _parse_details(raw: Any) -> dict:
    """Defensively parse the ``details`` column into a dict.

    Returns an empty dict for ``None``, empty strings, malformed JSON,
    or anything that doesn't decode to a dict (legacy bad data).
    """
    if raw is None:
        return {}
    try:
        decoded = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _project_summary(action: str, details: dict) -> str:
    if action == "created":
        if details.get("source") == "opportunity":
            opp_id = details.get("opportunity_id", "?")
            return f"Converted from opportunity #{opp_id}"
        name = details.get("name")
        if name:
            return f"Project created: {name}"
        return "Project created"

    if action == "updated":
        # Filter out the auto-added updated_at key so it doesn't
        # masquerade as a "changed field".
        meaningful = {k: v for k, v in details.items() if k != "updated_at"}
        if "status" in meaningful:
            status_val = meaningful["status"]
            label = PROJECT_STATUS_LABELS.get(
                status_val,
                str(status_val).replace("_", " ").title(),
            )
            return f"Status changed to {label}"
        if not meaningful:
            return "Touched (no field changes)"
        keys = ", ".join(sorted(meaningful.keys()))
        return f"Updated: {keys}"

    if action == "deleted":
        return "Project deleted"

    # Defensive fallback.
    return f"{action.title()} Project"


def _milestone_summary(action: str, details: dict) -> str:
    if action == "created":
        name = details.get("name")
        if name:
            return f"Milestone added: {name}"
        return "Milestone added"

    if action == "updated":
        # "done" key isn't actually how milestones get toggled in this
        # codebase (the Projects page uses status="completed"), but the
        # prompt asks us to recognize it — milestones could be edited
        # via a generic update_milestone(done=1) call in the future.
        if "done" in details:
            return "Milestone completed" if details["done"] == 1 else "Milestone reopened"
        if "status" in details:
            status_val = details["status"]
            if status_val == "completed":
                return "Milestone completed"
            if status_val in ("pending", "in_progress"):
                return (
                    "Milestone reopened"
                    if status_val == "pending"
                    else "Milestone started"
                )
            return f"Milestone status: {status_val}"
        if "name" in details:
            return f"Milestone renamed: {details['name']}"
        return "Milestone updated"

    return f"{action.title()} Milestone"


def summarize_activity(row: sqlite3.Row) -> str:
    """Human-readable one-line summary of an activity_log row.

    Returns plain text (no HTML) — the renderer adds its own
    formatting. Defensively handles ``row["details"]`` being ``None``,
    an empty string, malformed JSON, or a non-dict JSON value.
    """
    try:
        entity_type = row["entity_type"]
        action = row["action"]
    except (KeyError, IndexError, TypeError):
        return "Activity"

    details = _parse_details(row["details"])

    if entity_type == "project":
        return _project_summary(action, details)
    if entity_type == "milestone":
        return _milestone_summary(action, details)

    # Defensive default for any other entity_type (shouldn't happen
    # for project-scoped queries, but the bridge / documents / etc.
    # writers also use activity_log).
    return f"{action.title()} {entity_type}"
