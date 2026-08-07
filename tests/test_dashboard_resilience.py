"""The dashboard must cache its reads and fail readably.

Covers three changes made after the live 'connection is closed' outage:
- get_dashboard_data() runs ~20 queries and Streamlit re-runs the script on
  every interaction, so Home.py caches the payload. Anything st.cache_data
  stores gets pickled — a payload that isn't picklable breaks the page.
- A database failure renders a readable panel instead of a raw traceback.
"""
from __future__ import annotations

import pickle
import sqlite3
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.dashboard.queries import get_dashboard_data  # noqa: E402
from modules.invoicing.crud import get_ar_aging_report  # noqa: E402
from streamlit_app.components.db_status import (  # noqa: E402
    DB_ERRORS,
    friendly_reason,
)


# ---------------------------------------------------------------------------
# Cacheability — st.cache_data pickles whatever it stores
# ---------------------------------------------------------------------------
def test_dashboard_payload_survives_a_pickle_round_trip(db):
    """Home.py caches this dict; an unpicklable value there breaks the page."""
    data = get_dashboard_data(db)

    restored = pickle.loads(pickle.dumps(data))

    assert restored.keys() == data.keys()
    assert restored["total_projects"] == data["total_projects"]


def test_ar_aging_rows_are_cacheable_once_converted_to_dicts(db):
    """Raw sqlite3.Row objects cannot be pickled, so the dashboard converts
    the AR report to plain dicts before caching it."""
    converted = [dict(r) for r in get_ar_aging_report(db)]

    assert pickle.loads(pickle.dumps(converted)) == converted


# ---------------------------------------------------------------------------
# Readable failures
# ---------------------------------------------------------------------------
def test_db_errors_covers_what_the_adapter_raises():
    """pg_compat re-raises every psycopg failure as a sqlite3 exception, so
    catching sqlite3.Error catches database trouble on both backends."""
    assert issubclass(sqlite3.OperationalError, DB_ERRORS)
    assert issubclass(sqlite3.ProgrammingError, DB_ERRORS)
    assert issubclass(sqlite3.IntegrityError, DB_ERRORS)


@pytest.mark.parametrize(
    "message, expected_fragment",
    [
        ("the connection is closed", "dropped"),
        ("connection refused", "didn't answer"),
        ('relation "projects" does not exist', "migration"),
        ("password authentication failed for user", "credentials"),
        ("something nobody predicted", "couldn't read"),
    ],
)
def test_friendly_reason_is_plain_english(message, expected_fragment):
    reason = friendly_reason(sqlite3.OperationalError(message))

    assert expected_fragment in reason
    # No Python internals leaking into the user-facing sentence.
    assert "Error" not in reason and "psycopg" not in reason


# ---------------------------------------------------------------------------
# The page still renders end to end
# ---------------------------------------------------------------------------
@pytest.fixture()
def home_page(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from db import get_connection, init_db

    db_path = tmp_path / "platform_home.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO clients (name) VALUES ('Dashboard Client')")
    cid = conn.execute("SELECT id FROM clients").fetchone()[0]
    conn.execute(
        "INSERT INTO projects (job_number, name, status, client_id, start_date) "
        "VALUES ('260910', 'Dashboard Project', 'active', ?, '2026-04-01')",
        (cid,),
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

    return AppTest.from_file(str(_PLATFORM_ROOT / "streamlit_app" / "Home.py"))


def test_dashboard_renders_and_offers_a_refresh(home_page):
    at = home_page.run(timeout=60)

    assert not at.exception, f"Dashboard raised: {at.exception}"
    labels = [b.label for b in at.button]
    assert "Refresh" in labels, f"no Refresh control; buttons were {labels}"


def test_refresh_button_reruns_cleanly(home_page):
    at = home_page.run(timeout=60)
    refresh = [b for b in at.button if b.label == "Refresh"][0]

    at = refresh.click().run(timeout=60)

    assert not at.exception, f"Refresh raised: {at.exception}"
