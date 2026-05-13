"""Shared UI formatting helpers for the 6DE Streamlit platform."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------

def format_currency(amount: float | int | None) -> str:
    """Format a numeric amount as USD with commas and two decimals.

    Returns "$0.00" for None / zero.
    """
    if amount is None:
        return "$0.00"
    return f"${amount:,.2f}"


def format_currency_compact(amount: float | int | None) -> str:
    """Compact currency for KPI cards where horizontal space is tight.

    Examples:
      None    -> "$0"
      850     -> "$850"
      15_000  -> "$15.0K"
      157_800 -> "$157.8K"
      1_250_000 -> "$1.25M"
      1_500_000_000 -> "$1.50B"

    Used on cards that previously truncated to "$157,..." (A3 fix).
    """
    if amount is None:
        return "$0"
    a = float(amount)
    sign = "-" if a < 0 else ""
    a = abs(a)
    if a < 1_000:
        return f"{sign}${a:.0f}"
    if a < 1_000_000:
        return f"{sign}${a / 1_000:.1f}K"
    if a < 1_000_000_000:
        return f"{sign}${a / 1_000_000:.2f}M"
    return f"{sign}${a / 1_000_000_000:.2f}B"


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def format_date(date_str: str | None) -> str:
    """Convert an ISO date string to a readable format like 'May 12, 2026'.

    Returns a dash for None or unparseable values.
    """
    if not date_str:
        return "—"
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return "—"


def days_until(date_str: str | None) -> Optional[int]:
    """Return the number of days from today until *date_str*.

    Positive means in the future; negative means past.  Returns None if
    *date_str* is missing or invalid.
    """
    if not date_str:
        return None
    try:
        target = datetime.fromisoformat(date_str).date()
        return (target - date.today()).days
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Urgency / colour helpers
# ---------------------------------------------------------------------------

def urgency_color(days: int | None) -> str:
    """Return a CSS-friendly colour name based on how many days remain.

    * <= 7 days  -> "red"
    * <= 21 days -> "orange"
    * otherwise  -> "green"
    * None       -> "gray"
    """
    if days is None:
        return "gray"
    if days <= 7:
        return "red"
    if days <= 21:
        return "orange"
    return "green"


# ---------------------------------------------------------------------------
# Status badges
# ---------------------------------------------------------------------------

def format_hours(hours: float | int | None) -> str:
    if hours is None:
        return "0.0 hrs"
    return f"{hours:,.1f} hrs"


def format_percentage(pct: float | int | None) -> str:
    if pct is None:
        return "0.0%"
    return f"{pct:,.1f}%"


_STATUS_COLORS: dict[str, dict[str, str]] = {
    "project": {
        "prospect":  "#6c757d",
        "active":    "#198754",
        "on_hold":   "#fd7e14",
        "completed": "#0d6efd",
        "archived":  "#adb5bd",
    },
    "invoice": {
        "draft":   "#6c757d",
        "sent":    "#0d6efd",
        "paid":    "#198754",
        "overdue": "#dc3545",
        "void":    "#adb5bd",
    },
    "permit": {
        "pending":              "#6c757d",
        "submitted":            "#0d6efd",
        "in_review":            "#0dcaf0",
        "approved":             "#198754",
        "issued":               "#198754",
        "expired":              "#dc3545",
        "failed_inspection":    "#dc3545",
        "closed":               "#adb5bd",
        "extension_requested":  "#fd7e14",
    },
    "milestone": {
        "pending":     "#6c757d",
        "in_progress": "#0d6efd",
        "completed":   "#198754",
        "skipped":     "#adb5bd",
    },
    "opportunity": {
        "lead":          "#6c757d",
        "qualifying":    "#0dcaf0",
        "proposal_sent": "#0d6efd",
        "negotiating":   "#fd7e14",
        "won":           "#198754",
        "lost":          "#dc3545",
        "dormant":       "#adb5bd",
    },
    "bid": {
        "monitoring": "#6c757d",
        "go":         "#0d6efd",
        "no_go":      "#adb5bd",
        "preparing":  "#fd7e14",
        "submitted":  "#0dcaf0",
        "won":        "#198754",
        "lost":       "#dc3545",
        "cancelled":  "#adb5bd",
        "protest":    "#dc3545",
    },
    "expense": {
        "unbilled": "#fd7e14",
        "billed":   "#198754",
    },
}


def status_badge(status: str | None, entity_type: str = "project") -> str:
    """Return a small coloured HTML/Markdown badge for *status*.

    Works inside ``st.markdown(..., unsafe_allow_html=True)``.
    """
    if not status:
        return ""
    color_map = _STATUS_COLORS.get(entity_type, _STATUS_COLORS["project"])
    bg = color_map.get(status, "#6c757d")
    label = status.replace("_", " ").title()
    return (
        f'<span style="background:{bg};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:0.8em;font-weight:600;">'
        f"{label}</span>"
    )
