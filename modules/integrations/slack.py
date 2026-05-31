"""Slack notification on project updates (integrations roadmap #3, Phase 0).

When a client-facing or internal project update is logged, the firm wants a
Slack ping so the team stays aware without opening the platform. This is the
**credential-free, composition-only slice**: it decides whether an update
qualifies and builds the Slack message payload (Block Kit blocks + a text
fallback) — it does **not** POST to a webhook. Live delivery (incoming webhook
or Web API) is a later slice. Composition is gated for UI exposure by
``ENABLE_SLACK_NOTIFY`` (config.py); the functions here are always safe to call.

Per the roadmap, only ``client_communication`` and ``internal_note`` updates
notify — routine ``status``/``permitting``/``billing`` updates do not.
"""
from __future__ import annotations

import sqlite3

# project_updates.category values that should ping Slack.
NOTIFY_CATEGORIES: tuple[str, ...] = ("client_communication", "internal_note")

# Human labels + a leading emoji for the Slack header.
_CATEGORY_LABEL: dict[str, str] = {
    "client_communication": "📣 Client communication",
    "internal_note": "📝 Internal note",
}


def should_notify(category: str | None) -> bool:
    """True if an update of this category should generate a Slack notification."""
    return category in NOTIFY_CATEGORIES


def _project_label(row: sqlite3.Row) -> str:
    job = (row["job_number"] or "").strip() if "job_number" in row.keys() else ""
    name = (row["project_name"] or "").strip() if "project_name" in row.keys() else ""
    return " - ".join(p for p in (job, name) if p) or "a project"


def compose_slack_message(conn: sqlite3.Connection, update_id: int) -> dict | None:
    """Compose the Slack payload for a notifiable project update.

    Returns a payload dict, or ``None`` if the update does not exist or its
    category is not in ``NOTIFY_CATEGORIES`` (so callers can pass any update id
    and only act on a returned dict). No webhook is called.

    Payload keys: ``channel`` (None — caller/route decides), ``text`` (fallback),
    ``blocks`` (Block Kit), ``update_id``, ``project_id``.
    """
    row = conn.execute(
        "SELECT u.id AS update_id, u.content, u.category, u.author, u.created_at, "
        "       u.project_id, p.job_number, p.name AS project_name "
        "FROM project_updates u "
        "JOIN projects p ON p.id = u.project_id "
        "WHERE u.id = ?",
        (update_id,),
    ).fetchone()

    if row is None or not should_notify(row["category"]):
        return None

    project = _project_label(row)
    label = _CATEGORY_LABEL.get(row["category"], row["category"])
    author = (row["author"] or "Someone").strip()
    when = row["created_at"] or ""
    content = row["content"] or ""

    text = f"{label} on {project} — {content} (by {author})"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{label}", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{project}*\n{content}"}},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"by {author}{f' · {when}' if when else ''}"},
        ]},
    ]
    return {
        "channel": None,
        "text": text,
        "blocks": blocks,
        "update_id": row["update_id"],
        "project_id": row["project_id"],
    }


def find_notifiable_updates(
    conn: sqlite3.Connection, project_id: int | None = None
) -> list[sqlite3.Row]:
    """Return project updates whose category is notifiable (newest first).

    Optionally scoped to one *project_id*. Useful for a future sweep/backfill.
    """
    placeholders = ",".join("?" for _ in NOTIFY_CATEGORIES)
    sql = f"SELECT * FROM project_updates WHERE category IN ({placeholders})"
    params: list[object] = list(NOTIFY_CATEGORIES)
    if project_id is not None:
        sql += " AND project_id = ?"
        params.append(project_id)
    sql += " ORDER BY created_at DESC, id DESC"
    return conn.execute(sql, params).fetchall()
