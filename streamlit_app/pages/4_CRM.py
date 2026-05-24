"""CRM & Pipeline — 6th Degree Engineering Company Platform.

Full pipeline management page: metrics dashboard, opportunity tracking by
stage, client management, and analytics (win/loss, service-line breakdown).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Path bootstrap — allow imports from the platform root
# ---------------------------------------------------------------------------
_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from db import ensure_db  # noqa: E402
from modules.crm.crud import (  # noqa: E402
    SOURCES,
    SERVICE_LINES,
    STAGES,
    advance_stage,
    convert_to_project,
    create_client,
    create_opportunity,
    get_client,
    get_opportunity,
    get_pipeline_summary,
    get_win_loss_stats,
    list_clients,
    list_opportunities,
    search_opportunities,
    update_client,
    update_opportunity,
)
from streamlit_app.components.formatters import (  # noqa: E402
    format_currency,
    format_date,
    format_percentage,
    status_badge,
)
from streamlit_app.auth import require_auth  # noqa: E402

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(page_title="CRM | 6DE Platform", page_icon="📊", layout="wide")
require_auth()
st.title("CRM & Pipeline")
st.caption("6th Degree Engineering -- Opportunity Pipeline and Client Management")

conn = ensure_db()

# ---------------------------------------------------------------------------
# Constants / labels
# ---------------------------------------------------------------------------

STAGE_LABELS: dict[str, str] = {
    "lead":          "Lead",
    "qualifying":    "Qualifying",
    "proposal_sent": "Proposal Sent",
    "negotiating":   "Negotiating",
    "won":           "Won",
    "lost":          "Lost",
    "dormant":       "Dormant",
}

SERVICE_LINE_LABELS: dict[str, str] = {
    "structural":      "Structural",
    "civil":           "Civil",
    "sirs":            "SIRS",
    "forensics":       "Forensics",
    "pools":           "Pools",
    "recertification": "Recertification",
    "threshold":       "Threshold",
    "government":      "Government",
    "other":           "Other",
}

SOURCE_LABELS: dict[str, str] = {
    "referral":       "Referral",
    "repeat":         "Repeat Client",
    "website":        "Website",
    "bid_portal":     "Bid Portal",
    "cold_outreach":  "Cold Outreach",
    "conference":     "Conference",
    "other":          "Other",
}

STAGE_COLORS: dict[str, str] = {
    "lead":          "gray",
    "qualifying":    "blue",
    "proposal_sent": "orange",
    "negotiating":   "orange",
    "won":           "green",
    "lost":          "red",
    "dormant":       "gray",
}

# Which stages can an opportunity be advanced to from each stage
_NEXT_STAGES: dict[str, list[str]] = {
    "lead":          ["qualifying", "lost", "dormant"],
    "qualifying":    ["proposal_sent", "lost", "dormant"],
    "proposal_sent": ["negotiating", "won", "lost", "dormant"],
    "negotiating":   ["won", "lost", "dormant"],
    "won":           ["dormant"],
    "lost":          ["lead", "dormant"],
    "dormant":       ["lead"],
}


def _stage_badge(stage: str) -> str:
    """Colored Streamlit Markdown badge for a pipeline stage."""
    color = STAGE_COLORS.get(stage, "gray")
    label = STAGE_LABELS.get(stage, stage)
    return f":{color}[**{label}**]"


def _date_to_str(d: date | None) -> str | None:
    if d is None:
        return None
    return d.isoformat()


def _date_input_value(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Metrics row
# ---------------------------------------------------------------------------
summary = get_pipeline_summary(conn)
wl_stats = get_win_loss_stats(conn)

st.markdown("---")
met_col1, met_col2, met_col3, met_col4 = st.columns(4)
met_col1.metric(
    "Total Pipeline Value",
    format_currency(summary["total_pipeline_value"]),
    help="Sum of estimated values for all active opportunities (excludes lost/dormant)",
)
met_col2.metric(
    "Weighted Forecast",
    format_currency(summary["weighted_pipeline_total"]),
    help="Pipeline value weighted by probability",
)
met_col3.metric(
    "Active Opportunities",
    str(summary["active_count"]),
    help="Opportunities not in lost or dormant stage",
)
met_col4.metric(
    "Win Rate",
    format_percentage(wl_stats["win_rate"]),
    delta=f"{wl_stats['total_won']}W / {wl_stats['total_lost']}L" if (wl_stats["total_won"] + wl_stats["total_lost"]) > 0 else None,
    help="Won / (Won + Lost) across all time",
)
st.markdown("---")

# ---------------------------------------------------------------------------
# New Opportunity form (expandable, at top)
# ---------------------------------------------------------------------------
clients = list_clients(conn)
client_map: dict[int, str] = {c["id"]: c["name"] for c in clients}

with st.expander("New Opportunity", expanded=False):
    with st.form("create_opp_form", clear_on_submit=True):
        st.subheader("Create New Opportunity")
        no_col1, no_col2 = st.columns(2)

        with no_col1:
            no_name = st.text_input(
                "Opportunity Name *",
                placeholder="e.g. Coral Gables Condo - Recertification",
            )
            # Client selection: existing or new
            no_client_choice = st.radio(
                "Client",
                ["Select Existing", "Create New"],
                horizontal=True,
                key="no_client_radio",
            )
            if no_client_choice == "Select Existing":
                if clients:
                    no_client_id = st.selectbox(
                        "Client",
                        options=[c["id"] for c in clients],
                        format_func=lambda cid: client_map.get(cid, f"ID {cid}"),
                        key="no_client_select",
                    )
                    no_new_client_name = None
                else:
                    st.caption("No clients yet. Select 'Create New' to add one.")
                    no_client_id = None
                    no_new_client_name = None
            else:
                no_new_client_name = st.text_input(
                    "New Client Name *", key="no_new_client"
                )
                no_client_id = None

            no_service = st.selectbox(
                "Service Line",
                list(SERVICE_LINES),
                format_func=lambda s: SERVICE_LINE_LABELS.get(s, s),
                key="no_service",
            )
            no_source = st.selectbox(
                "Source",
                list(SOURCES),
                format_func=lambda s: SOURCE_LABELS.get(s, s),
                key="no_source",
            )

        with no_col2:
            no_value = st.number_input(
                "Estimated Value ($)", min_value=0.0, step=500.0, format="%.2f",
                key="no_value",
            )
            no_probability = st.slider(
                "Probability (%)", min_value=0, max_value=100, value=50,
                key="no_prob",
            )
            no_close_date = st.date_input(
                "Expected Close Date", value=None, key="no_close",
            )
            no_contact_name = st.text_input("Contact Name", key="no_cname")
            no_contact_email = st.text_input("Contact Email", key="no_cemail")
            no_contact_phone = st.text_input("Contact Phone", key="no_cphone")

        no_notes = st.text_area("Notes", key="no_notes")

        submitted = st.form_submit_button("Create Opportunity", type="primary")
        if submitted:
            if not no_name.strip():
                st.error("Opportunity name is required.")
            else:
                # Resolve client
                resolved_client_id = no_client_id
                if no_client_choice == "Create New":
                    if not no_new_client_name or not no_new_client_name.strip():
                        st.error("New client name is required.")
                        st.stop()
                    resolved_client_id = create_client(conn, no_new_client_name.strip())

                kwargs: dict[str, Any] = {
                    "service_line": no_service,
                    "source": no_source,
                    "estimated_value": no_value,
                    "probability": no_probability,
                }
                if resolved_client_id:
                    kwargs["client_id"] = resolved_client_id
                if no_close_date:
                    kwargs["close_date"] = no_close_date.isoformat()
                if no_contact_name.strip():
                    kwargs["contact_name"] = no_contact_name.strip()
                if no_contact_email.strip():
                    kwargs["contact_email"] = no_contact_email.strip()
                if no_contact_phone.strip():
                    kwargs["contact_phone"] = no_contact_phone.strip()
                if no_notes.strip():
                    kwargs["notes"] = no_notes.strip()

                new_id = create_opportunity(conn, no_name.strip(), **kwargs)
                st.success(f"Opportunity created (ID {new_id}).")
                st.rerun()

# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------
tab_pipeline, tab_clients, tab_analytics = st.tabs(
    ["Pipeline", "Clients", "Analytics"]
)

# ============================= PIPELINE TAB ================================
with tab_pipeline:
    # Search bar
    search_query = st.text_input(
        "Search opportunities",
        placeholder="Search by name, contact, email, or notes...",
        key="opp_search",
        label_visibility="collapsed",
    )

    # Stage sub-tabs
    stage_tab_labels = ["All"] + [STAGE_LABELS[s] for s in STAGES]
    stage_tabs = st.tabs(stage_tab_labels)

    _STAGE_TAB_MAP: dict[int, str | None] = {0: None}
    for i, s in enumerate(STAGES):
        _STAGE_TAB_MAP[i + 1] = s

    for tab_idx, stage_tab in enumerate(stage_tabs):
        with stage_tab:
            stage_filter = _STAGE_TAB_MAP[tab_idx]

            # Fetch opportunities
            if search_query.strip():
                all_results = search_opportunities(conn, search_query.strip())
                if stage_filter:
                    opps = [o for o in all_results if o["stage"] == stage_filter]
                else:
                    opps = all_results
            else:
                opps = list_opportunities(conn, stage=stage_filter)

            if not opps:
                st.info(
                    "No opportunities found."
                    if search_query
                    else "No opportunities in this stage."
                )
                continue

            st.markdown(f"**{len(opps)} opportunit{'ies' if len(opps) != 1 else 'y'}**")

            for opp in opps:
                oid = opp["id"]
                opp_stage = opp["stage"]
                badge = _stage_badge(opp_stage)
                value_str = format_currency(opp["estimated_value"])
                svc = SERVICE_LINE_LABELS.get(opp["service_line"] or "", opp["service_line"] or "")
                client_label = opp["client_name"] or "—"

                header = f"{badge}  **{opp['name']}**  |  {client_label}  |  {svc}  |  {value_str}"

                with st.expander(header, expanded=False):
                    # ---- Detail section ----
                    d_col1, d_col2, d_col3 = st.columns(3)
                    with d_col1:
                        st.markdown(f"**Name:** {opp['name']}")
                        st.markdown(f"**Client:** {client_label}")
                        st.markdown(f"**Service Line:** {svc}")
                        st.markdown(f"**Source:** {SOURCE_LABELS.get(opp['source'] or '', opp['source'] or '---')}")
                        st.markdown(f"**Stage:** {badge}")
                    with d_col2:
                        st.markdown(f"**Estimated Value:** {value_str}")
                        st.markdown(f"**Probability:** {opp['probability'] or 0}%")
                        weighted = (opp["estimated_value"] or 0) * (opp["probability"] or 0) / 100.0
                        st.markdown(f"**Weighted Value:** {format_currency(weighted)}")
                        st.markdown(f"**Close Date:** {format_date(opp['close_date'])}")
                    with d_col3:
                        st.markdown(f"**Contact:** {opp['contact_name'] or '---'}")
                        st.markdown(f"**Email:** {opp['contact_email'] or '---'}")
                        st.markdown(f"**Phone:** {opp['contact_phone'] or '---'}")
                        if opp["project_id"]:
                            st.markdown(f"**Project ID:** {opp['project_id']}")
                    if opp["notes"]:
                        st.markdown(f"**Notes:** {opp['notes']}")

                    st.markdown("---")

                    # ---- Action buttons ----
                    action_col1, action_col2 = st.columns(2)

                    next_stages = _NEXT_STAGES.get(opp_stage, [])
                    with action_col1:
                        if next_stages:
                            adv_cols = st.columns(len(next_stages))
                            for si, ns in enumerate(next_stages):
                                with adv_cols[si]:
                                    btn_label = STAGE_LABELS.get(ns, ns)
                                    btn_type = "primary" if ns == "won" else "secondary"
                                    if st.button(
                                        f"Move to {btn_label}",
                                        key=f"adv_{oid}_{ns}_{tab_idx}",
                                        type=btn_type,
                                        use_container_width=True,
                                    ):
                                        try:
                                            advance_stage(conn, oid, ns)
                                            st.success(f"Moved to {btn_label}.")
                                            st.rerun()
                                        except ValueError as e:
                                            st.error(str(e))

                    with action_col2:
                        if opp_stage == "won" and not opp["project_id"]:
                            if st.button(
                                "Convert to Project",
                                key=f"conv_{oid}_{tab_idx}",
                                type="primary",
                                use_container_width=True,
                            ):
                                try:
                                    proj_id = convert_to_project(conn, oid)
                                    st.success(f"Project created (ID {proj_id}).")
                                    st.rerun()
                                except ValueError as e:
                                    st.error(str(e))
                        elif opp_stage == "won" and opp["project_id"]:
                            st.info(f"Already linked to Project ID {opp['project_id']}")

                    st.markdown("---")

                    # ---- Edit form ----
                    with st.form(f"edit_opp_{oid}_{tab_idx}", clear_on_submit=False):
                        st.markdown("**Edit Opportunity**")
                        e_col1, e_col2 = st.columns(2)
                        with e_col1:
                            e_name = st.text_input(
                                "Name", value=opp["name"],
                                key=f"eon_{oid}_{tab_idx}",
                            )
                            # Client dropdown
                            current_clients = list_clients(conn)
                            client_ids = [0] + [c["id"] for c in current_clients]
                            client_names = ["-- None --"] + [c["name"] for c in current_clients]
                            current_idx = 0
                            if opp["client_id"]:
                                try:
                                    current_idx = client_ids.index(opp["client_id"])
                                except ValueError:
                                    pass
                            e_client_id = st.selectbox(
                                "Client",
                                options=client_ids,
                                index=current_idx,
                                format_func=lambda x: client_names[client_ids.index(x)],
                                key=f"eoc_{oid}_{tab_idx}",
                            )
                            e_service = st.selectbox(
                                "Service Line",
                                list(SERVICE_LINES),
                                index=list(SERVICE_LINES).index(opp["service_line"]) if opp["service_line"] in SERVICE_LINES else 0,
                                format_func=lambda s: SERVICE_LINE_LABELS.get(s, s),
                                key=f"eosv_{oid}_{tab_idx}",
                            )
                            e_source = st.selectbox(
                                "Source",
                                list(SOURCES),
                                index=list(SOURCES).index(opp["source"]) if opp["source"] in SOURCES else 0,
                                format_func=lambda s: SOURCE_LABELS.get(s, s),
                                key=f"eosr_{oid}_{tab_idx}",
                            )

                        with e_col2:
                            e_value = st.number_input(
                                "Estimated Value ($)",
                                value=float(opp["estimated_value"] or 0),
                                min_value=0.0, step=500.0, format="%.2f",
                                key=f"eov_{oid}_{tab_idx}",
                            )
                            e_prob = st.slider(
                                "Probability (%)",
                                min_value=0, max_value=100,
                                value=int(opp["probability"] or 50),
                                key=f"eop_{oid}_{tab_idx}",
                            )
                            e_close = st.date_input(
                                "Close Date",
                                value=_date_input_value(opp["close_date"]),
                                key=f"eocd_{oid}_{tab_idx}",
                            )
                            e_contact_name = st.text_input(
                                "Contact Name",
                                value=opp["contact_name"] or "",
                                key=f"eocn_{oid}_{tab_idx}",
                            )
                            e_contact_email = st.text_input(
                                "Contact Email",
                                value=opp["contact_email"] or "",
                                key=f"eoce_{oid}_{tab_idx}",
                            )
                            e_contact_phone = st.text_input(
                                "Contact Phone",
                                value=opp["contact_phone"] or "",
                                key=f"eocp_{oid}_{tab_idx}",
                            )

                        e_notes = st.text_area(
                            "Notes",
                            value=opp["notes"] or "",
                            key=f"eonotes_{oid}_{tab_idx}",
                        )

                        if st.form_submit_button("Save Changes", type="primary"):
                            updates: dict[str, Any] = {}
                            if e_name.strip() and e_name.strip() != opp["name"]:
                                updates["name"] = e_name.strip()
                            resolved_cid = e_client_id if e_client_id != 0 else None
                            if resolved_cid != opp["client_id"]:
                                updates["client_id"] = resolved_cid
                            if e_service != opp["service_line"]:
                                updates["service_line"] = e_service
                            if e_source != opp["source"]:
                                updates["source"] = e_source
                            if e_value != (opp["estimated_value"] or 0):
                                updates["estimated_value"] = e_value
                            if e_prob != (opp["probability"] or 50):
                                updates["probability"] = e_prob
                            close_str = _date_to_str(e_close)
                            if close_str != opp["close_date"]:
                                updates["close_date"] = close_str
                            if e_contact_name.strip() != (opp["contact_name"] or ""):
                                updates["contact_name"] = e_contact_name.strip()
                            if e_contact_email.strip() != (opp["contact_email"] or ""):
                                updates["contact_email"] = e_contact_email.strip()
                            if e_contact_phone.strip() != (opp["contact_phone"] or ""):
                                updates["contact_phone"] = e_contact_phone.strip()
                            if e_notes.strip() != (opp["notes"] or ""):
                                updates["notes"] = e_notes.strip()

                            if updates:
                                update_opportunity(conn, oid, **updates)
                                st.success("Opportunity updated.")
                                st.rerun()
                            else:
                                st.info("No changes detected.")


# ============================= CLIENTS TAB =================================
with tab_clients:
    cl_search = st.text_input(
        "Search clients",
        placeholder="Search by name...",
        key="client_search",
        label_visibility="collapsed",
    )

    all_clients = list_clients(conn)
    if cl_search.strip():
        q = cl_search.strip().lower()
        display_clients = [
            c for c in all_clients
            if q in (c["name"] or "").lower()
            or q in (c["company"] or "").lower()
            or q in (c["email"] or "").lower()
        ]
    else:
        display_clients = all_clients

    if not display_clients:
        st.info("No clients found." if cl_search else "No clients yet. Add one below.")
    else:
        st.markdown(f"**{len(display_clients)} client{'s' if len(display_clients) != 1 else ''}**")

        for client in display_clients:
            cid = client["id"]
            company_text = f" ({client['company']})" if client["company"] else ""
            with st.expander(f"**{client['name']}**{company_text}", expanded=False):
                # Details
                cd_col1, cd_col2 = st.columns(2)
                with cd_col1:
                    st.markdown(f"**Name:** {client['name']}")
                    st.markdown(f"**Company:** {client['company'] or '---'}")
                    st.markdown(f"**Email:** {client['email'] or '---'}")
                with cd_col2:
                    st.markdown(f"**Phone:** {client['phone'] or '---'}")
                    st.markdown(f"**Address:** {client['address'] or '---'}")
                if client["notes"]:
                    st.markdown(f"**Notes:** {client['notes']}")

                # Client's opportunity history
                st.markdown("---")
                st.markdown("**Opportunity History**")
                client_opps = list_opportunities(conn, client_id=cid)
                if client_opps:
                    for co in client_opps:
                        co_badge = _stage_badge(co["stage"])
                        co_svc = SERVICE_LINE_LABELS.get(co["service_line"] or "", co["service_line"] or "")
                        co_val = format_currency(co["estimated_value"])
                        st.markdown(
                            f"- {co_badge} **{co['name']}** -- {co_svc} -- {co_val} "
                            f"-- Close: {format_date(co['close_date'])}"
                        )
                else:
                    st.caption("No opportunities for this client.")

                # Edit form
                st.markdown("---")
                with st.form(f"edit_client_{cid}", clear_on_submit=False):
                    st.markdown("**Edit Client**")
                    ec_col1, ec_col2 = st.columns(2)
                    with ec_col1:
                        ec_name = st.text_input("Name", value=client["name"], key=f"ecn_{cid}")
                        ec_company = st.text_input("Company", value=client["company"] or "", key=f"ecc_{cid}")
                        ec_email = st.text_input("Email", value=client["email"] or "", key=f"ece_{cid}")
                    with ec_col2:
                        ec_phone = st.text_input("Phone", value=client["phone"] or "", key=f"ecp_{cid}")
                        ec_address = st.text_input("Address", value=client["address"] or "", key=f"eca_{cid}")
                        ec_notes = st.text_area("Notes", value=client["notes"] or "", key=f"ecno_{cid}")

                    if st.form_submit_button("Save Changes", type="primary"):
                        cl_updates: dict[str, Any] = {}
                        if ec_name.strip() and ec_name.strip() != client["name"]:
                            cl_updates["name"] = ec_name.strip()
                        if ec_company.strip() != (client["company"] or ""):
                            cl_updates["company"] = ec_company.strip() or None
                        if ec_email.strip() != (client["email"] or ""):
                            cl_updates["email"] = ec_email.strip() or None
                        if ec_phone.strip() != (client["phone"] or ""):
                            cl_updates["phone"] = ec_phone.strip() or None
                        if ec_address.strip() != (client["address"] or ""):
                            cl_updates["address"] = ec_address.strip() or None
                        if ec_notes.strip() != (client["notes"] or ""):
                            cl_updates["notes"] = ec_notes.strip() or None
                        if cl_updates:
                            update_client(conn, cid, **cl_updates)
                            st.success("Client updated.")
                            st.rerun()
                        else:
                            st.info("No changes detected.")

    # Create new client
    st.markdown("---")
    st.subheader("Add New Client")
    with st.form("create_client_form", clear_on_submit=True):
        nc_col1, nc_col2 = st.columns(2)
        with nc_col1:
            nc_name = st.text_input("Name *", key="nc_name")
            nc_company = st.text_input("Company", key="nc_company")
            nc_email = st.text_input("Email", key="nc_email")
        with nc_col2:
            nc_phone = st.text_input("Phone", key="nc_phone")
            nc_address = st.text_input("Address", key="nc_address")
            nc_notes = st.text_area("Notes", key="nc_notes")

        if st.form_submit_button("Add Client", type="primary"):
            if not nc_name.strip():
                st.error("Client name is required.")
            else:
                new_cid = create_client(
                    conn,
                    nc_name.strip(),
                    company=nc_company.strip() or None,
                    email=nc_email.strip() or None,
                    phone=nc_phone.strip() or None,
                    address=nc_address.strip() or None,
                    notes=nc_notes.strip() or None,
                )
                st.success(f"Client added (ID {new_cid}).")
                st.rerun()


# ============================= ANALYTICS TAB ================================
with tab_analytics:

    # ---- Win/Loss Stats ----
    st.subheader("Win / Loss Performance")

    # Date range filter
    an_col1, an_col2 = st.columns(2)
    with an_col1:
        an_from = st.date_input("From Date", value=None, key="an_from")
    with an_col2:
        an_to = st.date_input("To Date", value=None, key="an_to")

    filtered_wl = get_win_loss_stats(
        conn,
        date_from=an_from.isoformat() if an_from else None,
        date_to=an_to.isoformat() if an_to else None,
    )

    wl_col1, wl_col2, wl_col3, wl_col4, wl_col5 = st.columns(5)
    wl_col1.metric("Won", str(filtered_wl["total_won"]))
    wl_col2.metric("Lost", str(filtered_wl["total_lost"]))
    wl_col3.metric("Win Rate", format_percentage(filtered_wl["win_rate"]))
    wl_col4.metric("Avg Deal Size", format_currency(filtered_wl["avg_deal_size"]))
    wl_col5.metric("Total Won Value", format_currency(filtered_wl["total_won_value"]))

    st.markdown("---")

    # ---- Pipeline by Service Line ----
    st.subheader("Pipeline by Service Line")

    svc_rows = conn.execute(
        "SELECT service_line, "
        "       COUNT(*) AS count, "
        "       COALESCE(SUM(estimated_value), 0) AS total_value, "
        "       COALESCE(SUM(estimated_value * probability / 100.0), 0) AS weighted_value "
        "FROM opportunities "
        "WHERE stage NOT IN ('lost', 'dormant') AND service_line IS NOT NULL "
        "GROUP BY service_line "
        "ORDER BY total_value DESC"
    ).fetchall()

    if svc_rows:
        # Build data for a bar chart
        import pandas as pd

        chart_data = pd.DataFrame(
            [
                {
                    "Service Line": SERVICE_LINE_LABELS.get(r["service_line"], r["service_line"]),
                    "Total Value": r["total_value"],
                    "Weighted Value": r["weighted_value"],
                    "Count": r["count"],
                }
                for r in svc_rows
            ]
        )
        st.bar_chart(
            chart_data.set_index("Service Line")[["Total Value", "Weighted Value"]],
        )

        # Table view
        for row in svc_rows:
            svc_label = SERVICE_LINE_LABELS.get(row["service_line"], row["service_line"])
            st.markdown(
                f"**{svc_label}** -- {row['count']} opp{'s' if row['count'] != 1 else ''} -- "
                f"Total: {format_currency(row['total_value'])} -- "
                f"Weighted: {format_currency(row['weighted_value'])}"
            )
    else:
        st.info("No active opportunities to chart.")

    st.markdown("---")

    # ---- Pipeline by Stage ----
    st.subheader("Pipeline by Stage")
    if summary["by_stage"]:
        stage_order = ["lead", "qualifying", "proposal_sent", "negotiating", "won"]
        for s in stage_order:
            if s in summary["by_stage"]:
                data = summary["by_stage"][s]
                badge = _stage_badge(s)
                st.markdown(
                    f"{badge} -- {data['count']} opp{'s' if data['count'] != 1 else ''} -- "
                    f"Total: {format_currency(data['total_value'])} -- "
                    f"Weighted: {format_currency(data['weighted_value'])}"
                )
    else:
        st.info("No active pipeline data.")

    st.markdown("---")

    # ---- Monthly Trends ----
    st.subheader("Monthly Trends (Won Opportunities)")

    monthly_rows = conn.execute(
        "SELECT strftime('%Y-%m', updated_at) AS month, "
        "       COUNT(*) AS count, "
        "       COALESCE(SUM(estimated_value), 0) AS total_value "
        "FROM opportunities "
        "WHERE stage = 'won' "
        "GROUP BY month "
        "ORDER BY month DESC "
        "LIMIT 12"
    ).fetchall()

    if monthly_rows:
        import pandas as pd

        trend_data = pd.DataFrame(
            [
                {
                    "Month": r["month"],
                    "Deals Won": r["count"],
                    "Value Won": r["total_value"],
                }
                for r in reversed(monthly_rows)
            ]
        )
        st.bar_chart(trend_data.set_index("Month")[["Value Won"]])

        for row in monthly_rows:
            st.markdown(
                f"**{row['month']}** -- {row['count']} deal{'s' if row['count'] != 1 else ''} -- "
                f"{format_currency(row['total_value'])}"
            )
    else:
        st.info("No won opportunities yet to show trends.")
