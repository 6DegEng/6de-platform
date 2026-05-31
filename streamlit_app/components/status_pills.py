"""Project status constants and HTML pill renderer.

Re-exports from ``modules.status_colors`` for backward compatibility.
The centralized module owns the color palette, WCAG AA validation,
and HTML renderers; this thin wrapper preserves the import paths that
existing callers use.
"""

from __future__ import annotations

from modules.status_colors import (
    STATUS_COLORS as PROJECT_STATUS_COLORS,
    STATUS_LABELS as PROJECT_STATUS_LABELS,
    status_pill_html,
)

# Public re-export surface (kept explicit so the unused-import linter treats
# these backward-compat aliases as intentional API, not dead imports).
__all__ = [
    "PROJECT_STATUS_COLORS",
    "PROJECT_STATUS_LABELS",
    "PROJECT_STATUSES",
    "render_status_pill",
    "status_pill_html",
]

PROJECT_STATUSES: tuple[str, ...] = (
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


def render_status_pill(status: str) -> str:
    """Return an HTML ``<span>`` styled as a status pill."""
    return status_pill_html(status)
