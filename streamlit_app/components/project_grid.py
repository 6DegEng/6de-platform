"""streamlit-aggrid Table view for the Projects page.

Inline-editable AgGrid with status/priority pill renderers, bulk actions,
density toggle, and lifecycle bucket grouping. All writes route through
``modules/projects/crud.py:update_project`` for activity log consistency.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any, Iterable, Mapping, Optional, Sequence

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, JsCode

from modules.projects.crud import update_project
from modules.projects.workflow import (
    PRIORITY_COLORS,
    PRIORITY_LABELS,
    PRIORITY_VALUES,
)
from modules.status_colors import STATUS_TO_BUCKET
from streamlit_app.components.status_pills import (
    PROJECT_STATUS_COLORS,
    PROJECT_STATUS_LABELS,
    PROJECT_STATUSES,
)


# ---------------------------------------------------------------------------
# Columns the grid surfaces, left-to-right.
# ---------------------------------------------------------------------------
EDITABLE_COLUMNS: tuple[str, ...] = (
    "name",
    "status",
    "priority",
    "percent_complete",
    "action_by",
    "next_action",
    "address",
    "city",
    "county",
    "scope",
    "contract_value",
    "start_date",
    "target_end_date",
    "notes",
)

READONLY_COLUMNS: tuple[str, ...] = (
    "id",
    "job_number",
    "client_name",
)

GRID_COLUMN_ORDER: tuple[str, ...] = (
    "id",
    "job_number",
    "name",
    "status",
    "lifecycle_bucket",
    "priority",
    "percent_complete",
    "client_name",
    "action_by",
    "next_action",
    "address",
    "city",
    "county",
    "scope",
    "contract_value",
    "start_date",
    "target_end_date",
    "updated_at",
    "notes",
)

COLUMN_HEADERS: dict[str, str] = {
    "id": "ID",
    "job_number": "Job #",
    "name": "Project",
    "status": "Status",
    "lifecycle_bucket": "Bucket",
    "priority": "Priority",
    "percent_complete": "% Complete",
    "client_name": "Client",
    "action_by": "Action By",
    "next_action": "Next Action",
    "address": "Address",
    "city": "City",
    "county": "County",
    "scope": "Scope",
    "contract_value": "Contract $",
    "start_date": "Start",
    "target_end_date": "Target Close",
    "updated_at": "Updated",
    "notes": "Notes",
}

DENSITY_OPTIONS: dict[str, int] = {
    "Compact": 28,
    "Default": 36,
    "Comfortable": 48,
}


# ---------------------------------------------------------------------------
# JsCode cell renderers that paint the cell with the pill palette.
# Drawn entirely client-side; no HTML round-trip on every edit.
#
# IMPORTANT: in streamlit-aggrid 1.2.x (AG Grid React v34) a *plain function*
# cellRenderer is mounted as a React component — so returning a DOM element
# makes React throw "Minified React error #31: Objects are not valid as a
# React child (found: [object HTMLSpanElement])", which crashes the whole
# grid behind a "Component Error" banner once enough cells render (the
# 68-row production import made it constant). And returning an HTML *string*
# from a function renderer is assigned via ``element.textContent``, which
# shows the markup as literal escaped text. The only shape that renders HTML
# safely is an AG Grid *JS component class* (init/getGui/refresh) — AG Grid
# instantiates it outside React entirely. Each renderer below is therefore a
# class expression, not a function.
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
        class {{
            init(params) {{
                const colors = {color_map_js};
                const labels = {label_map_js};
                const darkText = {dark_text_js};
                const value = params.value || '';
                const bg = colors[value] || '#C6BCAE';
                const fg = darkText.includes(value) ? '#111827' : '#ffffff';
                const label = labels[value] || value;
                this.eGui = document.createElement('span');
                this.eGui.innerHTML = `<span style="background:${{bg}};color:${{fg}};` +
                       `padding:2px 10px;border-radius:10px;font-size:0.85em;` +
                       `font-weight:600;">${{label}}</span>`;
            }}
            getGui() {{ return this.eGui; }}
            refresh() {{ return false; }}
        }}
        """
    )


def _build_priority_renderer() -> JsCode:
    color_map_js = "{" + ", ".join(
        f"'{p}': '{c}'" for p, c in PRIORITY_COLORS.items()
    ) + "}"
    label_map_js = "{" + ", ".join(
        f"'{p}': '{lbl}'" for p, lbl in PRIORITY_LABELS.items()
    ) + "}"
    return JsCode(
        f"""
        class {{
            init(params) {{
                this.eGui = document.createElement('span');
                const value = params.value || '';
                if (!value) return;
                const colors = {color_map_js};
                const labels = {label_map_js};
                const color = colors[value] || '#C6BCAE';
                const label = labels[value] || value;
                this.eGui.innerHTML = `<span style="color:${{color}};font-weight:600;` +
                       `font-size:0.85em;">● ${{label}}</span>`;
            }}
            getGui() {{ return this.eGui; }}
            refresh() {{ return false; }}
        }}
        """
    )


def _build_percent_renderer() -> JsCode:
    return JsCode(
        """
        class {
            init(params) {
                this.eGui = document.createElement('div');
                const val = params.value;
                if (val === null || val === undefined || val === '') return;
                const pct = Math.round(Number(val));
                const width = Math.min(100, Math.max(0, pct));
                const color = pct >= 100 ? '#62C384' : pct >= 50 ? '#8FB8F2' : '#E5A54E';
                this.eGui.innerHTML = `<div style="display:flex;align-items:center;gap:6px;">` +
                       `<div style="flex:1;background:#3a3128;border-radius:4px;height:8px;">` +
                       `<div style="width:${width}%;background:${color};border-radius:4px;height:100%;"></div>` +
                       `</div><span style="font-size:0.8em;min-width:30px;">${pct}%</span></div>`;
            }
            getGui() { return this.eGui; }
            refresh() { return false; }
        }
        """
    )


# ---------------------------------------------------------------------------
# DataFrame normalization — list_projects() returns sqlite3.Row instances.
# The grid wants a plain pandas DataFrame with stringy date columns and a
# stable column order matching GRID_COLUMN_ORDER.
# ---------------------------------------------------------------------------
_NUMERIC_COLUMNS = {"percent_complete", "contract_value"}
_COMPUTED_COLUMNS = {"lifecycle_bucket"}


def projects_to_dataframe(projects: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Convert a sequence of sqlite3.Row-like rows into the grid DataFrame.

    Computes ``lifecycle_bucket`` from ``status`` via STATUS_TO_BUCKET.
    Missing text values become empty strings; numeric columns keep native type.
    """
    rows: list[dict[str, Any]] = []
    for p in projects:
        row: dict[str, Any] = {}
        for col in GRID_COLUMN_ORDER:
            if col == "lifecycle_bucket":
                status = ""
                try:
                    status = p["status"] or ""
                except (KeyError, IndexError):
                    pass
                row[col] = STATUS_TO_BUCKET.get(status, "")
                continue
            try:
                val = p[col]
            except (KeyError, IndexError):
                val = None
            if val is None and col not in _NUMERIC_COLUMNS:
                val = ""
            row[col] = val
        rows.append(row)
    df = pd.DataFrame(rows, columns=list(GRID_COLUMN_ORDER))
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

    if "priority" in changes:
        pv = changes["priority"]
        if pv and pv not in PRIORITY_VALUES:
            return (
                f"Invalid priority: {pv!r}. Must be one of "
                f"{', '.join(PRIORITY_VALUES)}."
            )
        if not pv:
            changes["priority"] = None

    if "percent_complete" in changes:
        try:
            changes["percent_complete"] = max(0, min(100, int(float(changes["percent_complete"] or 0))))
        except (ValueError, TypeError):
            changes["percent_complete"] = 0

    if "contract_value" in changes:
        # Blank/garbage -> None (NULL), never NaN or a misleading 0. NaN is
        # truthy, so the old ``float(x or 0)`` let NaN through and it poisoned
        # SUMs / rendered as "$nan".
        raw = changes["contract_value"]
        try:
            val = float(raw)
            changes["contract_value"] = None if math.isnan(val) or math.isinf(val) else val
        except (ValueError, TypeError):
            changes["contract_value"] = None

    try:
        update_project(conn, int(pid), **changes)
    except (sqlite3.IntegrityError, ValueError) as exc:
        return f"Update rejected: {exc}"
    return None


# ---------------------------------------------------------------------------
# Grid options builder
# ---------------------------------------------------------------------------
def _build_relative_time_formatter() -> JsCode:
    return JsCode(
        """function(params) {
            if (!params.value) return '';
            try {
                const dt = new Date(params.value);
                const now = new Date();
                const secs = Math.floor((now - dt) / 1000);
                if (secs < 60) return 'just now';
                const mins = Math.floor(secs / 60);
                if (mins < 60) return mins + 'm ago';
                const hrs = Math.floor(mins / 60);
                if (hrs < 24) return hrs + 'h ago';
                const days = Math.floor(hrs / 24);
                if (days < 7) return days + 'd ago';
                if (days < 30) return Math.floor(days / 7) + 'w ago';
                if (days < 365) return Math.floor(days / 30) + 'mo ago';
                return Math.floor(days / 365) + 'y ago';
            } catch (e) { return params.value; }
        }"""
    )


def _build_bucket_renderer() -> JsCode:
    from modules.status_colors import LIFECYCLE_BUCKET_COLORS, LIFECYCLE_BUCKET_LABELS
    color_map_js = "{" + ", ".join(
        f"'{b}': '{c}'" for b, c in LIFECYCLE_BUCKET_COLORS.items()
    ) + "}"
    label_map_js = "{" + ", ".join(
        f"'{b}': '{lbl}'" for b, lbl in LIFECYCLE_BUCKET_LABELS.items()
    ) + "}"
    return JsCode(
        f"""
        class {{
            init(params) {{
                this.eGui = document.createElement('span');
                const value = params.value || '';
                if (!value) return;
                const colors = {color_map_js};
                const labels = {label_map_js};
                const bg = colors[value] || '#C6BCAE';
                const label = labels[value] || value;
                this.eGui.innerHTML = `<span style="background:${{bg}};color:#fff;` +
                       `padding:2px 8px;border-radius:8px;font-size:0.8em;` +
                       `font-weight:500;">${{label}}</span>`;
            }}
            getGui() {{ return this.eGui; }}
            refresh() {{ return false; }}
        }}
        """
    )


def _build_grid_options(
    df: pd.DataFrame,
    *,
    row_height: int = 36,
    multi_select: bool = False,
    group_by_bucket: bool = False,
) -> dict[str, Any]:
    gb = GridOptionsBuilder.from_dataframe(df)

    gb.configure_default_column(
        editable=False,
        sortable=True,
        filter=True,
        resizable=True,
        floatingFilter=True,
    )

    gb.configure_column("id", hide=True, editable=False)

    gb.configure_column(
        "job_number",
        header_name=COLUMN_HEADERS["job_number"],
        editable=False,
        width=110,
        pinned="left",
        checkboxSelection=multi_select,
        headerCheckboxSelection=multi_select,
    )

    gb.configure_column(
        "name",
        header_name=COLUMN_HEADERS["name"],
        editable=True,
        minWidth=200,
    )

    gb.configure_column(
        "status",
        header_name=COLUMN_HEADERS["status"],
        editable=True,
        cellEditor="agSelectCellEditor",
        cellEditorParams={"values": list(PROJECT_STATUSES)},
        cellRenderer=_build_status_renderer(),
        width=140,
    )

    # True row-grouping is an AG Grid Enterprise module (we ship community
    # only — enable_enterprise_modules=False), so "group by bucket" surfaces
    # the bucket column pinned + pre-sorted instead of a real group tree.
    gb.configure_column(
        "lifecycle_bucket",
        header_name=COLUMN_HEADERS["lifecycle_bucket"],
        editable=False,
        cellRenderer=_build_bucket_renderer(),
        width=120,
        hide=not group_by_bucket,
        sort="asc" if group_by_bucket else None,
    )

    gb.configure_column(
        "priority",
        header_name=COLUMN_HEADERS["priority"],
        editable=True,
        cellEditor="agSelectCellEditor",
        cellEditorParams={"values": [""] + list(PRIORITY_VALUES)},
        cellRenderer=_build_priority_renderer(),
        width=120,
    )

    gb.configure_column(
        "percent_complete",
        header_name=COLUMN_HEADERS["percent_complete"],
        editable=True,
        cellRenderer=_build_percent_renderer(),
        width=140,
        type=["numericColumn"],
    )

    gb.configure_column(
        "client_name",
        header_name=COLUMN_HEADERS["client_name"],
        editable=False,
        minWidth=160,
    )

    for col in ("action_by", "next_action"):
        gb.configure_column(
            col,
            header_name=COLUMN_HEADERS[col],
            editable=True,
            minWidth=130,
        )

    for col in ("address", "city", "county"):
        gb.configure_column(
            col,
            header_name=COLUMN_HEADERS[col],
            editable=True,
            minWidth=140,
        )

    for col in ("scope", "notes"):
        gb.configure_column(
            col,
            header_name=COLUMN_HEADERS[col],
            editable=True,
            wrapText=True,
            autoHeight=True,
            minWidth=200,
        )

    gb.configure_column(
        "contract_value",
        header_name=COLUMN_HEADERS["contract_value"],
        editable=True,
        type=["numericColumn"],
        valueFormatter=JsCode(
            """function(params) {
                if (params.value === null || params.value === undefined || params.value === '' || params.value === 0) return '';
                return '$' + Number(params.value).toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0});
            }"""
        ),
        width=120,
    )

    for col in ("start_date", "target_end_date"):
        gb.configure_column(
            col,
            header_name=COLUMN_HEADERS[col],
            editable=True,
            cellEditor="agDateCellEditor",
            width=130,
        )

    gb.configure_column(
        "updated_at",
        header_name=COLUMN_HEADERS["updated_at"],
        editable=False,
        valueFormatter=_build_relative_time_formatter(),
        width=110,
    )

    selection_mode = "multiple" if multi_select else "single"
    gb.configure_selection(selection_mode=selection_mode, use_checkbox=False)

    # NOTE: configure_side_bar() / rowGroupPanelShow / enableRowGroup are
    # Enterprise-module features; with community modules they only log
    # AG Grid error #200 in the console and do nothing — removed on purpose.

    grid_options = gb.build()

    grid_options["suppressClipboardPaste"] = False
    grid_options["suppressRowClickSelection"] = False
    grid_options["animateRows"] = True
    grid_options["rowHeight"] = row_height
    grid_options["enableCellTextSelection"] = True
    grid_options["accentedSort"] = True
    # Stable row identity for edit/selection round-trips (also silences the
    # "getRowId was not set" warning).
    grid_options["getRowId"] = JsCode("function(params) { return String(params.data.id); }")

    return grid_options


# ---------------------------------------------------------------------------
# Public render entrypoint
# ---------------------------------------------------------------------------
def _apply_bulk_update(
    conn: sqlite3.Connection,
    pids: list[int],
    **kwargs: Any,
) -> tuple[int, list[str]]:
    """Apply the same update to multiple projects. Returns (success_count, errors)."""
    ok = 0
    errors: list[str] = []
    for pid in pids:
        try:
            update_project(conn, pid, **kwargs)
            ok += 1
        except (sqlite3.IntegrityError, ValueError) as exc:
            errors.append(f"Project {pid}: {exc}")
    return ok, errors


def render_grid_toolbar(key: str = "ui:projects:grid") -> dict[str, Any]:
    """Render density toggle and group-by-bucket controls above the grid.

    Returns a dict with ``row_height``, ``multi_select``, ``group_by_bucket``.
    """
    st.session_state.setdefault(f"{key}:density", "Default")
    st.session_state.setdefault(f"{key}:multi_select", False)
    st.session_state.setdefault(f"{key}:group_by_bucket", False)

    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        density = st.segmented_control(
            "Row density",
            options=list(DENSITY_OPTIONS.keys()),
            default=st.session_state[f"{key}:density"],
            label_visibility="collapsed",
            key=f"{key}:density_ctrl",
        )
        if density:
            st.session_state[f"{key}:density"] = density

    with c2:
        multi = st.checkbox(
            "Multi-select",
            value=st.session_state[f"{key}:multi_select"],
            key=f"{key}:multi_ctrl",
        )
        st.session_state[f"{key}:multi_select"] = multi

    with c3:
        bucket = st.checkbox(
            "Group by bucket",
            value=st.session_state[f"{key}:group_by_bucket"],
            key=f"{key}:bucket_ctrl",
        )
        st.session_state[f"{key}:group_by_bucket"] = bucket

    active_density = st.session_state[f"{key}:density"]
    return {
        "row_height": DENSITY_OPTIONS.get(active_density, 36),
        "multi_select": st.session_state[f"{key}:multi_select"],
        "group_by_bucket": st.session_state[f"{key}:group_by_bucket"],
    }


def render_bulk_bar(
    conn: sqlite3.Connection,
    selected_rows: list[dict[str, Any]],
    key: str = "ui:projects:grid",
) -> None:
    """Render a bulk-action bar when multiple rows are selected."""
    if len(selected_rows) < 2:
        return

    pids = []
    for r in selected_rows:
        try:
            pids.append(int(r["id"]))
        except (KeyError, TypeError, ValueError):
            pass

    if not pids:
        return

    st.info(f"**{len(pids)} projects selected** — bulk update:")
    c1, c2, c3 = st.columns(3)

    with c1:
        new_status = st.selectbox(
            "Set status",
            options=[""] + list(PROJECT_STATUSES),
            format_func=lambda v: PROJECT_STATUS_LABELS.get(v, "— Select —") if v else "— Select —",
            key=f"{key}:bulk_status",
        )
    with c2:
        new_priority = st.selectbox(
            "Set priority",
            options=[""] + list(PRIORITY_VALUES),
            format_func=lambda v: PRIORITY_LABELS.get(v, "— Select —") if v else "— Select —",
            key=f"{key}:bulk_priority",
        )
    with c3:
        if st.button("Apply bulk update", key=f"{key}:bulk_apply", type="primary"):
            kwargs: dict[str, Any] = {}
            if new_status:
                kwargs["status"] = new_status
            if new_priority:
                kwargs["priority"] = new_priority
            if kwargs:
                ok, errors = _apply_bulk_update(conn, pids, **kwargs)
                if ok:
                    st.toast(f"Updated {ok} projects", icon="✅")
                for err in errors:
                    st.error(err)
                if ok:
                    st.rerun()
            else:
                st.warning("Select a status or priority to apply.")


def render_project_grid(
    conn: sqlite3.Connection,
    projects: Sequence[Mapping[str, Any]],
    key: str = "ui:projects:grid",
) -> dict[str, Any]:
    """Render the AgGrid with toolbar, bulk bar, and inline edit handling."""
    toolbar = render_grid_toolbar(key)
    df = projects_to_dataframe(projects)
    grid_options = _build_grid_options(
        df,
        row_height=toolbar["row_height"],
        multi_select=toolbar["multi_select"],
        group_by_bucket=toolbar["group_by_bucket"],
    )

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

    # ----- Bulk action bar -----
    selected = response.get("selected_rows")
    if isinstance(selected, pd.DataFrame):
        selected = selected.to_dict("records")
    if selected and toolbar["multi_select"]:
        render_bulk_bar(conn, selected, key)

    # ----- Process edits -----
    new_data = response.get("data")
    if new_data is not None:
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
