"""Shared fixtures for platform smoke tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from db import get_connection, init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _drop_stale_pg_test_schemas():
    """On the postgres backend each tmp db_path maps to a throwaway t_<hash>
    schema. Drop leftovers from previous runs once per session so the dev
    database doesn't accumulate them."""
    import config

    if config.DB_BACKEND == "postgres":
        import psycopg

        with psycopg.connect(config.PLATFORM_DATABASE_URL, autocommit=True) as pg:
            rows = pg.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 't\\_%'"
            ).fetchall()
            for (name,) in rows:
                pg.execute(f'DROP SCHEMA "{name}" CASCADE')
    yield


@pytest.fixture()
def db(tmp_path):
    """Yield a fresh in-memory-like DB initialised from schema.sql."""
    db_path = tmp_path / "test_platform.db"
    init_db(db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Workaround: Streamlit AppTest ButtonGroup.value bug (streamlit 1.47.x)
#
# segmented_control with selection_mode="single" stores a scalar string in
# session_state, but ButtonGroup.indices iterates self.value expecting a
# list. Iterating a bare string yields individual characters → ValueError.
# Patch the value property to wrap scalars in a list.
# ---------------------------------------------------------------------------
def _patch_button_group_value():
    try:
        from streamlit.testing.v1.element_tree import ButtonGroup
    except ImportError:
        return

    _original_value = ButtonGroup.value.fget  # type: ignore[attr-defined]

    def _safe_value(self):
        val = _original_value(self)
        if isinstance(val, str):
            return [val]
        return val

    ButtonGroup.value = property(_safe_value)  # type: ignore[assignment]


_patch_button_group_value()
