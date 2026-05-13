"""Permit Tracker — 6th Degree Engineering Company Platform.

Tracks building permits, roofing permit re-issuances, 25/50-year
recertifications, and Compliance Consent Agreements (CCAs) with
Miami-Dade County RER.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Path setup — ensure the platform root is importable
# ---------------------------------------------------------------------------
_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from db import ensure_db
from modules.permits.crud import (
    create_contact,
    create_permit,
    get_cca_deadlines,
    get_expiring_permits,
    get_overdue_inspections,
    get_permit,
    get_permit_stats,
    list_contacts,
    list_permits,
    search_permits,
    update_contact,
    update_permit,
)
from streamlit_app.auth import require_auth  # noqa: E402

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Permits | 6DE Platform", page_icon="🏗️", layout="wide")
require_auth()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PERMIT_TYPES = [
    "building",
    "roofing",
    "electrical",
    "mechanical",
    "plumbing",
    "recertification",
    "demolition",
    "other",
]

PERMIT_STATUSES = [
    "pending",
    "submitted",
    "in_review",
    "approved",
    "issued",
    "expired",
    "failed_inspection",
    "closed",
    "extension_requested",
]

CONTACT_ROLES = [
    "county_official",
    "inspector",
    "attorney",
    "contractor",
    "architect",
    "consultant",
    "other",
]

STATUS_COLORS: dict[str, str] = {
    "pending": "gray",
    "submitted": "blue",
    "in_review": "orange",
    "approved": "green",
    "issued": "green",
    "expired": "red",
    "failed_inspection": "red",
    "closed": "gray",
    "extension_requested": "orange",
}

# Mapping for display labels
STATUS_LABELS: dict[str, str] = {
    "pending": "Pending",
    "submitted": "Submitted",
    "in_review": "In Review",
    "approved": "Approved",
    "issued": "Issued",
    "expired": "Expired",
    "failed_inspection": "Failed Inspection",
    "closed": "Closed",
    "extension_requested": "Extension Requested",
}

TYPE_LABELS: dict[str, str] = {
    "building": "Building",
    "roofing": "Roofing",
    "electrical": "Electrical",
    "mechanical": "Mechanical",
    "plumbing": "Plumbing",
    "recertification": "Recertification",
    "demolition": "Demolition",
    "other": "Other",
}

ROLE_LABELS: dict[str, str] = {
    "county_official": "County Official",
    "inspector": "Inspector",
    "attorney": "Attorney",
    "contractor": "Contractor",
    "architect": "Architect",
    "consultant": "Consultant",
    "other": "Other",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status_badge(status: str) -> str:
    """Return a colored Markdown badge for a permit status."""
    color = STATUS_COLORS.get(status, "gray")
    label = STATUS_LABELS.get(status, status)
    return f":{color}[**{label}**]"


def _days_until(date_str: str | None) -> int | None:
    """Return the number of days from today to *date_str* (YYYY-MM-DD)."""
    if not date_str:
        return None
    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        return None
    return (target - date.today()).days


def _urgency_indicator(days: int | None) -> str:
    """Return a text urgency indicator based on days remaining."""
    if days is None:
        return ""
    if days < 0:
        return "OVERDUE"
    if days == 0:
        return "TODAY"
    if days <= 7:
        return "URGENT"
    if days <= 14:
        return "SOON"
    return ""


def _format_date(date_str: str | None) -> str:
    """Format an ISO date string for display."""
    if not date_str:
        return "---"
    try:
        d = date.fromisoformat(date_str)
        return d.strftime("%b %d, %Y")
    except ValueError:
        return date_str


def _date_input_value(date_str: str | None) -> date | None:
    """Convert an ISO date string to a date object for st.date_input."""
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def _date_to_str(d: date | None) -> str | None:
    """Convert a date object to ISO string, or None."""
    if d is None:
        return None
    return d.isoformat()


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

conn = ensure_db()


# ---------------------------------------------------------------------------
# Fetch projects for dropdowns
# ---------------------------------------------------------------------------


def _get_projects():
    return conn.execute(
        "SELECT id, job_number, name FROM projects "
        "WHERE status IN ('active', 'prospect', 'on_hold') "
        "ORDER BY job_number DESC"
    ).fetchall()


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.title("Permit Tracker")
st.caption("Miami-Dade County RER -- Building Permits, Recertifications, and CCAs")

# ---------------------------------------------------------------------------
# Alert banner — expiring permits and CCA deadlines
# ---------------------------------------------------------------------------

expiring = get_expiring_permits(conn, days_ahead=30)
cca_upcoming = get_cca_deadlines(conn, days_ahead=60)
overdue_insp = get_overdue_inspections(conn)

_has_alerts = bool(expiring) or bool(cca_upcoming) or bool(overdue_insp)

if _has_alerts:
    st.markdown("---")

    # Overdue inspections — most urgent
    if overdue_insp:
        for row in overdue_insp:
            days = _days_until(row["inspection_date"])
            addr = row["address"] or "No address"
            pnum = row["permit_number"] or "No permit #"
            st.error(
                f"**OVERDUE INSPECTION** -- {pnum} at {addr} "
                f"(inspection was {_format_date(row['inspection_date'])}, "
                f"{abs(days)} days ago)",
                icon="🚨",
            )

    # CCA deadlines
    if cca_upcoming:
        for row in cca_upcoming:
            days = _days_until(row["cca_deadline"])
            addr = row["address"] or "No address"
            case = row["case_number"] or "No case #"
            if days is not None and days <= 14:
                st.error(
                    f"**CCA DEADLINE** -- Case {case} at {addr}: "
                    f"due {_format_date(row['cca_deadline'])} "
                    f"({days} day{'s' if days != 1 else ''} remaining)",
                    icon="⚠️",
                )
            else:
                st.warning(
                    f"**CCA Deadline Approaching** -- Case {case} at {addr}: "
                    f"due {_format_date(row['cca_deadline'])} "
                    f"({days} day{'s' if days != 1 else ''} remaining)",
                    icon="📋",
                )

    # Expiring permits
    if expiring:
        for row in expiring:
            days = _days_until(row["expiration_date"])
            addr = row["address"] or "No address"
            pnum = row["permit_number"] or "No permit #"
            ptype = TYPE_LABELS.get(row["permit_type"], row["permit_type"])
            if days is not None and days <= 7:
                st.error(
                    f"**PERMIT EXPIRING** -- {ptype} permit {pnum} at {addr}: "
                    f"expires {_format_date(row['expiration_date'])} "
                    f"({days} day{'s' if days != 1 else ''} remaining)",
                    icon="🔴",
                )
            else:
                st.warning(
                    f"**Permit Expiring Soon** -- {ptype} permit {pnum} at {addr}: "
                    f"expires {_format_date(row['expiration_date'])} "
                    f"({days} day{'s' if days != 1 else ''} remaining)",
                    icon="🟡",
                )

    st.markdown("---")

# ---------------------------------------------------------------------------
# Stats summary row
# ---------------------------------------------------------------------------

stats = get_permit_stats(conn)

if stats["total"] > 0:
    st.subheader("Overview")

    # Status counts
    col1, col2, col3, col4, col5 = st.columns(5)
    active_count = sum(
        stats["by_status"].get(s, 0)
        for s in ("pending", "submitted", "in_review", "approved", "issued", "extension_requested")
    )
    col1.metric("Total Permits", stats["total"])
    col2.metric("Active", active_count)
    col3.metric("Expired / Failed", stats["by_status"].get("expired", 0) + stats["by_status"].get("failed_inspection", 0))
    col4.metric("Expiring (30 days)", len(expiring))
    col5.metric("CCA Deadlines (60 days)", len(cca_upcoming))

    # Type breakdown in a second row
    if stats["by_type"]:
        type_cols = st.columns(min(len(stats["by_type"]), 8))
        for i, (ptype, cnt) in enumerate(sorted(stats["by_type"].items())):
            type_cols[i % len(type_cols)].metric(
                TYPE_LABELS.get(ptype, ptype), cnt
            )

    st.markdown("---")

# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------

tab_permits, tab_deadlines, tab_contacts = st.tabs(
    ["All Permits", "Deadlines", "Contacts"]
)

# ===== TAB 1: ALL PERMITS ================================================
with tab_permits:

    # --- Search & Filters ---
    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2, 1, 1, 1])

    with filter_col1:
        search_query = st.text_input(
            "Search",
            placeholder="Permit #, folio, or address...",
            key="permit_search",
        )

    with filter_col2:
        status_options = ["All Statuses"] + [STATUS_LABELS[s] for s in PERMIT_STATUSES]
        selected_status_label = st.selectbox("Status", status_options, key="filter_status")
        selected_status = None
        if selected_status_label != "All Statuses":
            selected_status = next(
                k for k, v in STATUS_LABELS.items() if v == selected_status_label
            )

    with filter_col3:
        type_options = ["All Types"] + [TYPE_LABELS[t] for t in PERMIT_TYPES]
        selected_type_label = st.selectbox("Type", type_options, key="filter_type")
        selected_type = None
        if selected_type_label != "All Types":
            selected_type = next(
                k for k, v in TYPE_LABELS.items() if v == selected_type_label
            )

    with filter_col4:
        projects = _get_projects()
        project_options = ["All Projects"] + [
            f"{p['job_number']} - {p['name']}" for p in projects
        ]
        selected_project_label = st.selectbox(
            "Project", project_options, key="filter_project"
        )
        selected_project_id = None
        if selected_project_label != "All Projects":
            idx = project_options.index(selected_project_label) - 1
            selected_project_id = projects[idx]["id"]

    # --- Fetch permits ---
    if search_query:
        permits = search_permits(conn, search_query)
    else:
        permits = list_permits(
            conn,
            project_id=selected_project_id,
            status_filter=selected_status,
            permit_type=selected_type,
        )

    # --- Permit list ---
    if not permits:
        st.info("No permits found matching your filters.")
    else:
        st.markdown(f"**{len(permits)} permit{'s' if len(permits) != 1 else ''}**")

        for permit in permits:
            pid = permit["id"]
            pnum = permit["permit_number"] or "---"
            ptype = TYPE_LABELS.get(permit["permit_type"], permit["permit_type"])
            addr = permit["address"] or "No address"
            proj_name = permit["project_name"] or "No project"
            job_num = permit["job_number"] or ""
            status = permit["status"]

            days_to_exp = _days_until(permit["expiration_date"])
            urgency = _urgency_indicator(days_to_exp)
            urgency_text = f"  |  :red[**{urgency}**]" if urgency else ""

            with st.expander(
                f"{_status_badge(status)}  {ptype} -- {pnum}  |  {addr}  |  {job_num} {proj_name}{urgency_text}",
                expanded=False,
            ):
                # Detail view
                detail_col1, detail_col2, detail_col3 = st.columns(3)

                with detail_col1:
                    st.markdown("**Permit Details**")
                    st.markdown(f"**Permit #:** {pnum}")
                    st.markdown(f"**Folio:** {permit['folio_number'] or '---'}")
                    st.markdown(f"**Type:** {ptype}")
                    st.markdown(f"**Status:** {_status_badge(status)}")
                    st.markdown(f"**Jurisdiction:** {permit['jurisdiction'] or '---'}")

                with detail_col2:
                    st.markdown("**Dates**")
                    st.markdown(f"**Submitted:** {_format_date(permit['submitted_date'])}")
                    st.markdown(f"**Approved:** {_format_date(permit['approved_date'])}")
                    st.markdown(f"**Expiration:** {_format_date(permit['expiration_date'])}")
                    st.markdown(f"**Inspection:** {_format_date(permit['inspection_date'])}")

                with detail_col3:
                    st.markdown("**Enforcement / CCA**")
                    st.markdown(f"**Case #:** {permit['case_number'] or '---'}")
                    st.markdown(f"**CCA Deadline:** {_format_date(permit['cca_deadline'])}")
                    st.markdown(f"**Extension Deadline:** {_format_date(permit['extension_deadline'])}")
                    st.markdown(f"**Inspector:** {permit['inspector_name'] or '---'}")

                if permit["notes"]:
                    st.markdown(f"**Notes:** {permit['notes']}")

                # --- Edit form ---
                with st.form(key=f"edit_permit_{pid}"):
                    st.markdown("**Edit Permit**")
                    e_col1, e_col2 = st.columns(2)

                    with e_col1:
                        new_permit_number = st.text_input(
                            "Permit #", value=permit["permit_number"] or "", key=f"ep_num_{pid}"
                        )
                        new_folio = st.text_input(
                            "Folio #", value=permit["folio_number"] or "", key=f"ep_folio_{pid}"
                        )
                        new_address = st.text_input(
                            "Address", value=permit["address"] or "", key=f"ep_addr_{pid}"
                        )
                        new_status = st.selectbox(
                            "Status",
                            PERMIT_STATUSES,
                            index=PERMIT_STATUSES.index(status),
                            format_func=lambda s: STATUS_LABELS.get(s, s),
                            key=f"ep_status_{pid}",
                        )
                        new_inspector = st.text_input(
                            "Inspector", value=permit["inspector_name"] or "", key=f"ep_insp_{pid}"
                        )
                        new_case = st.text_input(
                            "Case #", value=permit["case_number"] or "", key=f"ep_case_{pid}"
                        )

                    with e_col2:
                        new_submitted = st.date_input(
                            "Submitted Date",
                            value=_date_input_value(permit["submitted_date"]),
                            key=f"ep_sub_{pid}",
                        )
                        new_approved = st.date_input(
                            "Approved Date",
                            value=_date_input_value(permit["approved_date"]),
                            key=f"ep_app_{pid}",
                        )
                        new_expiration = st.date_input(
                            "Expiration Date",
                            value=_date_input_value(permit["expiration_date"]),
                            key=f"ep_exp_{pid}",
                        )
                        new_inspection = st.date_input(
                            "Inspection Date",
                            value=_date_input_value(permit["inspection_date"]),
                            key=f"ep_insp_d_{pid}",
                        )
                        new_cca = st.date_input(
                            "CCA Deadline",
                            value=_date_input_value(permit["cca_deadline"]),
                            key=f"ep_cca_{pid}",
                        )
                        new_ext = st.date_input(
                            "Extension Deadline",
                            value=_date_input_value(permit["extension_deadline"]),
                            key=f"ep_ext_{pid}",
                        )

                    new_notes = st.text_area(
                        "Notes", value=permit["notes"] or "", key=f"ep_notes_{pid}"
                    )

                    if st.form_submit_button("Save Changes", type="primary"):
                        update_permit(
                            conn,
                            pid,
                            permit_number=new_permit_number,
                            folio_number=new_folio,
                            address=new_address,
                            status=new_status,
                            inspector_name=new_inspector,
                            case_number=new_case,
                            submitted_date=_date_to_str(new_submitted),
                            approved_date=_date_to_str(new_approved),
                            expiration_date=_date_to_str(new_expiration),
                            inspection_date=_date_to_str(new_inspection),
                            cca_deadline=_date_to_str(new_cca),
                            extension_deadline=_date_to_str(new_ext),
                            notes=new_notes,
                        )
                        st.success("Permit updated.")
                        st.rerun()

    # --- Create new permit ---
    st.markdown("---")
    st.subheader("Add New Permit")

    with st.form("create_permit_form", clear_on_submit=True):
        cp_col1, cp_col2 = st.columns(2)

        with cp_col1:
            if not projects:
                st.warning("No active projects found. Create a project first.")
                cp_project_id = None
            else:
                cp_project_label = st.selectbox(
                    "Project *",
                    [f"{p['job_number']} - {p['name']}" for p in projects],
                    key="cp_project",
                )
                cp_project_idx = [
                    f"{p['job_number']} - {p['name']}" for p in projects
                ].index(cp_project_label)
                cp_project_id = projects[cp_project_idx]["id"]

            cp_type = st.selectbox(
                "Permit Type *",
                PERMIT_TYPES,
                format_func=lambda t: TYPE_LABELS.get(t, t),
                key="cp_type",
            )
            cp_permit_number = st.text_input("Permit #", key="cp_num")
            cp_folio = st.text_input("Folio #", key="cp_folio")
            cp_address = st.text_input("Address", key="cp_addr")
            cp_status = st.selectbox(
                "Status",
                PERMIT_STATUSES,
                format_func=lambda s: STATUS_LABELS.get(s, s),
                key="cp_status",
            )

        with cp_col2:
            cp_jurisdiction = st.text_input(
                "Jurisdiction", value="Miami-Dade County RER", key="cp_jur"
            )
            cp_inspector = st.text_input("Inspector", key="cp_insp")
            cp_case = st.text_input("Case #", key="cp_case")
            cp_submitted = st.date_input("Submitted Date", value=None, key="cp_sub")
            cp_approved = st.date_input("Approved Date", value=None, key="cp_app")
            cp_expiration = st.date_input("Expiration Date", value=None, key="cp_exp")
            cp_inspection = st.date_input("Inspection Date", value=None, key="cp_insp_d")
            cp_cca = st.date_input("CCA Deadline", value=None, key="cp_cca")
            cp_ext = st.date_input("Extension Deadline", value=None, key="cp_ext")

        cp_notes = st.text_area("Notes", key="cp_notes")

        submitted = st.form_submit_button("Create Permit", type="primary")

        if submitted:
            if cp_project_id is None:
                st.error("Please select a project.")
            else:
                new_id = create_permit(
                    conn,
                    cp_project_id,
                    cp_type,
                    permit_number=cp_permit_number,
                    folio_number=cp_folio,
                    address=cp_address,
                    status=cp_status,
                    jurisdiction=cp_jurisdiction,
                    inspector_name=cp_inspector,
                    case_number=cp_case,
                    submitted_date=_date_to_str(cp_submitted),
                    approved_date=_date_to_str(cp_approved),
                    expiration_date=_date_to_str(cp_expiration),
                    inspection_date=_date_to_str(cp_inspection),
                    cca_deadline=_date_to_str(cp_cca),
                    extension_deadline=_date_to_str(cp_ext),
                    notes=cp_notes,
                )
                st.success(f"Permit created (ID: {new_id}).")
                st.rerun()


# ===== TAB 2: DEADLINES ==================================================
with tab_deadlines:
    st.subheader("Upcoming Deadlines")
    st.caption(
        "All permits with an upcoming expiration, CCA deadline, inspection date, "
        "or extension deadline — sorted by urgency."
    )

    # Gather all deadline items into a unified list
    deadline_items: list[dict] = []

    # Expiring permits (broader window for deadlines tab)
    for row in get_expiring_permits(conn, days_ahead=90):
        days = _days_until(row["expiration_date"])
        deadline_items.append(
            {
                "date": row["expiration_date"],
                "days": days,
                "type": "Permit Expiration",
                "permit_type": TYPE_LABELS.get(row["permit_type"], row["permit_type"]),
                "permit_number": row["permit_number"] or "---",
                "address": row["address"] or "No address",
                "project": f"{row['job_number'] or ''} {row['project_name'] or ''}".strip(),
                "status": row["status"],
                "permit_id": row["id"],
            }
        )

    # CCA deadlines (broader window)
    for row in get_cca_deadlines(conn, days_ahead=120):
        days = _days_until(row["cca_deadline"])
        deadline_items.append(
            {
                "date": row["cca_deadline"],
                "days": days,
                "type": "CCA Deadline",
                "permit_type": TYPE_LABELS.get(row["permit_type"], row["permit_type"]),
                "permit_number": row["permit_number"] or "---",
                "address": row["address"] or "No address",
                "project": f"{row['job_number'] or ''} {row['project_name'] or ''}".strip(),
                "status": row["status"],
                "permit_id": row["id"],
            }
        )

    # Overdue inspections
    for row in overdue_insp:
        days = _days_until(row["inspection_date"])
        deadline_items.append(
            {
                "date": row["inspection_date"],
                "days": days,
                "type": "Overdue Inspection",
                "permit_type": TYPE_LABELS.get(row["permit_type"], row["permit_type"]),
                "permit_number": row["permit_number"] or "---",
                "address": row["address"] or "No address",
                "project": f"{row['job_number'] or ''} {row['project_name'] or ''}".strip(),
                "status": row["status"],
                "permit_id": row["id"],
            }
        )

    # Upcoming inspections (not overdue)
    upcoming_inspections = conn.execute(
        "SELECT p.*, pr.job_number, pr.name AS project_name "
        "FROM permits p "
        "LEFT JOIN projects pr ON p.project_id = pr.id "
        "WHERE p.inspection_date IS NOT NULL "
        "  AND p.inspection_date >= ? "
        "  AND p.status NOT IN ('closed', 'expired', 'failed_inspection') "
        "ORDER BY p.inspection_date ASC",
        (date.today().isoformat(),),
    ).fetchall()
    for row in upcoming_inspections:
        days = _days_until(row["inspection_date"])
        deadline_items.append(
            {
                "date": row["inspection_date"],
                "days": days,
                "type": "Scheduled Inspection",
                "permit_type": TYPE_LABELS.get(row["permit_type"], row["permit_type"]),
                "permit_number": row["permit_number"] or "---",
                "address": row["address"] or "No address",
                "project": f"{row['job_number'] or ''} {row['project_name'] or ''}".strip(),
                "status": row["status"],
                "permit_id": row["id"],
            }
        )

    # Extension deadlines
    ext_deadlines = conn.execute(
        "SELECT p.*, pr.job_number, pr.name AS project_name "
        "FROM permits p "
        "LEFT JOIN projects pr ON p.project_id = pr.id "
        "WHERE p.extension_deadline IS NOT NULL "
        "  AND p.extension_deadline >= ? "
        "  AND p.status NOT IN ('closed') "
        "ORDER BY p.extension_deadline ASC",
        (date.today().isoformat(),),
    ).fetchall()
    for row in ext_deadlines:
        days = _days_until(row["extension_deadline"])
        deadline_items.append(
            {
                "date": row["extension_deadline"],
                "days": days,
                "type": "Extension Deadline",
                "permit_type": TYPE_LABELS.get(row["permit_type"], row["permit_type"]),
                "permit_number": row["permit_number"] or "---",
                "address": row["address"] or "No address",
                "project": f"{row['job_number'] or ''} {row['project_name'] or ''}".strip(),
                "status": row["status"],
                "permit_id": row["id"],
            }
        )

    # Sort by date (None last), then by days ascending
    deadline_items.sort(key=lambda x: (x["date"] is None, x["date"] or "9999-12-31"))

    if not deadline_items:
        st.info("No upcoming deadlines. All clear.")
    else:
        st.markdown(f"**{len(deadline_items)} upcoming deadline item{'s' if len(deadline_items) != 1 else ''}**")
        st.markdown("")

        # Group by time horizon
        overdue_list = [d for d in deadline_items if d["days"] is not None and d["days"] < 0]
        this_week = [d for d in deadline_items if d["days"] is not None and 0 <= d["days"] <= 7]
        next_two_weeks = [d for d in deadline_items if d["days"] is not None and 7 < d["days"] <= 14]
        this_month = [d for d in deadline_items if d["days"] is not None and 14 < d["days"] <= 30]
        later = [d for d in deadline_items if d["days"] is not None and d["days"] > 30]

        def _render_deadline_group(title: str, items: list[dict], level: str = "info") -> None:
            if not items:
                return
            st.markdown(f"#### {title}")
            for item in items:
                days = item["days"]
                if days is not None and days < 0:
                    days_text = f"**{abs(days)} days overdue**"
                elif days == 0:
                    days_text = "**Today**"
                elif days == 1:
                    days_text = "**Tomorrow**"
                else:
                    days_text = f"**{days} days**"

                line = (
                    f"**{item['type']}** -- {item['permit_type']} permit "
                    f"{item['permit_number']} at {item['address']}  \n"
                    f"Project: {item['project']}  |  "
                    f"Date: {_format_date(item['date'])}  |  "
                    f"{days_text}  |  {_status_badge(item['status'])}"
                )

                if level == "error":
                    st.error(line, icon="🚨")
                elif level == "warning":
                    st.warning(line, icon="⚠️")
                else:
                    st.info(line, icon="📅")

        _render_deadline_group("Overdue", overdue_list, "error")
        _render_deadline_group("This Week", this_week, "warning")
        _render_deadline_group("Next Two Weeks", next_two_weeks, "warning")
        _render_deadline_group("This Month", this_month, "info")
        _render_deadline_group("Later", later, "info")


# ===== TAB 3: CONTACTS ===================================================
with tab_contacts:
    # A4 fix: count badge so importer results are visible from the UI.
    total_contacts = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]

    st.subheader("Permit Contacts")
    st.caption("County officials, inspectors, attorneys, and other contacts for permit work.")

    # Filter
    ct_filter_col1, ct_filter_col2 = st.columns([1, 3])
    with ct_filter_col1:
        role_options = ["All Roles"] + [ROLE_LABELS[r] for r in CONTACT_ROLES]
        selected_role_label = st.selectbox("Filter by Role", role_options, key="ct_role_filter")
        selected_role = None
        if selected_role_label != "All Roles":
            selected_role = next(
                k for k, v in ROLE_LABELS.items() if v == selected_role_label
            )

    contacts = list_contacts(conn, role_type=selected_role)

    # A4 fix: render "N contacts · N shown" badge between filter and list.
    _shown = len(contacts)
    st.markdown(
        f"<div style='margin:8px 0 16px 0;color:#495057;font-size:0.9rem;'>"
        f"<strong>{total_contacts}</strong> contact{'s' if total_contacts != 1 else ''} "
        f"&middot; <strong>{_shown}</strong> shown"
        f"{' (filtered)' if selected_role else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )

    if not contacts:
        st.info("No contacts found.")
    else:
        for contact in contacts:
            cid = contact["id"]
            role_label = ROLE_LABELS.get(contact["role_type"] or "", contact["role_type"] or "")
            title_text = f" -- {contact['title']}" if contact["title"] else ""
            org_text = f" at {contact['organization']}" if contact["organization"] else ""
            dept_text = f" ({contact['department']})" if contact["department"] else ""

            with st.expander(
                f"**{contact['name']}**{title_text}{org_text}{dept_text}  |  :blue[{role_label}]",
                expanded=False,
            ):
                ct_col1, ct_col2 = st.columns(2)
                with ct_col1:
                    st.markdown(f"**Name:** {contact['name']}")
                    st.markdown(f"**Title:** {contact['title'] or '---'}")
                    st.markdown(f"**Organization:** {contact['organization'] or '---'}")
                    st.markdown(f"**Department:** {contact['department'] or '---'}")
                with ct_col2:
                    st.markdown(f"**Email:** {contact['email'] or '---'}")
                    st.markdown(f"**Phone:** {contact['phone'] or '---'}")
                    st.markdown(f"**Role:** {role_label}")
                    if contact["notes"]:
                        st.markdown(f"**Notes:** {contact['notes']}")

                # Edit form
                with st.form(key=f"edit_contact_{cid}"):
                    st.markdown("**Edit Contact**")
                    ec_col1, ec_col2 = st.columns(2)
                    with ec_col1:
                        ec_name = st.text_input("Name", value=contact["name"], key=f"ec_name_{cid}")
                        ec_title = st.text_input("Title", value=contact["title"] or "", key=f"ec_title_{cid}")
                        ec_org = st.text_input("Organization", value=contact["organization"] or "", key=f"ec_org_{cid}")
                        ec_dept = st.text_input("Department", value=contact["department"] or "", key=f"ec_dept_{cid}")
                    with ec_col2:
                        ec_email = st.text_input("Email", value=contact["email"] or "", key=f"ec_email_{cid}")
                        ec_phone = st.text_input("Phone", value=contact["phone"] or "", key=f"ec_phone_{cid}")
                        ec_role = st.selectbox(
                            "Role",
                            CONTACT_ROLES,
                            index=CONTACT_ROLES.index(contact["role_type"]) if contact["role_type"] in CONTACT_ROLES else 0,
                            format_func=lambda r: ROLE_LABELS.get(r, r),
                            key=f"ec_role_{cid}",
                        )
                        ec_notes = st.text_area("Notes", value=contact["notes"] or "", key=f"ec_notes_{cid}")

                    if st.form_submit_button("Save Changes", type="primary"):
                        update_contact(
                            conn,
                            cid,
                            name=ec_name,
                            title=ec_title,
                            organization=ec_org,
                            department=ec_dept,
                            email=ec_email,
                            phone=ec_phone,
                            role_type=ec_role,
                            notes=ec_notes,
                        )
                        st.success("Contact updated.")
                        st.rerun()

    # --- Add new contact ---
    st.markdown("---")
    st.subheader("Add New Contact")

    with st.form("create_contact_form", clear_on_submit=True):
        nc_col1, nc_col2 = st.columns(2)
        with nc_col1:
            nc_name = st.text_input("Name *", key="nc_name")
            nc_title = st.text_input("Title", key="nc_title")
            nc_org = st.text_input("Organization", key="nc_org")
            nc_dept = st.text_input("Department", key="nc_dept")
        with nc_col2:
            nc_email = st.text_input("Email", key="nc_email")
            nc_phone = st.text_input("Phone", key="nc_phone")
            nc_role = st.selectbox(
                "Role *",
                CONTACT_ROLES,
                format_func=lambda r: ROLE_LABELS.get(r, r),
                key="nc_role",
            )
            nc_notes = st.text_area("Notes", key="nc_notes")

        if st.form_submit_button("Add Contact", type="primary"):
            if not nc_name.strip():
                st.error("Contact name is required.")
            else:
                new_cid = create_contact(
                    conn,
                    nc_name.strip(),
                    title=nc_title,
                    organization=nc_org,
                    department=nc_dept,
                    email=nc_email,
                    phone=nc_phone,
                    role_type=nc_role,
                    notes=nc_notes,
                )
                st.success(f"Contact added (ID: {new_cid}).")
                st.rerun()
