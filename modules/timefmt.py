"""Human-friendly relative time formatting."""

from __future__ import annotations

from datetime import datetime


def relative_time(dt_str: str | None) -> str:
    """Convert an ISO-8601 datetime string to a human-readable relative time.

    Returns '' for None/empty input. Falls back to the raw string on parse failure.
    """
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(dt_str))
    except (ValueError, TypeError):
        return str(dt_str)

    now = datetime.utcnow()
    delta = now - dt
    seconds = int(delta.total_seconds())

    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    if days < 30:
        weeks = days // 7
        return f"{weeks}w ago"
    if days < 365:
        months = days // 30
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"
