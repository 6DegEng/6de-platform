"""Inline-edit handler tests for the Projects aggrid table view.

Session 3a — subagent 4. These exercise the page-importable
``streamlit_app.components.project_grid.handle_row_save`` helper and its
underlying ``diff_row``.

The handler must:
  * route every change through ``modules.projects.crud.update_project``
    (so the activity_log row gets written),
  * pass ONLY the changed kwargs to ``update_project`` (no empty UPDATEs),
  * reject statuses outside ``PROJECT_STATUSES`` before SQLite raises the
    CHECK violation,
  * be a no-op when old == new.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock


_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from streamlit_app.components.project_grid import (  # noqa: E402
    diff_row,
    handle_row_save,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _seed_project(conn) -> int:
    """Insert a single project and return its id."""
    conn.execute("INSERT INTO clients (name) VALUES ('Acme Co')")
    cid = conn.execute("SELECT id FROM clients").fetchone()[0]
    conn.execute(
        "INSERT INTO projects (job_number, name, status, client_id, address, "
        "city, county, scope, notes, start_date, target_end_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "260523",
            "Test Project",
            "active",
            cid,
            "100 Main St",
            "Miami",
            "Miami-Dade",
            "framing inspection",
            "first pass",
            "2026-05-23",
            "2026-08-01",
        ),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM projects WHERE job_number = '260523'"
    ).fetchone()[0]


def _project_row_dict(conn, pid: int) -> dict:
    """Read the project row back as a plain dict (mirrors what the grid sees)."""
    row = conn.execute(
        "SELECT id, job_number, name, status, address, city, county, scope, "
        "notes, start_date, target_end_date FROM projects WHERE id = ?",
        (pid,),
    ).fetchone()
    return {k: ("" if row[k] is None else row[k]) for k in row.keys()}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_inline_edit_routes_through_update_project(db):
    """A name edit MUST call update_project with only the changed field."""
    pid = _seed_project(db)
    old_row = _project_row_dict(db, pid)
    new_row = dict(old_row)
    new_row["name"] = "Test Project — Renamed"

    with mock.patch(
        "streamlit_app.components.project_grid.update_project"
    ) as mock_update:
        error = handle_row_save(db, old_row, new_row)

    assert error is None
    assert mock_update.call_count == 1
    args, kwargs = mock_update.call_args
    # First positional is the connection, second is pid.
    assert args[1] == pid
    # The diffed kwargs should be JUST the changed field — not the entire row.
    assert kwargs == {"name": "Test Project — Renamed"}


def test_inline_edit_rejects_invalid_status(db):
    """A status value outside PROJECT_STATUSES MUST be rejected pre-DB."""
    pid = _seed_project(db)
    old_row = _project_row_dict(db, pid)
    new_row = dict(old_row)
    new_row["status"] = "frobnicated"

    with mock.patch(
        "streamlit_app.components.project_grid.update_project"
    ) as mock_update:
        error = handle_row_save(db, old_row, new_row)

    assert error is not None, "handler should return an error message"
    assert "frobnicated" in error
    assert mock_update.call_count == 0, "update_project must NOT be called"


def test_inline_edit_emits_activity_log(db):
    """Integration: a real update_project call writes one new activity_log row."""
    pid = _seed_project(db)
    # Baseline: how many activity_log rows existed BEFORE the edit?
    before = db.execute(
        "SELECT COUNT(*) FROM activity_log "
        "WHERE entity_type='project' AND entity_id=? AND action='updated'",
        (pid,),
    ).fetchone()[0]

    old_row = _project_row_dict(db, pid)
    new_row = dict(old_row)
    new_row["notes"] = "second pass"

    error = handle_row_save(db, old_row, new_row)
    assert error is None

    after = db.execute(
        "SELECT COUNT(*) FROM activity_log "
        "WHERE entity_type='project' AND entity_id=? AND action='updated'",
        (pid,),
    ).fetchone()[0]
    assert after == before + 1, (
        f"expected exactly one new 'updated' activity_log row, "
        f"got {after - before}"
    )

    # The newest log row's details JSON should contain ONLY the changed key
    # plus the auto-added updated_at — not the entire row payload.
    latest = db.execute(
        "SELECT details FROM activity_log "
        "WHERE entity_type='project' AND entity_id=? AND action='updated' "
        "ORDER BY id DESC LIMIT 1",
        (pid,),
    ).fetchone()[0]
    parsed = json.loads(latest)
    assert "notes" in parsed
    assert parsed["notes"] == "second pass"
    # update_project auto-injects updated_at; everything else should be absent.
    assert set(parsed.keys()) <= {"notes", "updated_at"}


def test_inline_edit_no_change_is_noop(db):
    """old == new means update_project MUST NOT be called (no empty UPDATEs)."""
    pid = _seed_project(db)
    old_row = _project_row_dict(db, pid)
    new_row = dict(old_row)  # identical

    with mock.patch(
        "streamlit_app.components.project_grid.update_project"
    ) as mock_update:
        error = handle_row_save(db, old_row, new_row)

    assert error is None
    assert mock_update.call_count == 0, (
        "no-op edit must not hit the DB (avoids empty UPDATE + spurious log)"
    )


# ---------------------------------------------------------------------------
# Light coverage for diff_row — load-bearing for the handler's correctness.
# ---------------------------------------------------------------------------
def test_diff_row_normalizes_none_and_empty_string():
    """None vs '' on an editable column should NOT register as a change."""
    old = {"name": "X", "address": None, "id": 1}
    new = {"name": "X", "address": "", "id": 1}
    assert diff_row(old, new) == {}


def test_diff_row_blanking_a_text_field_writes_null():
    """'' on an editable column was originally non-empty -> write back as None."""
    old = {"name": "X", "notes": "old text", "id": 1}
    new = {"name": "X", "notes": "", "id": 1}
    out = diff_row(old, new)
    assert out == {"notes": None}


def test_diff_row_ignores_readonly_columns():
    """job_number / client_name aren't in EDITABLE_COLUMNS — changing them is ignored."""
    old = {"name": "X", "job_number": "260101", "client_name": "Acme", "id": 1}
    new = {"name": "X", "job_number": "999999", "client_name": "Other", "id": 1}
    assert diff_row(old, new) == {}


# ---------------------------------------------------------------------------
# Session 3b column tests — priority, percent_complete, contract_value
# ---------------------------------------------------------------------------
def test_inline_edit_rejects_invalid_priority(db):
    """A priority value outside PRIORITY_VALUES MUST be rejected."""
    pid = _seed_project(db)
    old_row = _project_row_dict(db, pid)
    new_row = dict(old_row)
    new_row["priority"] = "extreme"

    with mock.patch(
        "streamlit_app.components.project_grid.update_project"
    ) as mock_update:
        error = handle_row_save(db, old_row, new_row)

    assert error is not None
    assert "extreme" in error
    assert mock_update.call_count == 0


def test_inline_edit_clamps_percent_complete(db):
    """percent_complete > 100 is clamped to 100."""
    pid = _seed_project(db)
    old_row = _project_row_dict(db, pid)
    new_row = dict(old_row)
    new_row["percent_complete"] = "150"

    error = handle_row_save(db, old_row, new_row)
    assert error is None

    row = db.execute(
        "SELECT percent_complete FROM projects WHERE id = ?", (pid,)
    ).fetchone()
    assert row["percent_complete"] == 100


def test_inline_edit_accepts_valid_priority(db):
    """A valid priority value is persisted."""
    pid = _seed_project(db)
    old_row = _project_row_dict(db, pid)
    new_row = dict(old_row)
    new_row["priority"] = "high"

    error = handle_row_save(db, old_row, new_row)
    assert error is None

    row = db.execute(
        "SELECT priority FROM projects WHERE id = ?", (pid,)
    ).fetchone()
    assert row["priority"] == "high"


def test_diff_row_detects_new_column_changes():
    """priority, action_by, percent_complete, contract_value are all editable."""
    old = {"name": "X", "priority": "", "action_by": "", "percent_complete": 0,
           "contract_value": 0, "next_action": "", "id": 1}
    new = {"name": "X", "priority": "high", "action_by": "6DE",
           "percent_complete": 50, "contract_value": 15000,
           "next_action": "Submit report", "id": 1}
    changes = diff_row(old, new)
    assert "priority" in changes
    assert "action_by" in changes
    assert "percent_complete" in changes
    assert "contract_value" in changes
    assert "next_action" in changes
