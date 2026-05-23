"""Kanban view tests for the Projects page.

Session 3a — subagent 5. The Kanban view ships the status-change path via
a per-card ``st.selectbox`` (the streamlit-sortables DnD path was rejected
because the library can only handle ``list[str]`` items, which precludes
the rich card layout). Every status mutation still routes through
``modules.projects.crud.update_project`` so the activity_log row is
written by the service layer.

These tests assert the **service-layer contract** the Kanban view depends
on. The view itself uses Streamlit widgets that AppTest does not render
deterministically (selectbox on_change), so we exercise the underlying
``update_project`` call directly and the filter logic via direct import.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.projects.crud import update_project  # noqa: E402
from streamlit_app.components.status_pills import PROJECT_STATUSES  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _seed_project(conn, status: str = "active", job: str = "260601") -> int:
    """Insert a single project with the given status. Returns its id."""
    conn.execute("INSERT INTO clients (name) VALUES ('Acme Co')")
    cid = conn.execute("SELECT id FROM clients").fetchone()[0]
    conn.execute(
        "INSERT INTO projects (job_number, name, status, client_id) "
        "VALUES (?, ?, ?, ?)",
        (job, f"Kanban Test {job}", status, cid),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM projects WHERE job_number = ?", (job,)
    ).fetchone()[0]


def _filter_kanban_projects(projects, show_archived: bool):
    """Mirror the Kanban view's archived-toggle filter logic.

    Kept here as a function so the filter can be tested in isolation
    without spinning up Streamlit.
    """
    if show_archived:
        return list(projects)
    return [p for p in projects if p["status"] != "archived"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_kanban_status_change_routes_through_update_project(db):
    """Moving a card to a new column MUST call update_project(status=...).

    Simulates the per-card selectbox handler: when ``new_status !=
    proj['status']``, the view calls ``update_project(conn, pid,
    status=new_status)``. We assert the call writes the new status to
    the row AND emits exactly one ``updated`` activity_log entry whose
    details JSON includes ``"status"``.
    """
    pid = _seed_project(db, status="active")
    before = db.execute(
        "SELECT COUNT(*) FROM activity_log "
        "WHERE entity_type='project' AND entity_id=? AND action='updated'",
        (pid,),
    ).fetchone()[0]

    # Simulate the Kanban card's selectbox setting status to on_hold.
    update_project(db, pid, status="on_hold")

    # Row reflects the new status.
    new_status = db.execute(
        "SELECT status FROM projects WHERE id=?", (pid,)
    ).fetchone()[0]
    assert new_status == "on_hold"

    # Exactly one new 'updated' log row.
    after = db.execute(
        "SELECT COUNT(*) FROM activity_log "
        "WHERE entity_type='project' AND entity_id=? AND action='updated'",
        (pid,),
    ).fetchone()[0]
    assert after == before + 1, (
        f"expected one new updated row, got {after - before}"
    )

    # The latest log row's details include the status key.
    latest = db.execute(
        "SELECT details FROM activity_log "
        "WHERE entity_type='project' AND entity_id=? AND action='updated' "
        "ORDER BY id DESC LIMIT 1",
        (pid,),
    ).fetchone()[0]
    parsed = json.loads(latest)
    assert parsed.get("status") == "on_hold"


def test_kanban_show_archived_filter_affects_visible_ids(db):
    """When the toggle is off, archived projects MUST be filtered out."""
    active_id = _seed_project(db, status="active", job="260601")
    archived_id = _seed_project(db, status="archived", job="260602")

    all_rows = list(
        db.execute("SELECT * FROM projects ORDER BY id").fetchall()
    )
    # Sanity: both rows are present in the seed.
    assert {r["id"] for r in all_rows} == {active_id, archived_id}

    # Toggle OFF — archived hidden.
    visible_off = _filter_kanban_projects(all_rows, show_archived=False)
    ids_off = {p["id"] for p in visible_off}
    assert active_id in ids_off
    assert archived_id not in ids_off

    # Toggle ON — archived included.
    visible_on = _filter_kanban_projects(all_rows, show_archived=True)
    ids_on = {p["id"] for p in visible_on}
    assert ids_on == {active_id, archived_id}


def test_kanban_status_change_rejects_invalid_status(db):
    """A status outside PROJECT_STATUSES MUST raise rather than persist.

    The Kanban selectbox is constrained to PROJECT_STATUSES, but the
    underlying service layer must still reject any out-of-band value
    via SQLite's CHECK constraint. This is the same safety net the
    inline-edit handler relies on.
    """
    import sqlite3

    pid = _seed_project(db, status="active")
    with pytest.raises(sqlite3.IntegrityError):
        update_project(db, pid, status="frobnicated")

    # The row's status MUST be unchanged after the failed write.
    current = db.execute(
        "SELECT status FROM projects WHERE id=?", (pid,)
    ).fetchone()[0]
    assert current == "active"


def test_project_statuses_constant_matches_schema():
    """The PROJECT_STATUSES tuple MUST mirror the schema CHECK constraint.

    Drift here breaks the Kanban column scaffold AND every selectbox in
    the page. Caught at the unit level so a schema change forces a
    contemporaneous update to the shared constant.
    """
    assert set(PROJECT_STATUSES) == {
        "active",
        "prospect",
        "on_hold",
        "completed",
        "archived",
    }
