"""Tests for internal (non-billable) time entries, the internal_codes
migration, and resource_calendars capacity in the utilization report."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

import config  # noqa: E402
import db as dbmod  # noqa: E402
from modules.timekeeping.crud import (  # noqa: E402
    create_time_entry,
    get_utilization_report,
    get_weekly_timesheet,
    list_internal_codes,
    list_time_entries,
)


def _mk_project(conn, job="260304", name="Buena Vista"):
    cur = conn.execute(
        "INSERT INTO projects (job_number, name) VALUES (?, ?)", (job, name)
    )
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Migration / seeds
# ---------------------------------------------------------------------------
def test_internal_codes_seeded(db):
    rows = db.execute(
        "SELECT code, category, description FROM internal_codes ORDER BY code"
    ).fetchall()
    assert len(rows) == 18
    by_code = {r["code"]: r for r in rows}
    assert by_code["001001"]["category"] == "Admin"
    assert "Accounting" in by_code["001001"]["description"]
    assert by_code["002002"]["category"] == "Business Dev"
    assert by_code["003002"]["description"].startswith("HGDW")
    assert by_code["004003"]["category"] == "Technology"


def test_resource_calendar_seeded_for_existing_employees(db):
    # init_db seeds Juan as employee 1 and a default 40h calendar row.
    row = db.execute(
        "SELECT hours_per_week, effective_date FROM resource_calendars "
        "WHERE employee_id = 1"
    ).fetchone()
    assert row is not None
    assert float(row["hours_per_week"]) == 40.0
    # Seeding is idempotent — re-running adds nothing.
    dbmod.seed_resource_calendars(db)
    n = db.execute(
        "SELECT COUNT(*) FROM resource_calendars WHERE employee_id = 1"
    ).fetchone()[0]
    assert n == 1


def test_check_rejects_both_and_neither(db):
    pid = _mk_project(db)
    base = (
        "INSERT INTO time_entries "
        "(employee_id, project_id, internal_code, entry_date, hours, role, rate) "
        "VALUES (1, ?, ?, '2026-06-29', 1.0, 'principal', 315)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(base, (pid, "001001"))  # both set
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(base, (None, None))  # neither set
    # exactly one of each is fine
    db.execute(base, (pid, None))
    db.execute(base, (None, "001001"))


def test_sqlite_upgrade_rebuilds_time_entries(tmp_path):
    """Simulate a pre-migration DB and check the rebuild preserves rows."""
    if config.DB_BACKEND != "sqlite":
        pytest.skip("sqlite table-rebuild path")
    db_path = tmp_path / "upgrade.db"
    dbmod.init_db(db_path)
    conn = dbmod.get_connection(db_path)
    pid = _mk_project(conn)

    # Downgrade time_entries to the old shape (project_id NOT NULL, no
    # internal_code) and insert a legacy row.
    conn.execute("DROP TABLE time_entries")
    conn.execute(
        "CREATE TABLE time_entries ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " employee_id INTEGER NOT NULL REFERENCES employees(id),"
        " project_id INTEGER NOT NULL REFERENCES projects(id),"
        " entry_date TEXT NOT NULL,"
        " hours REAL NOT NULL CHECK (hours > 0),"
        " role TEXT NOT NULL,"
        " rate REAL NOT NULL,"
        " multiplier REAL NOT NULL DEFAULT 1.0,"
        " billable INTEGER NOT NULL DEFAULT 1,"
        " description TEXT,"
        " invoice_id INTEGER REFERENCES invoices(id),"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "INSERT INTO time_entries (employee_id, project_id, entry_date, hours, "
        "role, rate) VALUES (1, ?, '2026-06-29', 2.5, 'principal', 315)",
        (pid,),
    )

    dbmod._migrate_time_entries_internal(conn)

    # Legacy row preserved
    row = conn.execute("SELECT * FROM time_entries").fetchone()
    assert row["project_id"] == pid
    assert float(row["hours"]) == 2.5
    # New shape works: internal-only insert OK, both/neither rejected
    conn.execute(
        "INSERT INTO time_entries (employee_id, internal_code, entry_date, "
        "hours, role, rate) VALUES (1, '004001', '2026-06-30', 1, 'principal', 315)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO time_entries (employee_id, entry_date, hours, role, "
            "rate) VALUES (1, '2026-06-30', 1, 'principal', 315)"
        )
    conn.close()


def test_postgres_upgrade_alters_time_entries(db):
    """Simulate a pre-migration Postgres table and run the ALTER path."""
    if config.DB_BACKEND != "postgres":
        pytest.skip("postgres ALTER path")
    db.execute(
        "ALTER TABLE time_entries "
        "DROP CONSTRAINT time_entries_project_xor_internal"
    )
    # CASCADE also drops v_weekly_timesheet, which references the column;
    # the production migration never drops columns, this is test-only setup.
    db.execute("ALTER TABLE time_entries DROP COLUMN internal_code CASCADE")
    db.execute("ALTER TABLE time_entries ALTER COLUMN project_id SET NOT NULL")

    dbmod._migrate_time_entries_internal(db)

    db.execute(
        "INSERT INTO time_entries (employee_id, internal_code, entry_date, "
        "hours, role, rate) VALUES (1, '004001', '2026-06-30', 1, 'principal', 315)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO time_entries (employee_id, entry_date, hours, role, "
            "rate) VALUES (1, '2026-06-30', 1, 'principal', 315)"
        )
    # Idempotent — a second pass is a no-op.
    dbmod._migrate_time_entries_internal(db)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def test_create_internal_entry_forces_nonbillable(db):
    entry_id = create_time_entry(
        db, employee_id=1, internal_code="001002",
        entry_date="2026-06-30", hours=0.5, role="admin",
        billable=1,  # deliberately wrong — must be forced to 0
    )
    row = db.execute(
        "SELECT * FROM time_entries WHERE id = ?", (entry_id,)
    ).fetchone()
    assert row["internal_code"] == "001002"
    assert row["project_id"] is None
    assert row["billable"] == 0
    assert float(row["rate"]) == 65.0  # admin rate auto-snapshotted


def test_create_time_entry_xor_validation(db):
    pid = _mk_project(db)
    with pytest.raises(ValueError):
        create_time_entry(
            db, employee_id=1, project_id=pid, internal_code="001001",
            entry_date="2026-06-30", hours=1, role="principal",
        )
    with pytest.raises(ValueError):
        create_time_entry(
            db, employee_id=1,
            entry_date="2026-06-30", hours=1, role="principal",
        )
    with pytest.raises(ValueError):
        create_time_entry(
            db, employee_id=1, internal_code="999999",
            entry_date="2026-06-30", hours=1, role="principal",
        )


def test_create_time_entry_rejects_inactive_code(db):
    db.execute("UPDATE internal_codes SET is_active = 0 WHERE code = '003001'")
    with pytest.raises(ValueError):
        create_time_entry(
            db, employee_id=1, internal_code="003001",
            entry_date="2026-06-30", hours=1, role="principal",
        )


def test_list_and_weekly_include_internal_rows(db):
    pid = _mk_project(db)
    create_time_entry(
        db, employee_id=1, project_id=pid,
        entry_date="2026-06-29", hours=5, role="professional_engineer",
        description="Recert rework",
    )
    create_time_entry(
        db, employee_id=1, internal_code="004001",
        entry_date="2026-06-30", hours=2.5, role="principal",
        description="Platform dev",
    )

    rows = list_time_entries(db, employee_id=1)
    assert len(rows) == 2
    by_date = {r["entry_date"]: r for r in rows}
    proj = by_date["2026-06-29"]
    internal = by_date["2026-06-30"]
    assert proj["job_number"] == "260304"
    assert proj["ref_code"] == "260304"
    assert internal["internal_code"] == "004001"
    assert internal["ref_code"] == "004001"
    assert "AI" in internal["ref_name"]
    assert internal["internal_category"] == "Technology"

    weekly = get_weekly_timesheet(db, 1, "2026-06-29")
    assert len(weekly) == 2
    assert {r["ref_code"] for r in weekly} == {"260304", "004001"}


def test_internal_code_list_helper(db):
    codes = list_internal_codes(db)
    assert [c["code"] for c in codes][:2] == ["001001", "001002"]
    db.execute("UPDATE internal_codes SET is_active = 0 WHERE code = '001001'")
    active = list_internal_codes(db)
    assert "001001" not in [c["code"] for c in active]
    everything = list_internal_codes(db, active_only=False)
    assert "001001" in [c["code"] for c in everything]


# ---------------------------------------------------------------------------
# Utilization capacity
# ---------------------------------------------------------------------------
def test_utilization_report_includes_capacity(db):
    pid = _mk_project(db)
    create_time_entry(
        db, employee_id=1, project_id=pid,
        entry_date="2026-06-29", hours=20, role="professional_engineer",
    )
    create_time_entry(
        db, employee_id=1, internal_code="001001",
        entry_date="2026-06-30", hours=4, role="admin",
    )
    report = get_utilization_report(db, "2026-06-29", "2026-07-05")
    juan = next(e for e in report["employees"] if e["employee_id"] == 1)
    # 7-day period at 40 h/week -> 40 hours capacity
    assert juan["capacity_hours"] == 40.0
    assert juan["total_hours"] == 24.0
    assert juan["billable_hours"] == 20.0
    assert report["totals"]["capacity_hours"] >= 40.0

    # 14-day period -> 80 hours
    report2 = get_utilization_report(db, "2026-06-22", "2026-07-05")
    juan2 = next(e for e in report2["employees"] if e["employee_id"] == 1)
    assert juan2["capacity_hours"] == 80.0
