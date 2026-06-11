"""Financial analytics queries for 6th Degree Engineering.

Provides profitability analysis, utilization metrics, revenue reporting,
and financial summaries used by the Financials dashboard page.

Reads from the v_project_profitability, v_ar_aging, and v_pipeline_forecast
views defined in db/schema.sql, as well as direct queries against invoices,
time_entries, and expenses.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _year_start(year: int | None = None) -> str:
    """ISO date for January 1 of the given (or current) year."""
    y = year or date.today().year
    return f"{y}-01-01"


def _year_end(year: int | None = None) -> str:
    """ISO date for December 31 of the given (or current) year."""
    y = year or date.today().year
    return f"{y}-12-31"


# ---------------------------------------------------------------------------
# Project profitability
# ---------------------------------------------------------------------------

def get_project_profitability(
    conn: sqlite3.Connection,
    project_id: int | None = None,
) -> list[sqlite3.Row]:
    """Return profitability data from the v_project_profitability view.

    Optionally filtered to a single project.  Results include:
    project_id, job_number, name, total_labor_cost, total_expenses,
    total_invoiced, total_paid, net_margin.
    """
    query = "SELECT * FROM v_project_profitability"
    params: list[Any] = []
    if project_id is not None:
        query += " WHERE project_id = ?"
        params.append(project_id)
    query += " ORDER BY job_number DESC"
    return conn.execute(query, params).fetchall()


def get_profitability_by_client(conn: sqlite3.Connection) -> list[dict]:
    """Aggregate profitability grouped by client.

    Returns list of dicts with: client_name, project_count,
    total_labor_cost, total_expenses, total_invoiced, total_paid, net_margin.
    """
    rows = conn.execute(
        "SELECT "
        "    COALESCE(c.name, 'No Client') AS client_name, "
        "    COUNT(DISTINCT pp.project_id) AS project_count, "
        "    SUM(pp.total_labor_cost) AS total_labor_cost, "
        "    SUM(pp.total_expenses) AS total_expenses, "
        "    SUM(pp.total_invoiced) AS total_invoiced, "
        "    SUM(pp.total_paid) AS total_paid, "
        "    SUM(pp.net_margin) AS net_margin "
        "FROM v_project_profitability pp "
        "LEFT JOIN projects p ON p.id = pp.project_id "
        "LEFT JOIN clients c ON c.id = p.client_id "
        "GROUP BY c.name "
        "ORDER BY SUM(pp.total_invoiced) DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Utilization
# ---------------------------------------------------------------------------

def get_utilization_by_role(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
) -> list[dict]:
    """Calculate billable utilization by role within a date range.

    Returns list of dicts with: role, total_hours, billable_hours,
    non_billable_hours, utilization_pct.
    """
    rows = conn.execute(
        "SELECT "
        "    role, "
        "    ROUND(SUM(hours), 2) AS total_hours, "
        "    ROUND(SUM(CASE WHEN billable = 1 THEN hours ELSE 0 END), 2) "
        "        AS billable_hours, "
        "    ROUND(SUM(CASE WHEN billable = 0 THEN hours ELSE 0 END), 2) "
        "        AS non_billable_hours "
        "FROM time_entries "
        "WHERE entry_date BETWEEN ? AND ? "
        "GROUP BY role "
        "ORDER BY role",
        (date_from, date_to),
    ).fetchall()

    results = []
    for r in rows:
        total = r["total_hours"] or 0
        billable = r["billable_hours"] or 0
        pct = round((billable / total) * 100, 1) if total > 0 else 0.0
        results.append({
            "role": r["role"],
            "total_hours": total,
            "billable_hours": billable,
            "non_billable_hours": r["non_billable_hours"] or 0,
            "utilization_pct": pct,
        })
    return results


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------

def get_revenue_by_month(
    conn: sqlite3.Connection,
    year: int | None = None,
) -> list[dict]:
    """Return paid invoice totals grouped by month.

    Returns list of dicts with: month (YYYY-MM), total_paid, invoice_count.
    Defaults to the current year if *year* is not specified.
    """
    ys = _year_start(year)
    ye = _year_end(year)
    rows = conn.execute(
        "SELECT "
        "    substr(paid_date, 1, 7) AS month, "
        "    ROUND(SUM(paid_amount), 2) AS total_paid, "
        "    COUNT(*) AS invoice_count "
        "FROM invoices "
        "WHERE status = 'paid' "
        "  AND paid_date BETWEEN ? AND ? "
        "GROUP BY substr(paid_date, 1, 7) "
        "ORDER BY month",
        (ys, ye),
    ).fetchall()
    return [dict(r) for r in rows]


def get_revenue_forecast(conn: sqlite3.Connection) -> dict:
    """Build a forward-looking revenue forecast.

    Combines:
    - pipeline_weighted: sum of (estimated_value * probability / 100) from
      active opportunities
    - scheduled_pending: sum of amounts from pending payment_schedules
    - outstanding_invoices: sum of balance from sent/overdue invoices

    Returns dict with those three components plus a total.
    """
    # Weighted pipeline
    row = conn.execute(
        "SELECT COALESCE(SUM(estimated_value * probability / 100.0), 0) AS val "
        "FROM opportunities "
        "WHERE stage NOT IN ('lost', 'dormant', 'won')"
    ).fetchone()
    pipeline_weighted = round(row["val"], 2)

    # Pending payment schedules
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS val "
        "FROM payment_schedules "
        "WHERE status = 'pending' AND amount IS NOT NULL"
    ).fetchone()
    scheduled_pending = round(row["val"], 2)

    # Outstanding invoices (sent + overdue)
    row = conn.execute(
        "SELECT COALESCE(SUM(amount - COALESCE(paid_amount, 0)), 0) AS val "
        "FROM invoices "
        "WHERE status IN ('sent', 'overdue')"
    ).fetchone()
    outstanding = round(row["val"], 2)

    total = round(pipeline_weighted + scheduled_pending + outstanding, 2)

    return {
        "pipeline_weighted": pipeline_weighted,
        "scheduled_pending": scheduled_pending,
        "outstanding_invoices": outstanding,
        "total_forecast": total,
    }


# ---------------------------------------------------------------------------
# Financial summary (dashboard-level)
# ---------------------------------------------------------------------------

def get_financial_summary(conn: sqlite3.Connection) -> dict:
    """Comprehensive financial summary for the metrics row.

    Returns dict with:
        revenue_ytd        - paid invoices this calendar year
        outstanding        - sent + overdue invoice balance
        overdue            - overdue invoice balance only
        unbilled_time      - value of unbilled billable time entries
        unbilled_expenses  - value of unbilled reimbursable expenses (with markup)
        pipeline_weighted  - weighted opportunity value
    """
    year_start = _year_start()

    # Revenue YTD
    row = conn.execute(
        "SELECT COALESCE(SUM(paid_amount), 0) AS val "
        "FROM invoices WHERE status = 'paid' AND paid_date >= ?",
        (year_start,),
    ).fetchone()
    revenue_ytd = round(row["val"], 2)

    # Outstanding
    row = conn.execute(
        "SELECT COALESCE(SUM(amount - COALESCE(paid_amount, 0)), 0) AS val "
        "FROM invoices WHERE status IN ('sent', 'overdue')"
    ).fetchone()
    outstanding = round(row["val"], 2)

    # Overdue
    row = conn.execute(
        "SELECT COALESCE(SUM(amount - COALESCE(paid_amount, 0)), 0) AS val "
        "FROM invoices WHERE status = 'overdue'"
    ).fetchone()
    overdue = round(row["val"], 2)

    # Unbilled time (billable entries with no invoice_id)
    row = conn.execute(
        "SELECT COALESCE(SUM(hours * rate * multiplier), 0) AS val "
        "FROM time_entries "
        "WHERE invoice_id IS NULL AND billable = 1"
    ).fetchone()
    unbilled_time = round(row["val"], 2)

    # Unbilled expenses (reimbursable with no invoice_id, including markup)
    row = conn.execute(
        "SELECT COALESCE(SUM(amount * (1 + markup_pct / 100.0)), 0) AS val "
        "FROM expenses "
        "WHERE invoice_id IS NULL AND reimbursable = 1"
    ).fetchone()
    unbilled_expenses = round(row["val"], 2)

    # Pipeline weighted
    row = conn.execute(
        "SELECT COALESCE(SUM(estimated_value * probability / 100.0), 0) AS val "
        "FROM opportunities "
        "WHERE stage NOT IN ('lost', 'dormant', 'won')"
    ).fetchone()
    pipeline_weighted = round(row["val"], 2)

    return {
        "revenue_ytd": revenue_ytd,
        "outstanding": outstanding,
        "overdue": overdue,
        "unbilled_time": unbilled_time,
        "unbilled_expenses": unbilled_expenses,
        "pipeline_weighted": pipeline_weighted,
    }
