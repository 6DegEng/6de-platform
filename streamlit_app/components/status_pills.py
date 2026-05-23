"""Project status constants and HTML pill renderer.

Single source of truth for the Projects-page status enum, display labels,
and color palette. The 5 status values mirror the CHECK constraint on
``projects.status`` declared in ``db/schema.sql``; they are hardcoded
here for simplicity (no runtime introspection of the DB schema).

Used by ``streamlit_app/pages/1_Projects.py`` and the four view modules
(Table / Kanban / Timeline / Calendar) that consume the same palette.
The colors come from the Session 3a UI uplift prompt — they intentionally
differ from the previous palette in ``formatters.py`` to match a Monday-
style board aesthetic.
"""

from __future__ import annotations

from typing import Dict, Tuple


# ---------------------------------------------------------------------------
# Status enum — ordered as it should appear in selectboxes and Kanban columns.
# Mirrors the CHECK constraint at db/schema.sql:34-35.
# ---------------------------------------------------------------------------
PROJECT_STATUSES: Tuple[str, ...] = (
    "prospect",
    "active",
    "drafting",
    "ahj_permitting",
    "inspection",
    "revisions",
    "on_hold",
    "completed",
    "cancelled",
    "archived",
)


# ---------------------------------------------------------------------------
# Color palette — adopted globally per the Session 3a UI uplift prompt.
# Session 3b added 5 new statuses with distinct colors.
# ---------------------------------------------------------------------------
PROJECT_STATUS_COLORS: Dict[str, str] = {
    "prospect":       "#F7B500",
    "active":         "#1FBA66",
    "drafting":       "#3B82F6",
    "ahj_permitting": "#F59E0B",
    "inspection":     "#06B6D4",
    "revisions":      "#EF4444",
    "on_hold":        "#A85FFF",
    "completed":      "#9CA3AF",
    "cancelled":      "#6B7280",
    "archived":       "#374151",
}


# ---------------------------------------------------------------------------
# Display labels — Title-cased with spaces for the underscore variants.
# ---------------------------------------------------------------------------
PROJECT_STATUS_LABELS: Dict[str, str] = {
    "prospect":       "Prospect",
    "active":         "Active",
    "drafting":       "Drafting",
    "ahj_permitting": "AHJ/Permitting",
    "inspection":     "Inspection",
    "revisions":      "Revisions",
    "on_hold":        "On Hold",
    "completed":      "Completed",
    "cancelled":      "Cancelled",
    "archived":       "Archived",
}


# Fallback color used when a status value is not in PROJECT_STATUS_COLORS.
_FALLBACK_BG = "#6c757d"

# Status values whose backgrounds are light enough that black text reads
# better than white. The "completed" gray (#9CA3AF) and the "prospect"
# amber (#F7B500) fall into this category; the rest stay white.
_DARK_TEXT_STATUSES = frozenset({"completed", "prospect", "ahj_permitting", "cancelled"})


def render_status_pill(status: str) -> str:
    """Return an HTML ``<span>`` styled as a status pill.

    The caller is responsible for rendering the returned string via
    ``st.markdown(..., unsafe_allow_html=True)``.

    The pill uses the matching background color from
    ``PROJECT_STATUS_COLORS``, falling back to neutral gray for unknown
    statuses. Text color is white for the darker backgrounds and black
    for the lighter ones (``completed`` gray, ``prospect`` amber) so the
    label stays legible against every palette entry.

    Parameters
    ----------
    status:
        A project status string. Unknown values render with a gray
        background and the raw value Title-cased as the label.
    """
    bg = PROJECT_STATUS_COLORS.get(status, _FALLBACK_BG)
    label = PROJECT_STATUS_LABELS.get(status, status.replace("_", " ").title())
    fg = "#111827" if status in _DARK_TEXT_STATUSES else "#ffffff"
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 10px;'
        f'border-radius:10px;font-size:0.85em;font-weight:600;">'
        f"{label}</span>"
    )
