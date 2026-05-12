"""Accounting — transactions, cashflow, and recurring expenses."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from db import ensure_db  # noqa: E402
from streamlit_app.components.formatters import (  # noqa: E402
    days_until,
    format_currency,
    format_date,
    urgency_color,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Accounting | 6DE Platform",
    page_icon="\U0001f4b0",
    layout="wide",
)

# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------
conn = ensure_db()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("Accounting")
st.caption("6th Degree Engineering - Transactions, Cashflow & Recurring Expenses")

# ---------------------------------------------------------------------------
# Helper queries
# ---------------------------------------------------------------------------
current_year = date.today().year
year_start = f"{current_year}-01-01"
year_end = f"{current_year}-12-31"


def _fetch_ytd_totals(conn):
    """Return income, expenses, and net for the current year."""
    row = conn.execute(
        "SELECT "
        "  COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS income, "
        "  COALESCE(SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END), 0) AS expenses, "
        "  COALESCE(SUM(amount), 0) AS net "
        "FROM transactions "
        "WHERE txn_date BETWEEN ? AND ?",
        (year_start, year_end),
    ).fetchone()
    return dict(row)


def _fetch_recurring_monthly_burn(conn):
    """Sum of monthly_amount for all active recurring expenses."""
    row = conn.execute(
        "SELECT COALESCE(SUM(monthly_amount), 0) AS total "
        "FROM recurring_expenses WHERE active = 1"
    ).fetchone()
    return row["total"]


def _fetch_projects(conn):
    """Return all projects for filter dropdowns."""
    return conn.execute(
        "SELECT id, job_number, name FROM projects ORDER BY job_number DESC"
    ).fetchall()


# ---------------------------------------------------------------------------
# Top-level metrics
# ---------------------------------------------------------------------------
ytd = _fetch_ytd_totals(conn)
monthly_burn = _fetch_recurring_monthly_burn(conn)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Income YTD", format_currency(ytd["income"]))
m2.metric("Total Expenses YTD", format_currency(abs(ytd["expenses"])))
m3.metric("Net Cashflow YTD", format_currency(ytd["net"]))
m4.metric("Recurring Monthly Burn", format_currency(monthly_burn))

st.divider()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_txn, tab_cashflow, tab_recurring = st.tabs(
    ["Transactions", "Cashflow", "Recurring Expenses"]
)

# ========================== TAB 1: TRANSACTIONS ============================
with tab_txn:
    st.subheader("Transactions")

    # -- Filters --
    projects = _fetch_projects(conn)
    project_map = {0: "All Projects"} | {
        p["id"]: f'{p["job_number"]} - {p["name"]}' for p in projects
    }

    # Distinct categories for filter
    cat_rows = conn.execute(
        "SELECT DISTINCT expense_category FROM transactions "
        "WHERE expense_category IS NOT NULL ORDER BY expense_category"
    ).fetchall()
    categories = ["All"] + [r["expense_category"] for r in cat_rows]

    # Distinct months for filter
    month_rows = conn.execute(
        "SELECT DISTINCT strftime('%Y-%m', txn_date) AS m "
        "FROM transactions ORDER BY m DESC"
    ).fetchall()
    months = ["All"] + [r["m"] for r in month_rows]

    fc1, fc2, fc3, fc4 = st.columns(4)
    sel_month = fc1.selectbox("Month", months, key="txn_month")
    sel_category = fc2.selectbox("Category", categories, key="txn_category")
    sel_project = fc3.selectbox(
        "Project",
        options=list(project_map.keys()),
        format_func=lambda x: project_map[x],
        key="txn_project",
    )
    dcol1, dcol2 = fc4.columns(2)
    sel_date_from = dcol1.date_input(
        "From", value=date(current_year, 1, 1), key="txn_from"
    )
    sel_date_to = dcol2.date_input("To", value=date.today(), key="txn_to")

    # Build query
    where_clauses = ["txn_date BETWEEN ? AND ?"]
    params: list = [sel_date_from.isoformat(), sel_date_to.isoformat()]

    if sel_month != "All":
        where_clauses.append("strftime('%Y-%m', txn_date) = ?")
        params.append(sel_month)
    if sel_category != "All":
        where_clauses.append("expense_category = ?")
        params.append(sel_category)
    if sel_project:
        where_clauses.append("project_id = ?")
        params.append(sel_project)

    where_sql = " AND ".join(where_clauses)

    txn_rows = conn.execute(
        f"SELECT t.*, p.job_number "
        f"FROM transactions t "
        f"LEFT JOIN projects p ON p.id = t.project_id "
        f"WHERE {where_sql} "
        f"ORDER BY t.txn_date DESC",
        params,
    ).fetchall()

    if txn_rows:
        txn_data = []
        for r in txn_rows:
            txn_data.append({
                "Date": format_date(r["txn_date"]),
                "Account": r["account"] or "",
                "Type": r["account_type"] or "",
                "Description": r["description"] or "",
                "Amount": r["amount"],
                "Balance": r["balance"],
                "Category": r["expense_category"] or "",
                "Txn Type": r["txn_type"] or "",
                "Project": r["job_number"] or "",
            })

        df_txn = pd.DataFrame(txn_data)

        # Color-code amounts
        def _color_amount(val):
            if isinstance(val, (int, float)):
                if val > 0:
                    return "color: #198754; font-weight: 600"
                if val < 0:
                    return "color: #dc3545; font-weight: 600"
            return ""

        st.dataframe(
            df_txn.style.format({
                "Amount": "${:,.2f}",
                "Balance": "${:,.2f}",
            }).map(_color_amount, subset=["Amount"]),
            use_container_width=True,
            hide_index=True,
            height=500,
        )

        # Totals row
        total_income = sum(r["amount"] for r in txn_rows if r["amount"] > 0)
        total_expenses = sum(r["amount"] for r in txn_rows if r["amount"] < 0)
        net = total_income + total_expenses

        tc1, tc2, tc3 = st.columns(3)
        tc1.metric("Total Income (filtered)", format_currency(total_income))
        tc2.metric("Total Expenses (filtered)", format_currency(abs(total_expenses)))
        tc3.metric("Net (filtered)", format_currency(net))
    else:
        st.info("No transactions match the current filters.")

# ============================ TAB 2: CASHFLOW =============================
with tab_cashflow:
    st.subheader("Monthly Cashflow")

    # Summary metrics
    avg_net = ytd["net"] / max(date.today().month, 1)
    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Total Income YTD", format_currency(ytd["income"]))
    sm2.metric("Total Expenses YTD", format_currency(abs(ytd["expenses"])))
    sm3.metric("Net YTD", format_currency(ytd["net"]))
    sm4.metric("Avg Monthly Net", format_currency(avg_net))

    st.markdown("")

    # Monthly cashflow from view
    cf_rows = conn.execute(
        "SELECT month, income, outflow, net FROM v_cashflow_monthly ORDER BY month"
    ).fetchall()

    if cf_rows:
        cf_data = []
        for r in cf_rows:
            cf_data.append({
                "Month": r["month"],
                "Income": r["income"] or 0,
                "Outflow": abs(r["outflow"] or 0),
                "Net": r["net"] or 0,
            })

        df_cf = pd.DataFrame(cf_data)

        # Bar chart for income and outflow
        st.markdown("**Monthly Income vs. Expenses**")
        chart_df = df_cf[["Month", "Income", "Outflow"]].copy()
        chart_df = chart_df.set_index("Month")
        st.bar_chart(chart_df, color=["#198754", "#dc3545"])

        # Net line chart
        st.markdown("**Monthly Net Cashflow**")
        net_df = df_cf[["Month", "Net"]].copy()
        net_df = net_df.set_index("Month")
        st.line_chart(net_df, color=["#0d6efd"])

        # Expense breakdown by category
        st.markdown("---")
        st.subheader("Expense Breakdown by Category")

        cat_data = conn.execute(
            "SELECT expense_category, "
            "  ROUND(SUM(ABS(amount)), 2) AS total "
            "FROM transactions "
            "WHERE amount < 0 AND expense_category IS NOT NULL "
            "GROUP BY expense_category "
            "ORDER BY total DESC"
        ).fetchall()

        if cat_data:
            cat_df = pd.DataFrame([dict(r) for r in cat_data])
            cat_df = cat_df.rename(columns={
                "expense_category": "Category",
                "total": "Total",
            })
            cat_df = cat_df.set_index("Category")
            st.bar_chart(cat_df, horizontal=True, color=["#dc3545"])

            # Detail table
            st.markdown("")
            detail_df = cat_df.reset_index()
            st.dataframe(
                detail_df.style.format({"Total": "${:,.2f}"}),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No categorized expenses found.")
    else:
        st.info("No transaction data available for cashflow analysis.")

# ====================== TAB 3: RECURRING EXPENSES =========================
with tab_recurring:
    st.subheader("Recurring Expenses")

    # Metrics
    active_rows = conn.execute(
        "SELECT * FROM recurring_expenses WHERE active = 1 "
        "ORDER BY next_due_date ASC"
    ).fetchall()

    total_monthly = sum(r["monthly_amount"] for r in active_rows)
    total_annual = total_monthly * 12

    rm1, rm2 = st.columns(2)
    rm1.metric("Total Monthly Recurring", format_currency(total_monthly))
    rm2.metric("Total Annual Recurring", format_currency(total_annual))

    st.markdown("")

    # Display recurring expenses table
    all_recurring = conn.execute(
        "SELECT * FROM recurring_expenses ORDER BY active DESC, next_due_date ASC"
    ).fetchall()

    if all_recurring:
        rec_data = []
        for r in all_recurring:
            days_left = days_until(r["next_due_date"])
            uc = urgency_color(days_left)

            # Build urgency label
            if days_left is not None:
                if days_left < 0:
                    urgency_label = f"{abs(days_left)}d overdue"
                elif days_left == 0:
                    urgency_label = "Due today"
                else:
                    urgency_label = f"In {days_left}d"
            else:
                urgency_label = ""

            rec_data.append({
                "ID": r["id"],
                "Vendor": r["vendor"],
                "Category": r["category"] or "",
                "Monthly Amount": r["monthly_amount"],
                "Frequency": (r["frequency"] or "monthly").title(),
                "Next Due": format_date(r["next_due_date"]),
                "Urgency": urgency_label,
                "Active": "Yes" if r["active"] else "No",
                "Notes": r["notes"] or "",
                "_urgency_color": uc,
            })

        df_rec = pd.DataFrame(rec_data)

        # Style urgency column
        def _style_urgency(row):
            color_map = {
                "red": "color: #dc3545; font-weight: 700",
                "orange": "color: #fd7e14; font-weight: 600",
                "green": "color: #198754",
                "gray": "color: #adb5bd",
            }
            uc = row["_urgency_color"]
            style = color_map.get(uc, "")
            return [
                style if col == "Urgency" else "" for col in row.index
            ]

        display_cols = [
            "Vendor", "Category", "Monthly Amount", "Frequency",
            "Next Due", "Urgency", "Active", "Notes",
        ]

        st.dataframe(
            df_rec[display_cols + ["_urgency_color"]].style
            .format({"Monthly Amount": "${:,.2f}"})
            .apply(_style_urgency, axis=1),
            use_container_width=True,
            hide_index=True,
            column_config={"_urgency_color": None},
        )
    else:
        st.info("No recurring expenses found.")

    # -- Add new recurring expense --
    st.markdown("---")
    st.subheader("Add Recurring Expense")

    with st.form("add_recurring_form", clear_on_submit=True):
        rc1, rc2 = st.columns(2)
        new_vendor = rc1.text_input("Vendor *")
        new_category = rc2.text_input("Category")

        rc3, rc4 = st.columns(2)
        new_amount = rc3.number_input(
            "Monthly Amount ($) *", min_value=0.0, step=10.0, format="%.2f"
        )
        new_frequency = rc4.selectbox(
            "Frequency", ["monthly", "quarterly", "annual", "weekly"]
        )

        rc5, rc6 = st.columns(2)
        new_due = rc5.date_input("Next Due Date", value=date.today())
        new_notes = rc6.text_input("Notes (optional)")

        submitted = st.form_submit_button(
            "Add Recurring Expense", type="primary", use_container_width=True
        )
        if submitted:
            if not new_vendor.strip():
                st.error("Vendor name is required.")
            elif new_amount <= 0:
                st.error("Monthly amount must be greater than zero.")
            else:
                conn.execute(
                    "INSERT INTO recurring_expenses "
                    "(vendor, category, monthly_amount, frequency, next_due_date, active, notes) "
                    "VALUES (?, ?, ?, ?, ?, 1, ?)",
                    (
                        new_vendor.strip(),
                        new_category.strip() or None,
                        new_amount,
                        new_frequency,
                        new_due.isoformat(),
                        new_notes.strip() or None,
                    ),
                )
                conn.commit()
                st.success(f"Added recurring expense: {new_vendor.strip()}")
                st.rerun()

    # -- Edit / Delete existing recurring expenses --
    if all_recurring:
        st.markdown("---")
        st.subheader("Edit / Delete Recurring Expense")

        rec_options = {
            r["id"]: f'{r["vendor"]} - {format_currency(r["monthly_amount"])}'
            for r in all_recurring
        }
        sel_rec_id = st.selectbox(
            "Select expense to edit",
            options=list(rec_options.keys()),
            format_func=lambda x: rec_options[x],
            key="edit_rec_select",
        )

        sel_rec = next(r for r in all_recurring if r["id"] == sel_rec_id)

        with st.form("edit_recurring_form", clear_on_submit=True):
            ec1, ec2 = st.columns(2)
            edit_vendor = ec1.text_input("Vendor", value=sel_rec["vendor"])
            edit_category = ec2.text_input(
                "Category", value=sel_rec["category"] or ""
            )

            ec3, ec4 = st.columns(2)
            edit_amount = ec3.number_input(
                "Monthly Amount ($)",
                min_value=0.0,
                step=10.0,
                format="%.2f",
                value=float(sel_rec["monthly_amount"]),
            )
            edit_frequency = ec4.selectbox(
                "Frequency",
                ["monthly", "quarterly", "annual", "weekly"],
                index=["monthly", "quarterly", "annual", "weekly"].index(
                    sel_rec["frequency"] or "monthly"
                ),
            )

            ec5, ec6 = st.columns(2)
            due_val = (
                datetime.fromisoformat(sel_rec["next_due_date"]).date()
                if sel_rec["next_due_date"]
                else date.today()
            )
            edit_due = ec5.date_input("Next Due Date", value=due_val)
            edit_active = ec6.checkbox("Active", value=bool(sel_rec["active"]))
            edit_notes = st.text_input(
                "Notes", value=sel_rec["notes"] or ""
            )

            btn1, btn2 = st.columns(2)
            save_clicked = btn1.form_submit_button(
                "Save Changes", type="primary", use_container_width=True
            )
            delete_clicked = btn2.form_submit_button(
                "Delete", use_container_width=True
            )

            if save_clicked:
                if not edit_vendor.strip():
                    st.error("Vendor name is required.")
                elif edit_amount <= 0:
                    st.error("Monthly amount must be greater than zero.")
                else:
                    conn.execute(
                        "UPDATE recurring_expenses SET "
                        "vendor = ?, category = ?, monthly_amount = ?, "
                        "frequency = ?, next_due_date = ?, active = ?, notes = ? "
                        "WHERE id = ?",
                        (
                            edit_vendor.strip(),
                            edit_category.strip() or None,
                            edit_amount,
                            edit_frequency,
                            edit_due.isoformat(),
                            1 if edit_active else 0,
                            edit_notes.strip() or None,
                            sel_rec_id,
                        ),
                    )
                    conn.commit()
                    st.success(f"Updated: {edit_vendor.strip()}")
                    st.rerun()

            if delete_clicked:
                conn.execute(
                    "DELETE FROM recurring_expenses WHERE id = ?",
                    (sel_rec_id,),
                )
                conn.commit()
                st.success(f"Deleted: {sel_rec['vendor']}")
                st.rerun()

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
conn.close()

st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#adb5bd;font-size:0.78rem;'>"
    "6th Degree Engineering &bull; Accounting &bull; "
    "Juan C. Castillo, P.E. (FL PE #98059)"
    "</div>",
    unsafe_allow_html=True,
)
