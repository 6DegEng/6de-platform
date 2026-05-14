"""Database layer for the 6DE Company Platform.

Phase 1 changes (2026-05-13):
- DB path moved out of OneDrive sync to %LOCALAPPDATA% by default (A1)
- WAL mode + 30s busy timeout + autocommit + check_same_thread=False (A1)
- Connection cached per Streamlit session via @st.cache_resource (A1)
- Schema migrations gated on a fingerprint stored in _meta — _ALTER_COLUMNS no
  longer runs on every page load (A1, the proximate cause of the lock cascade)
- One-time migration from the legacy OneDrive-located .db on first run
- DB_BACKEND seam: sqlite default, postgres stub raises NotImplementedError
  pointing at Phase 8 (C3)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from config import (
    AUTH_CONFIG_PATH,  # noqa: F401 — re-exported for convenience
    CALC_DB_PATH,
    DB_BACKEND,
    DB_PATH,
    LEGACY_DB_PATH,
    PLATFORM_DATABASE_URL,
    SCHEMA_PATH,
)
from modules.accounting.categorization import seed_rules_from_vba
from modules.calculator.required_checks import seed_required_checks

# ---------------------------------------------------------------------------
# Schema deltas applied at startup. Each entry: (table, column, column_type).
# Idempotent via try/except OperationalError on ALTER TABLE.
# ---------------------------------------------------------------------------
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
    ("transactions", "source", "TEXT DEFAULT 'excel_sync'"),
    ("opportunities", "source_proposal_id", "INTEGER"),
]

_PROPOSAL_STAGE_MAP = {
    "draft": "lead",
    "sent": "proposal_sent",
    "accepted": "won",
    "declined": "lost",
    "revised": "negotiating",
}

_PROPOSAL_PROBABILITY_MAP = {
    "draft": 20,
    "sent": 60,
    "accepted": 100,
    "declined": 0,
    "revised": 50,
}


# ---------------------------------------------------------------------------
# Backend dispatch
# ---------------------------------------------------------------------------
def _check_backend() -> None:
    """Raise early with a clear message if DB_BACKEND is misconfigured."""
    if DB_BACKEND == "sqlite":
        return
    if DB_BACKEND == "postgres":
        raise NotImplementedError(
            "DB_BACKEND=postgres is reserved for Phase 8 (Postgres + Render Deploy). "
            "See PLATFORM_GOAL_v1.md Phase 8 for the migration plan. "
            "For now, leave DB_BACKEND unset or set to 'sqlite'."
        )
    raise ValueError(
        f"Unknown DB_BACKEND={DB_BACKEND!r}. Expected 'sqlite' or 'postgres'."
    )


# ---------------------------------------------------------------------------
# One-time migration: OneDrive .db -> %LOCALAPPDATA% .db
# ---------------------------------------------------------------------------
def _migrate_legacy_db_if_needed() -> None:
    """Copy the OneDrive-located legacy .db to the new local-only path
    if (a) the legacy file exists, (b) the new file does not.

    Only the main .db file is copied — WAL/SHM siblings are deliberately
    skipped because (i) they may be locked by another process (Streamlit
    still running, OneDrive sync agent), (ii) SQLite recreates them on
    first WAL-mode connection. Any uncommitted WAL data is dropped, which
    is acceptable for a one-time migration of a single-user dev DB.
    """
    if DB_PATH.exists():
        return
    if not LEGACY_DB_PATH.exists():
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Use copy() not copy2() — skips metadata preservation that can choke on
    # OneDrive reparse-point attributes.
    shutil.copy(LEGACY_DB_PATH, DB_PATH)


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------
_PRAGMAS_APPLIED: set[str] = set()  # per-process guard for one-time PRAGMAs


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with locking-safe defaults.

    - timeout=30: wait up to 30 seconds for a lock instead of immediate failure
    - isolation_level=None: autocommit mode; explicit BEGIN/COMMIT optional
    - check_same_thread=False: allows Streamlit's thread-pool to share the conn
    - WAL journal_mode + NORMAL synchronous: cooperative concurrent reads/writes
    """
    _check_backend()
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(
        path,
        timeout=30,
        isolation_level=None,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row

    # PRAGMA WAL + synchronous=NORMAL are file-level and persist across opens,
    # so we only need to set them once per DB file per process.
    if path not in _PRAGMAS_APPLIED:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _PRAGMAS_APPLIED.add(path)
    else:
        conn.execute("PRAGMA foreign_keys=ON")

    return conn


def get_calc_connection() -> sqlite3.Connection | None:
    """Open the calc engine's common.db read-only. Returns None if unreachable."""
    if not CALC_DB_PATH.exists():
        return None
    conn = sqlite3.connect(
        f"file:{CALC_DB_PATH}?mode=ro",
        uri=True,
        timeout=10,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Schema fingerprint — skip _ALTER_COLUMNS when nothing has changed
# ---------------------------------------------------------------------------
def _ensure_meta_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _meta ("
        "  key TEXT PRIMARY KEY, "
        "  value TEXT NOT NULL"
        ")"
    )


def _current_schema_fingerprint() -> str:
    """Hash the schema file + the _ALTER_COLUMNS definition. Any change to
    either invalidates the cached fingerprint and forces a migration pass."""
    h = hashlib.sha256()
    if SCHEMA_PATH.exists():
        h.update(SCHEMA_PATH.read_bytes())
    h.update(json.dumps(_ALTER_COLUMNS, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def _get_stored_fingerprint(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM _meta WHERE key = 'schema_fingerprint'"
    ).fetchone()
    return row["value"] if row else None


def _store_fingerprint(conn: sqlite3.Connection, fingerprint: str) -> None:
    conn.execute(
        "INSERT INTO _meta (key, value) VALUES ('schema_fingerprint', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (fingerprint,),
    )


def _apply_alter_columns(conn: sqlite3.Connection) -> None:
    for table, col, col_type in _ALTER_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply the schema.sql DDL + the ALTER COLUMN list. Called only when
    the stored fingerprint doesn't match the current code state."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _ensure_meta_table(conn)
    _apply_alter_columns(conn)
    _store_fingerprint(conn, _current_schema_fingerprint())


# ---------------------------------------------------------------------------
# Shared helpers used by importers, CRUD modules, and seeds
# ---------------------------------------------------------------------------
def log_activity(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    action: str,
    details: dict | None = None,
) -> None:
    """Insert an activity_log row. Importers and CRUD layers call this."""
    conn.execute(
        "INSERT INTO activity_log (entity_type, entity_id, action, details) "
        "VALUES (?, ?, ?, ?)",
        (entity_type, entity_id, action, json.dumps(details or {})),
    )


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def seed_juan_as_employee(conn: sqlite3.Connection) -> None:
    """Seed Juan as employees.id=1 if the table is empty. Idempotent. B7/I2."""
    count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    if count > 0:
        return
    conn.execute(
        "INSERT INTO employees (name, email, role, is_active, hire_date, notes) "
        "VALUES (?, ?, ?, 1, ?, ?)",
        (
            "Juan C. Castillo",
            "juanccastillo93@outlook.com",
            "principal",
            "2024-01-01",
            "Auto-seeded by ensure_db() — see B7/I2 in SESSION34_BUG_BACKLOG.md",
        ),
    )
    log_activity(
        conn,
        entity_type="employee",
        entity_id=1,
        action="seeded",
        details={"source": "db.seed_juan_as_employee", "reason": "B7/I2 fix"},
    )


def bridge_proposals_to_opportunities(conn: sqlite3.Connection) -> int:
    """For every proposal without a linked opportunity, create one. Idempotent.
    Closes B5/B11/I3 via the bridge approach. See PLATFORM_GOAL_v1.md Phase 5
    for the eventual schema collapse."""
    rows = conn.execute(
        """
        SELECT
            p.id              AS proposal_id,
            p.project_id      AS project_id,
            p.proposal_number AS proposal_number,
            p.fee_amount      AS fee_amount,
            p.status          AS status,
            p.scope_text      AS scope_text,
            p.sent_date       AS sent_date,
            p.created_at      AS created_at,
            pr.name           AS project_name,
            pr.client_id      AS client_id,
            pr.service_line   AS project_service_line,
            cl.service_type   AS client_service_type
        FROM proposals p
        LEFT JOIN projects pr ON pr.id = p.project_id
        LEFT JOIN clients  cl ON cl.id = pr.client_id
        WHERE NOT EXISTS (
            SELECT 1 FROM opportunities o WHERE o.source_proposal_id = p.id
        )
        """
    ).fetchall()

    created = 0
    for r in rows:
        prop_status = (r["status"] or "draft").lower()
        stage = _PROPOSAL_STAGE_MAP.get(prop_status, "lead")
        probability = _PROPOSAL_PROBABILITY_MAP.get(prop_status, 50)
        service_line = r["project_service_line"] or r["client_service_type"] or "other"
        if service_line not in (
            "structural", "civil", "sirs", "forensics", "pools",
            "recertification", "threshold", "government", "other",
        ):
            service_line = "other"
        name = r["project_name"] or r["proposal_number"] or f"Proposal {r['proposal_id']}"
        cur = conn.execute(
            """
            INSERT INTO opportunities (
                client_id, project_id, name, service_line,
                stage, estimated_value, probability,
                source, close_date, notes,
                source_proposal_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r["client_id"],
                r["project_id"],
                name,
                service_line,
                stage,
                r["fee_amount"] or 0,
                probability,
                "referral",
                r["sent_date"],
                f"Auto-bridged from proposal {r['proposal_number']} "
                f"({prop_status}). See B5/I3 fix.",
                r["proposal_id"],
                r["created_at"] or _now_iso(),
                _now_iso(),
            ),
        )
        log_activity(
            conn,
            entity_type="opportunity",
            entity_id=cur.lastrowid,
            action="bridged_from_proposal",
            details={
                "source_proposal_id": r["proposal_id"],
                "proposal_status": prop_status,
                "mapped_stage": stage,
            },
        )
        created += 1
    return created


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def init_db(db_path: Path | str | None = None) -> None:
    """Full migration + seed pass. Called on fresh installs and for manual ops."""
    _check_backend()
    _migrate_legacy_db_if_needed()
    conn = get_connection(db_path)
    _run_migrations(conn)
    seed_rules_from_vba(conn)
    seed_required_checks(conn)
    seed_juan_as_employee(conn)
    bridge_proposals_to_opportunities(conn)
    conn.close()


def _ensure_db_impl() -> sqlite3.Connection:
    """Real implementation. Wrapped by ensure_db() below; the wrapper adds
    Streamlit per-session caching when Streamlit is available."""
    _check_backend()
    _migrate_legacy_db_if_needed()

    new_db = not DB_PATH.exists()
    conn = get_connection()

    _ensure_meta_table(conn)
    current_fp = _current_schema_fingerprint()
    stored_fp = _get_stored_fingerprint(conn)

    if new_db or stored_fp != current_fp:
        _run_migrations(conn)
        seed_rules_from_vba(conn)
        seed_required_checks(conn)

    # Seeds are self-idempotent — cheap to call every time.
    seed_juan_as_employee(conn)
    bridge_proposals_to_opportunities(conn)
    return conn


# When Streamlit is importable, cache the connection per session so all 10
# pages reuse the same handle across reruns. When called from importers or
# one-shot scripts (no Streamlit context), the decorator passes through.
try:
    import streamlit as _st
    ensure_db = _st.cache_resource(show_spinner=False)(_ensure_db_impl)
except ImportError:
    ensure_db = _ensure_db_impl  # type: ignore[assignment]


# Back-compat alias for any code that imports the new name explicitly.
get_session_connection = ensure_db
