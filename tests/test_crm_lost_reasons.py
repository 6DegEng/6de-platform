"""Lost reasons (crm-polish phase 2).

Marking an opportunity lost records a why (reason + free note), reopening
clears it, and the analytics breakdown groups lost deals by reason.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from modules.crm.crud import (
    advance_stage,
    get_lost_reason_breakdown,
    get_opportunity,
    mark_lost,
)
from modules.crm.stages import (
    DEFAULT_LOST_REASONS,
    create_lost_reason,
    list_lost_reasons,
    seed_lost_reasons,
    set_lost_reason_active,
)


def _insert_opp(conn: sqlite3.Connection, name: str, stage: str = "lead",
                value: float = 1000) -> int:
    cur = conn.execute(
        "INSERT INTO opportunities (name, stage, estimated_value, "
        "probability, created_at, updated_at) "
        "VALUES (?, ?, ?, 50, datetime('now'), datetime('now'))",
        (name, stage, value),
    )
    conn.commit()
    return cur.lastrowid


def _reason_id(conn: sqlite3.Connection, name: str) -> int:
    return next(r["id"] for r in list_lost_reasons(conn) if r["name"] == name)


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------
def test_default_reasons_seeded_and_idempotent(db):
    names = [r["name"] for r in list_lost_reasons(db)]
    assert names == list(DEFAULT_LOST_REASONS)
    seed_lost_reasons(db)
    assert len(list_lost_reasons(db)) == len(DEFAULT_LOST_REASONS)


def test_create_and_deactivate_reason(db):
    rid = create_lost_reason(db, "Out of service area")
    assert "Out of service area" in [r["name"] for r in list_lost_reasons(db)]

    set_lost_reason_active(db, rid, False)
    assert "Out of service area" not in [r["name"] for r in list_lost_reasons(db)]
    assert "Out of service area" in [
        r["name"] for r in list_lost_reasons(db, include_inactive=True)
    ]


# ---------------------------------------------------------------------------
# Recording on the opportunity
# ---------------------------------------------------------------------------
def test_mark_lost_records_reason_and_note(db):
    oid = _insert_opp(db, "losing-opp")
    rid = _reason_id(db, "Price")
    mark_lost(db, oid, lost_reason_id=rid, lost_note="20% over budget")

    opp = get_opportunity(db, oid)
    assert opp["stage"] == "lost"
    assert opp["lost_reason_id"] == rid
    assert opp["lost_note"] == "20% over budget"
    assert opp["probability"] == 0  # lost stage default probability

    # Activity log carries the reason for the audit trail.
    row = db.execute(
        "SELECT details FROM activity_log "
        "WHERE entity_type = 'opportunity' AND entity_id = ? "
        "  AND action = 'stage_change' "
        "ORDER BY id DESC",
        (oid,),
    ).fetchone()
    details = json.loads(row["details"])
    assert details["new_stage"] == "lost"
    assert details["lost_reason_id"] == rid
    assert details["lost_note"] == "20% over budget"


def test_mark_lost_without_reason_is_allowed(db):
    oid = _insert_opp(db, "silent-loss")
    mark_lost(db, oid)
    opp = get_opportunity(db, oid)
    assert opp["stage"] == "lost"
    assert opp["lost_reason_id"] is None
    assert opp["lost_note"] is None


def test_reopening_clears_lost_fields(db):
    oid = _insert_opp(db, "second-chance")
    mark_lost(db, oid, lost_reason_id=_reason_id(db, "Price"), lost_note="x")
    advance_stage(db, oid, "lead")  # lost -> lead is a valid transition

    opp = get_opportunity(db, oid)
    assert opp["stage"] == "lead"
    assert opp["lost_reason_id"] is None
    assert opp["lost_note"] is None


# ---------------------------------------------------------------------------
# Breakdown reporting
# ---------------------------------------------------------------------------
def test_breakdown_groups_by_reason_with_no_reason_bucket(db):
    price = _reason_id(db, "Price")
    competitor = _reason_id(db, "Went with competitor")

    mark_lost(db, _insert_opp(db, "l1", value=1000), lost_reason_id=price)
    mark_lost(db, _insert_opp(db, "l2", value=2000), lost_reason_id=price)
    mark_lost(db, _insert_opp(db, "l3", value=500), lost_reason_id=competitor)
    mark_lost(db, _insert_opp(db, "l4", value=700))  # no reason

    rows = get_lost_reason_breakdown(db)
    by_reason = {r["reason"]: r for r in rows}
    assert by_reason["Price"]["count"] == 2
    assert by_reason["Price"]["total_value"] == pytest.approx(3000.0)
    assert by_reason["Went with competitor"]["count"] == 1
    assert by_reason["(no reason recorded)"]["count"] == 1
    assert by_reason["(no reason recorded)"]["total_value"] == pytest.approx(700.0)
    # Biggest bucket first.
    assert rows[0]["reason"] == "Price"


def test_breakdown_only_counts_lost_stages(db):
    _insert_opp(db, "still-open", "lead")
    _insert_opp(db, "won-one", "won")
    mark_lost(db, _insert_opp(db, "gone"), lost_reason_id=_reason_id(db, "Price"))

    rows = get_lost_reason_breakdown(db)
    assert sum(r["count"] for r in rows) == 1


def test_breakdown_respects_date_range(db):
    mark_lost(db, _insert_opp(db, "recent-loss"))
    rows = get_lost_reason_breakdown(db, date_from="2000-01-01", date_to="2000-12-31")
    assert rows == []
    rows = get_lost_reason_breakdown(db, date_from="2000-01-01")
    assert sum(r["count"] for r in rows) == 1
