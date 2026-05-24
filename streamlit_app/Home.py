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
from modules.invoicing.crud import get_ar_aging_report, get_ar_aging_summary
from streamlit_app.auth import require_auth, show_logout_button
from streamlit_app.components.formatters import (
    days_until,
    empty_state,
    format_currency,
    format_currency_compact,
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
    /* A2 fix: explicit dark color so values render on the light card
       background even when the user's system / Streamlit theme defaults
       to a light foreground colour. */
    [data-testid="stMetricValue"],
    [data-testid="stMetricValue"] > div {
        font-size: 1.6rem;
        font-weight: 700;
        color: #212529 !important;
    }
    [data-testid="stMetricDelta"] {
        color: #495057 !important;
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
# Auth gate
# ---------------------------------------------------------------------------
require_auth()

# ---------------------------------------------------------------------------
# Sidebar — grouped information architecture (4 sections)
# ---------------------------------------------------------------------------
# Hide the default auto-generated sidebar nav so our grouped nav is the
# only navigation the user sees.
st.markdown(
    """
    <style>
    /* Hide default Streamlit multi-page sidebar nav */
    [data-testid="stSidebarNav"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    show_logout_button()
    st.markdown("# 6th Degree Engineering")
    st.caption("ERP Platform v3.5")
    st.divider()

    # -- Overview --
    st.markdown(
        "<span style='font-size:0.75rem;font-weight:700;color:#6c757d;"
        "text-transform:uppercase;letter-spacing:0.05em;'>Overview</span>",
        unsafe_allow_html=True,
    )
    st.page_link("Home.py", label="Home", icon=":material/home:")

    st.markdown("")  # spacer

    # -- Sales Pipeline --
    st.markdown(
        "<span style='font-size:0.75rem;font-weight:700;color:#6c757d;"
        "text-transform:uppercase;letter-spacing:0.05em;'>Sales Pipeline</span>",
        unsafe_allow_html=True,
    )
    st.page_link("pages/4_CRM.py", label="CRM", icon=":material/handshake:")
    st.page_link("pages/7_Bids.py", label="Gov Solicitations", icon=":material/gavel:")
    st.page_link("pages/1_Projects.py", label="Projects", icon=":material/folder:")
    st.page_link("pages/3_Permits.py", label="Permits", icon=":material/description:")

    st.markdown("")  # spacer

    # -- Tools --
    st.markdown(
        "<span style='font-size:0.75rem;font-weight:700;color:#6c757d;"
        "text-transform:uppercase;letter-spacing:0.05em;'>Tools</span>",
        unsafe_allow_html=True,
    )
    st.page_link("pages/8_Calculator.py", label="Engineering", icon=":material/calculate:")

    st.markdown("")  # spacer

    # -- Finance --
    st.markdown(
        "<span style='font-size:0.75rem;font-weight:700;color:#6c757d;"
        "text-transform:uppercase;letter-spacing:0.05em;'>Finance</span>",
        unsafe_allow_html=True,
    )
    st.page_link("pages/2_Billing.py", label="Billing", icon=":material/receipt_long:")
    st.page_link("pages/5_Timekeeping.py", label="Timekeeping", icon=":material/schedule:")
    st.page_link("pages/6_Financials.py", label="Financials", icon=":material/monitoring:")
    st.page_link("pages/9_Accounting.py", label="Accounting", icon=":material/account_balance:")

    st.divider()
    st.markdown("**SharePoint mirror**")
    if st.button("Regenerate snapshots", key="ui:home:regen_mirrors",
                 use_container_width=True,
                 help="Render all _AUTO_*.md and _AUTO_portfolio_overview.xlsx, "
                      "uploading only files that changed."):
        from modules.mirror.sync import sync_all
        with st.spinner("Syncing snapshots…"):
            _result = sync_all(ensure_db())
        _counts = _result["project_counts"]
        st.success(
            f"Synced {_result['total_projects']} projects + 1 portfolio.  "
            f"Uploaded: {_counts.get('uploaded', 0) + _counts.get('local', 0)} · "
            f"Unchanged: {_counts.get('unchanged', 0)} · "
            f"Errors: {len(_result['errors'])}"
        )
        if _result["errors"]:
            with st.expander("Error details"):
                st.json(_result["errors"])
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
    # A2 fix: coerce to str so the value always renders even if the query
    # ever returns None; clamp the delta to non-zero to avoid noisy badges.
    active_n = int(data.get("active_projects") or 0)
    new_n = int(data.get("new_projects_this_month") or 0)
    delta = f"+{new_n} this month" if new_n else None
    st.metric("Active Projects", str(active_n), delta=delta)

with c2:
    outstanding_display = max(
        data["outstanding_amount"], data.get("project_outstanding", 0)
    )
    st.metric("Contracted Backlog", format_currency_compact(outstanding_display),
              help="Contracted work not yet invoiced (project basis). "
                   "See docs/data_definitions.md §6.")

with c3:
    overdue_val = format_currency_compact(data["overdue_amount"])
    st.metric("Overdue Invoices", overdue_val)
    if data["overdue_amount"] > 0:
        st.markdown(
            f"<span style='color:#dc3545;font-weight:600;'>"
            f"{format_currency(data['overdue_amount'])} past due</span>",
            unsafe_allow_html=True,
        )

with c4:
    # A2 fix: expiring_permits is always a list (default []), so len() is 0
    # when empty — but we coerce to str to guarantee the value slot renders.
    permit_count = len(data.get("expiring_permits") or [])
    st.metric("Expiring Permits", str(permit_count))
    if permit_count > 0:
        st.markdown(
            f"<span style='color:#fd7e14;font-weight:600;'>"
            f"{permit_count} within 30 days</span>",
            unsafe_allow_html=True,
        )

# ===================================================================
# ROW 1b — Financial Metrics
# ===================================================================
c5, c6, c7, c8 = st.columns(4)
with c5:
    # A5 disambiguation: this is cash-inflow-YTD from the bank transactions
    # import, NOT invoiced revenue. See docs/data_definitions.md.
    income_ytd = data.get("txn_income_ytd", 0) or data["paid_ytd"]
    st.metric("Cash Inflows YTD", format_currency_compact(income_ytd),
              help="Sum of positive bank transactions year-to-date (cash basis). "
                   "See docs/data_definitions.md.")
with c6:
    expenses_ytd = abs(data.get("txn_expenses_ytd", 0))
    st.metric("Cash Outflows YTD", format_currency_compact(expenses_ytd),
              help="Sum of negative bank transactions year-to-date (cash basis).")
with c7:
    net_ytd = data.get("txn_net_ytd", 0)
    st.metric("Net Cashflow YTD", format_currency_compact(net_ytd))
with c8:
    burn = data.get("recurring_monthly_burn", 0)
    st.metric("Monthly Burn", format_currency_compact(burn))

# ===================================================================
# ROW 1c — Pipeline & Bids
# ===================================================================
c9, c10, c11, c12 = st.columns(4)
with c9:
    # A3 fix: was "$157,..." truncating; use compact form ($158K)
    st.metric("Pipeline Forecast",
              format_currency_compact(data.get("pipeline_weighted", 0)))
with c10:
    unbilled = data.get("unbilled_time_amount", 0) + data.get("unbilled_expense_amount", 0)
    st.metric("Unbilled Work", format_currency_compact(unbilled))
with c11:
    total_projects = data.get("total_projects", 0)
    active_projects = data.get("active_projects", 0)
    pct = (active_projects / total_projects * 100) if total_projects else 0
    st.metric("Active Rate", f"{pct:.0f}%")
with c12:
    bid_count = len(data.get("upcoming_bid_deadlines", []))
    st.metric("Bid Deadlines", f"{bid_count} upcoming")
    if bid_count > 0:
        st.markdown(
            f"<span style='color:#fd7e14;font-weight:600;'>"
            f"{bid_count} within 14 days</span>",
            unsafe_allow_html=True,
        )

# ===================================================================
# ROW 1d — AR Aging
# ===================================================================
st.markdown("---")
st.markdown("### AR Aging")

aging_summary = get_ar_aging_summary(conn)
aging_total = sum(aging_summary.values())

_bucket_colors = {
    "current": "#198754",
    "1-30": "#fd7e14",
    "31-60": "#e67e22",
    "61-90": "#dc3545",
    "90+": "#8b0000",
}
_bucket_labels = {
    "current": "Current",
    "1-30": "1-30 Days",
    "31-60": "31-60 Days",
    "61-90": "61-90 Days",
    "90+": "90+ Days",
}

ar1, ar2, ar3, ar4, ar5, ar6 = st.columns(6)
_ar_cols = [ar1, ar2, ar3, ar4, ar5]
for _col, (_bucket, _amount) in zip(_ar_cols, aging_summary.items()):
    _color = _bucket_colors[_bucket]
    _label = _bucket_labels[_bucket]
    _col.markdown(
        f"<div style='border-left:4px solid {_color};padding:8px 12px;'>"
        f"<span style='font-size:0.85rem;color:#6c757d;'>{_label}</span><br>"
        f"<span style='font-size:1.3rem;font-weight:700;'>"
        f"{format_currency(_amount)}</span></div>",
        unsafe_allow_html=True,
    )
ar6.markdown(
    f"<div style='border-left:4px solid #0d6efd;padding:8px 12px;'>"
    f"<span style='font-size:0.85rem;color:#6c757d;'>Total</span><br>"
    f"<span style='font-size:1.3rem;font-weight:700;'>"
    f"{format_currency(aging_total)}</span></div>",
    unsafe_allow_html=True,
)

# Top delinquent clients callout (90+ days past due)
if aging_summary.get("90+", 0) > 0:
    aging_rows = get_ar_aging_report(conn)
    delinquent = [r for r in aging_rows if r["aging_bucket"] == "90+"]
    # Aggregate by client
    client_totals: dict[str, float] = {}
    for r in delinquent:
        client = r["client_name"] or r["project_name"] or "Unknown"
        client_totals[client] = client_totals.get(client, 0) + (r["balance_due"] or 0)
    top_clients = sorted(client_totals.items(), key=lambda x: x[1], reverse=True)[:3]
    client_lines = "  \n".join(
        f"- **{name}**: {format_currency(bal)}" for name, bal in top_clients
    )
    st.warning(
        f"**{format_currency(aging_summary['90+'])} is 90+ days past due.** "
        f"Top delinquent clients:  \n{client_lines}"
    )

# ===================================================================
# ROW 2 — Alerts (conditional)
# ===================================================================
has_alerts = (
    data["overdue_invoices"]
    or data["expiring_permits"]
    or data["cca_deadlines"]
    or data["upcoming_milestones"]
    or data.get("recurring_due_soon")
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

    # Recurring expenses due soon
    for rec in data.get("recurring_due_soon", []):
        st.warning(
            f"**Recurring: {rec.get('vendor', '?')}** -- "
            f"{format_currency(rec.get('monthly_amount', 0))} "
            f"due {format_date(rec.get('next_due_date'))}"
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
        st.info(empty_state("activity"))

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

    if st.button("Accounting", use_container_width=True):
        try:
            st.switch_page("pages/9_Accounting.py")
        except st.errors.StreamlitAPIException:
            st.toast("Accounting page not yet available.", icon="⚠️")

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
        status_order = ["prospect", "active", "on_hold", "completed", "archived"]
        labels = [s.replace("_", " ").title() for s in status_order if s in pbs]
        values = [pbs[s] for s in status_order if s in pbs]
        df = pd.DataFrame({"Status": labels, "Count": values}).set_index("Status")
        if df["Count"].sum() > 0:
            st.bar_chart(df, horizontal=True)
        else:
            st.info("No project data yet.")
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
        if df["Count"].sum() > 0:
            st.bar_chart(df, horizontal=True)
        else:
            st.info("No permit data yet.")
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
