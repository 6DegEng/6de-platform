"""Projects — 6th Degree Engineering Company Platform.

Full project management page: list, create, edit, search, milestones,
calculator integration, and per-status filtering.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Path bootstrap — allow imports from the platform root
# ---------------------------------------------------------------------------
_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from config import CALC_EXE_PATH  # noqa: E402
from db import ensure_db, get_calc_connection  # noqa: E402
from modules.calculator.bridge import (  # noqa: E402
    get_calc_outputs,
    get_linked_calcs,
    link_calc_to_erp,
    read_calc_projects,
)
from modules.projects.crud import (  # noqa: E402
    create_milestone,
    create_project,
    delete_project,
    get_project,
    get_project_stats,
    list_milestones,
    list_projects,
    search_projects,
    update_milestone,
    update_project,
)
from streamlit_app.auth import require_auth  # noqa: E402

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Projects | 6DE", page_icon="🏗️", layout="wide")
require_auth()
st.title("Projects")

conn = ensure_db()

# ---------------------------------------------------------------------------
# Status styling helpers
# ---------------------------------------------------------------------------
_STATUS_COLORS = {
    "active": "green",
    "prospect": "orange",
    "completed": "gray",
    "on_hold": "red",
    "archived": "violet",
}

_STATUS_ICONS = {
    "active": "🟢",
    "prospect": "🟡",
    "completed": "⚪",
    "on_hold": "🔴",
    "archived": "🟣",
}

_MILESTONE_ICONS = {
    "pending": "⬜",
    "in_progress": "🔵",
    "completed": "✅",
    "skipped": "⏭️",
}


def _status_badge(status: str) -> str:
    icon = _STATUS_ICONS.get(status, "")
    return f"{icon} {status.replace('_', ' ').title()}"


# ---------------------------------------------------------------------------
# Stats summary
# ---------------------------------------------------------------------------
stats = get_project_stats(conn)

st.markdown("---")
cols = st.columns(5)
cols[0].metric("Total Projects", stats.get("total", 0))
cols[1].metric("Active", stats.get("active", 0))
cols[2].metric("Prospects", stats.get("prospect", 0))
cols[3].metric("On Hold", stats.get("on_hold", 0))
cols[4].metric("Completed", stats.get("completed", 0))
st.markdown("---")

# ---------------------------------------------------------------------------
# Create project form (expandable)
# ---------------------------------------------------------------------------
with st.expander("Create New Project", expanded=False):
    with st.form("create_project_form", clear_on_submit=True):
        st.subheader("New Project")
        cp_col1, cp_col2 = st.columns(2)
        with cp_col1:
            cp_name = st.text_input("Project Name *", placeholder="e.g. Buena Vista Apartments")
            cp_address = st.text_input("Address", placeholder="1234 NW 1st Ave")
            cp_city = st.text_input("City", value="Miami")
            cp_scope = st.text_area("Scope", placeholder="Brief description of work")
        with cp_col2:
            cp_job = st.text_input(
                "Job Number",
                placeholder="Auto-generated if blank (YYMMDD)",
            )
            cp_status = st.selectbox(
                "Status",
                ["active", "prospect", "on_hold", "completed", "archived"],
                index=0,
            )
            cp_county = st.text_input("County", value="Miami-Dade")
            cp_start = st.date_input("Start Date", value=date.today())
            cp_target_end = st.date_input("Target End Date", value=None)

        cp_notes = st.text_area("Notes", key="cp_notes")

        submitted = st.form_submit_button("Create Project", type="primary")
        if submitted:
            if not cp_name.strip():
                st.error("Project name is required.")
            else:
                kwargs: dict = {
                    "name": cp_name.strip(),
                    "status": cp_status,
                    "city": cp_city.strip(),
                    "county": cp_county.strip(),
                    "state": "FL",
                }
                if cp_job.strip():
                    kwargs["job_number"] = cp_job.strip()
                if cp_address.strip():
                    kwargs["address"] = cp_address.strip()
                if cp_scope.strip():
                    kwargs["scope"] = cp_scope.strip()
                if cp_start:
                    kwargs["start_date"] = cp_start.isoformat()
                if cp_target_end:
                    kwargs["target_end_date"] = cp_target_end.isoformat()
                if cp_notes.strip():
                    kwargs["notes"] = cp_notes.strip()

                new_id = create_project(conn, **kwargs)
                st.success(f"Project created (ID {new_id}).")
                st.rerun()

# ---------------------------------------------------------------------------
# Search bar
# ---------------------------------------------------------------------------
search_query = st.text_input(
    "Search projects",
    placeholder="Search by name, address, or job number ...",
    label_visibility="collapsed",
)

# ---------------------------------------------------------------------------
# Status filter tabs
# ---------------------------------------------------------------------------
tab_labels = ["All", "Active", "Prospect", "On Hold", "Completed", "Archived"]
tabs = st.tabs(tab_labels)

_TAB_STATUS_MAP: dict[int, str | None] = {
    0: None,
    1: "active",
    2: "prospect",
    3: "on_hold",
    4: "completed",
    5: "archived",
}

for tab_idx, tab in enumerate(tabs):
    with tab:
        status_filter = _TAB_STATUS_MAP[tab_idx]

        # Fetch projects
        if search_query.strip():
            all_results = search_projects(conn, search_query.strip())
            if status_filter:
                projects = [p for p in all_results if p["status"] == status_filter]
            else:
                projects = all_results
        else:
            projects = list_projects(conn, status_filter=status_filter)

        if not projects:
            st.info("No projects found." if search_query else "No projects in this category.")
            continue

        # ----- Project cards -----
        for proj in projects:
            pid = proj["id"]
            badge = _status_badge(proj["status"])
            header = f"{proj['job_number']} — {proj['name']}"
            if proj["client_name"]:
                header += f"  |  {proj['client_name']}"

            with st.expander(f"{badge}  **{header}**"):
                # ---- Detail / edit section ----
                detail_tab, edit_tab, milestone_tab, calc_tab = st.tabs(
                    ["Details", "Edit", "Milestones", "Calculations"]
                )

                # --- Details ---
                with detail_tab:
                    d_col1, d_col2 = st.columns(2)
                    with d_col1:
                        st.markdown(f"**Job Number:** {proj['job_number']}")
                        st.markdown(f"**Name:** {proj['name']}")
                        st.markdown(f"**Status:** {badge}")
                        st.markdown(f"**Client:** {proj['client_name'] or '—'}")
                        st.markdown(f"**Address:** {proj['address'] or '—'}")
                    with d_col2:
                        st.markdown(
                            f"**City:** {proj['city'] or '—'}  /  "
                            f"**County:** {proj['county'] or '—'}  /  "
                            f"**State:** {proj['state'] or '—'}"
                        )
                        st.markdown(f"**Start Date:** {proj['start_date'] or '—'}")
                        st.markdown(f"**Target End:** {proj['target_end_date'] or '—'}")
                        st.markdown(f"**Actual End:** {proj['actual_end_date'] or '—'}")
                        st.markdown(f"**Folder:** `{proj['folder_path'] or '—'}`")
                    if proj["scope"]:
                        st.markdown(f"**Scope:** {proj['scope']}")
                    if proj["notes"]:
                        st.markdown(f"**Notes:** {proj['notes']}")

                # --- Edit ---
                with edit_tab:
                    with st.form(f"edit_{pid}", clear_on_submit=False):
                        e_col1, e_col2 = st.columns(2)
                        with e_col1:
                            e_name = st.text_input("Name", value=proj["name"], key=f"en_{pid}")
                            e_address = st.text_input(
                                "Address", value=proj["address"] or "", key=f"ea_{pid}"
                            )
                            e_city = st.text_input(
                                "City", value=proj["city"] or "Miami", key=f"ec_{pid}"
                            )
                            e_scope = st.text_area(
                                "Scope", value=proj["scope"] or "", key=f"es_{pid}"
                            )
                        with e_col2:
                            current_statuses = [
                                "active", "prospect", "on_hold", "completed", "archived",
                            ]
                            e_status = st.selectbox(
                                "Status",
                                current_statuses,
                                index=current_statuses.index(proj["status"]),
                                key=f"est_{pid}",
                            )
                            e_county = st.text_input(
                                "County",
                                value=proj["county"] or "Miami-Dade",
                                key=f"eco_{pid}",
                            )
                            e_start = st.text_input(
                                "Start Date (YYYY-MM-DD)",
                                value=proj["start_date"] or "",
                                key=f"esd_{pid}",
                            )
                            e_target = st.text_input(
                                "Target End Date (YYYY-MM-DD)",
                                value=proj["target_end_date"] or "",
                                key=f"ete_{pid}",
                            )
                            e_actual = st.text_input(
                                "Actual End Date (YYYY-MM-DD)",
                                value=proj["actual_end_date"] or "",
                                key=f"eae_{pid}",
                            )
                        e_notes = st.text_area(
                            "Notes", value=proj["notes"] or "", key=f"eno_{pid}"
                        )

                        save_col, delete_col = st.columns([3, 1])
                        with save_col:
                            save_clicked = st.form_submit_button(
                                "Save Changes", type="primary"
                            )
                        with delete_col:
                            delete_clicked = st.form_submit_button(
                                "Delete Project"
                            )

                        if save_clicked:
                            updates: dict = {}
                            if e_name.strip() and e_name.strip() != proj["name"]:
                                updates["name"] = e_name.strip()
                            if e_status != proj["status"]:
                                updates["status"] = e_status
                            if e_address.strip() != (proj["address"] or ""):
                                updates["address"] = e_address.strip()
                            if e_city.strip() != (proj["city"] or ""):
                                updates["city"] = e_city.strip()
                            if e_county.strip() != (proj["county"] or ""):
                                updates["county"] = e_county.strip()
                            if e_scope.strip() != (proj["scope"] or ""):
                                updates["scope"] = e_scope.strip()
                            if e_notes.strip() != (proj["notes"] or ""):
                                updates["notes"] = e_notes.strip()
                            if e_start.strip() != (proj["start_date"] or ""):
                                updates["start_date"] = e_start.strip() or None
                            if e_target.strip() != (proj["target_end_date"] or ""):
                                updates["target_end_date"] = e_target.strip() or None
                            if e_actual.strip() != (proj["actual_end_date"] or ""):
                                updates["actual_end_date"] = e_actual.strip() or None
                            if updates:
                                update_project(conn, pid, **updates)
                                st.success("Project updated.")
                                st.rerun()
                            else:
                                st.info("No changes detected.")

                        if delete_clicked:
                            st.session_state[f"confirm_delete_{pid}"] = True

                    # Confirmation outside the form
                    if st.session_state.get(f"confirm_delete_{pid}", False):
                        st.warning(
                            f"Are you sure you want to delete **{proj['name']}** "
                            f"({proj['job_number']})? This cannot be undone."
                        )
                        c1, c2, _ = st.columns([1, 1, 3])
                        with c1:
                            if st.button("Yes, delete", key=f"del_yes_{pid}", type="primary"):
                                delete_project(conn, pid)
                                st.session_state.pop(f"confirm_delete_{pid}", None)
                                st.success("Project deleted.")
                                st.rerun()
                        with c2:
                            if st.button("Cancel", key=f"del_no_{pid}"):
                                st.session_state.pop(f"confirm_delete_{pid}", None)
                                st.rerun()

                # --- Milestones ---
                with milestone_tab:
                    milestones = list_milestones(conn, pid)

                    if milestones:
                        for ms in milestones:
                            ms_id = ms["id"]
                            icon = _MILESTONE_ICONS.get(ms["status"], "")
                            due = f" — due {ms['due_date']}" if ms["due_date"] else ""
                            completed_info = ""
                            if ms["completed_date"]:
                                completed_info = f"  (completed {ms['completed_date']})"

                            ms_col1, ms_col2, ms_col3 = st.columns([5, 2, 2])
                            with ms_col1:
                                st.markdown(
                                    f"{icon} **{ms['name']}**{due}{completed_info}"
                                )
                            with ms_col2:
                                if ms["status"] in ("pending", "in_progress"):
                                    if st.button(
                                        "Mark Complete",
                                        key=f"ms_done_{ms_id}_{tab_idx}",
                                    ):
                                        update_milestone(
                                            conn,
                                            ms_id,
                                            status="completed",
                                            completed_date=date.today().isoformat(),
                                        )
                                        st.rerun()
                                elif ms["status"] == "completed":
                                    st.caption("Completed")
                            with ms_col3:
                                if ms["status"] in ("pending", "in_progress"):
                                    new_status = (
                                        "in_progress"
                                        if ms["status"] == "pending"
                                        else "pending"
                                    )
                                    label = (
                                        "Start"
                                        if ms["status"] == "pending"
                                        else "Reset to Pending"
                                    )
                                    if st.button(
                                        label,
                                        key=f"ms_toggle_{ms_id}_{tab_idx}",
                                    ):
                                        update_milestone(
                                            conn, ms_id, status=new_status
                                        )
                                        st.rerun()
                    else:
                        st.caption("No milestones yet.")

                    # Add milestone form
                    st.markdown("---")
                    with st.form(f"add_ms_{pid}_{tab_idx}", clear_on_submit=True):
                        ms_add_col1, ms_add_col2 = st.columns([3, 1])
                        with ms_add_col1:
                            ms_name = st.text_input(
                                "Milestone name",
                                placeholder="e.g. Submit permit application",
                                key=f"msn_{pid}_{tab_idx}",
                            )
                        with ms_add_col2:
                            ms_due = st.date_input(
                                "Due date (optional)",
                                value=None,
                                key=f"msd_{pid}_{tab_idx}",
                            )
                        if st.form_submit_button("Add Milestone"):
                            if not ms_name.strip():
                                st.error("Milestone name is required.")
                            else:
                                create_milestone(
                                    conn,
                                    pid,
                                    ms_name.strip(),
                                    due_date=ms_due.isoformat() if ms_due else None,
                                )
                                st.success(f"Milestone added.")
                                st.rerun()

                # --- Calculations ---
                with calc_tab:
                    calc_conn = get_calc_connection()
                    linked_calcs = get_linked_calcs(conn, pid)

                    # -- Open in Calculator button --
                    btn_col, info_col = st.columns([1, 3])
                    with btn_col:
                        if st.button(
                            "Open in Calculator",
                            key=f"open_calc_{pid}_{tab_idx}",
                        ):
                            try:
                                if CALC_EXE_PATH.exists():
                                    subprocess.Popen([str(CALC_EXE_PATH)])
                                    st.toast("Calculator launched.", icon="🔢")
                                else:
                                    st.warning(
                                        f"Calculator executable not found at "
                                        f"`{CALC_EXE_PATH}`."
                                    )
                            except Exception as exc:
                                st.error(f"Failed to launch calculator: {exc}")
                    with info_col:
                        if linked_calcs:
                            st.caption(
                                f"{len(linked_calcs)} linked calc "
                                f"project{'s' if len(linked_calcs) != 1 else ''}"
                            )

                    if linked_calcs and calc_conn is not None:
                        # -- Show outputs for each linked calc project --
                        for lk in linked_calcs:
                            calc_pid = lk["calc_project_id"]
                            st.markdown(
                                f"**Calc Project #{calc_pid}** "
                                f"({lk['structure_type'] or 'unknown type'}) "
                                f"— linked {lk['linked_at'] or '—'}"
                            )

                            outputs = get_calc_outputs(calc_conn, calc_pid)
                            if outputs:
                                for out in outputs:
                                    if out.get("overall_pass") is True:
                                        icon = "✅"
                                        status_text = "PASS"
                                    elif out.get("overall_pass") is False:
                                        icon = "❌"
                                        status_text = "FAIL"
                                    else:
                                        icon = "⏳"
                                        status_text = "Pending"

                                    ts_display = out.get("timestamp") or "—"
                                    standards = (
                                        ", ".join(out["standards_cited"])
                                        if out["standards_cited"]
                                        else "—"
                                    )

                                    st.markdown(
                                        f"{icon} **{out['title']}** — "
                                        f"{status_text} | "
                                        f"{out['step_count']} steps | "
                                        f"Standards: {standards} | "
                                        f"Last run: {ts_display}"
                                    )
                            else:
                                st.caption("No calculation outputs yet.")

                            st.markdown("---")
                    elif linked_calcs and calc_conn is None:
                        st.warning(
                            "Calculator database (common.db) not found. "
                            "Run a calculation first to see outputs."
                        )
                    else:
                        st.info("No calculator project linked yet.")

                    # -- Link Calculator Project section --
                    if calc_conn is not None:
                        st.markdown("**Link Calculator Project**")
                        calc_projects = read_calc_projects(calc_conn)
                        if calc_projects:
                            with st.form(
                                f"link_calc_{pid}_{tab_idx}",
                                clear_on_submit=True,
                            ):
                                calc_options = {}
                                for cp in calc_projects:
                                    label = (
                                        f"#{cp['project_id']} — "
                                        f"{cp.get('project_name', 'Untitled')} "
                                        f"({cp.get('structure_type', '?')})"
                                    )
                                    calc_options[label] = cp["project_id"]
                                calc_sel = st.selectbox(
                                    "Calculator Project",
                                    list(calc_options.keys()),
                                    key=f"calc_sel_{pid}_{tab_idx}",
                                )
                                if st.form_submit_button("Link Project"):
                                    calc_id = calc_options[calc_sel]
                                    link_calc_to_erp(
                                        conn, pid, calc_id, calc_conn
                                    )
                                    st.success(
                                        f"Linked calc #{calc_id} to this project."
                                    )
                                    st.rerun()
                        else:
                            st.caption(
                                "No calculator projects found in common.db."
                            )

                    if calc_conn is not None:
                        calc_conn.close()
