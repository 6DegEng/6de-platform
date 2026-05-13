"""Billing & Invoicing page for the 6th Degree Engineering platform.

Displays financial summaries, invoice management, and proposal tracking.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Path bootstrap — ensure the platform root is on sys.path
# ---------------------------------------------------------------------------
_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from db import ensure_db  # noqa: E402
from modules.billing.crud import (  # noqa: E402
    accept_proposal,
    create_invoice,
    create_proposal,
    get_billing_summary,
    get_invoice,
    get_project_billing,
    list_invoices,
    list_proposals,
    mark_overdue,
    mark_paid,
    update_invoice,
    update_proposal,
)
from streamlit_app.auth import require_auth  # noqa: E402

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Billing | 6DE Platform", page_icon="$", layout="wide")
require_auth()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_currency(val: float | None) -> str:
    """Format a number as $X,XXX.XX."""
    if val is None:
        return "$0.00"
    return f"${val:,.2f}"


_STATUS_COLORS = {
    "paid": "green",
    "overdue": "red",
    "sent": "orange",
    "draft": "gray",
    "void": "gray",
    "accepted": "green",
    "declined": "red",
    "revised": "blue",
}


def _status_badge(status: str) -> str:
    """Return a colored markdown badge for a status value."""
    color = _STATUS_COLORS.get(status, "gray")
    return f":{color}[**{status.upper()}**]"


def _date_warning(due_date_str: str | None, status: str) -> str:
    """Return a warning string if an invoice is near or past due."""
    if status in ("paid", "void") or not due_date_str:
        return ""
    try:
        due = datetime.strptime(due_date_str, "%Y-%m-%d").date()
    except ValueError:
        return ""
    delta = (due - date.today()).days
    if delta < 0:
        return f" :red[({abs(delta)}d overdue)]"
    if delta <= 7:
        return f" :orange[(due in {delta}d)]"
    return ""


def _get_projects(conn):
    """Fetch all projects for dropdowns."""
    return conn.execute(
        "SELECT id, job_number, name FROM projects ORDER BY job_number DESC"
    ).fetchall()


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------
conn = ensure_db()

# Auto-mark overdue invoices on every page load
overdue_count = mark_overdue(conn)
if overdue_count:
    st.toast(f"Marked {overdue_count} invoice(s) as overdue", icon="⚠️")

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("Billing & Invoicing")
st.caption("6th Degree Engineering - Financial Overview")

# ---------------------------------------------------------------------------
# Financial summary metrics
# ---------------------------------------------------------------------------
summary = get_billing_summary(conn)
counts = summary["invoice_count_by_status"]

col1, col2, col3, col4 = st.columns(4)
col1.metric(
    label="Outstanding",
    value=_fmt_currency(summary["total_outstanding"]),
    help="Total unpaid invoices (sent + overdue)",
)
col2.metric(
    label="Overdue",
    value=_fmt_currency(summary["total_overdue"]),
    delta=f"{counts.get('overdue', 0)} invoices" if counts.get("overdue") else None,
    delta_color="inverse",
    help="Invoices past their due date",
)
col3.metric(
    label="Paid YTD",
    value=_fmt_currency(summary["total_paid_ytd"]),
    help="Total payments received this calendar year",
)
col4.metric(
    label="Drafts",
    value=str(counts.get("draft", 0)),
    help="Invoices in draft status",
)

st.divider()

# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------
tab_invoices, tab_proposals, tab_project = st.tabs(
    ["Invoices", "Proposals", "Project Billing"]
)

# ============================= INVOICES TAB ===============================
with tab_invoices:
    # -- Filters --
    fcol1, fcol2 = st.columns(2)
    projects = _get_projects(conn)
    project_options = {0: "All Projects"} | {
        p["id"]: f'{p["job_number"]} - {p["name"]}' for p in projects
    }
    filter_project = fcol1.selectbox(
        "Filter by Project",
        options=list(project_options.keys()),
        format_func=lambda x: project_options[x],
        key="inv_filter_project",
    )
    status_options = ["All", "draft", "sent", "paid", "overdue", "void"]
    filter_status = fcol2.selectbox(
        "Filter by Status", status_options, key="inv_filter_status"
    )

    inv_project_id = filter_project if filter_project else None
    inv_status = filter_status if filter_status != "All" else None
    invoices = list_invoices(conn, project_id=inv_project_id, status_filter=inv_status)

    if invoices:
        for inv in invoices:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                c1.markdown(
                    f"**{inv['invoice_number']}** - "
                    f"{inv['project_name'] or 'Unknown Project'}"
                )
                c2.markdown(f"Amount: **{_fmt_currency(inv['amount'])}**")
                badge = _status_badge(inv["status"])
                due_warn = _date_warning(inv["due_date"], inv["status"])
                c3.markdown(f"{badge}{due_warn}")

                # Action buttons
                with c4:
                    btn_cols = st.columns(2)
                    if inv["status"] in ("draft", "sent", "overdue"):
                        if btn_cols[0].button(
                            "Mark Paid",
                            key=f"pay_{inv['id']}",
                            type="primary",
                            use_container_width=True,
                        ):
                            mark_paid(conn, inv["id"])
                            st.rerun()
                    if inv["status"] == "draft":
                        if btn_cols[1].button(
                            "Send",
                            key=f"send_{inv['id']}",
                            use_container_width=True,
                        ):
                            update_invoice(conn, inv["id"], status="sent")
                            st.rerun()

                # Expandable details
                with st.expander("Details"):
                    dcol1, dcol2, dcol3 = st.columns(3)
                    dcol1.write(f"**Issue Date:** {inv['issue_date'] or '-'}")
                    dcol2.write(f"**Due Date:** {inv['due_date'] or '-'}")
                    dcol3.write(
                        f"**Paid Date:** {inv['paid_date'] or '-'}"
                    )
                    if inv["description"]:
                        st.write(f"**Description:** {inv['description']}")
                    if inv["payment_method"]:
                        st.write(f"**Payment Method:** {inv['payment_method']}")
                    if inv["notes"]:
                        st.write(f"**Notes:** {inv['notes']}")
    else:
        st.info("No invoices match the current filters.")

    # -- Create new invoice --
    st.subheader("Create New Invoice")
    if not projects:
        st.warning("No projects found. Create a project first.")
    else:
        with st.form("new_invoice_form", clear_on_submit=True):
            ncol1, ncol2 = st.columns(2)
            new_inv_project = ncol1.selectbox(
                "Project",
                options=[p["id"] for p in projects],
                format_func=lambda x: next(
                    f'{p["job_number"]} - {p["name"]}'
                    for p in projects
                    if p["id"] == x
                ),
                key="new_inv_project",
            )
            new_inv_amount = ncol2.number_input(
                "Amount ($)", min_value=0.0, step=100.0, format="%.2f"
            )
            ncol3, ncol4 = st.columns(2)
            new_inv_desc = ncol3.text_input("Description (optional)")
            new_inv_date = ncol4.date_input("Issue Date", value=date.today())

            submitted = st.form_submit_button(
                "Create Invoice", type="primary", use_container_width=True
            )
            if submitted:
                if new_inv_amount <= 0:
                    st.error("Amount must be greater than zero.")
                else:
                    new_id = create_invoice(
                        conn,
                        project_id=new_inv_project,
                        amount=new_inv_amount,
                        description=new_inv_desc or None,
                        issue_date=new_inv_date.isoformat(),
                    )
                    new_inv = get_invoice(conn, new_id)
                    st.success(
                        f"Invoice **{new_inv['invoice_number']}** created for "
                        f"{_fmt_currency(new_inv_amount)}"
                    )
                    st.rerun()

# ============================ PROPOSALS TAB ================================
with tab_proposals:
    # -- Filters --
    pcol1, pcol2 = st.columns(2)
    prop_filter_project = pcol1.selectbox(
        "Filter by Project",
        options=list(project_options.keys()),
        format_func=lambda x: project_options[x],
        key="prop_filter_project",
    )
    prop_status_options = ["All", "draft", "sent", "accepted", "declined", "revised"]
    prop_filter_status = pcol2.selectbox(
        "Filter by Status", prop_status_options, key="prop_filter_status"
    )

    p_proj_id = prop_filter_project if prop_filter_project else None
    p_status = prop_filter_status if prop_filter_status != "All" else None
    proposals = list_proposals(conn, project_id=p_proj_id, status_filter=p_status)

    if proposals:
        for prop in proposals:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                c1.markdown(
                    f"**{prop['proposal_number']}** - "
                    f"{prop['project_name'] or 'Unknown Project'}"
                )
                c2.markdown(f"Fee: **{_fmt_currency(prop['fee_amount'])}**")
                c3.markdown(_status_badge(prop["status"]))

                with c4:
                    btn_cols = st.columns(2)
                    if prop["status"] in ("draft", "sent"):
                        if btn_cols[0].button(
                            "Accept",
                            key=f"accept_{prop['id']}",
                            type="primary",
                            use_container_width=True,
                        ):
                            accept_proposal(conn, prop["id"])
                            st.rerun()
                    if prop["status"] == "draft":
                        if btn_cols[1].button(
                            "Send",
                            key=f"prop_send_{prop['id']}",
                            use_container_width=True,
                        ):
                            update_proposal(
                                conn,
                                prop["id"],
                                status="sent",
                                sent_date=date.today().isoformat(),
                            )
                            st.rerun()
                    if prop["status"] in ("draft", "sent"):
                        if st.button(
                            "Decline",
                            key=f"decline_{prop['id']}",
                            use_container_width=True,
                        ):
                            update_proposal(conn, prop["id"], status="declined")
                            st.rerun()

                # Expandable details
                with st.expander("Details"):
                    if prop["scope_text"]:
                        st.write(f"**Scope:** {prop['scope_text']}")
                    dcol1, dcol2 = st.columns(2)
                    dcol1.write(f"**Sent Date:** {prop['sent_date'] or '-'}")
                    dcol2.write(f"**Accepted Date:** {prop['accepted_date'] or '-'}")
                    if prop["notes"]:
                        st.write(f"**Notes:** {prop['notes']}")
    else:
        st.info("No proposals match the current filters.")

    # -- Create new proposal --
    st.subheader("Create New Proposal")
    if not projects:
        st.warning("No projects found. Create a project first.")
    else:
        with st.form("new_proposal_form", clear_on_submit=True):
            ncol1, ncol2 = st.columns(2)
            new_prop_project = ncol1.selectbox(
                "Project",
                options=[p["id"] for p in projects],
                format_func=lambda x: next(
                    f'{p["job_number"]} - {p["name"]}'
                    for p in projects
                    if p["id"] == x
                ),
                key="new_prop_project",
            )
            new_prop_fee = ncol2.number_input(
                "Fee Amount ($)", min_value=0.0, step=100.0, format="%.2f"
            )
            new_prop_scope = st.text_area("Scope of Work (optional)")

            submitted = st.form_submit_button(
                "Create Proposal", type="primary", use_container_width=True
            )
            if submitted:
                if new_prop_fee <= 0:
                    st.error("Fee amount must be greater than zero.")
                else:
                    new_id = create_proposal(
                        conn,
                        project_id=new_prop_project,
                        fee_amount=new_prop_fee,
                        scope_text=new_prop_scope or None,
                    )
                    st.success(
                        f"Proposal created for {_fmt_currency(new_prop_fee)}"
                    )
                    st.rerun()

# ========================= PROJECT BILLING TAB =============================
with tab_project:
    if not projects:
        st.warning("No projects found.")
    else:
        selected_project = st.selectbox(
            "Select Project",
            options=[p["id"] for p in projects],
            format_func=lambda x: next(
                f'{p["job_number"]} - {p["name"]}'
                for p in projects
                if p["id"] == x
            ),
            key="project_billing_select",
        )

        billing = get_project_billing(conn, selected_project)

        # Summary metrics for this project
        mcol1, mcol2, mcol3, mcol4 = st.columns(4)
        mcol1.metric("Total Proposed", _fmt_currency(billing["total_proposed"]))
        mcol2.metric("Total Invoiced", _fmt_currency(billing["total_invoiced"]))
        mcol3.metric("Total Paid", _fmt_currency(billing["total_paid"]))
        mcol4.metric(
            "Balance Due",
            _fmt_currency(billing["balance_due"]),
            delta=(
                f"-{_fmt_currency(billing['balance_due'])}"
                if billing["balance_due"] > 0
                else None
            ),
            delta_color="inverse",
        )

        st.divider()

        # Proposals section
        st.subheader("Proposals")
        if billing["proposals"]:
            for prop in billing["proposals"]:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([4, 2, 2])
                    c1.markdown(f"**{prop['proposal_number']}**")
                    c2.write(_fmt_currency(prop["fee_amount"]))
                    c3.markdown(_status_badge(prop["status"]))
                    if prop["scope_text"]:
                        st.caption(prop["scope_text"][:200])
        else:
            st.info("No proposals for this project.")

        # Invoices section
        st.subheader("Invoices")
        if billing["invoices"]:
            for inv in billing["invoices"]:
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                    c1.markdown(f"**{inv['invoice_number']}**")
                    c2.write(_fmt_currency(inv["amount"]))
                    badge = _status_badge(inv["status"])
                    due_warn = _date_warning(inv["due_date"], inv["status"])
                    c3.markdown(f"{badge}{due_warn}")
                    c4.write(f"Issued: {inv['issue_date'] or '-'}")
        else:
            st.info("No invoices for this project.")
