"""Dashboard aggregate queries for the 6DE Company Platform."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta


def _today() -> str:
    return date.today().isoformat()


def _year_start() -> str:
    return f"{date.today().year}-01-01"


def _month_start() -> str:
    d = date.today()
    return f"{d.year}-{d.month:02d}-01"


def get_dashboard_data(conn: sqlite3.Connection) -> dict:
    """Return a single dict with all data the dashboard needs.

    Every key is safe to use directly — counts default to 0, sums default
    to 0.0, and lists default to [].
    """
    today = _today()
    year_start = _year_start()
    month_start = _month_start()
    horizon_30 = (date.today() + timedelta(days=30)).isoformat()
    horizon_60 = (date.today() + timedelta(days=60)).isoformat()
    horizon_14 = (date.today() + timedelta(days=14)).isoformat()

    data: dict = {}

    # ------------------------------------------------------------------
    # Project counts
    # ------------------------------------------------------------------
    row = conn.execute(
        "SELECT COUNT(*) AS total,"
        "       SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active "
        "FROM projects"
    ).fetchone()
    data["total_projects"] = row["total"] or 0
    data["active_projects"] = row["active"] or 0

    # New projects this month — use start_date (not created_at which reflects
    # bulk-import time and inflates the count). B8 fix.
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM projects "
        "WHERE start_date >= ? AND status = 'active'",
        (month_start,),
    ).fetchone()
    data["new_projects_this_month"] = row["cnt"] or 0

    # ------------------------------------------------------------------
    # Invoice / revenue summaries
    # ------------------------------------------------------------------
    row = conn.execute(
        "SELECT COALESCE(SUM(amount - paid_amount), 0) AS outstanding "
        "FROM invoices WHERE status IN ('sent', 'overdue')"
    ).fetchone()
    data["outstanding_amount"] = row["outstanding"]

    row = conn.execute(
        "SELECT COALESCE(SUM(amount - paid_amount), 0) AS overdue "
        "FROM invoices WHERE status = 'overdue'"
    ).fetchone()
    data["overdue_amount"] = row["overdue"]

    row = conn.execute(
        "SELECT COALESCE(SUM(paid_amount), 0) AS paid "
        "FROM invoices WHERE status = 'paid' AND paid_date >= ?",
        (year_start,),
    ).fetchone()
    data["paid_ytd"] = row["paid"]

    # ------------------------------------------------------------------
    # Overdue invoices (detail list)
    # ------------------------------------------------------------------
    data["overdue_invoices"] = [
        dict(r)
        for r in conn.execute(
            "SELECT i.id, i.invoice_number, i.amount, i.paid_amount,"
            "       i.due_date, i.issue_date, i.description,"
            "       p.name AS project_name, p.job_number "
            "FROM invoices i "
            "LEFT JOIN projects p ON p.id = i.project_id "
            "WHERE i.status = 'overdue' "
            "ORDER BY i.due_date ASC"
        ).fetchall()
    ]

    # ------------------------------------------------------------------
    # Permits expiring within 30 days
    # ------------------------------------------------------------------
    data["expiring_permits"] = [
        dict(r)
        for r in conn.execute(
            "SELECT pm.id, pm.permit_number, pm.permit_type, pm.address,"
            "       pm.expiration_date, pm.status,"
            "       p.name AS project_name, p.job_number "
            "FROM permits pm "
            "LEFT JOIN projects p ON p.id = pm.project_id "
            "WHERE pm.expiration_date BETWEEN ? AND ? "
            "  AND pm.status NOT IN ('closed', 'expired') "
            "ORDER BY pm.expiration_date ASC",
            (today, horizon_30),
        ).fetchall()
    ]

    # ------------------------------------------------------------------
    # CCA deadlines within 60 days
    # ------------------------------------------------------------------
    data["cca_deadlines"] = [
        dict(r)
        for r in conn.execute(
            "SELECT pm.id, pm.permit_number, pm.case_number, pm.cca_deadline,"
            "       pm.address, pm.status,"
            "       p.name AS project_name, p.job_number "
            "FROM permits pm "
            "LEFT JOIN projects p ON p.id = pm.project_id "
            "WHERE pm.cca_deadline BETWEEN ? AND ? "
            "  AND pm.status NOT IN ('closed') "
            "ORDER BY pm.cca_deadline ASC",
            (today, horizon_60),
        ).fetchall()
    ]

    # ------------------------------------------------------------------
    # Recent activity (last 20 entries)
    # ------------------------------------------------------------------
    data["recent_activity"] = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    ]

    # ------------------------------------------------------------------
    # Upcoming milestones (within 14 days)
    # ------------------------------------------------------------------
    data["upcoming_milestones"] = [
        dict(r)
        for r in conn.execute(
            "SELECT m.id, m.name, m.due_date, m.status,"
            "       p.name AS project_name, p.job_number "
            "FROM milestones m "
            "LEFT JOIN projects p ON p.id = m.project_id "
            "WHERE m.due_date BETWEEN ? AND ? "
            "  AND m.status IN ('pending', 'in_progress') "
            "ORDER BY m.due_date ASC",
            (today, horizon_14),
        ).fetchall()
    ]

    # ------------------------------------------------------------------
    # Projects by status (for chart)
    # ------------------------------------------------------------------
    data["projects_by_status"] = {
        r["status"]: r["cnt"]
        for r in conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM projects GROUP BY status"
        ).fetchall()
    }

    # ------------------------------------------------------------------
    # Permits by status (for chart)
    # ------------------------------------------------------------------
    data["permits_by_status"] = {
        r["status"]: r["cnt"]
        for r in conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM permits GROUP BY status"
        ).fetchall()
    }

    # ------------------------------------------------------------------
    # ERP extensions: pipeline, utilization, unbilled, bids
    # ------------------------------------------------------------------
    row = conn.execute(
        "SELECT COALESCE(SUM(estimated_value * probability / 100.0), 0) AS weighted "
        "FROM opportunities WHERE stage NOT IN ('lost', 'dormant', 'won')"
    ).fetchone()
    data["pipeline_weighted"] = row["weighted"]

    row = conn.execute(
        "SELECT COALESCE(SUM(hours * rate * multiplier), 0) AS unbilled "
        "FROM time_entries WHERE invoice_id IS NULL AND billable = 1"
    ).fetchone()
    data["unbilled_time_amount"] = row["unbilled"]

    row = conn.execute(
        "SELECT COALESCE(SUM(amount * (1 + markup_pct / 100.0)), 0) AS unbilled "
        "FROM expenses WHERE invoice_id IS NULL AND reimbursable = 1"
    ).fetchone()
    data["unbilled_expense_amount"] = row["unbilled"]

    data["upcoming_bid_deadlines"] = [
        dict(r)
        for r in conn.execute(
            "SELECT id, title, portal, agency, submission_deadline, status "
            "FROM bid_opportunities "
            "WHERE submission_deadline BETWEEN ? AND ? "
            "  AND status IN ('monitoring', 'go', 'preparing') "
            "ORDER BY submission_deadline ASC",
            (today, horizon_14),
        ).fetchall()
    ]

    # ------------------------------------------------------------------
    # Accounting: income/expense YTD from transactions
    # ------------------------------------------------------------------
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS income,"
        "       COALESCE(SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END), 0) AS expenses,"
        "       COALESCE(SUM(amount), 0) AS net "
        "FROM transactions WHERE txn_date >= ?",
        (year_start,),
    ).fetchone()
    data["txn_income_ytd"] = row["income"]
    data["txn_expenses_ytd"] = row["expenses"]
    data["txn_net_ytd"] = row["net"]

    row = conn.execute(
        "SELECT COALESCE(SUM(monthly_amount), 0) AS burn "
        "FROM recurring_expenses WHERE active = 1"
    ).fetchone()
    data["recurring_monthly_burn"] = row["burn"]

    # Total outstanding from project contract values
    row = conn.execute(
        "SELECT COALESCE(SUM(outstanding_balance), 0) AS outstanding "
        "FROM projects WHERE status = 'active'"
    ).fetchone()
    data["project_outstanding"] = row["outstanding"]

    # Recurring expenses due within 7 days
    horizon_7 = (date.today() + timedelta(days=7)).isoformat()
    data["recurring_due_soon"] = [
        dict(r)
        for r in conn.execute(
            "SELECT id, vendor, category, monthly_amount, next_due_date "
            "FROM recurring_expenses "
            "WHERE active = 1 AND next_due_date BETWEEN ? AND ? "
            "ORDER BY next_due_date ASC",
            (today, horizon_7),
        ).fetchall()
    ]

    return data
