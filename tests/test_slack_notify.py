"""Tests for the Slack project-update notification (composition-only slice).

Covers the category filter, the composed Block Kit payload, the not-notifiable /
missing guards, and the sweep helper. No webhook is called.
"""
from __future__ import annotations

import pytest

from modules.integrations.slack import (
    NOTIFY_CATEGORIES,
    compose_slack_message,
    find_notifiable_updates,
    should_notify,
)
from modules.projects.crud import create_project
from modules.projects.updates import create_project_update


def _project(db, job_number="260601", name="Tower Recert"):
    return create_project(db, name=name, status="active", state="FL", job_number=job_number)


@pytest.mark.parametrize("cat,expected", [
    ("client_communication", True),
    ("internal_note", True),
    ("status", False),
    ("permitting", False),
    ("billing", False),
    (None, False),
])
def test_should_notify(cat, expected):
    assert should_notify(cat) is expected


def test_compose_for_client_communication(db):
    pid = _project(db)
    uid = create_project_update(db, pid, "Called the board; they approved the scope.",
                                category="client_communication", author="Juan")
    db.commit()
    msg = compose_slack_message(db, uid)
    assert msg is not None
    assert "260601 - Tower Recert" in msg["text"]
    assert "Called the board" in msg["text"]
    assert "by Juan" in msg["text"]
    assert msg["update_id"] == uid and msg["project_id"] == pid
    # Block Kit: header + section + context; section carries the content
    types = [b["type"] for b in msg["blocks"]]
    assert types == ["header", "section", "context"]
    assert "Called the board" in msg["blocks"][1]["text"]["text"]
    assert "Client communication" in msg["blocks"][0]["text"]["text"]


def test_compose_for_internal_note(db):
    pid = _project(db, job_number="260602", name="Bayside")
    uid = create_project_update(db, pid, "Waiting on the survey before we draft.",
                                category="internal_note", author="JC")
    db.commit()
    msg = compose_slack_message(db, uid)
    assert msg is not None
    assert "Internal note" in msg["blocks"][0]["text"]["text"]


def test_compose_returns_none_for_non_notifiable_category(db):
    pid = _project(db)
    uid = create_project_update(db, pid, "Status: drafting.", category="status")
    db.commit()
    assert compose_slack_message(db, uid) is None


def test_compose_returns_none_for_missing_update(db):
    assert compose_slack_message(db, 999_999) is None


def test_find_notifiable_updates_filters_and_scopes(db):
    pid = _project(db)
    create_project_update(db, pid, "A", category="client_communication")
    create_project_update(db, pid, "B", category="internal_note")
    create_project_update(db, pid, "C", category="status")        # excluded
    create_project_update(db, pid, "D", category="billing")        # excluded
    other = _project(db, job_number="260699", name="Other")
    create_project_update(db, other, "E", category="client_communication")
    db.commit()

    assert len(find_notifiable_updates(db)) == 3
    assert all(r["category"] in NOTIFY_CATEGORIES for r in find_notifiable_updates(db))
    scoped = find_notifiable_updates(db, project_id=pid)
    assert len(scoped) == 2
