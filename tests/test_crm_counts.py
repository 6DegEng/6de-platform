"""CRM pipeline counting consistency tests.

Covers the fix for the divergent "Active Opportunities" KPI vs the pipeline
list count: the KPI and the documented active-stage set must agree by
definition, and NULL-client opportunities must render safely.
"""
from __future__ import annotations

import sqlite3


from modules.crm.crud import (
    ACTIVE_STAGES,
    CLOSED_STAGES,
    STAGES,
    count_active_opportunities,
    get_pipeline_summary,
    list_opportunities,
)


def _insert_opp(conn: sqlite3.Connection, name: str, stage: str,
                client_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO opportunities (name, stage, client_id, estimated_value, "
        "probability, created_at, updated_at) "
        "VALUES (?, ?, ?, 1000, 50, datetime('now'), datetime('now'))",
        (name, stage, client_id),
    )
    conn.commit()
    return cur.lastrowid


def test_active_and_closed_stages_partition_all_stages():
    """ACTIVE_STAGES + CLOSED_STAGES must exactly cover STAGES with no overlap."""
    assert set(ACTIVE_STAGES).isdisjoint(CLOSED_STAGES)
    assert set(ACTIVE_STAGES) | set(CLOSED_STAGES) == set(STAGES)
    # Documented intent: the closed/terminal stages.
    assert set(CLOSED_STAGES) == {"won", "lost", "dormant"}


def test_active_count_matches_documented_active_stages(db):
    """The KPI's active_count must equal a COUNT over exactly ACTIVE_STAGES."""
    # Seed one opportunity in every stage so closed stages are present.
    for s in STAGES:
        _insert_opp(db, f"opp-{s}", s)

    summary = get_pipeline_summary(db)

    # Independent ground-truth count straight from the DB against the set.
    placeholders = ", ".join("?" for _ in ACTIVE_STAGES)
    expected = db.execute(
        f"SELECT COUNT(*) AS c FROM opportunities WHERE stage IN ({placeholders})",
        ACTIVE_STAGES,
    ).fetchone()["c"]

    assert expected == len(ACTIVE_STAGES)  # one per active stage seeded
    assert summary["active_count"] == expected
    assert count_active_opportunities(db) == expected


def test_active_count_excludes_won_lost_dormant(db):
    """active_count must NOT include won/lost/dormant (the original bug)."""
    _insert_opp(db, "lead-1", "lead")
    _insert_opp(db, "won-1", "won")
    _insert_opp(db, "lost-1", "lost")
    _insert_opp(db, "dormant-1", "dormant")

    summary = get_pipeline_summary(db)
    # Only the single 'lead' opp is active.
    assert summary["active_count"] == 1
    assert count_active_opportunities(db) == 1
    # by_stage must not carry any closed stage.
    assert set(summary["by_stage"]).issubset(set(ACTIVE_STAGES))


def test_active_count_le_total_list_count(db):
    """Active count is a subset of the full pipeline list (KPI <= list total)."""
    for s in STAGES:
        _insert_opp(db, f"o-{s}", s)
    total = len(list_opportunities(db, stage=None))
    active = count_active_opportunities(db)
    assert active <= total
    assert total == len(STAGES)
    assert active == len(ACTIVE_STAGES)


def test_null_client_opportunity_renders_safely(db):
    """An opportunity with NULL client_id yields client_name=None (renders '—').

    Mirrors the four Proposal-Sent records imported without a source company.
    """
    oid = _insert_opp(db, "601 E 33rd St", "proposal_sent", client_id=None)
    rows = list_opportunities(db, stage="proposal_sent")
    match = next(r for r in rows if r["id"] == oid)
    assert match["client_id"] is None
    assert match["client_name"] is None
    # The page renders `opp["client_name"] or "No client"` — exercise that path.
    assert (match["client_name"] or "No client") == "No client"
