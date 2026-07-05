"""Proposals -> opportunities bridge completion (crm-polish phase 2).

Covers the three gaps the audit called out on the S35 bridge:
- fields not carried (client contact info now flows onto the opportunity),
- dedupe (proposal revisions for the same project no longer spawn
  duplicate opportunities),
- status sync back (proposal status changes re-stage the bridged
  opportunity unless the user already moved it manually).
"""
from __future__ import annotations

import sqlite3

from db import bridge_proposals_to_opportunities
from modules.crm.crud import advance_stage, get_opportunity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mk_client(conn: sqlite3.Connection, name: str = "Acme Condo Assn",
               email: str = "board@acme.test", phone: str = "305-555-0100") -> int:
    cur = conn.execute(
        "INSERT INTO clients (name, email, phone) VALUES (?, ?, ?)",
        (name, email, phone),
    )
    conn.commit()
    return cur.lastrowid


def _mk_project(conn: sqlite3.Connection, client_id: int,
                name: str = "Acme Recert", job: str = "260701") -> int:
    cur = conn.execute(
        "INSERT INTO projects (job_number, name, client_id, status, service_line) "
        "VALUES (?, ?, ?, 'active', 'recertification')",
        (job, name, client_id),
    )
    conn.commit()
    return cur.lastrowid


def _mk_proposal(conn: sqlite3.Connection, project_id: int,
                 number: str = "P-1", fee: float = 5000,
                 status: str = "sent", sent_date: str = "2026-06-01") -> int:
    cur = conn.execute(
        "INSERT INTO proposals (project_id, proposal_number, fee_amount, "
        "status, sent_date) VALUES (?, ?, ?, ?, ?)",
        (project_id, number, fee, status, sent_date),
    )
    conn.commit()
    return cur.lastrowid


def _bridged_opp(conn: sqlite3.Connection, proposal_id: int):
    return conn.execute(
        "SELECT * FROM opportunities WHERE source_proposal_id = ?",
        (proposal_id,),
    ).fetchone()


def _opp_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS c FROM opportunities").fetchone()["c"]


# ---------------------------------------------------------------------------
# Creation — fields carried
# ---------------------------------------------------------------------------
def test_bridge_creates_opportunity_with_contact_fields(db):
    cid = _mk_client(db)
    pid = _mk_project(db, cid)
    prop_id = _mk_proposal(db, pid, fee=7500, status="sent")

    result = bridge_proposals_to_opportunities(db)
    assert result["created"] == 1

    opp = _bridged_opp(db, prop_id)
    assert opp is not None
    assert opp["stage"] == "proposal_sent"
    assert opp["estimated_value"] == 7500
    assert opp["client_id"] == cid
    assert opp["project_id"] == pid
    # Audit gap: contact fields now carried from the client record.
    assert opp["contact_name"] == "Acme Condo Assn"
    assert opp["contact_email"] == "board@acme.test"
    assert opp["contact_phone"] == "305-555-0100"
    # Sync bookkeeping recorded at creation time.
    assert opp["source_proposal_status"] == "sent"
    # Probability follows the mapped stage's configured default.
    assert opp["probability"] == 60


def test_bridge_is_idempotent(db):
    cid = _mk_client(db)
    pid = _mk_project(db, cid)
    _mk_proposal(db, pid)

    first = bridge_proposals_to_opportunities(db)
    second = bridge_proposals_to_opportunities(db)
    assert first["created"] == 1
    assert second["created"] == 0
    assert second["synced"] == 0
    assert _opp_count(db) == 1


# ---------------------------------------------------------------------------
# Dedupe — proposal revisions don't spawn duplicates
# ---------------------------------------------------------------------------
def test_bridge_dedupes_proposal_revisions(db):
    cid = _mk_client(db)
    pid = _mk_project(db, cid)
    _mk_proposal(db, pid, number="P-1", status="draft")
    rev2 = _mk_proposal(db, pid, number="P-1r2", status="sent")

    result = bridge_proposals_to_opportunities(db)
    assert result["created"] == 1
    assert _opp_count(db) == 1
    # The newest proposal for the project is the one bridged.
    opp = _bridged_opp(db, rev2)
    assert opp is not None
    assert opp["stage"] == "proposal_sent"


def test_bridge_skips_new_revision_when_project_already_bridged(db):
    cid = _mk_client(db)
    pid = _mk_project(db, cid)
    _mk_proposal(db, pid, number="P-1", status="sent")
    bridge_proposals_to_opportunities(db)

    _mk_proposal(db, pid, number="P-1r2", status="sent")
    result = bridge_proposals_to_opportunities(db)
    assert result["created"] == 0
    assert _opp_count(db) == 1


def test_bridge_separate_projects_get_separate_opportunities(db):
    cid = _mk_client(db)
    p1 = _mk_project(db, cid, name="Job A", job="260701")
    p2 = _mk_project(db, cid, name="Job B", job="260702")
    _mk_proposal(db, p1, number="A-1")
    _mk_proposal(db, p2, number="B-1")

    result = bridge_proposals_to_opportunities(db)
    assert result["created"] == 2
    assert _opp_count(db) == 2


# ---------------------------------------------------------------------------
# Status sync back
# ---------------------------------------------------------------------------
def test_status_sync_restages_unmoved_opportunity(db):
    cid = _mk_client(db)
    pid = _mk_project(db, cid)
    prop_id = _mk_proposal(db, pid, status="sent")
    bridge_proposals_to_opportunities(db)

    db.execute(
        "UPDATE proposals SET status = 'accepted' WHERE id = ?", (prop_id,)
    )
    db.commit()

    result = bridge_proposals_to_opportunities(db)
    assert result["synced"] == 1

    opp = _bridged_opp(db, prop_id)
    assert opp["stage"] == "won"
    assert opp["probability"] == 100
    assert opp["source_proposal_status"] == "accepted"


def test_status_sync_to_declined_maps_to_lost(db):
    cid = _mk_client(db)
    pid = _mk_project(db, cid)
    prop_id = _mk_proposal(db, pid, status="sent")
    bridge_proposals_to_opportunities(db)

    db.execute(
        "UPDATE proposals SET status = 'declined' WHERE id = ?", (prop_id,)
    )
    db.commit()
    bridge_proposals_to_opportunities(db)

    opp = _bridged_opp(db, prop_id)
    assert opp["stage"] == "lost"
    assert opp["probability"] == 0


def test_status_sync_does_not_clobber_manual_moves(db):
    cid = _mk_client(db)
    pid = _mk_project(db, cid)
    prop_id = _mk_proposal(db, pid, status="sent")
    bridge_proposals_to_opportunities(db)

    opp = _bridged_opp(db, prop_id)
    advance_stage(db, opp["id"], "negotiating")  # Juan moved it himself

    db.execute(
        "UPDATE proposals SET status = 'accepted' WHERE id = ?", (prop_id,)
    )
    db.commit()
    result = bridge_proposals_to_opportunities(db)
    assert result["synced"] == 0

    refreshed = get_opportunity(db, opp["id"])
    # The manual stage wins; the bookkeeping column still tracks the proposal.
    assert refreshed["stage"] == "negotiating"
    assert refreshed["source_proposal_status"] == "accepted"


def test_legacy_bridged_rows_get_baseline_without_restaging(db):
    """Rows bridged before source_proposal_status existed are baselined
    on the first pass (recorded, stage untouched), then sync normally."""
    cid = _mk_client(db)
    pid = _mk_project(db, cid)
    prop_id = _mk_proposal(db, pid, status="sent")
    bridge_proposals_to_opportunities(db)

    # Simulate a pre-phase-2 bridged row.
    db.execute(
        "UPDATE opportunities SET source_proposal_status = NULL "
        "WHERE source_proposal_id = ?",
        (prop_id,),
    )
    db.commit()

    result = bridge_proposals_to_opportunities(db)
    assert result["synced"] == 0
    opp = _bridged_opp(db, prop_id)
    assert opp["stage"] == "proposal_sent"  # untouched
    assert opp["source_proposal_status"] == "sent"  # baseline recorded

    # From the baseline on, syncing works as usual.
    db.execute(
        "UPDATE proposals SET status = 'accepted' WHERE id = ?", (prop_id,)
    )
    db.commit()
    result = bridge_proposals_to_opportunities(db)
    assert result["synced"] == 1
    assert _bridged_opp(db, prop_id)["stage"] == "won"


def test_synced_stage_change_is_logged(db):
    cid = _mk_client(db)
    pid = _mk_project(db, cid)
    prop_id = _mk_proposal(db, pid, status="sent")
    bridge_proposals_to_opportunities(db)
    opp = _bridged_opp(db, prop_id)

    db.execute(
        "UPDATE proposals SET status = 'accepted' WHERE id = ?", (prop_id,)
    )
    db.commit()
    bridge_proposals_to_opportunities(db)

    row = db.execute(
        "SELECT COUNT(*) AS c FROM activity_log "
        "WHERE entity_type = 'opportunity' AND entity_id = ? "
        "  AND action = 'stage_change'",
        (opp["id"],),
    ).fetchone()
    assert row["c"] == 1
