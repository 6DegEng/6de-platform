"""Projects — 6th Degree Engineering Company Platform.

Full project management page: list, create, edit, search, milestones,
calculator integration, and per-status filtering.

Session 3a introduces a four-view switcher (Table / Kanban / Timeline /
Calendar). This subagent lands the scaffold wiring only — Table view
reuses the existing per-project expander rendering as a stub; the other
three views are placeholders for subagents 4-6 to fill in.
"""

from __future__ import annotations

import sqlite3
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
from modules.projects.contacts import (  # noqa: E402
    CONTACT_ROLE_LABELS,
    CONTACT_ROLES,
    create_project_contact,
    delete_project_contact,
    list_project_contacts,
    update_project_contact,
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
from modules.projects.notes import (  # noqa: E402
    create_project_note,
    delete_project_note,
    list_project_notes,
    update_project_note,
)
from modules.projects.updates import (  # noqa: E402
    UPDATE_CATEGORIES,
    UPDATE_CATEGORY_LABELS,
    create_project_update,
    delete_project_update,
    list_project_updates,
)
from modules.projects.workflow import (  # noqa: E402
    PRIORITY_COLORS,
    PRIORITY_LABELS,
    PRIORITY_VALUES,
)
from modules.views.crud import (  # noqa: E402
    create_view,
    delete_view,
    get_view,
    hydrate_view,
    list_views,
    update_view,
)
from streamlit_app.auth import require_auth  # noqa: E402
from streamlit_app.components.activity_panel import render_activity_panel  # noqa: E402
from streamlit_app.components.project_grid import render_project_grid  # noqa: E402
from streamlit_app.components.status_pills import (  # noqa: E402
    PROJECT_STATUS_COLORS,
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


def render_filters() -> dict:
    """Render the view switcher + status filter and return active filter state.

    Extracted as a function so subagent 6 / saved-view loading can call
    this without rewriting the filter wiring. Returns a dict with:
      - "view": str — the active view name
      - "status_filter": str | None — the active status enum or None for All
    """
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
            for _enum, _lbl in PROJECT_STATUS_LABELS.items():
                if _lbl == selected_label:
                    st.session_state["ui:projects:status_filter"] = _enum
                    break

    return {
        "view": st.session_state["ui:projects:view"],
        "status_filter": st.session_state["ui:projects:status_filter"],
    }


render_filters()

# ---------------------------------------------------------------------------
# Saved views — load / save / manage
# ---------------------------------------------------------------------------
_VIEW_USER = "default"
st.session_state.setdefault("ui:projects:active_view_id", None)

_saved_views = list_views(conn, _VIEW_USER)
_view_names = ["(unsaved)"] + [v["name"] for v in _saved_views]
_view_ids: list[int | None] = [None] + [v["id"] for v in _saved_views]
_active_vid = st.session_state["ui:projects:active_view_id"]
_default_idx = _view_ids.index(_active_vid) if _active_vid in _view_ids else 0

vcol1, vcol2, vcol3, vcol4 = st.columns([3, 1, 1, 1])
with vcol1:
    if _saved_views:
        _sel_idx = st.selectbox(
            "Saved view",
            options=range(len(_view_names)),
            format_func=lambda i: _view_names[i],
            index=_default_idx,
            key="ui:projects:view_selector",
            label_visibility="collapsed",
        )
        _sel_vid = _view_ids[_sel_idx] if _sel_idx else None
        if _sel_vid != st.session_state["ui:projects:active_view_id"]:
            st.session_state["ui:projects:active_view_id"] = _sel_vid
            if _sel_vid is not None:
                _row = get_view(conn, _sel_vid)
                if _row:
                    _h = hydrate_view(_row)
                    if _h.get("filters") and "status" in _h["filters"]:
                        st.session_state["ui:projects:status_filter"] = _h["filters"]["status"]
    else:
        st.caption("No saved views yet — Save current to create your first.")

with vcol2:
    if st.button("Save current", key="ui:projects:save_view_btn", use_container_width=True):
        st.session_state["ui:projects:show_save_dialog"] = True

with vcol3:
    _active_vid_now = st.session_state["ui:projects:active_view_id"]
    _can_update = _active_vid_now is not None and any(
        v["id"] == _active_vid_now and v["owner_user_id"] == _VIEW_USER
        for v in _saved_views
    )
    if st.button(
        "Update",
        key="ui:projects:update_view_btn",
        use_container_width=True,
        disabled=not _can_update,
        help="Overwrite the active view's filters with the current selection."
            if _can_update else "Select a view you own to enable Update.",
    ):
        _filters = {"status": st.session_state.get("ui:projects:status_filter")}
        update_view(conn, _active_vid_now, _VIEW_USER, filters=_filters)
        st.rerun()

with vcol4:
    if st.button("Manage", key="ui:projects:manage_views_btn", use_container_width=True,
                 disabled=not _saved_views):
        st.session_state["ui:projects:show_manage"] = not st.session_state.get(
            "ui:projects:show_manage", False
        )

if st.session_state.get("ui:projects:show_save_dialog"):
    with st.expander("Save new view", expanded=True):
        _new_name = st.text_input("View name", key="ui:projects:save_view_name_input")
        _new_scope = st.radio("Scope", ["private", "shared"], horizontal=True,
                              key="ui:projects:save_view_scope")
        if st.button("Create", key="ui:projects:save_view_create"):
            if _new_name:
                _filters = {"status": st.session_state.get("ui:projects:status_filter")}
                try:
                    _new_id = create_view(
                        conn, _VIEW_USER, _new_name, scope=_new_scope, filters=_filters,
                    )
                    st.session_state["ui:projects:active_view_id"] = _new_id
                    st.session_state["ui:projects:show_save_dialog"] = False
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
            else:
                st.warning("Enter a view name.")

if st.session_state.get("ui:projects:show_manage") and _saved_views:
    with st.expander("Manage saved views", expanded=True):
        for v in _saved_views:
            mc1, mc2 = st.columns([4, 1])
            with mc1:
                scope_badge = "shared" if v["scope"] == "shared" else "private"
                st.text(f"{v['name']} ({scope_badge})")
            with mc2:
                if v["owner_user_id"] == _VIEW_USER:
                    if st.button("Delete", key=f"ui:projects:del_view_{v['id']}"):
                        delete_view(conn, v["id"], _VIEW_USER)
                        if st.session_state["ui:projects:active_view_id"] == v["id"]:
                            st.session_state["ui:projects:active_view_id"] = None
                        st.rerun()


status_filter: Optional[str] = st.session_state["ui:projects:status_filter"]

# ---------------------------------------------------------------------------
# Fetch projects ONCE per render at the top of the page.
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
    """Render the 9-tab project detail UI WITHOUT an enclosing ``st.expander``.

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
    (
        detail_tab,
        notes_tab,
        contacts_tab,
        updates_tab,
        activity_tab,
        milestone_tab,
        calc_tab,
        docs_tab,
        edit_tab,
    ) = st.tabs(
        [
            "Details", "Notes", "Contacts", "Updates", "Activity",
            "Milestones", "Calculations", "Documents", "Edit",
        ]
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

            # Priority pill
            try:
                priority = proj["priority"]
            except (KeyError, IndexError):
                priority = None
            if priority:
                from modules.status_colors import priority_pill_html
                st.markdown(
                    f"**Priority:** {priority_pill_html(priority)}",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown("**Priority:** —")

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

            # Action By / Next Action
            try:
                action_by = proj["action_by"]
            except (KeyError, IndexError):
                action_by = None
            try:
                next_action = proj["next_action"]
            except (KeyError, IndexError):
                next_action = None
            st.markdown(f"**Action By:** {action_by or '—'}")
            st.markdown(f"**Next Action:** {next_action or '—'}")

        # Percent complete bar
        try:
            pct = proj["percent_complete"]
        except (KeyError, IndexError):
            pct = None
        if pct is not None and pct > 0:
            st.progress(pct / 100.0, text=f"{pct}% complete")

        if proj["scope"]:
            st.markdown(f"**Scope:** {proj['scope']}")
        if proj["notes"]:
            st.markdown(f"**Notes:** {proj['notes']}")

    # --- Notes ---
    with notes_tab:
        _render_notes_tab(conn, pid, tab_idx)

    # --- Contacts ---
    with contacts_tab:
        _render_contacts_tab(conn, pid, tab_idx)

    # --- Updates ---
    with updates_tab:
        _render_updates_tab(conn, pid, tab_idx)

    # --- Edit ---
    with edit_tab:
        key_ns = f"t{tab_idx}_p{pid}"

        # Read current values with defensive access for new columns
        try:
            cur_priority = proj["priority"] or ""
        except (KeyError, IndexError):
            cur_priority = ""
        try:
            cur_action_by = proj["action_by"] or ""
        except (KeyError, IndexError):
            cur_action_by = ""
        try:
            cur_next_action = proj["next_action"] or ""
        except (KeyError, IndexError):
            cur_next_action = ""
        try:
            cur_pct = proj["percent_complete"] or 0
        except (KeyError, IndexError):
            cur_pct = 0

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
                e_priority = st.selectbox(
                    "Priority",
                    [""] + list(PRIORITY_VALUES),
                    index=(
                        list(PRIORITY_VALUES).index(cur_priority) + 1
                        if cur_priority in PRIORITY_VALUES
                        else 0
                    ),
                    format_func=lambda v: PRIORITY_LABELS.get(v, "— None —") if v else "— None —",
                    key=f"epr_{key_ns}",
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
                e_action_by = st.text_input(
                    "Action By",
                    value=cur_action_by,
                    placeholder="e.g. 6DE, AHJ, Client",
                    key=f"eab_{key_ns}",
                )
                e_next_action = st.text_input(
                    "Next Action",
                    value=cur_next_action,
                    placeholder="e.g. Submit permit application",
                    key=f"ena_{key_ns}",
                )
            e_pct = st.slider(
                "% Complete", min_value=0, max_value=100,
                value=int(cur_pct), key=f"epct_{key_ns}",
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
                new_priority = e_priority or None
                if new_priority != (cur_priority or None):
                    updates["priority"] = new_priority
                if e_action_by.strip() != cur_action_by:
                    updates["action_by"] = e_action_by.strip() or None
                if e_next_action.strip() != cur_next_action:
                    updates["next_action"] = e_next_action.strip() or None
                if e_pct != int(cur_pct):
                    updates["percent_complete"] = e_pct
                if updates:
                    try:
                        update_project(conn, pid, **updates)
                        st.success("Project updated.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
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

    # --- Activity (Session 3a — subagent 6) ---
    with activity_tab:
        render_activity_panel(conn, pid, view_idx=tab_idx)


def _render_notes_tab(conn, pid: int, tab_idx: int) -> None:
    """Render the Notes tab: list existing notes, create/edit/delete."""
    key_ns = f"t{tab_idx}_p{pid}"
    notes = list_project_notes(conn, pid)

    st.markdown(f"### Notes ({len(notes)})")

    if not notes:
        st.caption("No notes yet. Add one below.")

    for note in notes:
        nid = note["id"]
        edit_key = f"note_editing_{nid}_{key_ns}"
        is_editing = st.session_state.get(edit_key, False)

        with st.container():
            meta_col, btn_col = st.columns([5, 2])
            with meta_col:
                ts = note["created_at"] or ""
                author = note["author"] or ""
                st.caption(f"{ts}  —  {author}")
            with btn_col:
                b1, b2 = st.columns(2)
                with b1:
                    if st.button(
                        "Edit" if not is_editing else "Cancel",
                        key=f"note_edit_btn_{nid}_{key_ns}",
                    ):
                        st.session_state[edit_key] = not is_editing
                        st.rerun()
                with b2:
                    if st.button("Delete", key=f"note_del_{nid}_{key_ns}"):
                        delete_project_note(conn, nid)
                        st.rerun()

            if is_editing:
                with st.form(f"note_edit_form_{nid}_{key_ns}", clear_on_submit=False):
                    edited = st.text_area(
                        "Edit note",
                        value=note["content"],
                        key=f"note_edit_ta_{nid}_{key_ns}",
                        label_visibility="collapsed",
                    )
                    if st.form_submit_button("Save"):
                        if edited.strip():
                            update_project_note(conn, nid, edited.strip())
                            st.session_state[edit_key] = False
                            st.rerun()
            else:
                st.markdown(note["content"])

            st.markdown("---")

    # Add note form
    with st.form(f"add_note_{key_ns}", clear_on_submit=True):
        new_content = st.text_area(
            "New note",
            placeholder="Add a note about this project...",
            key=f"note_new_ta_{key_ns}",
        )
        if st.form_submit_button("Add Note"):
            if new_content.strip():
                create_project_note(conn, pid, new_content.strip())
                st.rerun()
            else:
                st.error("Note content is required.")


def _render_contacts_tab(conn, pid: int, tab_idx: int) -> None:
    """Render the Contacts tab: list per-project stakeholders, add/edit/delete."""
    key_ns = f"t{tab_idx}_p{pid}"
    contacts = list_project_contacts(conn, pid)

    st.markdown(f"### Contacts ({len(contacts)})")

    if not contacts:
        st.caption("No contacts yet. Add one below.")

    for ct in contacts:
        cid = ct["id"]
        role_label = CONTACT_ROLE_LABELS.get(ct["role"], ct["role"])
        edit_key = f"ct_editing_{cid}_{key_ns}"
        is_editing = st.session_state.get(edit_key, False)

        with st.container():
            info_col, btn_col = st.columns([5, 2])
            with info_col:
                st.markdown(f"**{ct['name']}** — {role_label}")
                details_parts = []
                if ct["company"]:
                    details_parts.append(ct["company"])
                if ct["email"]:
                    details_parts.append(ct["email"])
                if ct["phone"]:
                    details_parts.append(ct["phone"])
                if details_parts:
                    st.caption(" · ".join(details_parts))
                if ct["notes"]:
                    st.caption(ct["notes"])
            with btn_col:
                b1, b2 = st.columns(2)
                with b1:
                    if st.button(
                        "Edit" if not is_editing else "Cancel",
                        key=f"ct_edit_btn_{cid}_{key_ns}",
                    ):
                        st.session_state[edit_key] = not is_editing
                        st.rerun()
                with b2:
                    if st.button("Delete", key=f"ct_del_{cid}_{key_ns}"):
                        delete_project_contact(conn, cid)
                        st.rerun()

            if is_editing:
                with st.form(f"ct_edit_form_{cid}_{key_ns}", clear_on_submit=False):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        e_ct_name = st.text_input(
                            "Name", value=ct["name"],
                            key=f"ct_en_{cid}_{key_ns}",
                        )
                        e_ct_role = st.selectbox(
                            "Role", list(CONTACT_ROLES),
                            index=CONTACT_ROLES.index(ct["role"]) if ct["role"] in CONTACT_ROLES else 6,
                            format_func=lambda r: CONTACT_ROLE_LABELS.get(r, r),
                            key=f"ct_er_{cid}_{key_ns}",
                        )
                        e_ct_company = st.text_input(
                            "Company", value=ct["company"] or "",
                            key=f"ct_eco_{cid}_{key_ns}",
                        )
                    with ec2:
                        e_ct_email = st.text_input(
                            "Email", value=ct["email"] or "",
                            key=f"ct_ee_{cid}_{key_ns}",
                        )
                        e_ct_phone = st.text_input(
                            "Phone", value=ct["phone"] or "",
                            key=f"ct_ep_{cid}_{key_ns}",
                        )
                        e_ct_notes = st.text_input(
                            "Notes", value=ct["notes"] or "",
                            key=f"ct_eno_{cid}_{key_ns}",
                        )
                    if st.form_submit_button("Save Contact"):
                        ct_updates = {}
                        if e_ct_name.strip() != ct["name"]:
                            ct_updates["name"] = e_ct_name.strip()
                        if e_ct_role != ct["role"]:
                            ct_updates["role"] = e_ct_role
                        if e_ct_company.strip() != (ct["company"] or ""):
                            ct_updates["company"] = e_ct_company.strip() or None
                        if e_ct_email.strip() != (ct["email"] or ""):
                            ct_updates["email"] = e_ct_email.strip() or None
                        if e_ct_phone.strip() != (ct["phone"] or ""):
                            ct_updates["phone"] = e_ct_phone.strip() or None
                        if e_ct_notes.strip() != (ct["notes"] or ""):
                            ct_updates["notes"] = e_ct_notes.strip() or None
                        if ct_updates:
                            update_project_contact(conn, cid, **ct_updates)
                            st.session_state[edit_key] = False
                            st.rerun()
                        else:
                            st.info("No changes.")

            st.markdown("---")

    # Add contact form
    with st.form(f"add_ct_{key_ns}", clear_on_submit=True):
        st.markdown("**Add Contact**")
        ac1, ac2 = st.columns(2)
        with ac1:
            new_ct_name = st.text_input(
                "Name *", placeholder="e.g. Jane Smith",
                key=f"ct_new_name_{key_ns}",
            )
            new_ct_role = st.selectbox(
                "Role", list(CONTACT_ROLES),
                format_func=lambda r: CONTACT_ROLE_LABELS.get(r, r),
                key=f"ct_new_role_{key_ns}",
            )
            new_ct_company = st.text_input(
                "Company", key=f"ct_new_co_{key_ns}",
            )
        with ac2:
            new_ct_email = st.text_input(
                "Email", key=f"ct_new_email_{key_ns}",
            )
            new_ct_phone = st.text_input(
                "Phone", key=f"ct_new_phone_{key_ns}",
            )
            new_ct_notes = st.text_input(
                "Notes", key=f"ct_new_notes_{key_ns}",
            )
        if st.form_submit_button("Add Contact"):
            if not new_ct_name.strip():
                st.error("Contact name is required.")
            else:
                kwargs: dict = {}
                if new_ct_email.strip():
                    kwargs["email"] = new_ct_email.strip()
                if new_ct_phone.strip():
                    kwargs["phone"] = new_ct_phone.strip()
                if new_ct_company.strip():
                    kwargs["company"] = new_ct_company.strip()
                if new_ct_notes.strip():
                    kwargs["notes"] = new_ct_notes.strip()
                create_project_contact(
                    conn, pid, new_ct_name.strip(),
                    role=new_ct_role, **kwargs,
                )
                st.rerun()


def _render_updates_tab(conn, pid: int, tab_idx: int) -> None:
    """Render the Updates tab: timestamped status feed with category filter."""
    key_ns = f"t{tab_idx}_p{pid}"

    # Category filter
    cat_options = ["All"] + [UPDATE_CATEGORY_LABELS[c] for c in UPDATE_CATEGORIES]
    cat_filter = st.selectbox(
        "Filter by category",
        cat_options,
        key=f"upd_cat_filter_{key_ns}",
        label_visibility="collapsed",
    )
    cat_enum = None
    if cat_filter != "All":
        for k, v in UPDATE_CATEGORY_LABELS.items():
            if v == cat_filter:
                cat_enum = k
                break

    updates = list_project_updates(conn, pid, category_filter=cat_enum)
    st.markdown(f"### Updates ({len(updates)})")

    if not updates:
        st.caption("No updates yet. Add one below.")

    for upd in updates:
        uid = upd["id"]
        cat_label = UPDATE_CATEGORY_LABELS.get(upd["category"], upd["category"])
        ts = upd["created_at"] or ""
        author = upd["author"] or ""

        with st.container():
            meta_col, btn_col = st.columns([5, 1])
            with meta_col:
                st.caption(f"`{ts}` · **{cat_label}** · {author}")
            with btn_col:
                if st.button("Delete", key=f"upd_del_{uid}_{key_ns}"):
                    delete_project_update(conn, uid)
                    st.rerun()
            st.markdown(upd["content"])
            st.markdown("---")

    # Add update form
    with st.form(f"add_upd_{key_ns}", clear_on_submit=True):
        st.markdown("**Add Update**")
        new_upd_cat = st.selectbox(
            "Category",
            list(UPDATE_CATEGORIES),
            format_func=lambda c: UPDATE_CATEGORY_LABELS.get(c, c),
            key=f"upd_new_cat_{key_ns}",
        )
        new_upd_content = st.text_area(
            "Content",
            placeholder="What happened on this project?",
            key=f"upd_new_content_{key_ns}",
        )
        if st.form_submit_button("Post Update"):
            if not new_upd_content.strip():
                st.error("Update content is required.")
            else:
                create_project_update(
                    conn, pid, new_upd_content.strip(),
                    category=new_upd_cat,
                )
                st.rerun()


def _render_project_expander(proj, tab_idx: int = 0) -> None:
    """Render the 9-tab detail UI wrapped in an ``st.expander``.

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
    project's ID. The detail panel below the grid renders the 9-tab UI
    (Details / Notes / Contacts / Updates / Activity / Milestones /
    Calculations / Documents / Edit) for that one project.
    ``← Close`` returns focus to None.
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


def _render_kanban_card(proj, status: str) -> None:
    """Render one Kanban card with status-colored left border + metadata.

    The card uses ``unsafe_allow_html=True`` to draw the colored border
    + light gray panel. A small selectbox + View button sit below the
    HTML block (Streamlit widgets cannot live inside a raw HTML span).
    """
    pid = proj["id"]
    border_color = PROJECT_STATUS_COLORS.get(status, "#6c757d")
    name = proj["name"] or ""
    display_name = name if len(name) <= 40 else name[:37] + "..."
    client = proj["client_name"] or "—"
    target = proj["target_end_date"] or "—"

    # Escape HTML special chars in user-supplied text — name / client may
    # contain ampersands or angle brackets.
    import html as _html
    safe_job = _html.escape(str(proj["job_number"]))
    safe_name = _html.escape(display_name)
    safe_full_name = _html.escape(name)
    safe_client = _html.escape(str(client))
    safe_target = _html.escape(str(target))

    card_html = (
        f'<div style="border-left:4px solid {border_color};'
        f"background:#f8f9fa;padding:8px 12px;border-radius:4px;"
        f'margin-bottom:8px;" title="{safe_full_name}">'
        f'<div style="font-weight:bold;font-size:0.95em;">{safe_job}</div>'
        f'<div style="font-size:0.9em;color:#1f2937;">{safe_name}</div>'
        f'<div style="font-size:0.78em;color:#6b7280;">'
        f"Client: {safe_client}</div>"
        f'<div style="font-size:0.78em;color:#6b7280;">'
        f"Target: {safe_target}</div>"
        f"</div>"
    )
    st.markdown(card_html, unsafe_allow_html=True)

    # Status change + View button row.
    ctl_col1, ctl_col2 = st.columns([2, 1])
    with ctl_col1:
        current_idx = (
            PROJECT_STATUSES.index(proj["status"])
            if proj["status"] in PROJECT_STATUSES
            else 0
        )
        new_status = st.selectbox(
            "Status",
            list(PROJECT_STATUSES),
            index=current_idx,
            format_func=lambda s: PROJECT_STATUS_LABELS.get(s, s),
            label_visibility="collapsed",
            key=f"kanban_status_p{pid}",
        )
        if new_status != proj["status"]:
            if new_status not in PROJECT_STATUSES:
                st.error(f"Invalid status: {new_status!r}")
            else:
                try:
                    update_project(conn, pid, status=new_status)
                    st.toast(
                        f"{proj['job_number']} → "
                        f"{PROJECT_STATUS_LABELS[new_status]}",
                        icon="✅",
                    )
                    st.rerun()
                except sqlite3.IntegrityError as exc:
                    st.error(f"Database rejected status change: {exc}")
                except ValueError as exc:
                    st.error(f"Could not change status: {exc}")
    with ctl_col2:
        if st.button("View", key=f"kanban_open_p{pid}"):
            st.session_state["ui:projects:focus"] = pid
            st.rerun()


def render_kanban_view(projects: Sequence) -> None:
    """Monday-style board: one column per status, cards inside.

    Cross-column DnD via ``streamlit-sortables`` was evaluated but rejected:
    the library only accepts ``list[str]`` items, which precludes the rich
    card layout the prompt specifies (bold job number, truncated name,
    client / target-close captions, View button). The cleaner fallback —
    a per-card selectbox bound to ``PROJECT_STATUSES`` — ships here. Every
    status change still routes through ``update_project`` so the
    ``activity_log`` row gets written by the service layer.

    Archived projects are hidden by default; toggle the checkbox to show
    them as a 5th column.
    """
    # ------- Archived toggle -------
    show_archived = st.checkbox(
        "Show archived",
        value=False,
        key="ui:projects:kanban_show_archived",
    )

    if show_archived:
        visible_statuses = list(PROJECT_STATUSES)
        kanban_projects = list(projects)
    else:
        visible_statuses = [s for s in PROJECT_STATUSES if s != "archived"]
        kanban_projects = [p for p in projects if p["status"] != "archived"]

    # Update the test hook to reflect what's ACTUALLY rendered post-filter.
    st.session_state["ui:projects:_test_visible_ids"] = [
        p["id"] for p in kanban_projects
    ]

    if not kanban_projects:
        if not show_archived and any(p["status"] == "archived" for p in projects):
            st.info(
                "No projects in non-archived statuses. Toggle "
                '"Show archived" to surface the rest.'
            )
        else:
            st.info("No projects to display.")
        # Still render the column scaffold so the headers stay visible.

    # ------- Bucket projects by status -------
    buckets: dict[str, list] = {s: [] for s in visible_statuses}
    for p in kanban_projects:
        if p["status"] in buckets:
            buckets[p["status"]].append(p)

    # ------- Render columns -------
    columns = st.columns(len(visible_statuses))
    for col, status in zip(columns, visible_statuses):
        with col:
            pill_html = render_status_pill(status)
            count = len(buckets[status])
            st.markdown(
                f"{pill_html} <span style='color:#6b7280;font-size:0.9em;'>"
                f"({count})</span>",
                unsafe_allow_html=True,
            )
            st.markdown("")  # small spacer
            if not buckets[status]:
                st.caption("Empty")
                continue
            for proj in buckets[status]:
                _render_kanban_card(proj, status)

    # ------- Detail panel for the focused project -------
    focus_pid = st.session_state.get("ui:projects:focus")
    visible_ids = {p["id"] for p in kanban_projects}
    if focus_pid is None or focus_pid not in visible_ids:
        return

    focus_proj = next(p for p in kanban_projects if p["id"] == focus_pid)
    st.markdown("---")
    header_label = f"{focus_proj['job_number']} — {focus_proj['name']}"
    head_col1, head_col2 = st.columns([6, 1])
    with head_col1:
        st.subheader(header_label)
    with head_col2:
        if st.button(
            "← Close",
            key=f"close_detail_kanban_p{focus_pid}",
        ):
            st.session_state["ui:projects:focus"] = None
            st.rerun()
    _render_project_detail_tabs(focus_proj, tab_idx=1)


def _parse_iso_date(value) -> Optional[date]:
    """Parse an ISO date string (or pass through a date). None on failure."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


def render_timeline_view(projects: Sequence) -> None:
    """Plotly Gantt-style timeline of projects by start_date -> target_end_date.

    Bars are colored by status. Sorted by start_date ascending; projects
    with NULL start_date sort to the bottom. NULL-date handling:

    * Both start_date and target_end_date NULL: project is not rendered.
      A footer caption tallies the count.
    * Only target_end_date present: rendered as a single point (a 1-day
      bar centered on target_end_date) so the project still appears.
    * Only start_date present: rendered as an open-ended bar from
      start_date to today (datetime.now().date()) -- conveys "in progress
      with no committed end" more clearly than an arbitrary 60-day stub.

    Click-to-open is approximated via a below-chart selectbox; Plotly
    click events under Streamlit are unreliable.
    """
    import plotly.graph_objects as go

    # ------- Archived toggle (mirrors Kanban) -------
    show_archived = st.checkbox(
        "Show archived",
        value=False,
        key="ui:projects:timeline_show_archived",
    )

    if show_archived:
        timeline_projects = list(projects)
    else:
        timeline_projects = [p for p in projects if p["status"] != "archived"]

    # ------- Partition by date availability -------
    no_dates: list = []
    plottable: list = []
    today = datetime.now().date()
    for p in timeline_projects:
        sd = _parse_iso_date(p["start_date"])
        ted = _parse_iso_date(p["target_end_date"])
        if sd is None and ted is None:
            no_dates.append(p)
            continue
        plottable.append((p, sd, ted))

    # Sort: start_date asc; rows with no start_date (target_end only) sink.
    plottable.sort(
        key=lambda triple: (
            triple[1] is None,
            triple[1] or date.max,
            triple[2] or date.max,
        )
    )

    # Update the test hook to reflect what's ACTUALLY rendered on the chart.
    st.session_state["ui:projects:_test_visible_ids"] = [
        p["id"] for (p, _sd, _ted) in plottable
    ]

    if not plottable:
        st.info("No projects with dates to display.")
        if no_dates:
            st.caption(
                f"{len(no_dates)} project(s) with no dates — not shown on Timeline"
            )
        return

    # ------- Build the Plotly figure -------
    # We draw one horizontal bar per project. Plotly's px.timeline is the
    # idiomatic choice but pulls in pandas dependency; we use go.Bar with
    # base + width in milliseconds for the same effect with finer control.
    fig = go.Figure()

    bar_y: list[str] = []
    bar_base: list = []
    bar_width: list = []  # in milliseconds for Plotly's date axis
    bar_colors: list[str] = []
    bar_hovertext: list[str] = []
    bar_pids: list[int] = []
    bar_labels: list[str] = []

    one_day_ms = 24 * 60 * 60 * 1000

    for proj, sd, ted in plottable:
        # Compute effective start / end for this bar.
        if sd is not None and ted is not None:
            eff_start = sd
            eff_end = ted
        elif sd is not None and ted is None:
            # Open-ended: bar runs from start_date to today.
            eff_start = sd
            eff_end = max(today, sd)
        else:
            # ted only -> single point (1-day bar centered on ted).
            eff_start = ted
            eff_end = ted

        # Width in milliseconds; minimum 1 day so a single point is visible.
        delta_days = max((eff_end - eff_start).days, 1)

        bar_y.append(f"{proj['job_number']} — {(proj['name'] or '')[:30]}")
        bar_base.append(datetime.combine(eff_start, datetime.min.time()))
        bar_width.append(delta_days * one_day_ms)
        bar_colors.append(
            PROJECT_STATUS_COLORS.get(proj["status"], "#6c757d")
        )
        bar_pids.append(proj["id"])
        bar_labels.append(f"{proj['job_number']} — {(proj['name'] or '')[:30]}")

        # Hover: full name, client, status, % complete (if non-zero/non-null).
        hover_lines = [
            f"<b>{proj['name'] or '(no name)'}</b>",
            f"Job: {proj['job_number']}",
            f"Client: {proj['client_name'] or '—'}",
            f"Status: {PROJECT_STATUS_LABELS.get(proj['status'], proj['status'])}",
            f"Start: {sd or '—'}",
            f"Target end: {ted or '—'}",
        ]
        # percent_complete is a Session 3b column; surface ONLY if non-null
        # and non-zero per the spec.
        try:
            pct = proj["percent_complete"]
        except (KeyError, IndexError):
            pct = None
        if pct is not None and pct != 0:
            hover_lines.append(f"% complete: {pct}")
        bar_hovertext.append("<br>".join(hover_lines))

    fig.add_trace(
        go.Bar(
            x=bar_width,
            y=bar_y,
            base=bar_base,
            orientation="h",
            marker_color=bar_colors,
            text=bar_labels,
            textposition="inside",
            insidetextanchor="start",
            hovertext=bar_hovertext,
            hoverinfo="text",
            showlegend=False,
        )
    )

    # Height: 28 px per bar + 80 px chrome. Floor at 240, cap at 1600.
    chart_height = max(240, min(1600, 28 * len(plottable) + 80))

    fig.update_layout(
        height=chart_height,
        xaxis=dict(
            type="date",
            title="",
            showgrid=True,
            gridcolor="rgba(0,0,0,0.08)",
        ),
        yaxis=dict(
            autorange="reversed",  # earliest start at the top
            title="",
            tickfont=dict(size=11),
        ),
        margin=dict(l=10, r=10, t=20, b=10),
        plot_bgcolor="white",
        bargap=0.3,
    )

    # Today marker — vertical dashed line. Plotly date axes accept ms-since-
    # epoch, and add_vline serializes datetime through the same JSON path
    # the bar bases use, so the marker aligns with the bar base scale.
    fig.add_shape(
        type="line",
        x0=datetime.combine(today, datetime.min.time()),
        x1=datetime.combine(today, datetime.min.time()),
        y0=0,
        y1=1,
        yref="paper",
        line=dict(color="#ef4444", width=1, dash="dash"),
    )

    st.plotly_chart(fig, use_container_width=True, theme=None)

    # ------- Tally projects with no dates (per spec) -------
    if no_dates:
        st.caption(
            f"{len(no_dates)} project(s) with no dates — not shown on Timeline"
        )

    # ------- Click-to-open approximation via selectbox -------
    selector_options = [(None, "— select to open project details —")] + [
        (p["id"], f"{p['job_number']} — {p['name']}")
        for (p, _sd, _ted) in plottable
    ]
    selected = st.selectbox(
        "Open project",
        options=[opt[0] for opt in selector_options],
        format_func=lambda pid: next(
            (lbl for (oid, lbl) in selector_options if oid == pid),
            "—",
        ),
        key="ui:projects:timeline_open_select",
    )
    if selected is not None and selected != st.session_state.get(
        "ui:projects:focus"
    ):
        st.session_state["ui:projects:focus"] = selected
        st.rerun()

    # ------- Detail panel for the focused project -------
    focus_pid = st.session_state.get("ui:projects:focus")
    visible_ids = {p["id"] for (p, _sd, _ted) in plottable}
    if focus_pid is None or focus_pid not in visible_ids:
        return

    focus_proj = next(p for (p, _, _) in plottable if p["id"] == focus_pid)
    st.markdown("---")
    header_label = f"{focus_proj['job_number']} — {focus_proj['name']}"
    head_col1, head_col2 = st.columns([6, 1])
    with head_col1:
        st.subheader(header_label)
    with head_col2:
        if st.button(
            "← Close",
            key=f"close_detail_timeline_p{focus_pid}",
        ):
            st.session_state["ui:projects:focus"] = None
            st.rerun()
    _render_project_detail_tabs(focus_proj, tab_idx=2)


def render_calendar_view(projects: Sequence) -> None:
    """FullCalendar-backed month / week / list view of projects by date.

    Each project becomes 1-2 events:

    * **Target close** — primary event on ``target_end_date``, colored by
      status. Title is ``"{job_number} {name[:30]}"``.
    * **Start date** — secondary event on ``start_date``, only rendered
      when ``start_date`` is present AND differs from ``target_end_date``.
      Title is prefixed with ``▶`` so the lead arrow conveys "this is a
      start date." Same status color as the target event.

    Projects with no dates at all are skipped and tallied in a footer
    caption. Honors the page-level ``status_filter`` segmented control
    plus a local ``Show archived`` checkbox (default off, mirroring the
    Kanban / Timeline pattern).

    Click an event -> sets ``ui:projects:focus`` to that project's id and
    reruns; the 6-tab detail panel then renders below.
    """
    import html as _html

    try:
        from streamlit_calendar import calendar
    except ImportError:
        st.warning(
            "Install **streamlit-calendar** (`pip install streamlit-calendar`) "
            "to enable the Calendar view."
        )
        return

    # ------- Archived toggle (mirrors Kanban / Timeline) -------
    show_archived = st.checkbox(
        "Show archived",
        value=False,
        key="ui:projects:calendar_show_archived",
    )

    if show_archived:
        cal_projects = list(projects)
    else:
        cal_projects = [p for p in projects if p["status"] != "archived"]

    # ------- Partition by date availability -------
    no_dates: list = []
    dated: list = []
    for p in cal_projects:
        sd = _parse_iso_date(p["start_date"])
        ted = _parse_iso_date(p["target_end_date"])
        if sd is None and ted is None:
            no_dates.append(p)
            continue
        dated.append((p, sd, ted))

    # Update the test hook to reflect what's actually rendered on the
    # calendar (post status filter, post archived filter, post NULL filter).
    st.session_state["ui:projects:_test_visible_ids"] = [
        p["id"] for (p, _sd, _ted) in dated
    ]

    if not dated:
        if cal_projects and all(
            p["start_date"] is None and p["target_end_date"] is None
            for p in cal_projects
        ):
            st.info("No projects with dates in this filter.")
        else:
            st.info("No projects to display.")
        if no_dates:
            st.caption(
                f"{len(no_dates)} project(s) with no dates — not shown on Calendar"
            )
        return

    # ------- Build events -------
    events: list[dict] = []
    for proj, sd, ted in dated:
        pid = proj["id"]
        status = proj["status"]
        color = PROJECT_STATUS_COLORS.get(status, "#6c757d")
        # Truncate the display name but pass the full name through extended
        # props so a future hover-handler could surface it. ``html.escape``
        # guards against ampersands / angle brackets in user-supplied data
        # since FullCalendar renders titles as HTML by default.
        full_name = proj["name"] or ""
        short_name = full_name if len(full_name) <= 30 else full_name[:30]
        safe_job = _html.escape(str(proj["job_number"]))
        safe_name = _html.escape(short_name)

        # Target close event — primary, full color.
        if ted is not None:
            events.append(
                {
                    "title": f"{safe_job} {safe_name}".strip(),
                    "color": color,
                    "start": ted.isoformat(),
                    "allDay": True,
                    "extendedProps": {
                        "project_id": pid,
                        "kind": "target_close",
                    },
                }
            )

        # Start date event — secondary, only if start differs from target.
        if sd is not None and sd != ted:
            events.append(
                {
                    "title": f"▶ {safe_job}",
                    "color": color,
                    "start": sd.isoformat(),
                    "allDay": True,
                    "display": "block",
                    "extendedProps": {
                        "project_id": pid,
                        "kind": "start_date",
                    },
                }
            )

    # ------- Calendar options -------
    options = {
        "initialView": "dayGridMonth",
        "headerToolbar": {
            "left": "prev,next today",
            "center": "title",
            "right": "dayGridMonth,timeGridWeek,listMonth",
        },
        "height": 650,
        "eventDisplay": "block",
        "displayEventTime": False,
        "navLinks": True,
        "nowIndicator": True,
    }

    # ------- Render the calendar -------
    # Pin the widget key so state persists across reruns; restrict
    # callbacks to ``eventClick`` since we don't act on dateClick / select.
    state = calendar(
        events=events,
        options=options,
        callbacks=["eventClick"],
        key="ui:projects:calendar_widget",
    )

    # ------- Click-to-open handling -------
    # The streamlit-calendar return dict has the shape
    # ``{"callback": "eventClick", "eventClick": {"event": {"title": ...,
    # "extendedProps": {"project_id": 42, "kind": "..."}}}}`` per the
    # FullCalendar event-click API. Defensive lookups guard against minor
    # shape differences across versions.
    clicked_pid: Optional[int] = None
    if isinstance(state, dict) and state.get("callback") == "eventClick":
        event_payload = state.get("eventClick") or {}
        event_obj = event_payload.get("event") or {}
        ext_props = event_obj.get("extendedProps") or {}
        raw_pid = ext_props.get("project_id")
        if raw_pid is not None:
            try:
                clicked_pid = int(raw_pid)
            except (TypeError, ValueError):
                clicked_pid = None

    if clicked_pid is not None and clicked_pid != st.session_state.get(
        "ui:projects:focus"
    ):
        st.session_state["ui:projects:focus"] = clicked_pid
        st.rerun()

    # ------- Tally projects with no dates -------
    if no_dates:
        st.caption(
            f"{len(no_dates)} project(s) with no dates — not shown on Calendar"
        )

    # ------- Detail panel for the focused project -------
    focus_pid = st.session_state.get("ui:projects:focus")
    visible_ids = {p["id"] for (p, _sd, _ted) in dated}
    if focus_pid is None or focus_pid not in visible_ids:
        return

    focus_proj = next(p for (p, _, _) in dated if p["id"] == focus_pid)
    st.markdown("---")
    header_label = f"{focus_proj['job_number']} — {focus_proj['name']}"
    head_col1, head_col2 = st.columns([6, 1])
    with head_col1:
        st.subheader(header_label)
    with head_col2:
        if st.button(
            "← Close",
            key=f"close_detail_calendar_p{focus_pid}",
        ):
            st.session_state["ui:projects:focus"] = None
            st.rerun()
    _render_project_detail_tabs(focus_proj, tab_idx=3)


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
