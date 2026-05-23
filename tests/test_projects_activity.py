"""Tests for modules.projects.activity (per-project activity_log view).

Session 3a — subagent 6. Exercises the query helpers
(``list_project_activity`` / ``count_project_activity``) and the
``summarize_activity`` row formatter. The renderer in
``streamlit_app/components/activity_panel.py`` is exercised via
AppTest indirectly (the manual smoke pass in the verifier), so this
file focuses on the service-layer contract.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.projects.activity import (  # noqa: E402
    count_project_activity,
    list_project_activity,
    summarize_activity,
)
from modules.projects.crud import (  # noqa: E402
    create_milestone,
    create_project,
    update_milestone,
    update_project,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_row(conn, **fields) -> sqlite3.Row:
    """Build a one-off sqlite3.Row by inserting into activity_log.

    Easier than mocking — Row is opaque about its keys otherwise.
    """
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    cur = conn.execute(
        f"INSERT INTO activity_log ({cols}) VALUES ({placeholders})",
        list(fields.values()),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM activity_log WHERE id=?", (cur.lastrowid,)
    ).fetchone()


# ---------------------------------------------------------------------------
# list_project_activity / count_project_activity
# ---------------------------------------------------------------------------
def test_list_project_activity_returns_project_rows(db):
    """A create + an update yields 2 rows, newest-first."""
    pid = create_project(db, name="Test Project", status="active", state="FL")
    update_project(db, pid, name="Renamed Project")

    rows = list_project_activity(db, pid)
    actions = [r["action"] for r in rows]
    assert actions == ["updated", "created"], (
        f"Expected newest-first ordering; got {actions}"
    )
    # Both rows are for this project.
    for r in rows:
        assert r["entity_type"] == "project"
        assert r["entity_id"] == pid


def test_list_project_activity_paginates(db):
    """Manual writes >25 rows; limit/offset slices the result correctly."""
    pid = create_project(db, name="Big Activity", status="active", state="FL")

    # 25 manual update rows with timestamps guaranteed to be AFTER the
    # create row. create_project uses _now() (UTC), so we use a far-future
    # date to avoid wall-clock dependence.
    for i in range(25):
        db.execute(
            "INSERT INTO activity_log "
            "(entity_type, entity_id, action, details, created_at) "
            "VALUES ('project', ?, 'updated', '{}', ?)",
            (pid, f"2099-01-01 12:{i:02d}:00"),
        )
    db.commit()

    page1 = list_project_activity(db, pid, limit=25, offset=0)
    assert len(page1) == 25

    total = count_project_activity(db, pid)
    assert total == 26

    page2 = list_project_activity(db, pid, limit=25, offset=25)
    assert len(page2) == 1
    # The lone remaining row is the original create (oldest).
    assert page2[0]["action"] == "created"


def test_list_project_activity_includes_milestones_when_flag_true(db):
    """include_milestones=True surfaces milestone rows for this project."""
    pid = create_project(db, name="With Milestones", status="active", state="FL")
    ms_id = create_milestone(db, pid, "Submit permit application")
    update_milestone(db, ms_id, status="completed")

    with_ms = list_project_activity(db, pid, include_milestones=True)
    # Expected rows: project-create, milestone-create, milestone-update.
    assert len(with_ms) == 3, (
        f"Expected 3 rows (1 project + 2 milestone); got {len(with_ms)}: "
        f"{[(r['entity_type'], r['action']) for r in with_ms]}"
    )
    entity_types = {r["entity_type"] for r in with_ms}
    assert entity_types == {"project", "milestone"}

    without_ms = list_project_activity(db, pid, include_milestones=False)
    assert len(without_ms) == 1
    assert without_ms[0]["entity_type"] == "project"
    assert without_ms[0]["action"] == "created"


def test_count_project_activity_matches_list_count(db):
    """count_*() and list_*() must agree on cardinality for both modes."""
    pid = create_project(db, name="Count Match", status="active", state="FL")
    ms_id = create_milestone(db, pid, "ms-1")
    update_milestone(db, ms_id, status="completed")
    update_project(db, pid, status="completed")

    for include_ms in (True, False):
        listed = list_project_activity(
            db, pid, limit=999, include_milestones=include_ms
        )
        counted = count_project_activity(db, pid, include_milestones=include_ms)
        assert len(listed) == counted, (
            f"include_milestones={include_ms}: list={len(listed)} "
            f"count={counted}"
        )


# ---------------------------------------------------------------------------
# summarize_activity
# ---------------------------------------------------------------------------
def test_summarize_activity_status_change(db):
    """`action='updated'` with a `status` key reports the new label."""
    pid = create_project(db, name="Status Demo", status="active", state="FL")
    row = _make_row(
        db,
        entity_type="project",
        entity_id=pid,
        action="updated",
        details='{"status": "completed", "updated_at": "2026-05-23 12:00:00"}',
        created_at="2026-05-23 12:00:00",
    )
    assert summarize_activity(row) == "Status changed to Completed"


def test_summarize_activity_handles_null_details(db):
    """Defensive default when details column is NULL."""
    pid = create_project(db, name="Null Demo", status="active", state="FL")
    row = _make_row(
        db,
        entity_type="project",
        entity_id=pid,
        action="deleted",
        details=None,
        created_at="2026-05-23 12:00:00",
    )
    # Doesn't crash. action='deleted' is a known project verb so the
    # summary is the deletion line; verify the fallback path also
    # works for a totally unknown action.
    assert summarize_activity(row) == "Project deleted"

    unknown_row = _make_row(
        db,
        entity_type="project",
        entity_id=pid,
        action="frobnicated",
        details=None,
        created_at="2026-05-23 12:01:00",
    )
    assert summarize_activity(unknown_row) == "Frobnicated"


def test_summarize_activity_milestone_completed(db):
    """`done=1` in milestone-update details renders as 'Milestone completed'."""
    pid = create_project(db, name="Milestone Demo", status="active", state="FL")
    ms_id = create_milestone(db, pid, "ms-1")
    row = _make_row(
        db,
        entity_type="milestone",
        entity_id=ms_id,
        action="updated",
        details='{"done": 1, "updated_at": "2026-05-23 12:00:00"}',
        created_at="2026-05-23 12:00:00",
    )
    assert summarize_activity(row) == "Milestone completed"
