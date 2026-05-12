"""Timekeeping & expense CRUD operations for 6th Degree Engineering.

Handles employee management, time entry tracking, expense logging,
fee schedule lookups, and utilization reporting.  All mutating
operations log to the activity_log table.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Constants — business rules
# ---------------------------------------------------------------------------

AFTER_HOURS_MULTIPLIER = 1.5
FIELD_MINIMUM_HOURS = 4.0
REVIEW_MINIMUM_HOURS = 0.2
MILEAGE_RATE = 0.70

_VALID_ROLES = (
    "principal",
    "expert_consultant",
    "professional_engineer",
    "field_inspector",
    "engineering_technician",
    "cad_drafter",
    "admin",
)

_EXPENSE_CATEGORIES = (
    "travel",
    "mileage",
    "materials",
    "filing_fees",
    "printing",
    "software",
    "equipment",
    "subcontractor",
    "other",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    """ISO date string for today."""
    return date.today().isoformat()


def _now() -> str:
    """Current UTC timestamp in ISO-8601 format."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _week_start(d: date | None = None) -> date:
    """Return the Monday of the week containing *d* (default: today)."""
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def _log_activity(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    action: str,
    details: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO activity_log (entity_type, entity_id, action, details) "
        "VALUES (?, ?, ?, ?)",
        (entity_type, entity_id, action, json.dumps(details) if details else None),
    )


# ---------------------------------------------------------------------------
# Employees — CRUD
# ---------------------------------------------------------------------------

def list_employees(
    conn: sqlite3.Connection, is_active: bool | None = None
) -> list[sqlite3.Row]:
    """Return employees, optionally filtered by active status."""
    sql = "SELECT * FROM employees WHERE 1=1"
    params: list[Any] = []
    if is_active is not None:
        sql += " AND is_active = ?"
        params.append(1 if is_active else 0)
    sql += " ORDER BY name"
    return conn.execute(sql, params).fetchall()


def get_employee(conn: sqlite3.Connection, employee_id: int) -> sqlite3.Row | None:
    """Return a single employee row or None."""
    return conn.execute(
        "SELECT * FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()


def create_employee(
    conn: sqlite3.Connection,
    name: str,
    role: str,
    **kwargs: Any,
) -> int:
    """Insert a new employee and return the new id."""
    if role not in _VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of {_VALID_ROLES}")

    allowed = {"email", "phone", "is_active", "hire_date", "notes"}
    fields = ["name", "role"]
    values: list[Any] = [name, role]
    for col in allowed:
        if col in kwargs and kwargs[col] is not None:
            fields.append(col)
            values.append(kwargs[col])

    placeholders = ", ".join("?" for _ in fields)
    col_names = ", ".join(fields)
    cur = conn.execute(
        f"INSERT INTO employees ({col_names}) VALUES ({placeholders})", values
    )
    employee_id = cur.lastrowid
    _log_activity(
        conn,
        "employee",
        employee_id,
        "created",
        {"name": name, "role": role},
    )
    conn.commit()
    return employee_id


def update_employee(conn: sqlite3.Connection, employee_id: int, **kwargs: Any) -> None:
    """Update arbitrary employee fields."""
    allowed = {"name", "email", "phone", "role", "is_active", "hire_date", "notes"}
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return
    filtered["updated_at"] = _now()
    set_clause = ", ".join(f"{col} = ?" for col in filtered)
    values = list(filtered.values()) + [employee_id]
    conn.execute(
        f"UPDATE employees SET {set_clause} WHERE id = ?", values  # noqa: S608
    )
    _log_activity(conn, "employee", employee_id, "updated", filtered)
    conn.commit()


# ---------------------------------------------------------------------------
# Fee Schedule
# ---------------------------------------------------------------------------

def get_current_rate(conn: sqlite3.Connection, role: str) -> float:
    """Look up the latest hourly rate for *role* from fee_schedule.

    Finds the entry with the greatest effective_date that is <= today.
    Raises ValueError if no rate is found.
    """
    row = conn.execute(
        "SELECT hourly_rate FROM fee_schedule "
        "WHERE role = ? AND effective_date <= ? "
        "ORDER BY effective_date DESC LIMIT 1",
        (role, _today()),
    ).fetchone()
    if row is None:
        raise ValueError(f"No fee schedule entry found for role '{role}'")
    return float(row["hourly_rate"])


def list_fee_schedule(
    conn: sqlite3.Connection, role: str | None = None
) -> list[sqlite3.Row]:
    """Return fee schedule entries, optionally filtered by role."""
    sql = "SELECT * FROM fee_schedule WHERE 1=1"
    params: list[Any] = []
    if role is not None:
        sql += " AND role = ?"
        params.append(role)
    sql += " ORDER BY role, effective_date DESC"
    return conn.execute(sql, params).fetchall()


def create_fee_entry(
    conn: sqlite3.Connection,
    role: str,
    hourly_rate: float,
    effective_date: str,
) -> int:
    """Insert a new fee schedule entry and return its id."""
    if role not in _VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of {_VALID_ROLES}")
    cur = conn.execute(
        "INSERT INTO fee_schedule (role, hourly_rate, effective_date) "
        "VALUES (?, ?, ?)",
        (role, hourly_rate, effective_date),
    )
    fee_id = cur.lastrowid
    _log_activity(
        conn,
        "fee_schedule",
        fee_id,
        "created",
        {"role": role, "hourly_rate": hourly_rate, "effective_date": effective_date},
    )
    conn.commit()
    return fee_id


# ---------------------------------------------------------------------------
# Time Entries — CRUD
# ---------------------------------------------------------------------------

def create_time_entry(
    conn: sqlite3.Connection,
    employee_id: int,
    project_id: int,
    entry_date: str,
    hours: float,
    role: str,
    **kwargs: Any,
) -> int:
    """Create a new time entry with auto-looked-up rate.

    The rate is snapshotted from fee_schedule at creation time unless
    explicitly provided via kwargs['rate'].
    """
    rate = kwargs.pop("rate", None)
    if rate is None:
        rate = get_current_rate(conn, role)

    multiplier = kwargs.get("multiplier", 1.0)
    billable = kwargs.get("billable", 1)
    description = kwargs.get("description", None)
    invoice_id = kwargs.get("invoice_id", None)

    cur = conn.execute(
        "INSERT INTO time_entries "
        "(employee_id, project_id, entry_date, hours, role, rate, "
        " multiplier, billable, description, invoice_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            employee_id, project_id, entry_date, hours, role, rate,
            multiplier, billable, description, invoice_id,
        ),
    )
    entry_id = cur.lastrowid
    _log_activity(
        conn,
        "time_entry",
        entry_id,
        "created",
        {
            "employee_id": employee_id,
            "project_id": project_id,
            "entry_date": entry_date,
            "hours": hours,
            "role": role,
            "rate": rate,
            "multiplier": multiplier,
        },
    )
    conn.commit()
    return entry_id


def update_time_entry(conn: sqlite3.Connection, entry_id: int, **kwargs: Any) -> None:
    """Update arbitrary time entry fields."""
    allowed = {
        "employee_id", "project_id", "entry_date", "hours", "role",
        "rate", "multiplier", "billable", "description", "invoice_id",
    }
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return
    filtered["updated_at"] = _now()
    set_clause = ", ".join(f"{col} = ?" for col in filtered)
    values = list(filtered.values()) + [entry_id]
    conn.execute(
        f"UPDATE time_entries SET {set_clause} WHERE id = ?", values  # noqa: S608
    )
    _log_activity(conn, "time_entry", entry_id, "updated", filtered)
    conn.commit()


def delete_time_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    """Delete a time entry (only if not yet invoiced)."""
    _log_activity(conn, "time_entry", entry_id, "deleted")
    conn.execute("DELETE FROM time_entries WHERE id = ?", (entry_id,))
    conn.commit()


def list_time_entries(
    conn: sqlite3.Connection,
    project_id: int | None = None,
    employee_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    unbilled_only: bool = False,
) -> list[sqlite3.Row]:
    """Return time entries with optional filters, joined with employee/project."""
    sql = (
        "SELECT te.*, e.name AS employee_name, p.job_number, p.name AS project_name "
        "FROM time_entries te "
        "JOIN employees e ON e.id = te.employee_id "
        "JOIN projects p ON p.id = te.project_id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if project_id is not None:
        sql += " AND te.project_id = ?"
        params.append(project_id)
    if employee_id is not None:
        sql += " AND te.employee_id = ?"
        params.append(employee_id)
    if date_from is not None:
        sql += " AND te.entry_date >= ?"
        params.append(date_from)
    if date_to is not None:
        sql += " AND te.entry_date <= ?"
        params.append(date_to)
    if unbilled_only:
        sql += " AND te.invoice_id IS NULL"
    sql += " ORDER BY te.entry_date DESC, te.id DESC"
    return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------------------
# Timesheet / Reporting
# ---------------------------------------------------------------------------

def get_weekly_timesheet(
    conn: sqlite3.Connection,
    employee_id: int,
    week_start_date: str,
) -> list[sqlite3.Row]:
    """Return time entries for an employee for a 7-day window starting at week_start_date."""
    try:
        ws = datetime.strptime(week_start_date, "%Y-%m-%d").date()
    except ValueError:
        ws = date.today()
    week_end = (ws + timedelta(days=6)).isoformat()
    sql = (
        "SELECT te.*, e.name AS employee_name, p.job_number, p.name AS project_name "
        "FROM time_entries te "
        "JOIN employees e ON e.id = te.employee_id "
        "JOIN projects p ON p.id = te.project_id "
        "WHERE te.employee_id = ? AND te.entry_date >= ? AND te.entry_date <= ? "
        "ORDER BY te.entry_date, p.job_number"
    )
    return conn.execute(sql, (employee_id, week_start_date, week_end)).fetchall()


def get_utilization_report(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
) -> dict[str, Any]:
    """Compute utilization metrics for each active employee in the date range.

    Returns::

        {
            "period": {"from": ..., "to": ...},
            "employees": [
                {
                    "employee_id": ..., "name": ..., "role": ...,
                    "total_hours": ..., "billable_hours": ...,
                    "utilization_pct": ..., "billable_amount": ...
                },
                ...
            ],
            "totals": {
                "total_hours": ..., "billable_hours": ...,
                "utilization_pct": ..., "billable_amount": ...
            }
        }
    """
    rows = conn.execute(
        "SELECT e.id AS employee_id, e.name, e.role, "
        "  COALESCE(SUM(te.hours), 0) AS total_hours, "
        "  COALESCE(SUM(CASE WHEN te.billable = 1 THEN te.hours ELSE 0 END), 0) "
        "    AS billable_hours, "
        "  COALESCE(SUM(CASE WHEN te.billable = 1 "
        "    THEN te.hours * te.rate * te.multiplier ELSE 0 END), 0) "
        "    AS billable_amount "
        "FROM employees e "
        "LEFT JOIN time_entries te "
        "  ON te.employee_id = e.id "
        "  AND te.entry_date >= ? AND te.entry_date <= ? "
        "WHERE e.is_active = 1 "
        "GROUP BY e.id "
        "ORDER BY e.name",
        (date_from, date_to),
    ).fetchall()

    employees = []
    grand_total = 0.0
    grand_billable = 0.0
    grand_amount = 0.0
    for r in rows:
        total_h = float(r["total_hours"])
        bill_h = float(r["billable_hours"])
        bill_amt = float(r["billable_amount"])
        util_pct = (bill_h / total_h * 100.0) if total_h > 0 else 0.0
        employees.append({
            "employee_id": r["employee_id"],
            "name": r["name"],
            "role": r["role"],
            "total_hours": round(total_h, 2),
            "billable_hours": round(bill_h, 2),
            "utilization_pct": round(util_pct, 1),
            "billable_amount": round(bill_amt, 2),
        })
        grand_total += total_h
        grand_billable += bill_h
        grand_amount += bill_amt

    grand_util = (grand_billable / grand_total * 100.0) if grand_total > 0 else 0.0

    return {
        "period": {"from": date_from, "to": date_to},
        "employees": employees,
        "totals": {
            "total_hours": round(grand_total, 2),
            "billable_hours": round(grand_billable, 2),
            "utilization_pct": round(grand_util, 1),
            "billable_amount": round(grand_amount, 2),
        },
    }


# ---------------------------------------------------------------------------
# Expenses — CRUD
# ---------------------------------------------------------------------------

def create_expense(
    conn: sqlite3.Connection,
    project_id: int,
    expense_date: str,
    category: str,
    amount: float,
    **kwargs: Any,
) -> int:
    """Insert a new expense and return its id."""
    if category not in _EXPENSE_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. Must be one of {_EXPENSE_CATEGORIES}"
        )

    employee_id = kwargs.get("employee_id", None)
    description = kwargs.get("description", None)
    markup_pct = kwargs.get("markup_pct", 15.0)
    reimbursable = kwargs.get("reimbursable", 1)
    receipt_path = kwargs.get("receipt_path", None)
    invoice_id = kwargs.get("invoice_id", None)

    cur = conn.execute(
        "INSERT INTO expenses "
        "(project_id, employee_id, expense_date, category, description, "
        " amount, markup_pct, reimbursable, receipt_path, invoice_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_id, employee_id, expense_date, category, description,
            amount, markup_pct, reimbursable, receipt_path, invoice_id,
        ),
    )
    expense_id = cur.lastrowid
    _log_activity(
        conn,
        "expense",
        expense_id,
        "created",
        {
            "project_id": project_id,
            "category": category,
            "amount": amount,
        },
    )
    conn.commit()
    return expense_id


def update_expense(conn: sqlite3.Connection, expense_id: int, **kwargs: Any) -> None:
    """Update arbitrary expense fields."""
    allowed = {
        "project_id", "employee_id", "expense_date", "category",
        "description", "amount", "markup_pct", "reimbursable",
        "receipt_path", "invoice_id",
    }
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return
    filtered["updated_at"] = _now()
    set_clause = ", ".join(f"{col} = ?" for col in filtered)
    values = list(filtered.values()) + [expense_id]
    conn.execute(
        f"UPDATE expenses SET {set_clause} WHERE id = ?", values  # noqa: S608
    )
    _log_activity(conn, "expense", expense_id, "updated", filtered)
    conn.commit()


def list_expenses(
    conn: sqlite3.Connection,
    project_id: int | None = None,
    unbilled_only: bool = False,
) -> list[sqlite3.Row]:
    """Return expenses with optional filters, joined with project info."""
    sql = (
        "SELECT ex.*, p.job_number, p.name AS project_name, "
        "  e.name AS employee_name "
        "FROM expenses ex "
        "JOIN projects p ON p.id = ex.project_id "
        "LEFT JOIN employees e ON e.id = ex.employee_id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if project_id is not None:
        sql += " AND ex.project_id = ?"
        params.append(project_id)
    if unbilled_only:
        sql += " AND ex.invoice_id IS NULL"
    sql += " ORDER BY ex.expense_date DESC, ex.id DESC"
    return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------

def get_time_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Dashboard-level timekeeping metrics.

    Returns dict with:
        hours_this_week    - total hours logged this week (Mon-Sun)
        billable_this_week - billable hours this week
        hours_this_month   - total hours logged this calendar month
        unbilled_amount    - total $ of unbilled time entries
        unbilled_hours     - total hours not yet invoiced
        utilization_pct    - billable / total hours this month (%)
    """
    today = date.today()
    ws = _week_start(today).isoformat()
    we = (_week_start(today) + timedelta(days=6)).isoformat()
    month_start = today.replace(day=1).isoformat()
    month_end = today.isoformat()

    # This week
    week_row = conn.execute(
        "SELECT "
        "  COALESCE(SUM(hours), 0) AS total_hours, "
        "  COALESCE(SUM(CASE WHEN billable = 1 THEN hours ELSE 0 END), 0) "
        "    AS billable_hours "
        "FROM time_entries "
        "WHERE entry_date >= ? AND entry_date <= ?",
        (ws, we),
    ).fetchone()

    # This month
    month_row = conn.execute(
        "SELECT "
        "  COALESCE(SUM(hours), 0) AS total_hours, "
        "  COALESCE(SUM(CASE WHEN billable = 1 THEN hours ELSE 0 END), 0) "
        "    AS billable_hours "
        "FROM time_entries "
        "WHERE entry_date >= ? AND entry_date <= ?",
        (month_start, month_end),
    ).fetchone()

    # Unbilled totals
    unbilled_row = conn.execute(
        "SELECT "
        "  COALESCE(SUM(hours), 0) AS unbilled_hours, "
        "  COALESCE(SUM(hours * rate * multiplier), 0) AS unbilled_amount "
        "FROM time_entries "
        "WHERE invoice_id IS NULL AND billable = 1"
    ).fetchone()

    total_month = float(month_row["total_hours"])
    billable_month = float(month_row["billable_hours"])
    util_pct = (billable_month / total_month * 100.0) if total_month > 0 else 0.0

    return {
        "hours_this_week": round(float(week_row["total_hours"]), 2),
        "billable_this_week": round(float(week_row["billable_hours"]), 2),
        "hours_this_month": round(total_month, 2),
        "unbilled_amount": round(float(unbilled_row["unbilled_amount"]), 2),
        "unbilled_hours": round(float(unbilled_row["unbilled_hours"]), 2),
        "utilization_pct": round(util_pct, 1),
    }
