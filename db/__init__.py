from __future__ import annotations

import sqlite3
from pathlib import Path

from config import CALC_DB_PATH, DB_PATH, SCHEMA_PATH

_ALTER_COLUMNS = [
    ("clients", "ytd_revenue", "REAL DEFAULT 0"),
    ("clients", "service_type", "TEXT"),
    ("projects", "service_line", "TEXT"),
    ("projects", "budget_amount", "REAL"),
    ("projects", "contract_value", "REAL DEFAULT 0"),
    ("projects", "amount_paid", "REAL DEFAULT 0"),
    ("projects", "outstanding_balance", "REAL DEFAULT 0"),
    ("projects", "cogs", "REAL DEFAULT 0"),
    ("projects", "profit", "REAL DEFAULT 0"),
    ("projects", "percent_complete", "REAL DEFAULT 0"),
    ("projects", "priority", "TEXT"),
    ("projects", "action_by", "TEXT"),
    ("projects", "next_action", "TEXT"),
    ("projects", "lead_source", "TEXT"),
    ("projects", "contact_name", "TEXT"),
    ("projects", "contact_phone", "TEXT"),
]


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_calc_connection() -> sqlite3.Connection | None:
    if not CALC_DB_PATH.exists():
        return None
    conn = sqlite3.connect(f"file:{CALC_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _apply_alter_columns(conn: sqlite3.Connection) -> None:
    for table, col, col_type in _ALTER_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass


def init_db(db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _apply_alter_columns(conn)
    conn.close()


def ensure_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        init_db()
    conn = get_connection()
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _apply_alter_columns(conn)
    return conn
