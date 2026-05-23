"""Per-project Activity tab renderer.

Session 3a — subagent 6. Mounted as the 6th tab on each project's
detail view by ``streamlit_app/pages/1_Projects.py``. Reads from
``modules.projects.activity`` — no DB writes.

Widget keys are namespaced ``*_t{view_idx}_p{pid}`` so the same tab
rendered from different views (Table / Kanban / Timeline detail
panels) does not collide. The smoke test
(``tests/test_smoke.py:test_no_duplicate_widget_keys_in_projects_page``)
checks for the ``t{tab_idx}_p{pid}`` pattern.
"""

from __future__ import annotations

import html as _html
import json
import sqlite3
from datetime import datetime

import streamlit as st

from modules.projects.activity import (
    count_project_activity,
    list_project_activity,
    summarize_activity,
)


def _format_timestamp(raw: str | None) -> str:
    """Render an activity_log ``created_at`` as ``YYYY-MM-DD HH:MM``.

    The writer (``modules/projects/crud.py:_now``) emits ISO-ish
    strings of the form ``YYYY-MM-DD HH:MM:SS``. We strip the seconds
    for compactness. Falls back to the raw string on parse failure.
    """
    if not raw:
        return "—"
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").strftime(
            "%Y-%m-%d %H:%M"
        )
    except (TypeError, ValueError):
        return str(raw)


def render_activity_panel(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    view_idx: int,
    page_size: int = 25,
) -> None:
    """Render the Activity tab for one project.

    ``view_idx`` threads into widget keys so the same tab in different
    views (Table / Kanban / Timeline detail panels) doesn't collide.
    """
    ns = f"t{view_idx}_p{project_id}"

    # ------- Toggle: include milestone events (default on) -------
    include_ms = st.toggle(
        "Include milestone events",
        value=True,
        key=f"activity_inc_ms_{ns}",
    )

    # ------- Header with total count -------
    total = count_project_activity(
        conn, project_id, include_milestones=include_ms
    )
    st.markdown(f"### Activity ({total} total)")

    if total == 0:
        st.caption(
            "No activity yet — events appear here as you edit this project."
        )
        return

    # ------- Pagination state -------
    page_key = f"activity_page_{ns}"
    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    # Clamp page index in case the include-milestones toggle flips and
    # reduces the row count below the current page's offset.
    total_pages = max(1, (total + page_size - 1) // page_size)
    current_page = max(0, min(st.session_state[page_key], total_pages - 1))
    st.session_state[page_key] = current_page

    offset = current_page * page_size
    rows = list_project_activity(
        conn,
        project_id,
        limit=page_size,
        offset=offset,
        include_milestones=include_ms,
    )

    # ------- Render rows -------
    for row in rows:
        ts = _format_timestamp(row["created_at"])
        summary = summarize_activity(row)
        # HTML-escape the summary because it may contain project /
        # milestone names from user input. Rendered via markdown so
        # the timestamp can be styled with backticks.
        safe_summary = _html.escape(summary)
        st.markdown(f"`{ts}` &nbsp; {safe_summary}", unsafe_allow_html=True)

        # Show the raw JSON expander ONLY when the payload is richer
        # than the inferred summary captured. Heuristic from the spec:
        # >3 keys typically means there's more to show than a status
        # change (status changes carry 2-3 keys: status + updated_at,
        # maybe one other).
        details = row["details"]
        if details:
            try:
                parsed = json.loads(details)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict) and len(parsed) > 3:
                with st.expander("Details"):
                    st.code(
                        json.dumps(parsed, indent=2, sort_keys=True),
                        language="json",
                    )

    # ------- Pagination controls -------
    if total_pages > 1:
        st.markdown("")  # spacer
        prev_col, page_col, next_col = st.columns([1, 3, 1])
        with prev_col:
            if st.button(
                "← Prev",
                key=f"activity_prev_{ns}",
                disabled=(current_page == 0),
            ):
                st.session_state[page_key] = current_page - 1
                st.rerun()
        with page_col:
            st.caption(
                f"Page {current_page + 1} of {total_pages}",
            )
        with next_col:
            if st.button(
                "Next →",
                key=f"activity_next_{ns}",
                disabled=(current_page >= total_pages - 1),
            ):
                st.session_state[page_key] = current_page + 1
                st.rerun()
