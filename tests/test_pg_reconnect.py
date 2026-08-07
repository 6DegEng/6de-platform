"""Postgres adapter must survive the server dropping an idle connection.

Azure Postgres (and the gateway in front of it) closes connections that have
sat idle. The dashboard connection is cached for the life of the Streamlit
process, so the next page load used to hit a dead socket and render a raw
``psycopg.OperationalError: the connection is closed`` traceback.

These tests drive db/pg_compat.py against a fake psycopg connection, so they
run on the default sqlite backend with no Postgres server needed.
"""
from __future__ import annotations

import sqlite3

import pytest

psycopg = pytest.importorskip("psycopg")

from db import pg_compat  # noqa: E402


class _FakeInfo:
    def __init__(self, conn):
        self._conn = conn

    @property
    def status(self):
        return (
            psycopg.pq.ConnStatus.OK
            if self._conn.alive
            else psycopg.pq.ConnStatus.BAD
        )

    @property
    def transaction_status(self):
        if not self._conn.alive:
            return psycopg.pq.TransactionStatus.UNKNOWN
        return (
            psycopg.pq.TransactionStatus.INTRANS
            if self._conn.in_tx
            else psycopg.pq.TransactionStatus.IDLE
        )


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 1
        self.description = None

    def execute(self, sql, params=None):
        self._conn.run(sql)
        return self

    def executemany(self, sql, seq):
        self._conn.run(sql)
        return self

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def close(self):
        pass


class _FakeConn:
    """Minimal stand-in for psycopg.Connection.

    ``alive`` False models a server-side drop: psycopg has not closed the
    handle itself (``closed`` stays False) but libpq reports a BAD status,
    which is exactly the state behind the production traceback.
    """

    def __init__(self, server):
        self.server = server
        self.alive = True
        self.closed = False
        self.in_tx = False
        self.info = _FakeInfo(self)

    def run(self, sql):
        if not self.alive:
            raise psycopg.OperationalError("the connection is closed")
        self.server.statements.append(sql)
        if self.server.sql_error and self.server.sql_error in sql:
            raise psycopg.ProgrammingError('relation "nope" does not exist')
        head = sql.lstrip()[:6].upper()
        if head.startswith("BEGIN"):
            self.in_tx = True
        elif head.startswith(("COMMIT", "ROLLBA")):
            self.in_tx = False

    def execute(self, sql, params=None):
        self.run(sql)
        return _FakeCursor(self)

    def cursor(self):
        if not self.alive:
            raise psycopg.OperationalError("the connection is closed")
        return _FakeCursor(self)

    def close(self):
        self.closed = True
        self.alive = False


class _FakeServer:
    """Hands out connections and records every statement they ran."""

    def __init__(self):
        self.statements: list[str] = []
        self.handles: list[_FakeConn] = []
        self.sql_error: str | None = None
        self.refuse_connect = False
        self.connect_calls = 0

    def connect(self, conninfo, autocommit=False):
        self.connect_calls += 1
        if self.refuse_connect:
            raise psycopg.OperationalError("connection refused")
        conn = _FakeConn(self)
        self.handles.append(conn)
        return conn

    def drop_idle_connection(self):
        """What Azure does to a connection that has sat idle too long."""
        self.handles[-1].alive = False


@pytest.fixture()
def server(monkeypatch):
    srv = _FakeServer()
    monkeypatch.setattr(pg_compat.psycopg, "connect", srv.connect)
    return srv


@pytest.fixture()
def conn(server):
    return pg_compat.PgConnection("postgresql://x/y", "public", "/tmp/x.db")


# ---------------------------------------------------------------------------
# The production failure
# ---------------------------------------------------------------------------
def test_dropped_connection_is_reopened_transparently(server, conn):
    server.drop_idle_connection()
    server.statements.clear()

    rows = conn.execute("SELECT COUNT(*) FROM projects").fetchall()

    assert rows == []
    assert server.connect_calls == 2, "should have reconnected exactly once"
    assert any("projects" in s for s in server.statements)


def test_reconnect_replays_session_setup(server):
    """search_path is session state — a healed connection that skipped it
    would silently query the wrong schema."""
    c = pg_compat.PgConnection("postgresql://x/y", "t_abc", "/tmp/t.db")
    server.drop_idle_connection()
    server.statements.clear()

    c.execute("SELECT 1")

    assert any('SET search_path TO "t_abc"' in s for s in server.statements)
    assert any("CREATE SCHEMA IF NOT EXISTS" in s for s in server.statements)


def test_dropped_connection_error_is_a_sqlite_error(server, conn):
    """When reconnecting also fails, callers must still see a sqlite3
    exception — every ``except sqlite3.OperationalError`` in the app
    depends on that contract."""
    server.drop_idle_connection()
    server.refuse_connect = True

    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT COUNT(*) FROM projects")


def test_connect_failure_never_leaks_the_password(server):
    server.refuse_connect = True

    with pytest.raises(sqlite3.OperationalError) as excinfo:
        pg_compat.PgConnection("postgresql://u:sekret@h/db", "public", "")

    assert "sekret" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# The retry must stay narrow
# ---------------------------------------------------------------------------
def test_real_sql_error_is_raised_not_retried(server, conn):
    server.sql_error = "nope"
    server.statements.clear()

    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT * FROM nope")

    assert server.connect_calls == 1, "a live connection must not be reopened"
    assert len([s for s in server.statements if "nope" in s]) == 1


def test_no_silent_retry_inside_an_explicit_transaction(server, conn):
    """Replaying one statement of an interrupted BEGIN block on a fresh
    connection would commit partial work under autocommit."""
    conn.execute("BEGIN")
    server.drop_idle_connection()

    with pytest.raises(sqlite3.OperationalError):
        conn.execute("UPDATE projects SET status = 'active'")

    assert server.connect_calls == 1


def test_transaction_flag_clears_on_commit(server, conn):
    conn.execute("BEGIN")
    conn.execute("COMMIT")
    server.drop_idle_connection()

    conn.execute("SELECT 1")  # standalone again — safe to heal

    assert server.connect_calls == 2


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def test_commit_on_dead_connection_is_quiet(server, conn):
    conn.execute("BEGIN")
    server.drop_idle_connection()

    conn.commit()  # nothing to commit; must not raise or reconnect

    assert server.connect_calls == 1


def test_rollback_on_dead_connection_is_quiet(server, conn):
    server.drop_idle_connection()

    conn.rollback()

    assert server.connect_calls == 1


def test_closed_connection_is_not_resurrected(server, conn):
    conn.close()

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")

    assert server.connect_calls == 1


def test_executemany_also_heals(server, conn):
    server.drop_idle_connection()
    server.statements.clear()

    conn.executemany("INSERT INTO projects (name) VALUES (?)", [("a",), ("b",)])

    assert server.connect_calls == 2
    assert any("INSERT INTO projects" in s for s in server.statements)
