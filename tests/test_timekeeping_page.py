"""AppTest smoke tests for the Timekeeping page — internal-mode toggle and
the weekly export button must render without exceptions."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))


@pytest.fixture()
def app_test(tmp_path, monkeypatch):
    """Mount /Timekeeping with auth disabled and a seeded DB."""
    from streamlit.testing.v1 import AppTest

    from db import get_connection, init_db
    from modules.timekeeping.crud import create_time_entry

    db_path = tmp_path / "platform_test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    pid = conn.execute(
        "INSERT INTO projects (job_number, name) VALUES ('260304', 'Buena Vista')"
    ).lastrowid
    create_time_entry(
        conn, employee_id=1, project_id=pid, entry_date="2026-06-29",
        hours=5, role="professional_engineer", description="Recert rework",
    )
    create_time_entry(
        conn, employee_id=1, internal_code="004001", entry_date="2026-06-30",
        hours=2, role="principal", description="Platform dev",
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("PLATFORM_DB_PATH", str(db_path))
    monkeypatch.setattr("db.DB_PATH", db_path)
    monkeypatch.setattr("config.DB_PATH", db_path)
    import db as _db_mod
    if hasattr(_db_mod.ensure_db, "clear"):
        _db_mod.ensure_db.clear()
    monkeypatch.setattr("streamlit_app.auth.require_auth", lambda: None)

    return AppTest.from_file(
        str(_PLATFORM_ROOT / "streamlit_app" / "pages" / "5_Timekeeping.py")
    )


def test_page_renders_with_internal_entries(app_test):
    at = app_test.run(timeout=30)
    assert not at.exception
    # Both the project row and the internal row render in Recent Time Entries
    body = " ".join(str(m.value) for m in at.markdown)
    assert "Buena Vista" in body
    assert "AI / Automation Development" in body


def test_internal_toggle_switches_to_code_selectbox(app_test):
    at = app_test.run(timeout=30)
    toggles = [t for t in at.toggle if t.key == "te_internal_mode"]
    assert toggles, "Internal (non-billable) toggle missing"
    toggles[0].set_value(True).run(timeout=30)
    assert not at.exception
    keys = {s.key for s in at.selectbox}
    assert "te_internal_code" in keys
    assert "te_project" not in keys
