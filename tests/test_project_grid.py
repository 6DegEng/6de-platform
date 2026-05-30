"""Regression tests for the Projects AG Grid HTML cell renderers.

Bug (fix/projects-grid-html): AG Grid v32+ (streamlit-aggrid bundles v34)
assigns a cellRenderer function's *string* return value via
``element.textContent`` instead of ``innerHTML``. A renderer that returns a
raw HTML string (``return `<span ...>` ``) therefore shows up in the cell as
literal escaped HTML — e.g. ``<span style="...background:#F59E0B;..."></span>``
— for every row, instead of a rendered pill / progress bar.

The fix: each HTML-emitting renderer must build and return a DOM *element*
(``document.createElement(...)`` + ``el.innerHTML = ...``), not an HTML string.

These tests inspect the generated JsCode so the specific defect (a bare
``return `<...` `` HTML string with no DOM element) would be caught.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from streamlit_app.components.project_grid import (  # noqa: E402
    _build_bucket_renderer,
    _build_grid_options,
    _build_percent_renderer,
    _build_priority_renderer,
    _build_status_renderer,
    projects_to_dataframe,
)

# Renderers that emit styled HTML pills / bars. Each MUST hand AG Grid a DOM
# element (so AG Grid sets innerHTML), never a bare HTML string.
_HTML_RENDERER_BUILDERS = {
    "status": _build_status_renderer,
    "priority": _build_priority_renderer,
    "percent_complete": _build_percent_renderer,
    "lifecycle_bucket": _build_bucket_renderer,
}

# Pill/bar columns whose cells are HTML-rendered.
_RENDERED_COLUMNS = set(_HTML_RENDERER_BUILDERS.keys())

# Plain-text columns that must NOT carry any cellRenderer (would otherwise
# over-wrap plain text in HTML and re-introduce the escaped-markup smell).
_TEXT_COLUMNS = (
    "client_name",
    "action_by",
    "next_action",
    "address",
    "city",
    "county",
    "scope",
    "name",
    "notes",
)


@pytest.mark.parametrize("name,builder", list(_HTML_RENDERER_BUILDERS.items()))
def test_html_renderer_returns_dom_element_not_string(name, builder):
    """Each HTML renderer must return a DOM element with innerHTML set.

    Catches the exact defect: returning a raw HTML string makes AG Grid v34
    render it via textContent (literal escaped ``<span ...>`` text).
    """
    js = builder().js_code

    # The fix's fingerprint: build an element and set its innerHTML.
    assert "document.createElement" in js, (
        f"{name} renderer must create a DOM element so AG Grid renders HTML "
        f"via innerHTML, not textContent"
    )
    assert ".innerHTML" in js, (
        f"{name} renderer must assign markup to element.innerHTML"
    )

    # The defect itself: a bare `return `<tag...` HTML string. After the fix
    # the HTML markup is assigned to innerHTML and the function returns the
    # element, so no `return` should be immediately followed by an HTML tag.
    assert not re.search(r"return\s*`?\s*<[a-zA-Z]", js), (
        f"{name} renderer still returns a raw HTML string — AG Grid v34 will "
        f"escape it and show literal markup in the cell"
    )


def test_rendered_columns_have_html_renderer():
    """The pill/bar columns must carry a cellRenderer in the grid options."""
    df = projects_to_dataframe(
        [
            {
                "id": 1,
                "job_number": "260101",
                "name": "X",
                "status": "ahj_permitting",
                "priority": "high",
                "percent_complete": 50,
                "client_name": "Acme",
                "action_by": "6DE",
                "next_action": "Submit permit",
                "address": "1 Main St",
                "city": "Miami",
                "county": "Miami-Dade",
                "scope": "Reroof",
                "contract_value": 1000,
                "start_date": "2026-01-01",
                "target_end_date": "2026-02-01",
                "updated_at": "2026-01-01",
                "notes": "n",
            }
        ]
    )
    opts = _build_grid_options(df)
    by_field = {c["field"]: c for c in opts["columnDefs"]}

    for col in _RENDERED_COLUMNS:
        assert col in by_field, f"missing column def for {col}"
        assert "cellRenderer" in by_field[col], (
            f"{col} should carry an HTML cellRenderer"
        )


def test_text_columns_have_no_cell_renderer():
    """Plain-text columns must NOT carry a renderer.

    Address/City/County/Scope/Client/Action By/Next Action are plain text;
    wrapping them in HTML (then escaped by AG Grid v34) was the reported
    symptom. They must store/show clean text — no cellRenderer.
    """
    df = projects_to_dataframe(
        [
            {
                "id": 1,
                "job_number": "260101",
                "name": "X",
                "status": "active",
                "priority": "high",
                "percent_complete": 50,
                "client_name": "Acme",
                "action_by": "6DE",
                "next_action": "Submit permit",
                "address": "1 Main St",
                "city": "Miami",
                "county": "Miami-Dade",
                "scope": "Reroof",
                "contract_value": 1000,
                "start_date": "2026-01-01",
                "target_end_date": "2026-02-01",
                "updated_at": "2026-01-01",
                "notes": "n",
            }
        ]
    )
    opts = _build_grid_options(df)
    by_field = {c["field"]: c for c in opts["columnDefs"]}

    for col in _TEXT_COLUMNS:
        assert col in by_field, f"missing column def for {col}"
        assert "cellRenderer" not in by_field[col], (
            f"{col} is a plain-text column and must not carry a cellRenderer "
            f"(would emit/escape HTML)"
        )


def test_text_column_values_are_plain_text():
    """The DataFrame feeding the grid must hold clean text for text columns.

    No ``<span`` / HTML in the underlying cell values for the plain-text
    columns — the grid stores plain strings.
    """
    df = projects_to_dataframe(
        [
            {
                "id": 7,
                "job_number": "260304",
                "name": "Buena Vista",
                "status": "ahj_permitting",
                "priority": "high",
                "percent_complete": 30,
                "client_name": "Castillo Holdings",
                "action_by": "6DE",
                "next_action": "Submit CCA package",
                "address": "2000 NW 67 St",
                "city": "Miami",
                "county": "Miami-Dade",
                "scope": "Recertification + reroof",
                "contract_value": 25000,
                "start_date": "2026-03-04",
                "target_end_date": "2026-09-01",
                "updated_at": "2026-03-04",
                "notes": "CCA in progress",
            }
        ]
    )
    for col in _TEXT_COLUMNS:
        val = df.iloc[0][col]
        assert isinstance(val, str)
        assert "<span" not in val and "<div" not in val, (
            f"{col} cell value contains raw HTML: {val!r}"
        )
