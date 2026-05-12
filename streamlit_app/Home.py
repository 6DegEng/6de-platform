"""
6th Degree Engineering -- Company Platform Dashboard
=====================================================
Main Streamlit entry point.  Launch via ``launch_platform.py`` or directly::

    streamlit run streamlit_app/Home.py --server.port 8502
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Path setup — MUST run before any local imports
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import pandas as pd
import streamlit as st

from db import ensure_db
from modules.dashboard.queries import get_dashboard_data
from streamlit_app.components.formatters import (
    days_until,
    format_currency,
    format_date,
    status_badge,
    urgency_color,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="6DE Platform",
    page_icon="\U0001f3d7️",       # construction crane emoji
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Global CSS — clean, professional look
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    /* Tighten top padding */
    .block-container { padding-top: 1.5rem; }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 16px 20px;
    }
    [data-testid="stMetricLabel"] {
        font-weight: 600;
        font-size: 0.9rem;
        color: #495057;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.6rem;
        font-weight: 700;
    }

    /* Sidebar branding */
    [data-testid="stSidebar"] [data-testid="stMarkdown"] h1 {
        font-size: 1.3rem;
        padding-bottom: 0.4rem;
        border-bottom: 2px solid #0d6efd;
    }

    /* Alert boxes — slightly rounded */
    .stAlert { border-radius: 6px; }

    /* Activity feed items */
    .activity-item {
        padding: 8px 0;
        border-bottom: 1px solid #eee;
        font-size: 0.88rem;
    }
    .activity-item:last-child { border-bottom: none; }
    .activity-time {
        color: #6c757d;
        font-size: 0.78rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("# 6th Degree Engineering")
    st.caption("ERP Platform v2.0")
    st.divider()
    st.markdown(
        "Pages load automatically from the **pages/** folder.  "
        "Use the navigation above to switch views."
    )
    st.divider()
    st.markdown(
        "<small style='color:#6c757d;'>Juan C. Castillo, P.E.&ensp;|&ensp;"
        "FL PE #98059</small>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
conn = ensure_db()
data = get_dashboard_data(conn)
conn.close()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("## Dashboard")
st.caption(format_date(str(__import__("datetime").date.today())))

# ===================================================================
# ROW 1 — Key Metrics
# ===================================================================
c1, c2, c3, c4 = st.columns(4)

with c1:
    delta = (
        f"+{data['new_projects_this_month']} this month"
        if data["new_projects_this_month"]
        else None
    )
    st.metric("Active Projects", data["active_projects"], delta=delta)

with c2:
    st.metric("Outstanding Revenue", format_currency(data["outstanding_amount"]))

with c3:
    overdue_val = format_currency(data["overdue_amount"])
    st.metric("Overdue Invoices", overdue_val)
    if data["overdue_amount"] > 0:
        st.markdown(
            f"<span style='color:#dc3545;font-weight:600;'>"
            f"{overdue_val} past due</span>",
            unsafe_allow_html=True,
        )

with c4:
    permit_count = len(data["expiring_permits"])
    st.metric("Expiring Permits", permit_count)
    if permit_count > 0:
        st.markdown(
            f"<span style='color:#fd7e14;font-weight:600;'>"
            f"{permit_count} within 30 days</span>",
            unsafe_allow_html=True,
        )

# ===================================================================
# ROW 1b — ERP Metrics
# ===================================================================
c5, c6, c7, c8 = st.columns(4)
with c5:
    st.metric("Pipeline Forecast", format_currency(data.get("pipeline_weighted", 0)))
with c6:
    unbilled = data.get("unbilled_time_amount", 0) + data.get("unbilled_expense_amount", 0)
    st.metric("Unbilled Work", format_currency(unbilled))
with c7:
    st.metric("Paid YTD", format_currency(data["paid_ytd"]))
with c8:
    bid_count = len(data.get("upcoming_bid_deadlines", []))
    st.metric("Bid Deadlines", f"{bid_count} upcoming")
    if bid_count > 0:
        st.markdown(
            f"<span style='color:#fd7e14;font-weight:600;'>"
            f"{bid_count} within 14 days</span>",
            unsafe_allow_html=True,
        )

# ===================================================================
# ROW 2 — Alerts (conditional)
# ===================================================================
has_alerts = (
    data["overdue_invoices"]
    or data["expiring_permits"]
    or data["cca_deadlines"]
    or data["upcoming_milestones"]
)

if has_alerts:
    st.markdown("---")
    st.markdown("### Alerts")

    # Overdue invoices
    for inv in data["overdue_invoices"]:
        owed = (inv.get("amount") or 0) - (inv.get("paid_amount") or 0)
        st.error(
            f"**Overdue Invoice {inv.get('invoice_number', '?')}** "
            f"({inv.get('project_name', 'Unknown Project')}) -- "
            f"{format_currency(owed)} due {format_date(inv.get('due_date'))}"
        )

    # Expiring permits
    for pm in data["expiring_permits"]:
        d = days_until(pm.get("expiration_date"))
        label = f"{d} day{'s' if d != 1 else ''}" if d is not None else "soon"
        st.warning(
            f"**Permit {pm.get('permit_number', 'N/A')}** "
            f"({pm.get('project_name', 'Unknown')}) expires in {label} -- "
            f"{pm.get('address', '')}"
        )

    # CCA deadlines
    for cca in data["cca_deadlines"]:
        d = days_until(cca.get("cca_deadline"))
        label = f"{d} day{'s' if d != 1 else ''}" if d is not None else "soon"
        st.warning(
            f"**CCA Deadline** Case {cca.get('case_number', 'N/A')} "
            f"({cca.get('project_name', 'Unknown')}) -- "
            f"due in {label} ({format_date(cca.get('cca_deadline'))})"
        )

    # Upcoming milestones
    for ms in data["upcoming_milestones"]:
        d = days_until(ms.get("due_date"))
        label = f"{d} day{'s' if d != 1 else ''}" if d is not None else "soon"
        st.info(
            f"**{ms.get('name', 'Milestone')}** "
            f"({ms.get('project_name', 'Unknown')}) -- due in {label}"
        )

# ===================================================================
# ROW 3 — Recent Activity + Quick Actions
# ===================================================================
st.markdown("---")
left_col, right_col = st.columns([3, 1])

# --- Recent Activity ---
with left_col:
    st.markdown("### Recent Activity")
    activity = data["recent_activity"][:10]
    if activity:
        for entry in activity:
            entity = (entry.get("entity_type") or "").replace("_", " ").title()
            action = (entry.get("action") or "").replace("_", " ").title()
            details = entry.get("details") or ""
            ts = format_date(entry.get("created_at"))
            st.markdown(
                f'<div class="activity-item">'
                f"<strong>{action}</strong> {entity} #{entry.get('entity_id', '')}"
                f"{(' -- ' + details) if details else ''}"
                f'<br><span class="activity-time">{ts}</span>'
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        st.info("No recent activity recorded.")

# --- Quick Actions ---
with right_col:
    st.markdown("### Quick Actions")
    st.markdown("")  # spacer

    if st.button("Create Project", use_container_width=True, type="primary"):
        try:
            st.switch_page("pages/1_Projects.py")
        except st.errors.StreamlitAPIException:
            st.toast("Projects page not yet available.", icon="⚠️")

    if st.button("Create Invoice", use_container_width=True):
        try:
            st.switch_page("pages/2_Billing.py")
        except st.errors.StreamlitAPIException:
            st.toast("Billing page not yet available.", icon="⚠️")

    if st.button("Add Permit", use_container_width=True):
        try:
            st.switch_page("pages/3_Permits.py")
        except st.errors.StreamlitAPIException:
            st.toast("Permits page not yet available.", icon="⚠️")

    if st.button("Log Time", use_container_width=True):
        try:
            st.switch_page("pages/5_Timekeeping.py")
        except st.errors.StreamlitAPIException:
            st.toast("Timekeeping page not yet available.", icon="⚠️")

    if st.button("New Opportunity", use_container_width=True):
        try:
            st.switch_page("pages/4_CRM.py")
        except st.errors.StreamlitAPIException:
            st.toast("CRM page not yet available.", icon="⚠️")

    st.divider()
    st.metric("Total Projects", data["total_projects"])

# ===================================================================
# ROW 4 — Charts
# ===================================================================
st.markdown("---")
st.markdown("### Portfolio Overview")
chart_left, chart_right = st.columns(2)

# --- Projects by Status ---
with chart_left:
    st.markdown("**Projects by Status**")
    pbs = data["projects_by_status"]
    if pbs:
        # Desired display order
        status_order = ["prospect", "active", "on_hold", "completed", "archived"]
        labels = [s.replace("_", " ").title() for s in status_order if s in pbs]
        values = [pbs[s] for s in status_order if s in pbs]
        df = pd.DataFrame({"Status": labels, "Count": values}).set_index("Status")
        st.bar_chart(df, horizontal=True)
    else:
        st.info("No project data yet.")

# --- Permits by Status ---
with chart_right:
    st.markdown("**Permits by Status**")
    pmbs = data["permits_by_status"]
    if pmbs:
        status_order = [
            "pending", "submitted", "in_review", "approved", "issued",
            "extension_requested", "expired", "failed_inspection", "closed",
        ]
        labels = [s.replace("_", " ").title() for s in status_order if s in pmbs]
        values = [pmbs[s] for s in status_order if s in pmbs]
        df = pd.DataFrame({"Status": labels, "Count": values}).set_index("Status")
        st.bar_chart(df, horizontal=True)
    else:
        st.info("No permit data yet.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#adb5bd;font-size:0.78rem;'>"
    "6th Degree Engineering &bull; Company Platform &bull; "
    "Juan C. Castillo, P.E. (FL PE #98059)"
    "</div>",
    unsafe_allow_html=True,
)
