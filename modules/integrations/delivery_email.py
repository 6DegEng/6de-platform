"""Delivery-milestone notification email (integrations roadmap #2, Phase 0).

When a project milestone that represents a *delivery* (permit package submitted,
report delivered, plans issued, etc.) transitions to ``completed``, the firm
wants a notification email to the client. This module is the **credential-free,
composition-only slice**: it decides whether a milestone qualifies and builds
the message (recipient, subject, body) — it does **not** send anything. Live
SMTP / Microsoft Graph send is a later slice. Composition is gated for UI
exposure behind ``ENABLE_DELIVERY_EMAIL`` (see ``config.py``); the functions
here are always safe to call directly (tests, a future sweep job).

A "delivery" milestone is matched by name against ``DELIVERY_PATTERNS`` (case-
insensitive substring match) — deliberately conservative so internal milestones
("kickoff", "site visit") don't trigger client emails.
"""

from __future__ import annotations

import sqlite3

# Canonical firm identity (brand kit). General correspondence address.
FROM_ADDRESS = "info@6de.xyz"
FIRM_NAME = "6th Degree Engineering"
PE_SIGNATURE = "Juan C. Castillo, P.E.\nFlorida PE #98059 · 6th Degree Engineering"

# Substrings (lowercased) that mark a milestone as a client-facing delivery.
DELIVERY_PATTERNS: tuple[str, ...] = (
    "deliver",        # "Report delivered", "Deliverables"
    "submit",         # "Permit package submitted", "Submittal"
    "issued",         # "Plans issued"
    "permit package",
    "report",         # "Final report"
    "sent to client",
    "package complete",
)


def is_delivery_milestone(name: str | None) -> bool:
    """True if the milestone name matches a delivery pattern (case-insensitive)."""
    if not name:
        return False
    low = name.lower()
    return any(p in low for p in DELIVERY_PATTERNS)


def _project_label(row: sqlite3.Row) -> str:
    job = (row["job_number"] or "").strip() if "job_number" in row.keys() else ""
    name = (row["project_name"] or "").strip() if "project_name" in row.keys() else ""
    label = " - ".join(p for p in (job, name) if p)
    return label or "your project"


def compose_delivery_email(
    conn: sqlite3.Connection, milestone_id: int
) -> dict | None:
    """Compose the client notification for a completed delivery milestone.

    Returns a message dict, or ``None`` if the milestone does not exist, is not
    ``completed``, or is not a delivery milestone (so callers can pass any
    milestone id and only act on a returned dict). No email is sent.

    Message dict keys: ``to`` (client email or ``""``), ``to_resolved`` (bool),
    ``from_addr``, ``subject``, ``body``, ``milestone_id``, ``project_id``.
    """
    row = conn.execute(
        "SELECT m.id AS milestone_id, m.name AS milestone_name, m.status, "
        "       m.completed_date, m.project_id, "
        "       p.job_number, p.name AS project_name, "
        "       c.name AS client_name, c.email AS client_email "
        "FROM milestones m "
        "JOIN projects p ON p.id = m.project_id "
        "LEFT JOIN clients c ON c.id = p.client_id "
        "WHERE m.id = ?",
        (milestone_id,),
    ).fetchone()

    if row is None or row["status"] != "completed":
        return None
    if not is_delivery_milestone(row["milestone_name"]):
        return None

    project = _project_label(row)
    milestone = row["milestone_name"]
    client_name = (row["client_name"] or "").strip()
    greeting = f"Hi {client_name}," if client_name else "Hello,"
    when = row["completed_date"] or "today"
    to = (row["client_email"] or "").strip()

    subject = f"{FIRM_NAME} — {project}: {milestone}"
    body = (
        f"{greeting}\n\n"
        f"This is a notification from {FIRM_NAME} regarding {project}.\n\n"
        f"Milestone completed: {milestone} ({when}).\n\n"
        f"Please let us know if you have any questions.\n\n"
        f"Best regards,\n{PE_SIGNATURE}"
    )

    return {
        "to": to,
        "to_resolved": bool(to),
        "from_addr": FROM_ADDRESS,
        "subject": subject,
        "body": body,
        "milestone_id": row["milestone_id"],
        "project_id": row["project_id"],
    }


def find_completed_delivery_milestones(
    conn: sqlite3.Connection, project_id: int | None = None
) -> list[sqlite3.Row]:
    """Return completed milestones whose names match a delivery pattern.

    Pattern matching is done in Python (not SQL) so the curated
    ``DELIVERY_PATTERNS`` list stays the single source of truth. Optionally
    scoped to one *project_id*. Useful for a future "notify on delivery" sweep.
    """
    sql = (
        "SELECT id, project_id, name, status, completed_date "
        "FROM milestones WHERE status = 'completed'"
    )
    params: list[object] = []
    if project_id is not None:
        sql += " AND project_id = ?"
        params.append(project_id)
    sql += " ORDER BY completed_date, id"
    rows = conn.execute(sql, params).fetchall()
    return [r for r in rows if is_delivery_milestone(r["name"])]
