"""Configurable CRM stages (crm-polish phase 2).

The crm_stages table is seeded with the original seven stages so default
behavior is unchanged; these tests prove the pipeline actually *reads* the
config: deactivating a stage removes it from the open pipeline, custom
stages join it, renames only touch labels, and stage-default probabilities
drive the prorated (expected) revenue math.
"""
from __future__ import annotations

import sqlite3

import pytest

from modules.crm.crud import (
    ACTIVE_STAGES,
    STAGES,
    advance_stage,
    allowed_next_stages,
    convert_to_project,
    count_active_opportunities,
    create_opportunity,
    get_opportunity,
    get_pipeline_summary,
    get_win_loss_stats,
    list_opportunities,
    update_opportunity,
)
from modules.crm.stages import (
    DEFAULT_STAGES,
    create_stage,
    get_stage_by_key,
    list_stages,
    open_stage_keys,
    seed_crm_stages,
    stage_labels,
    stage_probability,
    update_stage,
)


def _insert_opp(conn: sqlite3.Connection, name: str, stage: str,
                value: float = 1000, probability: int = 50) -> int:
    cur = conn.execute(
        "INSERT INTO opportunities (name, stage, estimated_value, "
        "probability, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
        (name, stage, value, probability),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
def test_default_stages_seeded(db):
    rows = list_stages(db, include_inactive=True)
    assert [r["key"] for r in rows] == list(STAGES)
    # Out of the box the open pipeline equals the legacy ACTIVE_STAGES set.
    assert open_stage_keys(db) == ACTIVE_STAGES
    won = get_stage_by_key(db, "won")
    assert won["is_won"] == 1 and won["is_closed"] == 1
    lost = get_stage_by_key(db, "lost")
    assert lost["is_lost"] == 1 and lost["is_closed"] == 1
    dormant = get_stage_by_key(db, "dormant")
    assert dormant["is_won"] == 0 and dormant["is_lost"] == 0
    assert dormant["is_closed"] == 1


def test_seed_is_idempotent_and_respects_edits(db):
    seed_crm_stages(db)
    rows = list_stages(db, include_inactive=True)
    assert len(rows) == len(DEFAULT_STAGES)

    # A user edit must survive a re-seed (seed only fills an empty table).
    lead = get_stage_by_key(db, "lead")
    update_stage(db, lead["id"], name="Fresh Lead")
    seed_crm_stages(db)
    assert get_stage_by_key(db, "lead")["name"] == "Fresh Lead"
    assert len(list_stages(db, include_inactive=True)) == len(DEFAULT_STAGES)


# ---------------------------------------------------------------------------
# Stage config drives the pipeline
# ---------------------------------------------------------------------------
def test_deactivated_stage_leaves_open_pipeline(db):
    _insert_opp(db, "in-lead", "lead")
    _insert_opp(db, "in-qualifying", "qualifying")
    assert count_active_opportunities(db) == 2

    qualifying = get_stage_by_key(db, "qualifying")
    update_stage(db, qualifying["id"], active=False)

    assert "qualifying" not in open_stage_keys(db)
    assert count_active_opportunities(db) == 1
    summary = get_pipeline_summary(db)
    assert "qualifying" not in summary["by_stage"]
    assert summary["total_pipeline_value"] == 1000

    update_stage(db, qualifying["id"], active=True)
    assert count_active_opportunities(db) == 2


def test_custom_open_stage_counts_in_pipeline(db):
    create_stage(db, "Site Visit", probability=30, kind="open")
    assert "site_visit" in open_stage_keys(db)

    oid = _insert_opp(db, "custom-stage-opp", "lead", value=2000)
    advance_stage(db, oid, "site_visit")

    opp = get_opportunity(db, oid)
    assert opp["stage"] == "site_visit"
    # Stage-default probability applied on entry.
    assert opp["probability"] == 30

    summary = get_pipeline_summary(db)
    assert "site_visit" in summary["by_stage"]
    assert summary["by_stage"]["site_visit"]["weighted_value"] == pytest.approx(600.0)
    assert count_active_opportunities(db) == 1


def test_custom_lost_stage_counts_in_win_loss(db):
    create_stage(db, "No Bid", probability=0, kind="lost")
    oid = _insert_opp(db, "nobid-opp", "lead")
    advance_stage(db, oid, "no_bid")
    _insert_opp(db, "won-opp", "won")

    stats = get_win_loss_stats(db)
    assert stats["total_lost"] == 1
    assert stats["total_won"] == 1
    assert stats["win_rate"] == 50.0


def test_rename_changes_label_not_key(db):
    qualifying = get_stage_by_key(db, "qualifying")
    oid = _insert_opp(db, "renamed-stage-opp", "qualifying")
    update_stage(db, qualifying["id"], name="Vetting")

    assert stage_labels(db)["qualifying"] == "Vetting"
    assert get_opportunity(db, oid)["stage"] == "qualifying"
    assert count_active_opportunities(db) == 1


def test_reorder_changes_list_order(db):
    lead = get_stage_by_key(db, "lead")
    update_stage(db, lead["id"], sequence=999)
    keys = [r["key"] for r in list_stages(db, include_inactive=True)]
    assert keys[-1] == "lead"
    assert keys[0] == "qualifying"


# ---------------------------------------------------------------------------
# Transitions and prorated revenue
# ---------------------------------------------------------------------------
def test_builtin_transition_validation_still_enforced(db):
    oid = _insert_opp(db, "won-opp", "won")
    with pytest.raises(ValueError):
        advance_stage(db, oid, "qualifying")


def test_unknown_stage_rejected(db):
    oid = _insert_opp(db, "lead-opp", "lead")
    with pytest.raises(ValueError):
        advance_stage(db, oid, "does_not_exist")


def test_allowed_next_stages_builtin_plus_custom(db):
    assert allowed_next_stages(db, "lead") == ["qualifying", "lost", "dormant"]
    create_stage(db, "Site Visit", kind="open")
    assert "site_visit" in allowed_next_stages(db, "lead")
    # From a custom stage anything active (except itself) is reachable.
    from_custom = allowed_next_stages(db, "site_visit")
    assert "won" in from_custom and "lead" in from_custom
    assert "site_visit" not in from_custom


def test_advance_applies_stage_probability(db):
    oid = _insert_opp(db, "prob-opp", "qualifying", value=10000, probability=50)
    advance_stage(db, oid, "proposal_sent")
    opp = get_opportunity(db, oid)
    assert opp["probability"] == stage_probability(db, "proposal_sent") == 60
    assert opp["expected_revenue"] == pytest.approx(6000.0)

    advance_stage(db, oid, "won")
    opp = get_opportunity(db, oid)
    assert opp["probability"] == 100
    assert opp["expected_revenue"] == pytest.approx(10000.0)


def test_pipeline_totals_show_gross_and_expected(db):
    _insert_opp(db, "a", "lead", value=1000, probability=20)
    _insert_opp(db, "b", "negotiating", value=2000, probability=80)
    summary = get_pipeline_summary(db)
    assert summary["total_pipeline_value"] == pytest.approx(3000.0)
    assert summary["weighted_pipeline_total"] == pytest.approx(200.0 + 1600.0)


def test_expected_revenue_exposed_on_list(db):
    _insert_opp(db, "listed", "lead", value=5000, probability=40)
    row = list_opportunities(db, stage="lead")[0]
    assert row["expected_revenue"] == pytest.approx(2000.0)


def test_edited_stage_probability_flows_into_moves(db):
    negotiating = get_stage_by_key(db, "negotiating")
    update_stage(db, negotiating["id"], probability=90)
    oid = _insert_opp(db, "edited-prob", "proposal_sent", value=1000)
    advance_stage(db, oid, "negotiating")
    assert get_opportunity(db, oid)["probability"] == 90


def test_create_opportunity_defaults_unchanged(db):
    """Out-of-the-box creation still behaves like before the config table."""
    oid = create_opportunity(db, "plain", estimated_value=100, probability=50)
    opp = get_opportunity(db, oid)
    assert opp["stage"] == "lead"
    assert opp["probability"] == 50


def test_create_and_update_reject_unknown_stage(db):
    """App-layer validation replaces the retired DB CHECK on stage."""
    with pytest.raises(ValueError):
        create_opportunity(db, "bad-stage", stage="not_a_stage")

    oid = create_opportunity(db, "ok", stage="lead")
    with pytest.raises(ValueError):
        update_opportunity(db, oid, stage="not_a_stage")
    # Known custom stage passes.
    create_stage(db, "Site Visit", kind="open")
    update_opportunity(db, oid, stage="site_visit")
    assert get_opportunity(db, oid)["stage"] == "site_visit"


def test_convert_to_project_accepts_custom_won_stage(db):
    """The Convert button shows for any won-flagged stage — conversion
    must accept those stages too, not just the literal 'won' key."""
    create_stage(db, "Awarded", probability=100, kind="won")
    oid = _insert_opp(db, "awarded-opp", "lead", value=4000)
    advance_stage(db, oid, "awarded")

    project_id = convert_to_project(db, oid)
    row = db.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    assert row is not None
    assert get_opportunity(db, oid)["project_id"] == project_id


def test_allowed_next_stages_accepts_preloaded_keys(db):
    """The page passes its already-loaded stage keys to skip a query."""
    keys = [r["key"] for r in list_stages(db)]
    assert allowed_next_stages(db, "lead", active_keys=keys) == \
        allowed_next_stages(db, "lead")
