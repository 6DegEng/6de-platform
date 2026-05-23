"""Projects — 6th Degree Engineering Company Platform.

Full project management page: list, create, edit, search, milestones,
calculator integration, and per-status filtering.

Session 3a introduces a four-view switcher (Table / Kanban / Timeline /
Calendar). This subagent lands the scaffold wiring only — Table view
reuses the existing per-project expander rendering as a stub; the other
three views are placeholders for subagents 4-6 to fill in.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Sequence

import streamlit as st

# ---------------------------------------------------------------------------
# Path bootstrap — allow imports from the platform root
# ---------------------------------------------------------------------------
_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from config import CALC_EXE_PATH, MSGRAPH_CLIENT_ID, MSGRAPH_TENANT_ID  # noqa: E402
from db import ensure_db, get_calc_connection  # noqa: E402
from modules.calculator.bridge import (  # noqa: E402
    get_calc_outputs,
    get_linked_calcs,
    link_calc_to_erp,
    read_calc_projects,
)
from modules.documents.crud import list_documents  # noqa: E402
from modules.documents.sharepoint import CATEGORIES  # noqa: E402
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
from streamlit_app.components.project_grid import render_project_grid  # noqa: E402
from streamlit_app.components.status_pills import (  # noqa: E402
    PROJECT_STATUS_LABELS,
    PROJECT_STATUSES,
    render_status_pill,
)

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Projects | 6DE", page_icon="🏗️", layout="wide")
require_auth()
st.title("Projects")

conn = ensure_db()

# ---------------------------------------------------------------------------
# Session-state defaults — initialize BEFORE any UI renders so reruns see them.
# Persistent `ui:projects:*` namespace shared across the 4 views.
# ---------------------------------------------------------------------------
st.session_state.setdefault("ui:projects:view", "Table")
st.session_state.setdefault("ui:projects:focus", None)
st.session_state.setdefault("ui:projects:status_filter", None)
st.session_state.setdefault("ui:projects:expanded", set())
st.session_state.setdefault("ui:projects:_test_visible_ids", [])

# ---------------------------------------------------------------------------
# Milestone icon styling (kept page-local; not part of the status_pills module)
# ---------------------------------------------------------------------------
_MILESTONE_ICONS = {
    "pending": "⬜",
    "in_progress": "🔵",
    "completed": "✅",
    "skipped": "⏭️",
}


def open_project(pid: int) -> None:
    """Flip the shared focus slot so the detail panel binds to this project.

    Subagents 4-6 (table / kanban / timeline / calendar view authors) wire
    their row / card / bar click handlers to this helper. This subagent
    only sets up the slot — no callers in scaffolding code yet.
    """
    st.session_state["ui:projects:focus"] = pid


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
                list(PROJECT_STATUSES),
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
# Search bar — wrapped in an st.form so Enter explicitly commits the query.
# A bare st.text_input shows the browser focus indicator on Enter but doesn't
# reliably trigger a rerun across all Streamlit versions; the form wrapper
# binds Enter to form_submit_button, guaranteeing commit.
#
# Phase B regression test (tests/test_projects_search.py) asserts the label
# is exactly "Search projects" and form_id is non-empty — do NOT relocate
# or rename without updating that test.
# ---------------------------------------------------------------------------
with st.form("project_search_form", clear_on_submit=False, border=False):
    sf_col1, sf_col2 = st.columns([10, 1])
    with sf_col1:
        search_query = st.text_input(
            "Search projects",
            placeholder="Search by name, address, or job number ...",
            label_visibility="collapsed",
            key="project_search_query",
        )
    with sf_col2:
        st.form_submit_button("Search")

# ---------------------------------------------------------------------------
# View switcher + status filter
# ---------------------------------------------------------------------------
view_col, filter_col = st.columns([2, 5])

with view_col:
    st.radio(
        "View",
        options=["Table", "Kanban", "Timeline", "Calendar"],
        horizontal=True,
        label_visibility="collapsed",
        key="ui:projects:view",
    )

with filter_col:
    # Status filter — single segmented control replaces the old 6-tab strip.
    # "All" maps to None; each named status maps to its enum value.
    _filter_options = ["All"] + [PROJECT_STATUS_LABELS[s] for s in PROJECT_STATUSES]
    _current = st.session_state["ui:projects:status_filter"]
    _current_label = (
        "All" if _current is None else PROJECT_STATUS_LABELS.get(_current, "All")
    )
    selected_label = st.segmented_control(
        "Status filter",
        options=_filter_options,
        default=_current_label,
        label_visibility="collapsed",
        key="ui:projects:status_filter_widget",
    )
    if selected_label is None or selected_label == "All":
        st.session_state["ui:projects:status_filter"] = None
    else:
        # Reverse-lookup label -> enum value.
        for _enum, _lbl in PROJECT_STATUS_LABELS.items():
            if _lbl == selected_label:
                st.session_state["ui:projects:status_filter"] = _enum
                break

status_filter: Optional[str] = st.session_state["ui:projects:status_filter"]

# ---------------------------------------------------------------------------
# Fetch projects ONCE per render at the top of the page (was 6x — one per
# status tab). Each view then filters this list in memory by the active
# status filter.
# ---------------------------------------------------------------------------
if search_query.strip():
    all_projects = search_projects(conn, search_query.strip())
else:
    all_projects = list_projects(conn)

visible_projects = [
    p for p in all_projects if status_filter is None or p["status"] == status_filter
]

# Test hook — populated BEFORE rendering so even a render error leaves the
# session_state slot set to the would-be-visible list. Read by the 3
# AppTest tests in tests/test_projects_search.py.
st.session_state["ui:projects:_test_visible_ids"] = [p["id"] for p in visible_projects]


# ---------------------------------------------------------------------------
# View renderers
# ---------------------------------------------------------------------------
def _render_project_detail_tabs(proj, tab_idx: int = 0) -> None:
    """Render the 5-tab project detail UI WITHOUT an enclosing ``st.expander``.

    Used by:
      * ``_render_project_expander`` — wraps this in an expander (legacy
        per-row layout, kept available for any future view that wants it).
      * Table view's detail panel — renders the tabs directly below the
        aggrid for the focused project (one project shown at a time).

    The per-row widget keys MUST stay namespaced by ``t{tab_idx}_p{pid}``
    (see tests/test_smoke.py:test_no_duplicate_widget_keys_in_projects_page).
    """
    pid = proj["id"]
    status_html = render_status_pill(proj["status"])
    detail_tab, edit_tab, milestone_tab, calc_tab, docs_tab = st.tabs(
        ["Details", "Edit", "Milestones", "Calculations", "Documents"]
    )

    # --- Details ---
    with detail_tab:
        d_col1, d_col2 = st.columns(2)
        with d_col1:
            st.markdown(f"**Job Number:** {proj['job_number']}")
            st.markdown(f"**Name:** {proj['name']}")
            st.markdown(
                f"**Status:** {status_html}",
                unsafe_allow_html=True,
            )
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
        key_ns = f"t{tab_idx}_p{pid}"
        with st.form(f"edit_{key_ns}", clear_on_submit=False):
            e_col1, e_col2 = st.columns(2)
            with e_col1:
                e_name = st.text_input("Name", value=proj["name"], key=f"en_{key_ns}")
                e_address = st.text_input(
                    "Address", value=proj["address"] or "", key=f"ea_{key_ns}"
                )
                e_city = st.text_input(
                    "City", value=proj["city"] or "Miami", key=f"ec_{key_ns}"
                )
                e_scope = st.text_area(
                    "Scope", value=proj["scope"] or "", key=f"es_{key_ns}"
                )
            with e_col2:
                e_status = st.selectbox(
                    "Status",
                    list(PROJECT_STATUSES),
                    index=PROJECT_STATUSES.index(proj["status"]),
                    key=f"est_{key_ns}",
                )
                e_county = st.text_input(
                    "County",
                    value=proj["county"] or "Miami-Dade",
                    key=f"eco_{key_ns}",
                )
                e_start = st.text_input(
                    "Start Date (YYYY-MM-DD)",
                    value=proj["start_date"] or "",
                    key=f"esd_{key_ns}",
                )
                e_target = st.text_input(
                    "Target End Date (YYYY-MM-DD)",
                    value=proj["target_end_date"] or "",
                    key=f"ete_{key_ns}",
                )
                e_actual = st.text_input(
                    "Actual End Date (YYYY-MM-DD)",
                    value=proj["actual_end_date"] or "",
                    key=f"eae_{key_ns}",
                )
            e_notes = st.text_area(
                "Notes", value=proj["notes"] or "", key=f"eno_{key_ns}"
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
                if st.button("Yes, delete", key=f"del_yes_{key_ns}", type="primary"):
                    delete_project(conn, pid)
                    st.session_state.pop(f"confirm_delete_{pid}", None)
                    st.success("Project deleted.")
                    st.rerun()
            with c2:
                if st.button("Cancel", key=f"del_no_{key_ns}"):
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

    # --- Documents (Phase 2 — SharePoint document layer) ---
    with docs_tab:
        docs = list_documents(conn, entity_type="project", entity_id=pid)
        sharepoint_configured = bool(MSGRAPH_CLIENT_ID and MSGRAPH_TENANT_ID)

        status_col, count_col = st.columns([3, 1])
        with status_col:
            if sharepoint_configured:
                st.caption("✅ SharePoint configured")
            else:
                st.caption(
                    "⚙️ SharePoint not configured — set `MSGRAPH_CLIENT_ID` "
                    "and `MSGRAPH_TENANT_ID` to enable uploads. "
                    "Indexed files below still link to OneDrive."
                )
        with count_col:
            st.metric("Documents", len(docs))

        if not docs:
            st.info(
                "No documents indexed yet. Run "
                "`python scripts/scan_existing_project_docs.py --commit "
                f"--job {proj['job_number']}` to backfill from OneDrive."
            )
        else:
            # Group by category. Category lives in notes JSON (backfilled)
            # or is derivable from file_path's penultimate segment.
            import json as _json
            grouped: dict[str, list] = {c: [] for c in CATEGORIES}
            ungrouped: list = []
            for doc in docs:
                category = None
                if doc["notes"]:
                    try:
                        meta = _json.loads(doc["notes"])
                        category = meta.get("category")
                    except (ValueError, TypeError):
                        pass
                if not category and doc["file_path"]:
                    # Derive from path: .../{NUM}_{NAME}/{CATEGORY}/file
                    parts = doc["file_path"].split("/")
                    if len(parts) >= 2 and parts[-2] in CATEGORIES:
                        category = parts[-2]
                if category in CATEGORIES:
                    grouped[category].append(doc)
                else:
                    ungrouped.append(doc)

            for category in CATEGORIES:
                items = grouped[category]
                if not items:
                    continue
                st.markdown(f"**{category}** ({len(items)})")
                for doc in items:
                    row_a, row_b = st.columns([5, 2])
                    with row_a:
                        st.write(f"📄 {doc['file_name']}")
                    with row_b:
                        if doc["sharepoint_web_url"]:
                            st.markdown(
                                f"[Open in SharePoint]({doc['sharepoint_web_url']})"
                            )
                        elif doc["file_path"]:
                            st.caption(f"`{doc['file_path']}`")
            if ungrouped:
                with st.expander(f"Uncategorized ({len(ungrouped)})"):
                    for doc in ungrouped:
                        st.write(f"📄 {doc['file_name']}  —  `{doc['file_path']}`")


def _render_project_expander(proj, tab_idx: int = 0) -> None:
    """Render the 5-tab detail UI wrapped in an ``st.expander``.

    Kept for any view that wants the legacy per-row expander layout.
    The Table view no longer calls this — it uses the aggrid grid + a
    single detail panel keyed off ``ui:projects:focus``.
    """
    status_label = PROJECT_STATUS_LABELS.get(
        proj["status"], proj["status"].replace("_", " ").title()
    )
    header = f"{proj['job_number']} — {proj['name']}"
    if proj["client_name"]:
        header += f"  |  {proj['client_name']}"
    with st.expander(f"[{status_label}]  **{header}**"):
        _render_project_detail_tabs(proj, tab_idx=tab_idx)


def render_table_view(projects: Sequence) -> None:
    """Table view — streamlit-aggrid grid + a single detail panel.

    Rows are inline-editable for the safe columns (name, status, address,
    city, county, scope, dates, notes). Status edits route through an
    ``agSelectCellEditor`` constrained to ``PROJECT_STATUSES``. All saves
    funnel through ``modules.projects.crud.update_project`` via the
    ``project_grid.handle_row_save`` helper — NO ``st.rerun()`` in the
    save path (aggrid handles its own redraw).

    Clicking a row sets ``st.session_state['ui:projects:focus']`` to that
    project's ID. The detail panel below the grid renders the 5-tab UI
    (Details / Edit / Milestones / Calculations / Documents) for that
    one project. ``← Close`` returns focus to None.
    """
    # Empty-state handling — mirrors the wording the existing tests don't
    # assert against, so we have room to phrase it nicely.
    if not projects:
        if search_query.strip():
            st.info(f"No projects match '{search_query.strip()}'.")
        elif status_filter is None:
            st.info(
                "No projects yet. Use the form above to create your "
                "first project."
            )
        else:
            label = PROJECT_STATUS_LABELS.get(status_filter, status_filter)
            st.info(f"No {label} projects.")
        return

    # ---- Render the grid ----
    response = render_project_grid(conn, projects, key="ui:projects:grid")

    # ---- Selection -> focus slot ----
    selected = response.get("selected_rows")
    selected_pid: Optional[int] = None
    if selected is not None:
        try:
            if hasattr(selected, "iloc") and len(selected) > 0:
                selected_pid = int(selected.iloc[0]["id"])
            elif isinstance(selected, list) and selected:
                selected_pid = int(selected[0]["id"])
        except (KeyError, ValueError, TypeError):
            selected_pid = None
    if selected_pid is not None:
        st.session_state["ui:projects:focus"] = selected_pid

    # ---- Detail panel for the focused project ----
    focus_pid = st.session_state.get("ui:projects:focus")
    visible_ids = {p["id"] for p in projects}
    if focus_pid is None or focus_pid not in visible_ids:
        st.caption("Click a row to open project details.")
        return

    focus_proj = next(p for p in projects if p["id"] == focus_pid)

    st.markdown("---")
    header_label = f"{focus_proj['job_number']} — {focus_proj['name']}"
    head_col1, head_col2 = st.columns([6, 1])
    with head_col1:
        st.subheader(header_label)
    with head_col2:
        if st.button(
            "← Close",
            key=f"close_detail_t0_p{focus_pid}",
        ):
            st.session_state["ui:projects:focus"] = None
            st.rerun()
    _render_project_detail_tabs(focus_proj, tab_idx=0)


def render_kanban_view(projects: Sequence) -> None:
    """Kanban view stub — fills in for subagent 5.

    Shows per-status counts using the new palette so the colors can be
    verified visually before the real board lands.
    """
    st.info("Kanban view — coming up next. Click cards to open project details.")
    if not projects:
        st.caption("No projects to summarize.")
        return
    counts: dict[str, int] = {s: 0 for s in PROJECT_STATUSES}
    for p in projects:
        if p["status"] in counts:
            counts[p["status"]] += 1
    summary_cols = st.columns(len(PROJECT_STATUSES))
    for col, status in zip(summary_cols, PROJECT_STATUSES):
        with col:
            st.markdown(render_status_pill(status), unsafe_allow_html=True)
            st.metric(label=PROJECT_STATUS_LABELS[status], value=counts[status])


def render_timeline_view(projects: Sequence) -> None:
    """Timeline view stub — fills in for subagent 5.

    Lists each project's start_date -> target_end_date as plain text so the
    underlying data is observable before the Gantt-style view lands.
    """
    st.info("Timeline view — coming up next.")
    if not projects:
        st.caption("No projects to plot.")
        return
    for proj in projects:
        start = proj["start_date"] or "?"
        end = proj["target_end_date"] or "?"
        st.markdown(
            f"- **{proj['job_number']} — {proj['name']}**  "
            f"({start} → {end})"
        )


def render_calendar_view(projects: Sequence) -> None:
    """Calendar view stub — fills in for subagent 6.

    Counts projects whose target_end_date falls in the current calendar
    month so the placeholder still surfaces useful information.
    """
    st.info("Calendar view — coming up next.")
    today = date.today()
    due_this_month = 0
    for proj in projects:
        ted = proj["target_end_date"]
        if not ted:
            continue
        try:
            parsed = datetime.fromisoformat(ted).date()
        except (ValueError, TypeError):
            continue
        if parsed.year == today.year and parsed.month == today.month:
            due_this_month += 1
    st.metric(
        label=f"Target end dates in {today.strftime('%B %Y')}",
        value=due_this_month,
    )


# ---------------------------------------------------------------------------
# Branch on the selected view
# ---------------------------------------------------------------------------
view = st.session_state["ui:projects:view"]

if view == "Kanban":
    render_kanban_view(visible_projects)
elif view == "Timeline":
    render_timeline_view(visible_projects)
elif view == "Calendar":
    render_calendar_view(visible_projects)
else:
    render_table_view(visible_projects)
