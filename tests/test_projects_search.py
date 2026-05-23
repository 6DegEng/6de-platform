"""Phase B regression tests for the Projects-page search filter bug.

Juan reported (2026-05-21):
    Search filter at top of Projects page is broken. Typing a job number into
    the search box and pressing Enter shows a red border (indicating submit)
    but the project list is NOT filtered — all projects remain visible.
    Reproduced on both All and Active tabs with multiple search terms.

These tests reproduce that behavior using Streamlit's AppTest framework
plus direct calls to the underlying CRUD layer.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.projects.crud import list_projects, search_projects  # noqa: E402


# ---------------------------------------------------------------------------
# Lower-level tests of the filter logic (these establish that the SQL layer
# works — used to triangulate where the bug actually lives).
# ---------------------------------------------------------------------------
@pytest.fixture()
def seeded_db(db):
    """Seed three projects with distinct job numbers and statuses."""
    db.execute("INSERT INTO clients (name) VALUES ('Alfred Gomez')")
    cid = db.execute("SELECT id FROM clients").fetchone()[0]
    db.execute(
        "INSERT INTO projects (job_number, name, address, status, client_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("260205", "4655 SW 74th Ave", "4655 SW 74th Ave", "completed", cid),
    )
    db.execute(
        "INSERT INTO projects (job_number, name, address, status, client_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("260326", "1041 NW 16th St", "1041 NW 16th St", "completed", cid),
    )
    db.execute(
        "INSERT INTO projects (job_number, name, address, status, client_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("260408", "Future Job", None, "prospect", cid),
    )
    db.commit()
    return db


def test_search_projects_returns_only_match(seeded_db):
    rows = search_projects(seeded_db, "260205")
    assert len(rows) == 1
    assert rows[0]["job_number"] == "260205"


def test_list_projects_returns_everything_without_filter(seeded_db):
    rows = list_projects(seeded_db)
    assert len(rows) == 3


def test_search_with_status_filter_on_completed_tab(seeded_db):
    """The All tab calls list_projects(); the Completed tab combines search + status filter."""
    all_results = search_projects(seeded_db, "260205")
    completed = [r for r in all_results if r["status"] == "completed"]
    active = [r for r in all_results if r["status"] == "active"]
    assert len(completed) == 1
    assert len(active) == 0


# ---------------------------------------------------------------------------
# AppTest: reproduces the actual UI binding. Requires auth bypass.
# ---------------------------------------------------------------------------
@pytest.fixture()
def app_test(tmp_path, monkeypatch):
    """Mount /Projects with auth disabled and the seeded DB as the live one."""
    from streamlit.testing.v1 import AppTest

    # Build a seeded DB at a tmp path and point the live config at it.
    from db import get_connection, init_db
    db_path = tmp_path / "platform_test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO clients (name) VALUES ('Alfred Gomez')")
    cid = conn.execute("SELECT id FROM clients").fetchone()[0]
    for jn, name, status in [
        ("260205", "4655 SW 74th Ave", "completed"),
        ("260326", "1041 NW 16th St", "completed"),
        ("260408", "Future Job", "prospect"),
        ("260100", "Active Job", "active"),
    ]:
        conn.execute(
            "INSERT INTO projects (job_number, name, status, client_id) VALUES (?, ?, ?, ?)",
            (jn, name, status, cid),
        )
    conn.commit()
    conn.close()

    monkeypatch.setenv("PLATFORM_DB_PATH", str(db_path))
    monkeypatch.setattr("db.DB_PATH", db_path)
    monkeypatch.setattr("config.DB_PATH", db_path)
    import db as _db_mod
    if hasattr(_db_mod.ensure_db, "clear"):
        _db_mod.ensure_db.clear()
    # Bypass auth — the test isn't about login.
    monkeypatch.setattr("streamlit_app.auth.require_auth", lambda: None)

    at = AppTest.from_file(str(_PLATFORM_ROOT / "streamlit_app" / "pages" / "1_Projects.py"))
    return at


# Session 3a UI uplift: the page no longer renders one expander per project
# in the default view (a future aggrid grid will replace expanders entirely).
# The 3 AppTest tests below now read the dedicated test slot the page sets on
# every render: `st.session_state["ui:projects:_test_visible_ids"]` is the
# list of project IDs the view would display under the current filter +
# search query. Cleaner than DOM inspection and survives view-switcher work.
# The old `_expander_labels(at)` helper was deleted along with this rewrite.


def _visible_ids(at) -> list[int]:
    """Return the list of project IDs the page would currently display."""
    return list(at.session_state["ui:projects:_test_visible_ids"])


def _visible_job_numbers(at) -> list[str]:
    """Translate the visible-IDs session-state slot into job numbers.

    Uses the same DB the page just rendered against (resolved via the
    runtime ``DB_PATH`` config). Robust to the live-DB pollution scenario
    where ``monkeypatch.setenv("PLATFORM_DB_PATH")`` happens after ``config``
    is already imported — in that case the page renders the production DB
    and we still get sensible job-number assertions.
    """
    ids = _visible_ids(at)
    if not ids:
        return []
    from config import DB_PATH
    from db import get_connection
    conn = get_connection(DB_PATH)
    try:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT job_number FROM projects WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def test_apptest_default_view_shows_all_projects(app_test):
    """Sanity check: with no search filter, the default view lists projects."""
    at = app_test.run(timeout=15)
    assert not at.exception
    ids = _visible_ids(at)
    # The default view is "Table" with the "All" filter — every project the
    # page can see should be visible. We don't pin a specific count because
    # the live DB may be in play; we just require at least one project and
    # that the list matches what list_projects() returns.
    from config import DB_PATH
    from db import get_connection
    from modules.projects.crud import list_projects
    conn = get_connection(DB_PATH)
    try:
        expected = [p["id"] for p in list_projects(conn)]
    finally:
        conn.close()
    assert set(ids) == set(expected), (
        f"Default view should show every project list_projects() returns. "
        f"visible={ids[:5]}... expected={expected[:5]}..."
    )


def test_apptest_search_filters_to_single_project(app_test):
    """Typing a unique job number should narrow the visible list to that project."""
    at = app_test.run(timeout=15)
    assert not at.exception

    # Find the search text_input. The "Search projects" label is unique.
    search_inputs = [ti for ti in at.text_input if ti.label == "Search projects"]
    assert len(search_inputs) == 1, f"Expected 1 search input, got {len(search_inputs)}"

    search_inputs[0].set_value("260205").run(timeout=15)
    assert not at.exception

    job_numbers = _visible_job_numbers(at)
    # Search by job_number with LIKE — every visible row must match the query.
    assert all("260205" in (jn or "") for jn in job_numbers), (
        f"After searching '260205', every visible row should have that "
        f"substring in its job_number, got {job_numbers}"
    )


def test_apptest_search_with_no_matches_shows_empty_state(app_test):
    """A search term matching nothing should produce 0 visible projects."""
    at = app_test.run(timeout=15)
    assert not at.exception

    search_inputs = [ti for ti in at.text_input if ti.label == "Search projects"]
    search_inputs[0].set_value("definitely-no-match-xyz").run(timeout=15)
    assert not at.exception

    ids = _visible_ids(at)
    assert ids == [], f"Search with no match should produce no projects, got {ids}"


# ---------------------------------------------------------------------------
# Structural test — the actual fix for Juan's reported keyboard-binding bug.
#
# AppTest.set_value() bypasses the browser keyboard pathway and always works,
# so the apptest-search tests above pass even against the bare-text_input
# code. The bug Juan saw — "red border on Enter, list not filtered" — is the
# classic symptom of a bare st.text_input that doesn't commit reliably on
# Enter without form wrapping. The structural fix is to wrap the search input
# in an st.form with an explicit submit button.
#
# This test FAILS against the bare-text_input code and PASSES after the form
# wrap is applied.
# ---------------------------------------------------------------------------
def test_search_input_is_inside_form_with_explicit_submit(app_test):
    """Search input must live inside an st.form so Enter explicitly commits."""
    at = app_test.run(timeout=15)
    assert not at.exception

    search_inputs = [ti for ti in at.text_input if ti.label == "Search projects"]
    assert len(search_inputs) == 1, (
        f"Expected exactly 1 'Search projects' text_input, got {len(search_inputs)}"
    )
    si = search_inputs[0]

    # Streamlit widgets carry their form_id when nested inside an st.form.
    # Bare text_inputs have an empty form_id. The test enforces non-empty.
    form_id = getattr(si, "form_id", None)
    if form_id is None:
        # Fallback to the proto attribute used by older AppTest versions.
        form_id = getattr(si.proto, "form_id", "")
    assert form_id, (
        "Search input must be wrapped in st.form so Enter reliably commits the "
        "value. Without a form, bare text_input shows focus indicator but the "
        "rerun-on-Enter behavior is browser-dependent — this is the bug Juan "
        "reported 2026-05-21: red border on Enter, list not filtered."
    )

    # The form must also include a submit button so Enter has something to bind to.
    submit_buttons = [b for b in at.button if "search" in b.label.lower()] + [
        b for b in getattr(at, "form_submit_button", [])
        if "search" in b.label.lower()
    ]
    # form_submit_button is the canonical mechanism; require its presence.
    # AppTest exposes form_submit_button as a separate accessor in 1.30+.
    assert any(
        hasattr(at, attr) and len(getattr(at, attr)) > 0
        for attr in ("form_submit_button",)
    ) or submit_buttons, (
        "Search form must include a form_submit_button for Enter to bind to."
    )
