"""Status workflow constants and validation for projects.

Single source of truth for allowed status transitions. The status enum
values live in ``streamlit_app/components/status_pills.py``; this module
owns the transition rules and validation logic that the service layer
and UI both call.

Future automation rules must support AND/OR compound conditions (e.g.
"status=completed AND percent_complete=100"), not just single triggers.
"""

from __future__ import annotations

from datetime import date, datetime



from modules.status_colors import (
    PRIORITY_COLORS as PRIORITY_COLORS,
    PRIORITY_LABELS as PRIORITY_LABELS,
)

PRIORITY_VALUES = ("low", "normal", "high", "urgent")

# TODO: When a project transitions to a terminal status (completed, cancelled,
# archived), also set its lifecycle_bucket — wire when bucket column lands.
# See docs/import/legacy_status_map.md for the bucket groupings.

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "prospect":       {"active", "cancelled", "archived"},
    "active":         {"drafting", "on_hold", "ahj_permitting", "inspection", "revisions", "completed", "cancelled"},
    "drafting":       {"active", "on_hold", "ahj_permitting", "revisions", "cancelled"},
    "ahj_permitting": {"active", "drafting", "revisions", "inspection", "on_hold", "cancelled"},
    "inspection":     {"active", "revisions", "completed", "on_hold", "cancelled"},
    "revisions":      {"active", "drafting", "ahj_permitting", "inspection", "on_hold", "cancelled"},
    "on_hold":        {"active", "prospect", "drafting", "ahj_permitting", "cancelled"},
    "completed":      {"archived", "active"},
    "cancelled":      {"archived", "prospect"},
    "archived":       {"active"},
}


class InvalidStatusTransition(ValueError):
    """Raised when a status transition is not allowed."""

    def __init__(self, from_status: str, to_status: str):
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Cannot transition from '{from_status}' to '{to_status}'. "
            f"Allowed: {STATUS_TRANSITIONS.get(from_status, set())}"
        )


def validate_status_transition(
    from_status: str,
    to_status: str,
    *,
    unarchive: bool = False,
) -> None:
    """Validate that a status transition is allowed.

    Raises ``InvalidStatusTransition`` if the transition is forbidden.
    ``archived -> active`` requires ``unarchive=True``.
    """
    if from_status == to_status:
        return
    if from_status not in STATUS_TRANSITIONS:
        raise InvalidStatusTransition(from_status, to_status)
    allowed = STATUS_TRANSITIONS[from_status]
    if to_status not in allowed:
        raise InvalidStatusTransition(from_status, to_status)
    if from_status == "archived" and not unarchive:
        raise InvalidStatusTransition(from_status, to_status)


def validate_priority(priority: str) -> None:
    """Raise ValueError if priority is not in the allowed set."""
    if priority not in PRIORITY_VALUES:
        raise ValueError(
            f"Invalid priority: {priority!r}. "
            f"Must be one of {PRIORITY_VALUES}"
        )


def clamp_percent_complete(value: float | int) -> int:
    """Normalize percent_complete to an integer 0-100."""
    if isinstance(value, str):
        value = value.rstrip("%")
        try:
            value = float(value)
        except ValueError:
            return 0
    if isinstance(value, float) and value <= 1.0 and value > 0:
        value = value * 100
    return max(0, min(100, int(value)))


def get_project_age(start_date: str | None) -> int | None:
    """Compute project age in days from start_date to today.

    Returns None if start_date is missing or unparseable.
    """
    if not start_date:
        return None
    try:
        sd = datetime.fromisoformat(str(start_date)).date()
    except (ValueError, TypeError):
        return None
    return (date.today() - sd).days
