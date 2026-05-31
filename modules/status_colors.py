"""Centralized color system for status, priority, and lifecycle bucket pills.

Single source of truth for all color-coded UI elements across the platform.
Exports HTML pill renderers and validates WCAG AA contrast at import time.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# WCAG AA contrast helpers
# ---------------------------------------------------------------------------

def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def contrast_ratio(fg: str, bg: str) -> float:
    l1 = _relative_luminance(fg)
    l2 = _relative_luminance(bg)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _auto_fg(bg: str, light: str = "#ffffff", dark: str = "#111827") -> str:
    """Pick the foreground color with better contrast against bg."""
    if contrast_ratio(light, bg) >= contrast_ratio(dark, bg):
        return light
    return dark


# ---------------------------------------------------------------------------
# Status colors & labels (mirrors status_pills.py — that module re-exports)
# ---------------------------------------------------------------------------

STATUS_COLORS: dict[str, str] = {
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

STATUS_LABELS: dict[str, str] = {
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


# ---------------------------------------------------------------------------
# Priority colors & labels
# ---------------------------------------------------------------------------

PRIORITY_COLORS: dict[str, str] = {
    "low":    "#22C55E",
    "normal": "#6B7280",
    "high":   "#F59E0B",
    "urgent": "#EF4444",
}

PRIORITY_LABELS: dict[str, str] = {
    "low":    "Low",
    "normal": "Normal",
    "high":   "High",
    "urgent": "Urgent",
}


# ---------------------------------------------------------------------------
# Lifecycle bucket colors & labels
# ---------------------------------------------------------------------------

LIFECYCLE_BUCKET_COLORS: dict[str, str] = {
    "proposed":  "#F7B500",
    "active":    "#1FBA66",
    "stand_by":  "#A85FFF",
    "finished":  "#9CA3AF",
    "lost":      "#6B7280",
    "archived":  "#374151",
}

LIFECYCLE_BUCKET_LABELS: dict[str, str] = {
    "proposed":  "Proposed",
    "active":    "Active",
    "stand_by":  "Stand By",
    "finished":  "Finished",
    "lost":      "Lost",
    "archived":  "Archived",
}

STATUS_TO_BUCKET: dict[str, str] = {
    "prospect":       "proposed",
    "active":         "active",
    "drafting":       "active",
    "ahj_permitting": "active",
    "inspection":     "active",
    "revisions":      "active",
    "on_hold":        "stand_by",
    "completed":      "finished",
    "cancelled":      "lost",
    "archived":       "archived",
}

_FALLBACK_BG = "#6c757d"


# ---------------------------------------------------------------------------
# HTML pill renderers
# ---------------------------------------------------------------------------

def status_pill_html(status: str) -> str:
    """Return an HTML ``<span>`` styled as a status pill."""
    bg = STATUS_COLORS.get(status, _FALLBACK_BG)
    label = STATUS_LABELS.get(status, status.replace("_", " ").title())
    fg = _auto_fg(bg)
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 10px;'
        f'border-radius:10px;font-size:0.85em;font-weight:600;"'
        f' role="status" aria-label="Status: {label}">'
        f"{label}</span>"
    )


def priority_pill_html(priority: str) -> str:
    """Return an HTML ``<span>`` styled as a priority indicator."""
    color = PRIORITY_COLORS.get(priority, _FALLBACK_BG)
    label = PRIORITY_LABELS.get(priority, priority.title())
    return (
        f'<span style="color:{color};font-weight:600;font-size:0.85em;"'
        f' role="status" aria-label="Priority: {label}">'
        f"&#9679; {label}</span>"
    )


def bucket_pill_html(bucket: str) -> str:
    """Return an HTML ``<span>`` styled as a lifecycle bucket pill."""
    bg = LIFECYCLE_BUCKET_COLORS.get(bucket, _FALLBACK_BG)
    label = LIFECYCLE_BUCKET_LABELS.get(bucket, bucket.replace("_", " ").title())
    fg = _auto_fg(bg)
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 10px;'
        f'border-radius:10px;font-size:0.85em;font-weight:600;"'
        f' role="status" aria-label="Bucket: {label}">'
        f"{label}</span>"
    )


# ---------------------------------------------------------------------------
# WCAG AA contrast gate — runs at import time
# ---------------------------------------------------------------------------

_WCAG_AA_MIN = 4.5


def _validate_contrast() -> None:
    """Assert every color pairing meets WCAG AA (4.5:1) minimum contrast."""
    failures: list[str] = []

    for name, colors in [("STATUS", STATUS_COLORS), ("LIFECYCLE_BUCKET", LIFECYCLE_BUCKET_COLORS)]:
        for key, bg in colors.items():
            fg = _auto_fg(bg)
            ratio = contrast_ratio(fg, bg)
            if ratio < _WCAG_AA_MIN:
                failures.append(f"{name}[{key}]: {fg} on {bg} = {ratio:.2f} (need {_WCAG_AA_MIN})")

    if failures:
        raise ValueError(
            "WCAG AA contrast violations:\n" + "\n".join(failures)
        )


_validate_contrast()
