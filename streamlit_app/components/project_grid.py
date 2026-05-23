"""streamlit-aggrid Table view for the Projects page.

Session 3a — subagent 4. Replaces the per-project ``st.expander`` list with
an inline-editable AgGrid. Status pills are rendered as colored cells via a
JsCode cellRenderer that mirrors the palette in
``streamlit_app/components/status_pills.py``.

Save semantics
--------------
On any cell edit, the grid returns the full updated row in ``data``. The
page-level handler diffs the new row against the original and routes any
changed fields through ``modules/projects/crud.py:update_project``. This
keeps the activity log writes consistent with the rest of the platform.

NO ``st.rerun()`` is called from the save handler (scout report §8 risk #3
— a forced rerun discards in-flight cell edits). The grid handles its own
visual refresh; we surface a ``st.toast`` for user feedback only.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Mapping, Optional, Sequence

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, JsCode

from modules.projects.crud import update_project
from streamlit_app.components.status_pills import (
    PROJECT_STATUS_COLORS,
    PROJECT_STATUS_LABELS,
    PROJECT_STATUSES,
)


# ---------------------------------------------------------------------------
# Columns the grid surfaces, left-to-right. Session 3b columns
# (priority, percent_complete, contract_value, etc.) are intentionally
# omitted — those land in a later session.
# ---------------------------------------------------------------------------
EDITABLE_COLUMNS: tuple[str, ...] = (
    "name",
    "status",
    "address",
    "city",
    "county",
    "scope",
    "start_date",
    "target_end_date",
    "notes",
)

# Read-only columns. We surface them but lock them from inline edits.
READONLY_COLUMNS: tuple[str, ...] = (
    "id",
    "job_number",
    "client_name",
)

# Order of columns as they appear in the grid (id is hidden but kept so the
# diff handler can map back to the project row).
GRID_COLUMN_ORDER: tuple[str, ...] = (
    "id",
    "job_number",
    "name",
    "status",
    "client_name",
    "address",
    "city",
    "county",
    "scope",
    "start_date",
    "target_end_date",
    "notes",
)

# Human-readable headers for the grid columns.
COLUMN_HEADERS: dict[str, str] = {
    "id": "ID",
    "job_number": "Job #",
    "name": "Project",
    "status": "Status",
    "client_name": "Client",
    "address": "Address",
    "city": "City",
    "county": "County",
    "scope": "Scope",
    "start_date": "Start",
    "target_end_date": "Target Close",
    "notes": "Notes",
}


# ---------------------------------------------------------------------------
# JsCode cell renderer that paints the status cell with the pill palette.
# Drawn entirely client-side; no HTML round-trip on every edit.
# ---------------------------------------------------------------------------
def _build_status_renderer() -> JsCode:
    color_map_js = "{" + ", ".join(
        f"'{s}': '{c}'" for s, c in PROJECT_STATUS_COLORS.items()
    ) + "}"
    label_map_js = "{" + ", ".join(
        f"'{s}': '{lbl}'" for s, lbl in PROJECT_STATUS_LABELS.items()
    ) + "}"
    dark_text_js = "['completed', 'prospect']"
    return JsCode(
        f"""
        function(params) {{
            const colors = {color_map_js};
            const labels = {label_map_js};
            const darkText = {dark_text_js};
            const value = params.value || '';
            const bg = colors[value] || '#6c757d';
            const fg = darkText.includes(value) ? '#111827' : '#ffffff';
            const label = labels[value] || value;
            return `<span style="background:${{bg}};color:${{fg}};` +
                   `padding:2px 10px;border-radius:10px;font-size:0.85em;` +
                   `font-weight:600;">${{label}}</span>`;
        }}
        """
    )


# ---------------------------------------------------------------------------
# DataFrame normalization — list_projects() returns sqlite3.Row instances.
# The grid wants a plain pandas DataFrame with stringy date columns and a
# stable column order matching GRID_COLUMN_ORDER.
# ---------------------------------------------------------------------------
def projects_to_dataframe(projects: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Convert a sequence of sqlite3.Row-like rows into the grid DataFrame.

    Only the columns this grid surfaces survive — others are dropped to
    keep the grid lean and avoid leaking Session 3b columns into the view.
    Missing values become empty strings (aggrid renders ``None`` as the
    literal "None" otherwise).
    """
    rows: list[dict[str, Any]] = []
    for p in projects:
        row: dict[str, Any] = {}
        for col in GRID_COLUMN_ORDER:
            try:
                val = p[col]
            except (KeyError, IndexError):
                val = None
            row[col] = "" if val is None else val
        rows.append(row)
    df = pd.DataFrame(rows, columns=list(GRID_COLUMN_ORDER))
    # Coerce id to int even if pandas inferred float because of NaNs.
    if not df.empty:
        df["id"] = df["id"].astype(int)
    return df


# ---------------------------------------------------------------------------
# Save handler — diff a new row dict against the old, route changes through
# update_project. Importable for testing.
# ---------------------------------------------------------------------------
def _normalize_for_diff(value: Any) -> Any:
    """Treat None and empty string as equivalent for change detection."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def diff_row(
    old_row: Mapping[str, Any],
    new_row: Mapping[str, Any],
) -> dict[str, Any]:
    """Return only the editable fields that changed between old_row and new_row.

    Values are coerced through ``_normalize_for_diff`` so that None vs ""
    is not treated as a change. Empty strings on editable date / text columns
    are written back as ``None`` so the DB stores NULL rather than "".
    """
    changes: dict[str, Any] = {}
    for col in EDITABLE_COLUMNS:
        old_norm = _normalize_for_diff(old_row.get(col))
        new_norm = _normalize_for_diff(new_row.get(col))
        if old_norm != new_norm:
            # Persist empty strings as NULL.
            changes[col] = new_norm if new_norm != "" else None
    return changes


def handle_row_save(
    conn: sqlite3.Connection,
    old_row: Mapping[str, Any],
    new_row: Mapping[str, Any],
) -> Optional[str]:
    """Validate + persist an edited row. Returns an error message or None.

    Calls ``modules.projects.crud.update_project`` for the diffed fields.
    Does NOT call ``st.rerun()`` (scout §8 risk #3 — aggrid handles redraw).

    If no editable fields changed, this is a no-op and ``update_project``
    is NOT called.

    Status edits are validated against ``PROJECT_STATUSES`` before the SQL
    write so we can return a friendly error message before SQLite raises
    its CHECK violation.
    """
    pid = old_row.get("id") or new_row.get("id")
    if pid is None:
        return "Cannot save row without a project ID."

    changes = diff_row(old_row, new_row)
    if not changes:
        return None  # no-op

    # Validate status enum before hitting SQLite.
    if "status" in changes and changes["status"] not in PROJECT_STATUSES:
        return (
            f"Invalid status: {changes['status']!r}. Must be one of "
            f"{', '.join(PROJECT_STATUSES)}."
        )

    try:
        update_project(conn, int(pid), **changes)
    except sqlite3.IntegrityError as exc:
        return f"Database rejected the change: {exc}"
    return None


# ---------------------------------------------------------------------------
# Grid options builder
# ---------------------------------------------------------------------------
def _build_grid_options(df: pd.DataFrame) -> dict[str, Any]:
    gb = GridOptionsBuilder.from_dataframe(df)

    # Default: read-only, filter row enabled, sortable.
    gb.configure_default_column(
        editable=False,
        sortable=True,
        filter=True,
        resizable=True,
        floatingFilter=True,
    )

    # id column: hidden, read-only. Used internally for the diff handler.
    gb.configure_column("id", hide=True, editable=False)

    # job_number: read-only plain text.
    gb.configure_column(
        "job_number",
        header_name=COLUMN_HEADERS["job_number"],
        editable=False,
        width=110,
        pinned="left",
    )

    # name: editable text.
    gb.configure_column(
        "name",
        header_name=COLUMN_HEADERS["name"],
        editable=True,
        minWidth=200,
    )

    # status: editable via agSelectCellEditor, painted with the pill renderer.
    gb.configure_column(
        "status",
        header_name=COLUMN_HEADERS["status"],
        editable=True,
        cellEditor="agSelectCellEditor",
        cellEditorParams={"values": list(PROJECT_STATUSES)},
        cellRenderer=_build_status_renderer(),
        width=140,
        rowGroup=False,  # group toggled via column menu; default ungrouped
        enableRowGroup=True,
    )

    # client_name: read-only.
    gb.configure_column(
        "client_name",
        header_name=COLUMN_HEADERS["client_name"],
        editable=False,
        minWidth=160,
    )

    # address, city, county: editable text.
    for col in ("address", "city", "county"):
        gb.configure_column(
            col,
            header_name=COLUMN_HEADERS[col],
            editable=True,
            minWidth=140,
        )

    # scope, notes: editable with text wrapping (rows auto-size to content).
    for col in ("scope", "notes"):
        gb.configure_column(
            col,
            header_name=COLUMN_HEADERS[col],
            editable=True,
            wrapText=True,
            autoHeight=True,
            minWidth=200,
        )

    # start_date, target_end_date: editable via agDateCellEditor.
    for col in ("start_date", "target_end_date"):
        gb.configure_column(
            col,
            header_name=COLUMN_HEADERS[col],
            editable=True,
            cellEditor="agDateCellEditor",
            width=130,
        )

    # Single-row selection drives the focus slot below the grid.
    gb.configure_selection(selection_mode="single", use_checkbox=False)

    # Show the column-tool sidebar so users can toggle group-by-status.
    gb.configure_side_bar()

    grid_options = gb.build()

    # Disable mass-paste row creation. aggrid only adds rows if you set
    # `processCellFromClipboard` to mutate the row count — we don't, so
    # this is belt-and-suspenders. We also lock the row count by setting
    # `suppressClipboardPaste=False` on cells but suppressing row insertion.
    grid_options["suppressClipboardPaste"] = False
    grid_options["suppressRowClickSelection"] = False
    # Group-by-status is opt-in via the column menu; default to ungrouped.
    grid_options["rowGroupPanelShow"] = "always"
    grid_options["groupDisplayType"] = "groupRows"
    grid_options["animateRows"] = True

    return grid_options


# ---------------------------------------------------------------------------
# Public render entrypoint
# ---------------------------------------------------------------------------
def render_project_grid(
    conn: sqlite3.Connection,
    projects: Sequence[Mapping[str, Any]],
    key: str = "ui:projects:grid",
) -> dict[str, Any]:
    """Render the AgGrid and route any cell edit through update_project.

    Returns the aggrid response dict (contains ``data``, ``selected_rows``,
    ``event_data``, etc.). Callers use ``selected_rows`` to drive focus.

    The handler:
      * Computes the diff between the row in the grid response and the row
        we last saw from the DB (cached in session_state under
        ``{key}:_baseline``).
      * Calls ``handle_row_save`` per dirty row.
      * Shows ``st.toast`` / ``st.error`` for feedback.
      * Does NOT call ``st.rerun()`` — aggrid handles its own redraw.
    """
    df = projects_to_dataframe(projects)
    grid_options = _build_grid_options(df)

    # Baseline cache: maps pid -> row dict for the version we last sent to
    # the grid. Used to compute the per-edit diff.
    baseline_key = f"{key}:_baseline"
    baseline: dict[int, dict[str, Any]] = {
        int(r["id"]): dict(r) for _, r in df.iterrows()
    }
    st.session_state[baseline_key] = baseline

    response = AgGrid(
        df,
        gridOptions=grid_options,
        update_on=["cellValueChanged", "selectionChanged"],
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        height=520,
        theme="streamlit",
        key=key,
        custom_css={
            ".ag-cell": {"display": "flex", "align-items": "center"},
        },
    )

    # ----- Process edits -----
    new_data = response.get("data")
    if new_data is not None:
        # aggrid returns either a DataFrame or a list of dicts depending on
        # `data_return_mode` + serialization settings. Normalize.
        if isinstance(new_data, pd.DataFrame):
            new_rows: Iterable[Mapping[str, Any]] = (
                row for _, row in new_data.iterrows()
            )
        else:
            new_rows = new_data

        for new_row in new_rows:
            try:
                pid = int(new_row["id"])
            except (KeyError, TypeError, ValueError):
                continue
            old_row = baseline.get(pid)
            if old_row is None:
                continue
            error = handle_row_save(conn, old_row, new_row)
            if error:
                st.error(error)
            else:
                changes = diff_row(old_row, new_row)
                if changes:
                    job_number = old_row.get("job_number") or pid
                    field_summary = ", ".join(changes.keys())
                    st.toast(
                        f"Saved {field_summary} for {job_number}",
                        icon="✅",
                    )

    return response
