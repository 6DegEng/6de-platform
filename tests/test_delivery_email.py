"""Tests for the delivery-milestone notification email (composition-only slice).

Covers the delivery-pattern matcher, the completed-only / delivery-only guards
in compose_delivery_email, recipient resolution + fallback, message content,
and the completed-delivery sweep helper. No email is sent.
"""
from __future__ import annotations

import pytest

from modules.integrations.delivery_email import (
    FROM_ADDRESS,
    compose_delivery_email,
    find_completed_delivery_milestones,
    is_delivery_milestone,
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _client(db, name="Acme Condo Assn", email="board@acme.example"):
    return db.execute(
        "INSERT INTO clients (name, email) VALUES (?, ?)", (name, email)
    ).lastrowid


def _project(db, job_number="260501", name="Tower Recert", client_id=None):
    return db.execute(
        "INSERT INTO projects (job_number, name, client_id) VALUES (?, ?, ?)",
        (job_number, name, client_id),
    ).lastrowid


def _milestone(db, project_id, name, *, status="completed", completed_date="2026-05-30"):
    return db.execute(
        "INSERT INTO milestones (project_id, name, status, completed_date) "
        "VALUES (?, ?, ?, ?)",
        (project_id, name, status, completed_date),
    ).lastrowid


# ---------------------------------------------------------------------------
# Pattern matcher
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "Permit package submitted",
    "Final Report delivered",
    "Plans issued to AHJ",
    "Deliverables sent to client",
    "PERMIT PACKAGE",
])
def test_is_delivery_milestone_positive(name):
    assert is_delivery_milestone(name) is True


@pytest.mark.parametrize("name", [
    "Project kickoff",
    "Site visit",
    "Internal QA review",
    "",
    None,
])
def test_is_delivery_milestone_negative(name):
    assert is_delivery_milestone(name) is False


# ---------------------------------------------------------------------------
# compose_delivery_email
# ---------------------------------------------------------------------------

def test_compose_for_completed_delivery_milestone(db):
    cid = _client(db, name="Acme Board", email="board@acme.example")
    pid = _project(db, client_id=cid)
    mid = _milestone(db, pid, "Permit package submitted", completed_date="2026-05-29")
    db.commit()

    msg = compose_delivery_email(db, mid)
    assert msg is not None
    assert msg["to"] == "board@acme.example"
    assert msg["to_resolved"] is True
    assert msg["from_addr"] == FROM_ADDRESS
    assert "260501 - Tower Recert" in msg["subject"]
    assert "Permit package submitted" in msg["subject"]
    assert "Hi Acme Board," in msg["body"]
    assert "2026-05-29" in msg["body"]
    assert "PE #98059" in msg["body"]
    assert msg["milestone_id"] == mid and msg["project_id"] == pid


def test_compose_returns_none_when_not_completed(db):
    pid = _project(db)
    mid = _milestone(db, pid, "Permit package submitted", status="in_progress")
    db.commit()
    assert compose_delivery_email(db, mid) is None


def test_compose_returns_none_for_non_delivery_milestone(db):
    pid = _project(db)
    mid = _milestone(db, pid, "Project kickoff", status="completed")
    db.commit()
    assert compose_delivery_email(db, mid) is None


def test_compose_returns_none_for_missing_milestone(db):
    assert compose_delivery_email(db, 999999) is None


def test_compose_recipient_fallback_when_no_client_email(db):
    cid = _client(db, name="No Email Client", email=None)
    pid = _project(db, client_id=cid)
    mid = _milestone(db, pid, "Report delivered")
    db.commit()

    msg = compose_delivery_email(db, mid)
    assert msg is not None
    assert msg["to"] == ""
    assert msg["to_resolved"] is False
    assert "Hi No Email Client," in msg["body"]


def test_compose_generic_greeting_when_no_client(db):
    pid = _project(db, client_id=None)
    mid = _milestone(db, pid, "Plans issued")
    db.commit()
    msg = compose_delivery_email(db, mid)
    assert msg is not None
    assert "Hello," in msg["body"]


# ---------------------------------------------------------------------------
# sweep helper
# ---------------------------------------------------------------------------

def test_find_completed_delivery_milestones_filters(db):
    pid = _project(db)
    _milestone(db, pid, "Permit package submitted", status="completed")
    _milestone(db, pid, "Report delivered", status="completed")
    _milestone(db, pid, "Project kickoff", status="completed")        # not delivery
    _milestone(db, pid, "Final report", status="in_progress")          # not completed
    other = _project(db, job_number="260502", name="Other")
    _milestone(db, other, "Plans issued", status="completed")
    db.commit()

    all_hits = find_completed_delivery_milestones(db)
    assert len(all_hits) == 3  # two on pid + one on other

    scoped = find_completed_delivery_milestones(db, project_id=pid)
    names = sorted(r["name"] for r in scoped)
    assert names == ["Permit package submitted", "Report delivered"]
