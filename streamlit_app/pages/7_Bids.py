"""Government Bids, Documents & Subconsultants — 6DE Platform.

Tracks government solicitations (MFMP, DemandStar, BidNet, Sam.gov,
county-direct), manages document links across all entities, and maintains
the subconsultant/vendor roster with purchase orders.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

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
from modules.bids.crud import (  # noqa: E402
    create_bid,
    get_bid_stats,
    get_upcoming_deadlines,
    list_bids,
    search_bids,
    set_go_no_go,
    update_bid,
)
from modules.subconsultants.crud import (  # noqa: E402
    create_purchase_order,
    create_subconsultant,
    list_purchase_orders,
    list_subconsultants,
    update_subconsultant,
)
from streamlit_app.components.formatters import (  # noqa: E402
    days_until,
    status_badge,
)
from streamlit_app.auth import require_auth  # noqa: E402

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Gov Solicitations | 6DE",
    page_icon="📋",
    layout="wide",
)
require_auth()
render_sidebar()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PORTALS = ["MFMP", "DemandStar", "BidNet", "Sam.gov", "county_direct", "other"]
PORTAL_LABELS: dict[str, str] = {
    "MFMP": "MFMP",
    "DemandStar": "DemandStar",
    "BidNet": "BidNet",
    "Sam.gov": "Sam.gov",
    "county_direct": "County Direct",
    "other": "Other",
}

BID_STATUSES = [
    "monitoring", "go", "no_go", "preparing",
    "submitted", "won", "lost", "cancelled", "protest",
]
BID_STATUS_LABELS: dict[str, str] = {
    "monitoring": "Monitoring",
    "go": "Go",
    "no_go": "No-Go",
    "preparing": "Preparing",
    "submitted": "Submitted",
    "won": "Won",
    "lost": "Lost",
    "cancelled": "Cancelled",
    "protest": "Protest",
}

PO_STATUSES = ["draft", "issued", "partially_invoiced", "complete", "cancelled"]
PO_STATUS_LABELS: dict[str, str] = {
    "draft": "Draft",
    "issued": "Issued",
    "partially_invoiced": "Partially Invoiced",
    "complete": "Complete",
    "cancelled": "Cancelled",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bid_status_badge(status: str) -> str:
    """Return a colored Markdown badge for a bid status."""
    return status_badge(status, entity_type="bid")


def _fmt_currency(val: float | None) -> str:
    if val is None:
        return "$0.00"
    return f"${val:,.2f}"


def _days_label(date_str: str | None) -> str:
    """Return a human-friendly countdown string for a date."""
    d = days_until(date_str)
    if d is None:
        return "No date set"
    if d < 0:
        return f"{abs(d)}d overdue"
    if d == 0:
        return "Today"
    if d == 1:
        return "Tomorrow"
    return f"{d}d remaining"


def _format_date_short(date_str: str | None) -> str:
    if not date_str:
        return "---"
    try:
        d = date.fromisoformat(date_str)
        return d.strftime("%b %d, %Y")
    except ValueError:
        return date_str


def _date_input_value(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def _date_to_str(d: date | None) -> str | None:
    if d is None:
        return None
    return d.isoformat()


def _get_projects(conn):
    return conn.execute(
        "SELECT id, job_number, name FROM projects ORDER BY job_number DESC"
    ).fetchall()


def _get_opportunities(conn):
    return conn.execute(
        "SELECT id, name, stage FROM opportunities ORDER BY name"
    ).fetchall()


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------
conn = ensure_db()

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
page_header("Government Bids & Subconsultants", "Solicitations & teaming", "📑")
st.caption("Solicitation tracking, vendor management, and purchase orders")

# ---------------------------------------------------------------------------
# Alert bar — upcoming submission deadlines
# ---------------------------------------------------------------------------
deadlines_7 = get_upcoming_deadlines(conn, days_ahead=7)
deadlines_14 = get_upcoming_deadlines(conn, days_ahead=14)
# Only show 8-14 day deadlines that aren't already in the 7-day list
deadlines_7_ids = {b["id"] for b in deadlines_7}
deadlines_8_14 = [b for b in deadlines_14 if b["id"] not in deadlines_7_ids]

if deadlines_7 or deadlines_8_14:
    for bid in deadlines_7:
        d = days_until(bid["submission_deadline"])
        label = _days_label(bid["submission_deadline"])
        st.error(
            f"**SUBMISSION DEADLINE** -- {bid['title']} "
            f"({PORTAL_LABELS.get(bid['portal'], bid['portal'])}) -- "
            f"Due {_format_date_short(bid['submission_deadline'])} ({label})",
            icon="🚨",
        )
    for bid in deadlines_8_14:
        d = days_until(bid["submission_deadline"])
        label = _days_label(bid["submission_deadline"])
        st.warning(
            f"**Upcoming Deadline** -- {bid['title']} "
            f"({PORTAL_LABELS.get(bid['portal'], bid['portal'])}) -- "
            f"Due {_format_date_short(bid['submission_deadline'])} ({label})",
            icon="📋",
        )

# ---------------------------------------------------------------------------
# Metrics row
# ---------------------------------------------------------------------------
stats = get_bid_stats(conn)
all_deadlines_14 = get_upcoming_deadlines(conn, days_ahead=14)

# Pipeline value: sum estimated_value for active statuses
active_bids = list_bids(conn)
active_statuses = {"monitoring", "go", "preparing"}
active_count = sum(
    1 for b in active_bids if b["status"] in active_statuses
)
pipeline_value = sum(
    (b["estimated_value"] or 0)
    for b in active_bids
    if b["status"] in active_statuses
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Active Bids", active_count)
col2.metric("Upcoming Deadlines", len(all_deadlines_14))
col3.metric("Win Rate", f"{stats['win_rate']}%")
col4.metric("Pipeline Value", _fmt_currency(pipeline_value))

st.divider()

# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------
tab_pipeline, tab_deadlines, tab_subs = st.tabs(
    ["Bid Pipeline", "Deadlines", "Subconsultants"]
)

# ===== TAB 1: BID PIPELINE ================================================
with tab_pipeline:

    # Search bar
    search_query = st.text_input(
        "Search bids",
        placeholder="Search by title, agency, or solicitation number...",
        label_visibility="collapsed",
        key="bid_search",
    )

    # Status filter tabs
    status_tab_labels = [
        "All", "Monitoring", "Go", "Preparing", "Submitted", "Won/Lost",
    ]
    status_tabs = st.tabs(status_tab_labels)

    _STATUS_TAB_MAP: dict[int, list[str] | None] = {
        0: None,
        1: ["monitoring"],
        2: ["go"],
        3: ["preparing"],
        4: ["submitted"],
        5: ["won", "lost"],
    }

    for tab_idx, tab in enumerate(status_tabs):
        with tab:
            status_list = _STATUS_TAB_MAP[tab_idx]

            if search_query.strip():
                all_results = search_bids(conn, search_query.strip())
                if status_list:
                    bids = [b for b in all_results if b["status"] in status_list]
                else:
                    bids = all_results
            else:
                if status_list is None:
                    bids = list_bids(conn)
                elif len(status_list) == 1:
                    bids = list_bids(conn, status=status_list[0])
                else:
                    # Multiple statuses (Won/Lost)
                    bids = []
                    for s in status_list:
                        bids.extend(list_bids(conn, status=s))

            if not bids:
                empty_state("No bids found." if search_query else "No bids in this category.")
                continue

            st.markdown(f"**{len(bids)} bid{'s' if len(bids) != 1 else ''}**")

            for bid in bids:
                bid_id = bid["id"]
                deadline_d = days_until(bid["submission_deadline"])
                deadline_label = _days_label(bid["submission_deadline"])

                portal_label = PORTAL_LABELS.get(bid["portal"], bid["portal"])
                value_str = _fmt_currency(bid["estimated_value"]) if bid["estimated_value"] else "TBD"

                header = (
                    f"{bid['title']}  |  "
                    f":blue[{portal_label}]  |  "
                    f"{value_str}  |  "
                    f"{deadline_label}"
                )

                with st.expander(header, expanded=False):
                    # ---- Detail view ----
                    dc1, dc2, dc3 = st.columns(3)

                    with dc1:
                        st.markdown("**Bid Details**")
                        st.markdown(
                            f"**Status:** {_bid_status_badge(bid['status'])}",
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"**Title:** {bid['title']}")
                        st.markdown(f"**Agency:** {bid['agency'] or '---'}")
                        st.markdown(f"**Portal:** {portal_label}")
                        st.markdown(f"**Solicitation #:** {bid['solicitation_number'] or '---'}")
                        if bid["opportunity_name"]:
                            st.markdown(f"**Linked Opportunity:** {bid['opportunity_name']}")

                    with dc2:
                        st.markdown("**Deadlines**")
                        st.markdown(f"**Submission:** {_format_date_short(bid['submission_deadline'])}")
                        st.markdown(f"**Questions:** {_format_date_short(bid['question_deadline'])}")
                        st.markdown(f"**Pre-Bid Date:** {_format_date_short(bid['pre_bid_date'])}")
                        st.markdown(f"**Estimated Value:** {value_str}")

                    with dc3:
                        st.markdown("**Go/No-Go**")
                        st.markdown(f"**Decision Date:** {_format_date_short(bid['go_no_go_date'])}")
                        st.markdown(f"**Decision Notes:** {bid['go_no_go_notes'] or '---'}")
                        if bid["file_path"]:
                            st.markdown(f"**File Path:** `{bid['file_path']}`")

                    if bid["compliance_items"]:
                        st.markdown(f"**Compliance Items:**\n{bid['compliance_items']}")
                    if bid["notes"]:
                        st.markdown(f"**Notes:** {bid['notes']}")

                    st.markdown("---")

                    # ---- Go/No-Go decision form ----
                    if bid["status"] in ("monitoring",):
                        st.markdown("**Go / No-Go Decision**")
                        with st.form(key=f"gng_{bid_id}_{tab_idx}", clear_on_submit=True):
                            gng_col1, gng_col2 = st.columns([1, 3])
                            with gng_col1:
                                gng_decision = st.radio(
                                    "Decision",
                                    ["go", "no_go"],
                                    format_func=lambda x: BID_STATUS_LABELS.get(x, x),
                                    key=f"gng_dec_{bid_id}_{tab_idx}",
                                    horizontal=True,
                                )
                            with gng_col2:
                                gng_notes = st.text_area(
                                    "Decision Notes",
                                    placeholder="Rationale for go/no-go decision...",
                                    key=f"gng_notes_{bid_id}_{tab_idx}",
                                )
                            if st.form_submit_button("Record Decision", type="primary"):
                                set_go_no_go(conn, bid_id, gng_decision, gng_notes or None)
                                st.success(f"Decision recorded: {BID_STATUS_LABELS[gng_decision]}")
                                st.rerun()

                    # ---- Edit form ----
                    st.markdown("**Edit Bid**")
                    with st.form(key=f"edit_bid_{bid_id}_{tab_idx}"):
                        e_col1, e_col2 = st.columns(2)

                        with e_col1:
                            e_title = st.text_input(
                                "Title", value=bid["title"],
                                key=f"eb_title_{bid_id}_{tab_idx}",
                            )
                            e_agency = st.text_input(
                                "Agency", value=bid["agency"] or "",
                                key=f"eb_agency_{bid_id}_{tab_idx}",
                            )
                            e_portal = st.selectbox(
                                "Portal",
                                PORTALS,
                                index=PORTALS.index(bid["portal"]),
                                format_func=lambda p: PORTAL_LABELS.get(p, p),
                                key=f"eb_portal_{bid_id}_{tab_idx}",
                            )
                            e_sol = st.text_input(
                                "Solicitation #",
                                value=bid["solicitation_number"] or "",
                                key=f"eb_sol_{bid_id}_{tab_idx}",
                            )
                            e_status = st.selectbox(
                                "Status",
                                BID_STATUSES,
                                index=BID_STATUSES.index(bid["status"]),
                                format_func=lambda s: BID_STATUS_LABELS.get(s, s),
                                key=f"eb_status_{bid_id}_{tab_idx}",
                            )
                            e_value = st.number_input(
                                "Estimated Value ($)",
                                value=float(bid["estimated_value"] or 0),
                                min_value=0.0,
                                step=1000.0,
                                format="%.2f",
                                key=f"eb_val_{bid_id}_{tab_idx}",
                            )

                        with e_col2:
                            e_sub_deadline = st.date_input(
                                "Submission Deadline",
                                value=_date_input_value(bid["submission_deadline"]),
                                key=f"eb_sub_{bid_id}_{tab_idx}",
                            )
                            e_q_deadline = st.date_input(
                                "Question Deadline",
                                value=_date_input_value(bid["question_deadline"]),
                                key=f"eb_qd_{bid_id}_{tab_idx}",
                            )
                            e_prebid = st.date_input(
                                "Pre-Bid Date",
                                value=_date_input_value(bid["pre_bid_date"]),
                                key=f"eb_prebid_{bid_id}_{tab_idx}",
                            )
                            e_file = st.text_input(
                                "File Path",
                                value=bid["file_path"] or "",
                                key=f"eb_file_{bid_id}_{tab_idx}",
                            )
                            e_compliance = st.text_area(
                                "Compliance Items",
                                value=bid["compliance_items"] or "",
                                key=f"eb_comp_{bid_id}_{tab_idx}",
                            )

                        e_notes = st.text_area(
                            "Notes",
                            value=bid["notes"] or "",
                            key=f"eb_notes_{bid_id}_{tab_idx}",
                        )

                        if st.form_submit_button("Save Changes", type="primary"):
                            update_bid(
                                conn,
                                bid_id,
                                title=e_title,
                                agency=e_agency,
                                portal=e_portal,
                                solicitation_number=e_sol,
                                status=e_status,
                                estimated_value=e_value if e_value > 0 else None,
                                submission_deadline=_date_to_str(e_sub_deadline),
                                question_deadline=_date_to_str(e_q_deadline),
                                pre_bid_date=_date_to_str(e_prebid),
                                file_path=e_file,
                                compliance_items=e_compliance,
                                notes=e_notes,
                            )
                            st.success("Bid updated.")
                            st.rerun()

    # --- New bid form ---
    st.markdown("---")
    with st.expander("Create New Bid", expanded=False):
        opportunities = _get_opportunities(conn)

        with st.form("create_bid_form", clear_on_submit=True):
            st.subheader("New Bid Opportunity")
            nb_col1, nb_col2 = st.columns(2)

            with nb_col1:
                nb_title = st.text_input(
                    "Title *", placeholder="e.g. MDC RER Structural Inspection Services"
                )
                nb_portal = st.selectbox(
                    "Portal *",
                    PORTALS,
                    format_func=lambda p: PORTAL_LABELS.get(p, p),
                )
                nb_agency = st.text_input(
                    "Agency", placeholder="e.g. Miami-Dade County RER"
                )
                nb_sol = st.text_input(
                    "Solicitation #", placeholder="e.g. RFP-2026-001"
                )
                nb_value = st.number_input(
                    "Estimated Value ($)",
                    min_value=0.0,
                    step=1000.0,
                    format="%.2f",
                )

            with nb_col2:
                nb_sub_deadline = st.date_input(
                    "Submission Deadline", value=None, key="nb_sub_dl"
                )
                nb_q_deadline = st.date_input(
                    "Question Deadline", value=None, key="nb_q_dl"
                )
                nb_prebid = st.date_input(
                    "Pre-Bid Date", value=None, key="nb_prebid"
                )
                # Optional link to opportunity
                opp_options = [0] + [o["id"] for o in opportunities]
                opp_labels = {0: "-- None --"}
                for o in opportunities:
                    opp_labels[o["id"]] = f"{o['name']} ({o['stage']})"
                nb_opp = st.selectbox(
                    "Link to Opportunity (optional)",
                    options=opp_options,
                    format_func=lambda x: opp_labels.get(x, str(x)),
                    key="nb_opp",
                )

            nb_compliance = st.text_area(
                "Compliance Items",
                placeholder="DBE requirements, bonding, insurance minimums, etc.",
            )
            nb_notes = st.text_area("Notes", key="nb_notes")

            submitted = st.form_submit_button("Create Bid", type="primary")
            if submitted:
                if not nb_title.strip():
                    st.error("Bid title is required.")
                else:
                    kwargs: dict = {}
                    if nb_agency.strip():
                        kwargs["agency"] = nb_agency.strip()
                    if nb_sol.strip():
                        kwargs["solicitation_number"] = nb_sol.strip()
                    if nb_value > 0:
                        kwargs["estimated_value"] = nb_value
                    if nb_sub_deadline:
                        kwargs["submission_deadline"] = nb_sub_deadline.isoformat()
                    if nb_q_deadline:
                        kwargs["question_deadline"] = nb_q_deadline.isoformat()
                    if nb_prebid:
                        kwargs["pre_bid_date"] = nb_prebid.isoformat()
                    if nb_opp and nb_opp != 0:
                        kwargs["opportunity_id"] = nb_opp
                    if nb_compliance.strip():
                        kwargs["compliance_items"] = nb_compliance.strip()
                    if nb_notes.strip():
                        kwargs["notes"] = nb_notes.strip()

                    new_id = create_bid(conn, nb_title.strip(), nb_portal, **kwargs)
                    st.success(f"Bid created (ID: {new_id}).")
                    st.rerun()


# ===== TAB 2: DEADLINES ===================================================
with tab_deadlines:
    st.subheader("Upcoming Bid Deadlines")
    st.caption("Sorted by urgency. Shows submission, question, and pre-bid dates.")

    # Gather all deadline items from active bids
    active_for_deadlines = list_bids(conn)
    deadline_items: list[dict] = []

    for bid in active_for_deadlines:
        if bid["status"] in ("no_go", "cancelled", "won", "lost"):
            continue

        # Submission deadline
        if bid["submission_deadline"]:
            d = days_until(bid["submission_deadline"])
            deadline_items.append({
                "date": bid["submission_deadline"],
                "days": d,
                "type": "Submission Deadline",
                "title": bid["title"],
                "portal": PORTAL_LABELS.get(bid["portal"], bid["portal"]),
                "agency": bid["agency"] or "---",
                "status": bid["status"],
                "bid_id": bid["id"],
            })

        # Question deadline
        if bid["question_deadline"]:
            d = days_until(bid["question_deadline"])
            deadline_items.append({
                "date": bid["question_deadline"],
                "days": d,
                "type": "Question Deadline",
                "title": bid["title"],
                "portal": PORTAL_LABELS.get(bid["portal"], bid["portal"]),
                "agency": bid["agency"] or "---",
                "status": bid["status"],
                "bid_id": bid["id"],
            })

        # Pre-bid date
        if bid["pre_bid_date"]:
            d = days_until(bid["pre_bid_date"])
            deadline_items.append({
                "date": bid["pre_bid_date"],
                "days": d,
                "type": "Pre-Bid Date",
                "title": bid["title"],
                "portal": PORTAL_LABELS.get(bid["portal"], bid["portal"]),
                "agency": bid["agency"] or "---",
                "status": bid["status"],
                "bid_id": bid["id"],
            })

    # Sort by date (None last)
    deadline_items.sort(key=lambda x: (x["date"] is None, x["date"] or "9999-12-31"))

    if not deadline_items:
        empty_state("No upcoming bid deadlines. All clear.")
    else:
        st.markdown(f"**{len(deadline_items)} deadline item{'s' if len(deadline_items) != 1 else ''}**")

        # Group by urgency
        overdue = [d for d in deadline_items if d["days"] is not None and d["days"] < 0]
        this_week = [d for d in deadline_items if d["days"] is not None and 0 <= d["days"] <= 7]
        next_two = [d for d in deadline_items if d["days"] is not None and 7 < d["days"] <= 14]
        this_month = [d for d in deadline_items if d["days"] is not None and 14 < d["days"] <= 30]
        later = [d for d in deadline_items if d["days"] is not None and d["days"] > 30]

        def _render_dl_group(title: str, items: list[dict], level: str = "info") -> None:
            if not items:
                return
            st.markdown(f"#### {title}")
            for item in items:
                d = item["days"]
                if d is not None and d < 0:
                    days_text = f"**{abs(d)} days overdue**"
                elif d == 0:
                    days_text = "**Today**"
                elif d == 1:
                    days_text = "**Tomorrow**"
                else:
                    days_text = f"**{d} days**"

                _bid_status_badge(item["status"])
                line = (
                    f"**{item['type']}** -- {item['title']}  \n"
                    f"Agency: {item['agency']}  |  "
                    f"Portal: {item['portal']}  |  "
                    f"Date: {_format_date_short(item['date'])}  |  "
                    f"{days_text}"
                )

                if level == "error":
                    st.error(line, icon="🚨")
                elif level == "warning":
                    st.warning(line, icon="⚠️")
                else:
                    st.info(line, icon="📅")

        _render_dl_group("Overdue", overdue, "error")
        _render_dl_group("This Week", this_week, "error")
        _render_dl_group("Next Two Weeks", next_two, "warning")
        _render_dl_group("This Month", this_month, "info")
        _render_dl_group("Later", later, "info")


# ===== TAB 3: SUBCONSULTANTS ==============================================
with tab_subs:
    st.subheader("Subconsultant Roster")
    st.caption("Vendor list with specialty, contact info, W-9/insurance status, and purchase orders.")

    subconsultants = list_subconsultants(conn)

    if not subconsultants:
        empty_state("No subconsultants registered yet.")
    else:
        for sub in subconsultants:
            sid = sub["id"]
            w9_icon = "W-9 on file" if sub["w9_on_file"] else "No W-9"
            w9_color = "green" if sub["w9_on_file"] else "red"

            ins_text = "---"
            ins_color = "gray"
            if sub["insurance_expiry"]:
                ins_d = days_until(sub["insurance_expiry"])
                ins_text = _format_date_short(sub["insurance_expiry"])
                if ins_d is not None:
                    if ins_d < 0:
                        ins_color = "red"
                        ins_text += " (EXPIRED)"
                    elif ins_d <= 30:
                        ins_color = "orange"
                        ins_text += f" ({ins_d}d remaining)"
                    else:
                        ins_color = "green"

            header = (
                f"**{sub['company_name']}**"
                f"  |  {sub['specialty'] or 'General'}"
                f"  |  :{w9_color}[{w9_icon}]"
                f"  |  Ins: :{ins_color}[{ins_text}]"
            )

            with st.expander(header, expanded=False):
                # Detail view
                sc1, sc2 = st.columns(2)
                with sc1:
                    st.markdown(f"**Company:** {sub['company_name']}")
                    st.markdown(f"**Contact:** {sub['contact_name'] or '---'}")
                    st.markdown(f"**Email:** {sub['email'] or '---'}")
                    st.markdown(f"**Phone:** {sub['phone'] or '---'}")
                with sc2:
                    st.markdown(f"**Specialty:** {sub['specialty'] or '---'}")
                    st.markdown(f"**Rate Card:** {sub['rate_card'] or '---'}")
                    st.markdown(f"**W-9 on File:** {'Yes' if sub['w9_on_file'] else 'No'}")
                    st.markdown(f"**Insurance Expiry:** {ins_text}")
                if sub["notes"]:
                    st.markdown(f"**Notes:** {sub['notes']}")

                # ---- Purchase Orders for this vendor ----
                st.markdown("---")
                st.markdown("**Purchase Orders**")
                pos = list_purchase_orders(conn, subconsultant_id=sid)
                if pos:
                    for po in pos:
                        po_status_label = PO_STATUS_LABELS.get(po["status"], po["status"])
                        po_col1, po_col2, po_col3, po_col4 = st.columns([2, 2, 1, 1])
                        po_col1.markdown(
                            f"**{po['po_number']}** -- "
                            f"{po['project_name'] or 'Unknown Project'}"
                        )
                        po_col2.markdown(
                            f"Amount: {_fmt_currency(po['amount'])} "
                            f"(+{po['markup_pct']:.0f}% markup)"
                        )
                        po_col3.markdown(f"**{po_status_label}**")
                        po_col4.markdown(
                            f"Issued: {_format_date_short(po['issued_date'])}"
                        )
                        if po["description"]:
                            st.caption(f"  {po['description']}")
                else:
                    st.caption("No purchase orders for this vendor.")

                # ---- Edit subconsultant form ----
                st.markdown("---")
                with st.form(key=f"edit_sub_{sid}"):
                    st.markdown("**Edit Subconsultant**")
                    es_col1, es_col2 = st.columns(2)
                    with es_col1:
                        es_company = st.text_input(
                            "Company Name", value=sub["company_name"],
                            key=f"es_co_{sid}",
                        )
                        es_contact = st.text_input(
                            "Contact Name", value=sub["contact_name"] or "",
                            key=f"es_cn_{sid}",
                        )
                        es_email = st.text_input(
                            "Email", value=sub["email"] or "",
                            key=f"es_em_{sid}",
                        )
                        es_phone = st.text_input(
                            "Phone", value=sub["phone"] or "",
                            key=f"es_ph_{sid}",
                        )
                    with es_col2:
                        es_specialty = st.text_input(
                            "Specialty", value=sub["specialty"] or "",
                            key=f"es_sp_{sid}",
                        )
                        es_rate = st.text_input(
                            "Rate Card", value=sub["rate_card"] or "",
                            key=f"es_rc_{sid}",
                        )
                        es_w9 = st.checkbox(
                            "W-9 on File",
                            value=bool(sub["w9_on_file"]),
                            key=f"es_w9_{sid}",
                        )
                        es_ins = st.date_input(
                            "Insurance Expiry",
                            value=_date_input_value(sub["insurance_expiry"]),
                            key=f"es_ins_{sid}",
                        )
                    es_notes = st.text_area(
                        "Notes", value=sub["notes"] or "",
                        key=f"es_notes_{sid}",
                    )

                    if st.form_submit_button("Save Changes", type="primary"):
                        update_subconsultant(
                            conn,
                            sid,
                            company_name=es_company,
                            contact_name=es_contact,
                            email=es_email,
                            phone=es_phone,
                            specialty=es_specialty,
                            rate_card=es_rate,
                            w9_on_file=1 if es_w9 else 0,
                            insurance_expiry=_date_to_str(es_ins),
                            notes=es_notes,
                        )
                        st.success("Subconsultant updated.")
                        st.rerun()

                # ---- Create PO for this vendor ----
                st.markdown("---")
                projects = _get_projects(conn)
                if projects:
                    with st.form(key=f"new_po_{sid}", clear_on_submit=True):
                        st.markdown("**New Purchase Order**")
                        po_col1, po_col2 = st.columns(2)
                        with po_col1:
                            po_project = st.selectbox(
                                "Project",
                                options=[p["id"] for p in projects],
                                format_func=lambda x: next(
                                    f"{p['job_number']} - {p['name']}"
                                    for p in projects
                                    if p["id"] == x
                                ),
                                key=f"npo_proj_{sid}",
                            )
                            po_amount = st.number_input(
                                "Amount ($)",
                                min_value=0.0,
                                step=100.0,
                                format="%.2f",
                                key=f"npo_amt_{sid}",
                            )
                        with po_col2:
                            po_markup = st.number_input(
                                "Markup %",
                                value=15.0,
                                min_value=0.0,
                                step=1.0,
                                format="%.1f",
                                key=f"npo_mkup_{sid}",
                            )
                            po_desc = st.text_input(
                                "Description",
                                key=f"npo_desc_{sid}",
                            )
                        po_notes = st.text_area(
                            "Notes", key=f"npo_notes_{sid}"
                        )

                        if st.form_submit_button("Create PO", type="primary"):
                            if po_amount <= 0:
                                st.error("Amount must be greater than zero.")
                            else:
                                new_po_id = create_purchase_order(
                                    conn,
                                    project_id=po_project,
                                    subconsultant_id=sid,
                                    amount=po_amount,
                                    markup_pct=po_markup,
                                    description=po_desc or None,
                                    notes=po_notes or None,
                                )
                                st.success(f"Purchase order created (ID: {new_po_id}).")
                                st.rerun()
                else:
                    st.caption("No projects available. Create a project first to issue POs.")

    # --- Add new subconsultant ---
    st.markdown("---")
    with st.expander("Add New Subconsultant", expanded=False):
        with st.form("create_sub_form", clear_on_submit=True):
            st.subheader("New Subconsultant")
            ns_col1, ns_col2 = st.columns(2)
            with ns_col1:
                ns_company = st.text_input(
                    "Company Name *",
                    placeholder="e.g. Smith MEP Consulting",
                )
                ns_contact = st.text_input(
                    "Contact Name", placeholder="e.g. John Smith"
                )
                ns_email = st.text_input(
                    "Email", placeholder="john@smithmep.com"
                )
                ns_phone = st.text_input(
                    "Phone", placeholder="(305) 555-1234"
                )
            with ns_col2:
                ns_specialty = st.text_input(
                    "Specialty",
                    placeholder="e.g. Electrical Engineering, MEP, Geotechnical",
                )
                ns_rate = st.text_input(
                    "Rate Card",
                    placeholder="e.g. $150/hr or lump sum schedule",
                )
                ns_w9 = st.checkbox("W-9 on File", value=False)
                ns_ins = st.date_input(
                    "Insurance Expiry", value=None, key="ns_ins"
                )
            ns_notes = st.text_area("Notes", key="ns_notes")

            if st.form_submit_button("Add Subconsultant", type="primary"):
                if not ns_company.strip():
                    st.error("Company name is required.")
                else:
                    new_sid = create_subconsultant(
                        conn,
                        ns_company.strip(),
                        contact_name=ns_contact or None,
                        email=ns_email or None,
                        phone=ns_phone or None,
                        specialty=ns_specialty or None,
                        rate_card=ns_rate or None,
                        w9_on_file=1 if ns_w9 else 0,
                        insurance_expiry=_date_to_str(ns_ins),
                        notes=ns_notes or None,
                    )
                    st.success(f"Subconsultant added (ID: {new_sid}).")
                    st.rerun()
