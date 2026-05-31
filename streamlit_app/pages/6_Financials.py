"""Financials dashboard for the 6th Degree Engineering platform.

Displays AR aging, project profitability, utilization metrics, and
revenue analytics across four tabs with a top-level metrics row.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_app.components.sidebar import render_sidebar
from streamlit_app.components.branding import empty_state
from streamlit_app.components.branding import page_header

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from db import ensure_db  # noqa: E402
from modules.financials.queries import (  # noqa: E402
    get_financial_summary,
    get_profitability_by_client,
    get_project_profitability,
    get_revenue_by_month,
    get_revenue_forecast,
    get_utilization_by_role,
)
from modules.invoicing.crud import get_ar_aging_report, get_ar_aging_summary  # noqa: E402
from streamlit_app.components.formatters import (  # noqa: E402
    format_currency,
    format_percentage,
)
from streamlit_app.auth import require_auth  # noqa: E402

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Financials | 6DE Platform",
    page_icon="$",
    layout="wide",
)
require_auth()
render_sidebar()

# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------
conn = ensure_db()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
page_header("Financials", "Cashflow, AR aging & forecasts", "📈")
st.caption("6th Degree Engineering - Financial Analytics & Reporting")
st.info(
    "**Invoice / accrual basis** -- what has been billed. "
    "For cash movements, see **Accounting**.",
    icon="ℹ️",
)

# ---------------------------------------------------------------------------
# Metrics row
# ---------------------------------------------------------------------------
summary = get_financial_summary(conn)
forecast = get_revenue_forecast(conn)

m1, m2, m3, m4, m5 = st.columns(5)
# A5 fix: renamed "Revenue YTD" -> "Invoiced Revenue YTD" so it can't be
# confused with Home's "Cash Inflows YTD". See docs/data_definitions.md.
m1.metric(
    "Invoiced Revenue YTD",
    format_currency(summary["revenue_ytd"]),
    help="Sum of paid invoices, invoice basis (not cash). "
         "See docs/data_definitions.md §4.",
)
m2.metric(
    "Outstanding AR",
    format_currency(summary["outstanding"]),
    help="Sent + overdue invoice balance. See docs/data_definitions.md §5.",
)
m3.metric(
    "Overdue",
    format_currency(summary["overdue"]),
    delta_color="inverse",
    help="Past-due-date unpaid invoice balance. "
         "See docs/data_definitions.md §7.",
)
m4.metric(
    "Unbilled T&E",
    format_currency(summary["unbilled_time"] + summary["unbilled_expenses"]),
    help="Unbilled billable time + reimbursable expenses (with markup). "
         "See docs/data_definitions.md §8.",
)
m5.metric(
    "Pipeline Forecast",
    format_currency(forecast["total_forecast"]),
    help="Outstanding invoices + pending schedules + weighted pipeline. "
         "See docs/data_definitions.md §9.",
)

st.divider()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_aging, tab_profit, tab_util, tab_revenue = st.tabs(
    ["AR Aging", "Profitability", "Utilization", "Revenue"]
)

# ============================= TAB 1: AR AGING ============================
with tab_aging:
    st.subheader("Accounts Receivable Aging")

    aging_summary = get_ar_aging_summary(conn)
    aging_total = sum(aging_summary.values())

    # Bucket cards with color coding
    bucket_colors = {
        "current": "#198754",   # green
        "1-30": "#fd7e14",      # yellow-orange
        "31-60": "#e67e22",     # orange
        "61-90": "#dc3545",     # red
        "90+": "#8b0000",       # dark red
    }
    bucket_labels = {
        "current": "Current",
        "1-30": "1-30 Days",
        "31-60": "31-60 Days",
        "61-90": "61-90 Days",
        "90+": "90+ Days",
    }

    bc1, bc2, bc3, bc4, bc5, bc6 = st.columns(6)
    cols = [bc1, bc2, bc3, bc4, bc5]
    for col, (bucket, amount) in zip(cols, aging_summary.items()):
        color = bucket_colors[bucket]
        label = bucket_labels[bucket]
        col.markdown(
            f"<div style='border-left:4px solid {color};padding:8px 12px;'>"
            f"<span style='font-size:0.85rem;color:#6c757d;'>{label}</span><br>"
            f"<span style='font-size:1.3rem;font-weight:700;'>"
            f"{format_currency(amount)}</span></div>",
            unsafe_allow_html=True,
        )
    bc6.markdown(
        f"<div style='border-left:4px solid #0d6efd;padding:8px 12px;'>"
        f"<span style='font-size:0.85rem;color:#6c757d;'>Total</span><br>"
        f"<span style='font-size:1.3rem;font-weight:700;'>"
        f"{format_currency(aging_total)}</span></div>",
        unsafe_allow_html=True,
    )

    st.markdown("")

    # Detailed AR table
    aging_rows = get_ar_aging_report(conn)
    if aging_rows:
        ar_data = []
        for r in aging_rows:
            bucket = r["aging_bucket"]
            color = bucket_colors.get(bucket, "#6c757d")
            ar_data.append({
                "Invoice": r["invoice_number"],
                "Job #": r["job_number"],
                "Project": r["project_name"],
                "Client": r["client_name"] or "-",
                "Amount": r["amount"],
                "Paid": r["paid_amount"] or 0,
                "Balance Due": r["balance_due"],
                "Issue Date": r["issue_date"],
                "Due Date": r["due_date"],
                "Days Past Due": r["days_past_due"],
                "Bucket": bucket_labels.get(bucket, bucket),
            })

        df_ar = pd.DataFrame(ar_data)
        st.dataframe(
            df_ar.style.format({
                "Amount": "${:,.2f}",
                "Paid": "${:,.2f}",
                "Balance Due": "${:,.2f}",
            }).map(
                lambda _: "color: #198754",
                subset=pd.IndexSlice[df_ar["Bucket"] == "Current", :],
            ).map(
                lambda _: "color: #dc3545; font-weight: 600",
                subset=pd.IndexSlice[df_ar["Days Past Due"] > 60, :],
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        empty_state("No outstanding invoices in the aging report.")

# ========================== TAB 2: PROFITABILITY ==========================
with tab_profit:
    st.subheader("Project Profitability")

    prof_rows = get_project_profitability(conn)
    if prof_rows:
        prof_data = []
        for r in prof_rows:
            invoiced = r["total_invoiced"] or 0
            labor = r["total_labor_cost"] or 0
            expenses = r["total_expenses"] or 0
            margin = r["net_margin"] or 0
            margin_pct = round((margin / invoiced) * 100, 1) if invoiced > 0 else 0.0

            prof_data.append({
                "Job #": r["job_number"],
                "Project": r["name"],
                "Labor Cost": labor,
                "Expenses": expenses,
                "Invoiced": invoiced,
                "Paid": r["total_paid"] or 0,
                "Net Margin": margin,
                "Margin %": margin_pct,
            })

        df_prof = pd.DataFrame(prof_data)

        # Filter out projects with zero activity
        df_active = df_prof[
            (df_prof["Labor Cost"] > 0)
            | (df_prof["Expenses"] > 0)
            | (df_prof["Invoiced"] > 0)
        ]
        if df_active.empty:
            df_active = df_prof

        def _highlight_margin(val):
            """Highlight negative margins in red."""
            if isinstance(val, (int, float)) and val < 0:
                return "color: #dc3545; font-weight: 600"
            return ""

        st.dataframe(
            df_active.style.format({
                "Labor Cost": "${:,.2f}",
                "Expenses": "${:,.2f}",
                "Invoiced": "${:,.2f}",
                "Paid": "${:,.2f}",
                "Net Margin": "${:,.2f}",
                "Margin %": "{:.1f}%",
            }).map(_highlight_margin, subset=["Net Margin", "Margin %"]),
            use_container_width=True,
            hide_index=True,
        )

        # Client profitability summary
        st.markdown("---")
        st.subheader("Profitability by Client")
        client_data = get_profitability_by_client(conn)
        if client_data:
            df_client = pd.DataFrame(client_data).rename(columns={
                "client_name": "Client",
                "project_count": "Projects",
                "total_labor_cost": "Labor Cost",
                "total_expenses": "Expenses",
                "total_invoiced": "Invoiced",
                "total_paid": "Paid",
                "net_margin": "Net Margin",
            })
            st.dataframe(
                df_client.style.format({
                    "Labor Cost": "${:,.2f}",
                    "Expenses": "${:,.2f}",
                    "Invoiced": "${:,.2f}",
                    "Paid": "${:,.2f}",
                    "Net Margin": "${:,.2f}",
                }).map(
                    _highlight_margin,
                    subset=["Net Margin"],
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            empty_state("No client profitability data available.")
    else:
        empty_state("No project profitability data available.")

# ============================ TAB 3: UTILIZATION ==========================
with tab_util:
    st.subheader("Utilization by Role")

    # Date range selector
    ucol1, ucol2 = st.columns(2)
    current_year = date.today().year
    util_from = ucol1.date_input(
        "From",
        value=date(current_year, 1, 1),
        key="util_from",
    )
    util_to = ucol2.date_input(
        "To",
        value=date.today(),
        key="util_to",
    )

    util_data = get_utilization_by_role(
        conn, util_from.isoformat(), util_to.isoformat()
    )

    if util_data:
        df_util = pd.DataFrame(util_data)

        # Format role names for display
        df_util["Role"] = df_util["role"].apply(
            lambda x: (x or "").replace("_", " ").title()
        )

        # Utilization bar chart
        st.markdown("**Billable Utilization %**")
        chart_df = df_util[["Role", "utilization_pct"]].copy()
        chart_df = chart_df.rename(columns={"utilization_pct": "Utilization %"})
        chart_df = chart_df.set_index("Role")
        st.bar_chart(chart_df, horizontal=True)

        # Detail table
        st.markdown("")
        display_df = df_util[
            ["Role", "total_hours", "billable_hours", "non_billable_hours",
             "utilization_pct"]
        ].copy()
        display_df = display_df.rename(columns={
            "total_hours": "Total Hours",
            "billable_hours": "Billable Hours",
            "non_billable_hours": "Non-Billable Hours",
            "utilization_pct": "Utilization %",
        })
        st.dataframe(
            display_df.style.format({
                "Total Hours": "{:,.1f}",
                "Billable Hours": "{:,.1f}",
                "Non-Billable Hours": "{:,.1f}",
                "Utilization %": "{:.1f}%",
            }),
            use_container_width=True,
            hide_index=True,
        )

        # Monthly hours trend
        st.markdown("---")
        st.subheader("Monthly Hours Trend")
        monthly_hours = conn.execute(
            "SELECT "
            "    strftime('%Y-%m', entry_date) AS month, "
            "    ROUND(SUM(CASE WHEN billable = 1 THEN hours ELSE 0 END), 1) "
            "        AS billable, "
            "    ROUND(SUM(CASE WHEN billable = 0 THEN hours ELSE 0 END), 1) "
            "        AS non_billable "
            "FROM time_entries "
            "WHERE entry_date BETWEEN ? AND ? "
            "GROUP BY strftime('%Y-%m', entry_date) "
            "ORDER BY month",
            (util_from.isoformat(), util_to.isoformat()),
        ).fetchall()

        if monthly_hours:
            df_monthly = pd.DataFrame([dict(r) for r in monthly_hours])
            df_monthly = df_monthly.rename(columns={
                "month": "Month",
                "billable": "Billable",
                "non_billable": "Non-Billable",
            })
            df_monthly = df_monthly.set_index("Month")
            st.bar_chart(df_monthly)
        else:
            empty_state("No time entry data for the selected period.")
    else:
        empty_state("No time entries found for the selected date range.")

# ============================== TAB 4: REVENUE ============================
with tab_revenue:
    st.subheader("Revenue Analysis")

    # Year selector
    rcol1, _ = st.columns([1, 3])
    rev_year = rcol1.number_input(
        "Year",
        min_value=2020,
        max_value=2030,
        value=date.today().year,
        step=1,
        key="rev_year",
    )

    monthly_rev = get_revenue_by_month(conn, year=int(rev_year))

    if monthly_rev:
        df_rev = pd.DataFrame(monthly_rev)

        # Monthly revenue bar chart
        st.markdown("**Monthly Revenue (Paid Invoices)**")
        chart_data = df_rev[["month", "total_paid"]].copy()
        chart_data = chart_data.rename(columns={
            "month": "Month",
            "total_paid": "Revenue",
        })
        chart_data = chart_data.set_index("Month")
        st.bar_chart(chart_data)

        # YTD cumulative line
        st.markdown("**YTD Cumulative Revenue**")
        df_rev["cumulative"] = df_rev["total_paid"].cumsum()
        cum_data = df_rev[["month", "cumulative"]].copy()
        cum_data = cum_data.rename(columns={
            "month": "Month",
            "cumulative": "Cumulative Revenue",
        })
        cum_data = cum_data.set_index("Month")
        st.line_chart(cum_data)

        # Detail table
        st.markdown("")
        detail = df_rev[["month", "total_paid", "invoice_count", "cumulative"]].copy()
        detail = detail.rename(columns={
            "month": "Month",
            "total_paid": "Revenue",
            "invoice_count": "Invoices",
            "cumulative": "Cumulative",
        })
        st.dataframe(
            detail.style.format({
                "Revenue": "${:,.2f}",
                "Cumulative": "${:,.2f}",
            }),
            use_container_width=True,
            hide_index=True,
        )
    else:
        empty_state(f"No paid invoices found for {rev_year}.")

    # Pipeline forecast section
    st.markdown("---")
    st.subheader("Revenue Forecast")

    fc1, fc2, fc3, fc4 = st.columns(4)
    fc1.metric(
        "Outstanding Invoices",
        format_currency(forecast["outstanding_invoices"]),
    )
    fc2.metric(
        "Pending Schedules",
        format_currency(forecast["scheduled_pending"]),
    )
    fc3.metric(
        "Weighted Pipeline",
        format_currency(forecast["pipeline_weighted"]),
        help="Estimated value x probability for active opportunities",
    )
    fc4.metric(
        "Total Forecast",
        format_currency(forecast["total_forecast"]),
        help="Sum of outstanding + pending + weighted pipeline",
    )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#adb5bd;font-size:0.78rem;'>"
    "6th Degree Engineering &bull; Financials &bull; "
    "Juan C. Castillo, P.E. (FL PE #98059)"
    "</div>",
    unsafe_allow_html=True,
)
