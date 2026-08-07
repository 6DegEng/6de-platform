"""AppTest smoke for the CRM page after crm-polish phase 2.

Mounts streamlit_app/pages/4_CRM.py against a seeded temp DB and proves the
page renders with the config-driven stages, the new Settings tab, the
Expected Revenue metric, and a lost opportunity carrying a reason.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from db import get_connection, init_db  # noqa: E402
from modules.crm.crud import mark_lost  # noqa: E402
from modules.crm.stages import list_lost_reasons  # noqa: E402


@pytest.fixture()
def crm_page(tmp_path, monkeypatch):
    """Mount /CRM with auth disabled and a seeded DB."""
    from streamlit.testing.v1 import AppTest

    db_path = tmp_path / "platform_test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO clients (name, email) VALUES ('Smoke Client', 'c@x.test')"
    )
    cid = conn.execute("SELECT id FROM clients").fetchone()[0]
    for name, stage, value, prob in [
        ("Lead Opp", "lead", 1000, 20),
        ("Proposal Opp", "proposal_sent", 5000, 60),
        ("Won Opp", "won", 8000, 100),
    ]:
        conn.execute(
            "INSERT INTO opportunities (name, stage, client_id, "
            "estimated_value, probability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (name, stage, cid, value, prob),
        )
    cur = conn.execute(
        "INSERT INTO opportunities (name, stage, client_id, estimated_value, "
        "probability, created_at, updated_at) "
        "VALUES ('Losing Opp', 'lead', ?, 2000, 20, datetime('now'), datetime('now'))",
        (cid,),
    )
    reason_id = list_lost_reasons(conn)[0]["id"]
    mark_lost(conn, cur.lastrowid, lost_reason_id=reason_id, lost_note="too pricey")
    conn.commit()
    conn.close()

    monkeypatch.setenv("PLATFORM_DB_PATH", str(db_path))
    monkeypatch.setattr("db.DB_PATH", db_path)
    monkeypatch.setattr("config.DB_PATH", db_path)
    import db as _db_mod
    if hasattr(_db_mod.ensure_db, "clear"):
        _db_mod.ensure_db.clear()
    monkeypatch.setattr("streamlit_app.auth.require_auth", lambda: None)

    at = AppTest.from_file(
        str(_PLATFORM_ROOT / "streamlit_app" / "pages" / "4_CRM.py")
    )
    return at


def test_crm_page_renders_without_exception(crm_page):
    at = crm_page.run(timeout=30)
    assert not at.exception, f"Page raised: {at.exception}"


def test_settings_tab_and_stage_tabs_present(crm_page):
    at = crm_page.run(timeout=30)
    assert not at.exception
    tab_labels = [t.label for t in at.tabs]
    # Top-level tabs
    for label in ("Pipeline", "Clients", "Analytics", "Settings"):
        assert label in tab_labels, f"Missing tab {label}; saw {tab_labels}"
    # Stage sub-tabs come from the seeded crm_stages config
    for label in ("Lead", "Proposal Sent", "Won", "Lost", "Dormant"):
        assert label in tab_labels, f"Missing stage tab {label}; saw {tab_labels}"


def test_expected_revenue_metric_present(crm_page):
    at = crm_page.run(timeout=30)
    assert not at.exception
    metric_labels = [m.label for m in at.metric]
    assert "Expected Revenue" in metric_labels
    assert "Total Pipeline Value" in metric_labels
    assert "Active Opportunities" in metric_labels
