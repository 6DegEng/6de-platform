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
    database doesn't accumulate them.

    Safety: the suite creates and drops schemas on whatever database
    PLATFORM_DATABASE_URL points at, so refuse to run against a non-local
    server (e.g. a production URL still exported in the shell) unless
    explicitly allowed via PLATFORM_PG_TEST_ALLOW_REMOTE=1."""
    import os

    import config

    if config.DB_BACKEND == "postgres":
        import psycopg
        from psycopg import sql

        host = psycopg.conninfo.conninfo_to_dict(
            config.PLATFORM_DATABASE_URL
        ).get("host", "")
        local = host in ("localhost", "127.0.0.1", "::1")
        if not local and os.environ.get("PLATFORM_PG_TEST_ALLOW_REMOTE") != "1":
            pytest.exit(
                f"Refusing to run the test suite against non-local Postgres "
                f"host {host!r} — it creates and drops schemas. Set "
                f"PLATFORM_PG_TEST_ALLOW_REMOTE=1 only if you are sure.",
                returncode=2,
            )

        with psycopg.connect(config.PLATFORM_DATABASE_URL, autocommit=True) as pg:
            rows = pg.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 't\\_%'"
            ).fetchall()
            for (name,) in rows:
                pg.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name))
                )
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
