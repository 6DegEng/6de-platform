"""Every page must open the database through the error boundary.

A page that calls ensure_db() bare renders Streamlit's default traceback when
the database is unreachable — Python internals and server paths shown to
whoever is logged in. That is what the live 'connection is closed' outage
looked like on all 10 pages.

This is a structural test on purpose: it fails when a NEW page is added with
a bare call, which is exactly when the mistake gets reintroduced.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

# 99_Health.py is exempt by design: a health check must REPORT a database
# failure, not replace itself with a "couldn't load this page" panel. It
# catches its own errors and renders them as status. Any other exemption
# needs the same kind of justification written down here.
_EXEMPT = {"99_Health.py"}

_PAGES = sorted(
    p for p in (_PLATFORM_ROOT / "streamlit_app" / "pages").glob("[0-9]*.py")
    if p.name not in _EXEMPT
)
_ENTRY_POINTS = _PAGES + [_PLATFORM_ROOT / "streamlit_app" / "Home.py"]

# `conn = ensure_db()` at module level, i.e. outside any try/except.
_BARE_CALL = re.compile(r"^conn = ensure_db\(\)", re.MULTILINE)


def test_pages_were_actually_found():
    """Guard against the glob silently matching nothing and passing."""
    assert len(_PAGES) >= 9, f"only found {len(_PAGES)} pages"


@pytest.mark.parametrize("page", _ENTRY_POINTS, ids=lambda p: p.stem)
def test_page_opens_the_db_through_the_boundary(page):
    src = page.read_text(encoding="utf-8")

    assert not _BARE_CALL.search(src), (
        f"{page.name} calls ensure_db() bare — a database outage would render "
        f"a raw traceback. Use connect_or_explain('<Page>') instead."
    )
    assert "connect_or_explain" in src or "render_db_error" in src, (
        f"{page.name} has no database error boundary."
    )


def test_health_page_reports_ok_against_a_live_db(db, tmp_path, monkeypatch):
    """The point of the page: 'healthy' means a real query succeeded."""
    from streamlit.testing.v1 import AppTest

    import db as _db_mod
    monkeypatch.setattr(_db_mod, "ensure_db", lambda: db)

    at = AppTest.from_file(
        str(_PLATFORM_ROOT / "streamlit_app" / "pages" / "99_Health.py")
    ).run(timeout=60)

    assert not at.exception, f"Health page raised: {at.exception}"
    body = " ".join(c.value for c in at.code)
    assert "'ok'" in body, f"expected ok status, got: {body}"


def test_health_page_reports_a_dead_db_instead_of_crashing(monkeypatch):
    """A health check that raises tells a monitor nothing useful."""
    from streamlit.testing.v1 import AppTest

    import db as _db_mod

    def _boom():
        raise sqlite3.OperationalError("the connection is closed")

    monkeypatch.setattr(_db_mod, "ensure_db", _boom)

    at = AppTest.from_file(
        str(_PLATFORM_ROOT / "streamlit_app" / "pages" / "99_Health.py")
    ).run(timeout=60)

    assert not at.exception, "health page must never raise — it must report"
    body = " ".join(c.value for c in at.code)
    assert "'error'" in body
    assert "connection is closed" in body


def test_connect_or_explain_stops_the_page_on_failure(monkeypatch):
    """It must never hand back a dead connection — st.stop() ends the run."""
    import streamlit as st

    from streamlit_app.components import db_status

    calls = {}

    def _boom():
        raise sqlite3.OperationalError("the connection is closed")

    def _fake_stop():
        calls["stopped"] = True
        raise RuntimeError("st.stop() called")

    monkeypatch.setattr("db.ensure_db", _boom)
    monkeypatch.setattr(db_status, "render_db_error",
                        lambda exc, what: calls.setdefault("rendered", what))
    monkeypatch.setattr(st, "stop", _fake_stop)

    with pytest.raises(RuntimeError, match="st.stop"):
        db_status.connect_or_explain("Projects")

    assert calls["rendered"] == "Projects"
    assert calls["stopped"] is True
